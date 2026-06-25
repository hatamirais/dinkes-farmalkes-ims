import logging
from urllib.parse import urlencode
from decimal import Decimal, InvalidOperation

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from apps.core.decorators import module_scope_required, perm_required
from apps.stock.models import Stock
from apps.users.models import ModuleAccess

from .models import StockOpname, StockOpnameItem
from .forms import StockOpnameForm

logger = logging.getLogger(__name__)


@login_required
@perm_required("stock_opname.view_stockopname")
def opname_list(request):
    queryset = (
        StockOpname.objects.select_related("created_by")
        .prefetch_related(
            "categories",
            "assigned_to",
        )
        .all()
    )

    # Filters
    status = request.GET.get("status")
    if status:
        queryset = queryset.filter(status=status)

    period = request.GET.get("period")
    if period:
        queryset = queryset.filter(period_type=period)

    search = request.GET.get("q", "").strip()
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
            "selected_status": status or "",
            "selected_period": period or "",
            "status_choices": StockOpname.Status.choices,
            "period_choices": StockOpname.PeriodType.choices,
        },
    )


@login_required
@perm_required("stock_opname.add_stockopname")
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
def opname_edit(request, pk):
    opname = get_object_or_404(StockOpname, pk=pk)
    # F14: Only DRAFT opnames may have their header edited; once a snapshot
    # has been taken (IN_PROGRESS) the category list is locked to match it.
    if opname.status != StockOpname.Status.DRAFT:
        messages.error(request, "Hanya Stock Opname berstatus Draft yang dapat diubah.")
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
            "title": f"Edit Stock Opname — {opname.document_number}",
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

    # Group by location for display
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

    # F11: Compute summary from the already-evaluated `items` queryset so we
    # don't fire 5 extra COUNT queries that duplicate the loop above.
    items_list = list(items)
    total_items = len(items_list)
    counted_items = sum(1 for i in items_list if i.actual_quantity is not None)
    discrepancy_count = sum(
        1 for i in items_list
        if i.actual_quantity is not None and i.has_discrepancy
    )
    progress = int((counted_items / total_items) * 100) if total_items > 0 else 0

    return render(
        request,
        "stock_opname/opname_detail.html",
        {
            "opname": opname,
            "locations": locations.values(),
            "total_items": total_items,
            "counted_items": counted_items,
            "discrepancy_count": discrepancy_count,
            "progress": progress,
        },
    )


@login_required
@perm_required("stock_opname.change_stockopname")
def opname_start(request, pk):
    """Transition DRAFT → IN_PROGRESS and snapshot stock quantities filtered by categories."""
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

            snapshot_time = timezone.now()
            opname_items = [
                StockOpnameItem(
                    stock_opname=opname,
                    stock=stock,
                    system_quantity=stock.quantity,
                    created_at=snapshot_time,
                    updated_at=snapshot_time,
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

    # Get location filter (accept from GET or POST so filter is preserved when submitting the form)
    location_id = request.GET.get("location") or request.POST.get("location")

    items = opname.items.select_related(
        "stock__item",
        "stock__item__satuan",
        "stock__location",
        "stock__sumber_dana",
    ).order_by(
        "stock__location__code", "stock__expiry_date", "stock__item__nama_barang"
    )

    if location_id:
        items = items.filter(stock__location_id=location_id)

    # Get available locations for filter
    from apps.items.models import Location

    location_ids = opname.items.values_list("stock__location_id", flat=True).distinct()
    locations = Location.objects.filter(pk__in=location_ids).order_by("code")

    for item in items:
        item.input_quantity = item.actual_quantity
        item.input_notes = item.notes
        item.quantity_error = ""

    if request.method == "POST":
        updated_items = []
        has_errors = False
        for item in items:
            qty_key = f"qty_{item.pk}"
            notes_key = f"notes_{item.pk}"
            qty_val = request.POST.get(qty_key, "").strip()
            notes_val = request.POST.get(notes_key, "").strip()
            item.input_quantity = qty_val
            item.input_notes = notes_val
            item.quantity_error = ""

            if not qty_val:
                continue

            try:
                actual = Decimal(qty_val)
            except InvalidOperation:
                item.quantity_error = "Jumlah aktual harus berupa angka yang valid."
                has_errors = True
                continue

            if not actual.is_finite():
                item.quantity_error = "Jumlah aktual harus berupa angka yang valid."
                has_errors = True
                continue

            if actual < 0:
                item.quantity_error = "Jumlah aktual tidak boleh kurang dari 0."
                has_errors = True
                continue

            item.actual_quantity = actual
            item.notes = notes_val
            try:
                item.full_clean(exclude=["stock_opname", "stock", "system_quantity"])
            except ValidationError as exc:
                quantity_errors = exc.message_dict.get("actual_quantity", [])
                other_errors = [
                    error
                    for field, errors in exc.message_dict.items()
                    if field != "actual_quantity"
                    for error in errors
                ]
                item.quantity_error = (
                    " ".join(quantity_errors + other_errors) or "Data tidak valid."
                )
                has_errors = True
                continue

            updated_items.append(item)

        if has_errors:
            logger.warning(
                "Rejected invalid stock opname input",
                extra={"stock_opname_id": opname.pk, "user_id": request.user.pk},
            )
            messages.error(
                request,
                "Beberapa input jumlah aktual tidak valid. Periksa data yang ditandai.",
            )
            return render(
                request,
                "stock_opname/opname_input.html",
                {
                    "opname": opname,
                    "items": items,
                    "locations": locations,
                    "selected_location": location_id or "",
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

                update_time = timezone.now()
                for item in updated_items:
                    item.updated_at = update_time

                StockOpnameItem.objects.bulk_update(
                    updated_items,
                    ["actual_quantity", "notes", "updated_at"],
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
        # Redirect back with same location filter
        url = reverse("stock_opname:opname_input", args=[pk])
        if location_id:
            url = f"{url}?{urlencode({'location': location_id})}"
        return redirect(url)

    return render(
        request,
        "stock_opname/opname_input.html",
        {
            "opname": opname,
            "items": items,
            "locations": locations,
            "selected_location": location_id or "",
        },
    )


@login_required
@perm_required("stock_opname.change_stockopname")
@module_scope_required(ModuleAccess.Module.STOCK_OPNAME, ModuleAccess.Scope.APPROVE)
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
    """Printable discrepancy report — shows only items where actual ≠ system."""
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

    # Group by location
    locations = {}
    for item in discrepancy_items:
        loc = item.stock.location
        if loc.pk not in locations:
            locations[loc.pk] = {
                "location": loc,
                "items": [],
            }
        locations[loc.pk]["items"].append(item)

    # F12: discrepancy_items was already evaluated by the for-loop above;
    # use len() to avoid a second COUNT query against the database.
    discrepancy_list = list(discrepancy_items)  # materialise once
    return render(
        request,
        "stock_opname/opname_print.html",
        {
            "opname": opname,
            "locations": locations.values(),
            "total_discrepancies": len(discrepancy_list),
            "print_date": timezone.now(),
        },
    )


@login_required
@perm_required("stock_opname.delete_stockopname")
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
