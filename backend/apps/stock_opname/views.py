import logging
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import DatabaseError, transaction
from django.db.models import F
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.core.decorators import module_scope_required, perm_required
from apps.core.rate_limits import (
    stock_opname_form_mutation_ratelimit,
    stock_opname_input_mutation_ratelimit,
    stock_opname_workflow_mutation_ratelimit,
)
from apps.core.views import bad_request
from apps.stock.models import Stock
from apps.users.models import ModuleAccess

from .forms import (
    StockOpnameFilterForm,
    StockOpnameForm,
    StockOpnameItemInputForm,
    StockOpnameLocationFilterForm,
)
from .models import StockOpname, StockOpnameItem

logger = logging.getLogger(__name__)


def _invalid_request_response(request, *, message, log_message, extra=None):
    logger.warning(log_message, extra=extra or {})
    return bad_request(request, ValidationError(message))


@login_required
@perm_required("stock_opname.view_stockopname")
def opname_list(request):
    filter_form = StockOpnameFilterForm(request.GET or None)
    if request.GET and not filter_form.is_valid():
        return _invalid_request_response(
            request,
            message="Parameter filter stock opname tidak valid.",
            log_message="Rejected invalid stock opname list filter",
            extra={"user_id": request.user.pk},
        )

    queryset = (
        StockOpname.objects.select_related("created_by")
        .prefetch_related(
            "categories",
            "assigned_to",
        )
        .all()
    )

    cleaned_filters = filter_form.cleaned_data if filter_form.is_bound else {}
    status = cleaned_filters.get("status") or ""
    period = cleaned_filters.get("period") or ""
    search = cleaned_filters.get("q") or ""

    if status:
        queryset = queryset.filter(status=status)

    if period:
        queryset = queryset.filter(period_type=period)

    if search:
        queryset = queryset.filter(document_number__icontains=search)

    paginator = Paginator(queryset, 20)
    page = request.GET.get("page")
    opnames = paginator.get_page(page)

    return render(
        request,
        "stock_opname/opname_list.html",
        {
            "opnames": opnames,
            "search": search,
            "selected_status": status,
            "selected_period": period,
            "status_choices": StockOpname.Status.choices,
            "period_choices": StockOpname.PeriodType.choices,
        },
    )


@login_required
@perm_required("stock_opname.add_stockopname")
@stock_opname_form_mutation_ratelimit
def opname_create(request):
    if request.method == "POST":
        form = StockOpnameForm(request.POST)
        if form.is_valid():
            opname = form.save(commit=False)
            opname.created_by = request.user
            opname.save()
            form.save_m2m()
            messages.success(
                request, f"Stock Opname {opname.document_number} berhasil dibuat."
            )
            return redirect("stock_opname:opname_detail", pk=opname.pk)
    else:
        form = StockOpnameForm()

    return render(
        request,
        "stock_opname/opname_form.html",
        {
            "form": form,
            "title": "Buat Stock Opname Baru",
        },
    )


@login_required
@perm_required("stock_opname.change_stockopname")
@stock_opname_form_mutation_ratelimit
def opname_edit(request, pk):
    opname = get_object_or_404(StockOpname, pk=pk)
    if opname.status == StockOpname.Status.COMPLETED:
        messages.error(request, "Stock Opname yang sudah selesai tidak dapat diedit.")
        return redirect("stock_opname:opname_detail", pk=opname.pk)

    if request.method == "POST":
        form = StockOpnameForm(request.POST, instance=opname)
        if form.is_valid():
            form.save()
            messages.success(
                request, f"Stock Opname {opname.document_number} berhasil diperbarui."
            )
            return redirect("stock_opname:opname_detail", pk=opname.pk)
    else:
        form = StockOpnameForm(instance=opname)

    return render(
        request,
        "stock_opname/opname_form.html",
        {
            "form": form,
            "title": f"Edit Stock Opname - {opname.document_number}",
        },
    )


@login_required
@perm_required("stock_opname.view_stockopname")
def opname_detail(request, pk):
    opname = get_object_or_404(
        StockOpname.objects.select_related("created_by", "completed_by"),
        pk=pk,
    )
    items = opname.items.select_related(
        "stock__item",
        "stock__item__satuan",
        "stock__location",
        "stock__sumber_dana",
    ).order_by(
        "stock__location__code", "stock__expiry_date", "stock__item__nama_barang"
    )

    locations = {}
    for item in items:
        loc = item.stock.location
        if loc.pk not in locations:
            locations[loc.pk] = {
                "location": loc,
                "items": [],
                "counted": 0,
                "total": 0,
                "discrepancies": 0,
            }
        locations[loc.pk]["items"].append(item)
        locations[loc.pk]["total"] += 1
        if item.actual_quantity is not None:
            locations[loc.pk]["counted"] += 1
            if item.has_discrepancy:
                locations[loc.pk]["discrepancies"] += 1

    return render(
        request,
        "stock_opname/opname_detail.html",
        {
            "opname": opname,
            "locations": locations.values(),
            "total_items": opname.total_items,
            "counted_items": opname.counted_items,
            "discrepancy_count": opname.discrepancy_count,
            "progress": opname.progress_percentage,
        },
    )


@login_required
@perm_required("stock_opname.change_stockopname")
@stock_opname_workflow_mutation_ratelimit
def opname_start(request, pk):
    """Transition DRAFT -> IN_PROGRESS and snapshot stock quantities filtered by categories."""
    opname = get_object_or_404(StockOpname, pk=pk)

    if request.method != "POST":
        return redirect("stock_opname:opname_detail", pk=opname.pk)

    try:
        with transaction.atomic():
            opname = (
                StockOpname.objects.select_for_update()
                .prefetch_related("categories")
                .get(pk=pk)
            )

            if opname.status != StockOpname.Status.DRAFT:
                messages.error(
                    request,
                    "Stock Opname ini sudah dimulai atau diselesaikan.",
                )
                return redirect("stock_opname:opname_detail", pk=opname.pk)

            if opname.items.exists():
                logger.error(
                    "Draft stock opname already has snapshot rows",
                    extra={"stock_opname_id": opname.pk},
                )
                messages.error(
                    request,
                    "Stock Opname draft ini memiliki data snapshot yang tidak konsisten.",
                )
                return redirect("stock_opname:opname_detail", pk=opname.pk)

            selected_category_ids = list(
                opname.categories.values_list("pk", flat=True)
            )
            stocks = (
                Stock.objects.select_for_update()
                .filter(quantity__gt=0)
                .select_related(
                    "item",
                    "location",
                    "sumber_dana",
                )
                .order_by("pk")
            )
            if selected_category_ids:
                stocks = stocks.filter(item__kategori_id__in=selected_category_ids)

            opname_items = [
                StockOpnameItem(
                    stock_opname=opname,
                    stock=stock,
                    system_quantity=stock.quantity,
                )
                for stock in stocks
            ]
            StockOpnameItem.objects.bulk_create(opname_items)

            opname.status = StockOpname.Status.IN_PROGRESS
            opname.save(update_fields=["status", "updated_at"])

        messages.success(
            request,
            f"Stock Opname dimulai. {len(opname_items)} item stok berhasil di-snapshot.",
        )
        return redirect("stock_opname:opname_detail", pk=opname.pk)
    except DatabaseError:
        logger.exception(
            "Failed to start stock opname snapshot",
            extra={"stock_opname_id": pk, "user_id": request.user.pk},
        )
        messages.error(
            request,
            "Stock Opname gagal dimulai. Silakan coba lagi.",
        )
        return redirect("stock_opname:opname_detail", pk=pk)


@login_required
@perm_required("stock_opname.change_stockopnameitem")
@stock_opname_input_mutation_ratelimit
def opname_input(request, pk):
    """Input actual quantities for a stock opname session."""
    opname = get_object_or_404(
        StockOpname,
        pk=pk,
    )

    if opname.status != StockOpname.Status.IN_PROGRESS:
        messages.error(
            request,
            "Stock Opname ini sudah diselesaikan atau belum dimulai.",
        )
        return redirect("stock_opname:opname_detail", pk=opname.pk)

    location_filter_data = request.GET or None
    if request.method == "POST":
        location_filter_data = request.POST.copy()
        if not location_filter_data.get("location") and request.GET.get("location"):
            location_filter_data["location"] = request.GET.get("location")

    location_filter_form = StockOpnameLocationFilterForm(
        location_filter_data,
        allowed_location_ids=list(
            opname.items.values_list("stock__location_id", flat=True).distinct()
        ),
    )
    if location_filter_form.is_bound and not location_filter_form.is_valid():
        return _invalid_request_response(
            request,
            message="Filter lokasi stock opname tidak valid.",
            log_message="Rejected invalid stock opname location filter",
            extra={"stock_opname_id": opname.pk, "user_id": request.user.pk},
        )

    selected_location = None
    if location_filter_form.is_bound:
        selected_location = location_filter_form.cleaned_data.get("location")

    items_queryset = opname.items.select_related(
        "stock__item",
        "stock__item__satuan",
        "stock__location",
        "stock__sumber_dana",
    ).order_by(
        "stock__location__code", "stock__expiry_date", "stock__item__nama_barang"
    )

    if selected_location is not None:
        items_queryset = items_queryset.filter(stock__location=selected_location)

    items = list(items_queryset)
    locations = list(location_filter_form.fields["location"].queryset)
    selected_location_value = str(selected_location.pk) if selected_location else ""

    for item in items:
        item.input_quantity = item.actual_quantity
        item.input_notes = item.notes
        item.quantity_error = ""
        item.notes_error = ""

    if request.method == "POST":
        updated_items = []
        has_errors = False

        for item in items:
            raw_quantity = request.POST.get(f"qty_{item.pk}", "")
            raw_notes = request.POST.get(f"notes_{item.pk}", "")
            item.input_quantity = raw_quantity
            item.input_notes = raw_notes
            item.quantity_error = ""
            item.notes_error = ""

            form = StockOpnameItemInputForm(
                {
                    "actual_quantity": raw_quantity,
                    "notes": raw_notes,
                }
            )
            if not form.is_valid():
                item.quantity_error = " ".join(form.errors.get("actual_quantity", []))
                item.notes_error = " ".join(form.errors.get("notes", []))
                has_errors = True
                continue

            actual_quantity = form.cleaned_data["actual_quantity"]
            if actual_quantity is None:
                continue

            item.actual_quantity = actual_quantity
            item.notes = form.cleaned_data["notes"]
            updated_items.append(item)

        if has_errors:
            logger.warning(
                "Rejected invalid stock opname input",
                extra={"stock_opname_id": opname.pk, "user_id": request.user.pk},
            )
            messages.error(
                request,
                "Beberapa input Stock Opname tidak valid. Periksa data yang ditandai.",
            )
            return render(
                request,
                "stock_opname/opname_input.html",
                {
                    "opname": opname,
                    "items": items,
                    "locations": locations,
                    "selected_location": selected_location_value,
                },
                status=400,
            )

        try:
            with transaction.atomic():
                locked_opname = StockOpname.objects.select_for_update().get(pk=pk)
                if locked_opname.status != StockOpname.Status.IN_PROGRESS:
                    messages.error(
                        request,
                        "Stock Opname ini sudah diselesaikan atau belum dimulai.",
                    )
                    return redirect("stock_opname:opname_detail", pk=locked_opname.pk)

                updated_item_ids = [item.pk for item in updated_items]
                if updated_item_ids:
                    list(
                        StockOpnameItem.objects.select_for_update()
                        .filter(stock_opname=locked_opname, pk__in=updated_item_ids)
                        .values_list("pk", flat=True)
                    )

                StockOpnameItem.objects.bulk_update(
                    updated_items,
                    ["actual_quantity", "notes"],
                )
        except DatabaseError:
            logger.exception(
                "Failed to save stock opname input",
                extra={"stock_opname_id": opname.pk, "user_id": request.user.pk},
            )
            messages.error(
                request,
                "Input Stock Opname gagal disimpan. Silakan coba lagi.",
            )
            return redirect("stock_opname:opname_detail", pk=opname.pk)

        messages.success(request, f"{len(updated_items)} item berhasil diperbarui.")
        url = reverse("stock_opname:opname_input", args=[pk])
        if selected_location_value:
            url = f"{url}?{urlencode({'location': selected_location_value})}"
        return redirect(url)

    return render(
        request,
        "stock_opname/opname_input.html",
        {
            "opname": opname,
            "items": items,
            "locations": locations,
            "selected_location": selected_location_value,
        },
    )


@login_required
@perm_required("stock_opname.change_stockopname")
@module_scope_required(ModuleAccess.Module.STOCK_OPNAME, ModuleAccess.Scope.APPROVE)
@stock_opname_workflow_mutation_ratelimit
def opname_complete(request, pk):
    """Finalize a stock opname session."""
    opname = get_object_or_404(StockOpname, pk=pk)

    if request.method == "POST":
        try:
            with transaction.atomic():
                opname = StockOpname.objects.select_for_update().get(pk=pk)
                actual_quantities = list(
                    opname.items.select_for_update()
                    .order_by("pk")
                    .values_list("actual_quantity", flat=True)
                )
                if opname.status != StockOpname.Status.IN_PROGRESS:
                    messages.error(
                        request,
                        "Stock Opname ini sudah diselesaikan atau belum dimulai.",
                    )
                    return redirect("stock_opname:opname_detail", pk=opname.pk)
                if not actual_quantities or all(
                    quantity is None for quantity in actual_quantities
                ):
                    messages.error(
                        request,
                        "Stock Opname belum dapat diselesaikan karena belum ada item yang dihitung.",
                    )
                    return redirect("stock_opname:opname_detail", pk=opname.pk)
                if any(quantity is None for quantity in actual_quantities):
                    messages.error(
                        request,
                        "Stock Opname belum dapat diselesaikan karena masih ada item yang belum dihitung.",
                    )
                    return redirect("stock_opname:opname_detail", pk=opname.pk)

                opname.status = StockOpname.Status.COMPLETED
                opname.completed_by = request.user
                opname.completed_at = timezone.now()
                opname.save(
                    update_fields=[
                        "status",
                        "completed_by",
                        "completed_at",
                        "updated_at",
                    ]
                )
        except StockOpname.DoesNotExist:
            raise
        except DatabaseError:
            logger.exception(
                "Failed to complete stock opname",
                extra={"stock_opname_id": pk, "user_id": request.user.pk},
            )
            messages.error(
                request,
                "Stock Opname gagal diselesaikan. Silakan coba lagi.",
            )
            return redirect("stock_opname:opname_detail", pk=pk)

        messages.success(
            request, f"Stock Opname {opname.document_number} telah diselesaikan."
        )
        return redirect("stock_opname:opname_detail", pk=opname.pk)

    return redirect("stock_opname:opname_detail", pk=opname.pk)


@login_required
@perm_required("stock_opname.view_stockopname")
def opname_print(request, pk):
    """Printable discrepancy report - shows only items where actual != system."""
    opname = get_object_or_404(
        StockOpname.objects.select_related("created_by", "completed_by"),
        pk=pk,
    )

    discrepancy_items = (
        opname.items.select_related(
            "stock__item",
            "stock__item__satuan",
            "stock__location",
            "stock__sumber_dana",
        )
        .filter(actual_quantity__isnull=False)
        .exclude(actual_quantity=F("system_quantity"))
        .order_by(
            "stock__location__code", "stock__expiry_date", "stock__item__nama_barang"
        )
    )

    locations = {}
    for item in discrepancy_items:
        loc = item.stock.location
        if loc.pk not in locations:
            locations[loc.pk] = {
                "location": loc,
                "items": [],
            }
        locations[loc.pk]["items"].append(item)

    return render(
        request,
        "stock_opname/opname_print.html",
        {
            "opname": opname,
            "locations": locations.values(),
            "total_discrepancies": discrepancy_items.count(),
            "print_date": timezone.now(),
        },
    )


@login_required
@perm_required("stock_opname.delete_stockopname")
@stock_opname_workflow_mutation_ratelimit
def opname_delete(request, pk):
    """Delete a stock opname session (only DRAFT or IN_PROGRESS)."""
    opname = get_object_or_404(
        StockOpname,
        pk=pk,
        status__in=[StockOpname.Status.DRAFT, StockOpname.Status.IN_PROGRESS],
    )

    if request.method == "POST":
        doc_num = opname.document_number
        opname.delete()
        messages.success(request, f"Stock Opname {doc_num} berhasil dihapus.")
        return redirect("stock_opname:opname_list")

    return render(
        request,
        "stock_opname/opname_confirm_delete.html",
        {
            "opname": opname,
        },
    )
