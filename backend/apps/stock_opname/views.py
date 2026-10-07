import logging
from decimal import Decimal, InvalidOperation

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.utils import timezone

from apps.core.decorators import module_scope_required, perm_required
from apps.core.models import DocumentNumberRule
from apps.core.numbering import issue_document_number, void_document_number
from apps.stock.models import Stock
from apps.users.access import has_module_scope
from apps.users.models import ModuleAccess

from .models import StockOpname, StockOpnameItem
from .forms import StockOpnameForm

logger = logging.getLogger(__name__)


def _stock_update_quantity_for_item(item, opname):
    if (
        opname.status == StockOpname.Status.COMPLETED
        and item.completion_stock_quantity is not None
    ):
        return item.completion_stock_quantity
    return item.stock.quantity


def _annotate_current_stock_status(item, opname):
    item.stock_update_quantity = _stock_update_quantity_for_item(item, opname)
    item.current_difference = None
    item.has_current_discrepancy = False
    item.stock_update_matches_physical = False
    if item.actual_quantity is not None:
        item.current_difference = item.actual_quantity - item.stock_update_quantity
        item.has_current_discrepancy = item.current_difference != 0
        item.stock_update_matches_physical = item.current_difference == 0
    return item


def _user_can_complete_opname(user, has_current_discrepancy):
    if user.is_superuser:
        return True
    if not has_current_discrepancy and user.has_perm("stock_opname.change_stockopname"):
        return True
    required_scope = (
        ModuleAccess.Scope.APPROVE
        if has_current_discrepancy
        else ModuleAccess.Scope.OPERATE
    )
    return has_module_scope(
        user,
        ModuleAccess.Module.STOCK_OPNAME,
        required_scope,
    )


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
                request,
                "Draft Stock Opname berhasil dibuat. Nomor dokumen akan diterbitkan saat dimulai.",
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

    if request.method == "POST":
        with transaction.atomic():
            opname = StockOpname.objects.select_for_update().get(pk=pk)
            # Only DRAFT opnames may have their header edited; once a snapshot
            # has been taken (IN_PROGRESS) the category list is locked to match it.
            if opname.status != StockOpname.Status.DRAFT:
                messages.error(
                    request, "Hanya Stock Opname berstatus Draft yang dapat diubah."
                )
                return redirect("stock_opname:opname_detail", pk=opname.pk)

            form = StockOpnameForm(request.POST, instance=opname)
            if form.is_valid():
                form.save()
                messages.success(
                    request,
                    f"Stock Opname {opname.document_number or 'draft'} berhasil diperbarui.",
                )
                return redirect("stock_opname:opname_detail", pk=opname.pk)
    else:
        if opname.status != StockOpname.Status.DRAFT:
            messages.error(
                request, "Hanya Stock Opname berstatus Draft yang dapat diubah."
            )
            return redirect("stock_opname:opname_detail", pk=opname.pk)
        form = StockOpnameForm(instance=opname)

    return render(
        request,
        "stock_opname/opname_form.html",
        {
            "form": form,
            "title": f"Edit Stock Opname — {opname.document_number or 'draft'}",
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
        _annotate_current_stock_status(item, opname)
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
            if item.has_current_discrepancy:
                locations[loc.pk]["discrepancies"] += 1

    # F11: Compute summary from the already-evaluated `items` queryset so we
    # don't fire 5 extra COUNT queries that duplicate the loop above.
    items_list = list(items)
    total_items = len(items_list)
    counted_items = sum(1 for i in items_list if i.actual_quantity is not None)
    discrepancy_count = sum(
        1 for i in items_list
        if i.actual_quantity is not None and i.has_current_discrepancy
    )
    progress = int((counted_items / total_items) * 100) if total_items > 0 else 0
    can_complete_opname = _user_can_complete_opname(
        request.user,
        discrepancy_count > 0,
    )

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
            "can_complete_opname": can_complete_opname,
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

            issue_document_number(
                DocumentNumberRule.Key.STOCK_OPNAME,
                business_date=opname.period_end,
                target=opname,
                actor=request.user,
            )

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
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("stock_opname:opname_detail", pk=pk)
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
        _annotate_current_stock_status(item, opname)

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
        return redirect("stock_opname:opname_detail", pk=opname.pk)

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
def opname_complete(request, pk):
    """Finalize a stock opname session."""
    opname = get_object_or_404(StockOpname, pk=pk)

    if request.method == "POST":
        try:
            with transaction.atomic():
                opname = StockOpname.objects.select_for_update().get(pk=pk)
                counted_items = list(
                    opname.items.select_for_update()
                    .select_related("stock")
                    .order_by("pk")
                )
                if opname.status != StockOpname.Status.IN_PROGRESS:
                    messages.error(
                        request,
                        "Stock Opname ini sudah diselesaikan atau belum dimulai.",
                    )
                    return redirect("stock_opname:opname_detail", pk=opname.pk)
                if not counted_items or all(
                    item.actual_quantity is None for item in counted_items
                ):
                    messages.error(
                        request,
                        "Stock Opname belum dapat diselesaikan karena belum ada item yang dihitung.",
                    )
                    return redirect("stock_opname:opname_detail", pk=opname.pk)
                if any(item.actual_quantity is None for item in counted_items):
                    messages.error(
                        request,
                        "Stock Opname belum dapat diselesaikan karena masih ada item yang belum dihitung.",
                    )
                    return redirect("stock_opname:opname_detail", pk=opname.pk)
                has_current_discrepancy = any(
                    item.actual_quantity != item.stock.quantity
                    for item in counted_items
                )
                if has_current_discrepancy and not _user_can_complete_opname(
                    request.user,
                    has_current_discrepancy=True,
                ):
                    raise PermissionDenied(
                        "Stock Opname dengan selisih hanya dapat diselesaikan oleh approver."
                    )

                opname.status = StockOpname.Status.COMPLETED
                opname.completed_by = request.user
                opname.completed_at = timezone.now()
                completion_time = opname.completed_at
                for item in counted_items:
                    item.completion_stock_quantity = item.stock.quantity
                    item.updated_at = completion_time
                StockOpnameItem.objects.bulk_update(
                    counted_items,
                    ["completion_stock_quantity", "updated_at"],
                )
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
def opname_report_print(request, pk):
    """Printable full stock opname report."""
    opname = get_object_or_404(
        StockOpname.objects.select_related("created_by", "completed_by")
        .prefetch_related("assigned_to"),
        pk=pk,
    )

    items = (
        opname.items.select_related(
            "stock__item",
            "stock__item__satuan",
            "stock__location",
            "stock__sumber_dana",
        )
        .order_by(
            "stock__location__code", "stock__expiry_date", "stock__item__nama_barang"
        )
    )

    locations = {}
    total_items = 0
    counted_items = 0
    discrepancy_count = 0
    for item in items:
        _annotate_current_stock_status(item, opname)
        loc = item.stock.location
        if loc.pk not in locations:
            locations[loc.pk] = {
                "location": loc,
                "items": [],
            }
        locations[loc.pk]["items"].append(item)
        total_items += 1
        if item.actual_quantity is not None:
            counted_items += 1
            if item.has_current_discrepancy:
                discrepancy_count += 1

    return render(
        request,
        "stock_opname/opname_report_print.html",
        {
            "opname": opname,
            "locations": locations.values(),
            "assigned_users": opname.assigned_to.all(),
            "total_items": total_items,
            "counted_items": counted_items,
            "discrepancy_count": discrepancy_count,
            "print_date": timezone.now(),
        },
    )


@login_required
@perm_required("stock_opname.view_stockopname")
def opname_print(request, pk):
    """Printable discrepancy report — shows only items where physical count differs from current stock."""
    opname = get_object_or_404(
        StockOpname.objects.select_related("created_by", "completed_by"),
        pk=pk,
    )

    items = (
        opname.items.select_related(
            "stock__item",
            "stock__item__satuan",
            "stock__location",
            "stock__sumber_dana",
        )
        .filter(actual_quantity__isnull=False)
        .order_by(
            "stock__location__code", "stock__expiry_date", "stock__item__nama_barang"
        )
    )

    # Group by location
    locations = {}
    discrepancy_list = []
    for item in items:
        _annotate_current_stock_status(item, opname)
        if not item.has_current_discrepancy:
            continue
        discrepancy_list.append(item)
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
        with transaction.atomic():
            opname = get_object_or_404(
                StockOpname.objects.select_for_update(),
                pk=opname.pk,
                status__in=[
                    StockOpname.Status.DRAFT,
                    StockOpname.Status.IN_PROGRESS,
                ],
            )
            void_document_number(
                opname,
                actor=request.user,
                reason="Stock opname dihapus sebelum selesai.",
            )
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
