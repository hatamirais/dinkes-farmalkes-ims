from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, F
from django.utils import timezone

from apps.core.decorators import perm_required
from apps.stock.models import Stock

from .models import StockOpname, StockOpnameItem
from .forms import StockOpnameForm


@login_required
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
            "title": f"Edit Stock Opname — {opname.document_number}",
        },
    )


@login_required
def opname_detail(request, pk):
    opname = get_object_or_404(
        StockOpname.objects.select_related("created_by"),
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
def opname_start(request, pk):
    """Transition DRAFT → IN_PROGRESS and snapshot stock quantities filtered by categories."""
    opname = get_object_or_404(StockOpname, pk=pk, status=StockOpname.Status.DRAFT)

    if request.method == "POST":
        stocks = Stock.objects.filter(quantity__gt=0).select_related(
            "item",
            "location",
            "sumber_dana",
        )

        # Filter by assigned categories
        selected_categories = opname.categories.all()
        if selected_categories.exists():
            stocks = stocks.filter(item__kategori__in=selected_categories)

        with transaction.atomic():
            opname_items = []
            for stock in stocks:
                opname_items.append(
                    StockOpnameItem(
                        stock_opname=opname,
                        stock=stock,
                        system_quantity=stock.quantity,
                    )
                )
            StockOpnameItem.objects.bulk_create(opname_items)

            opname.status = StockOpname.Status.IN_PROGRESS
            opname.save(update_fields=["status", "updated_at"])

        messages.success(
            request,
            f"Stock Opname dimulai. {len(opname_items)} item stok berhasil di-snapshot.",
        )
        return redirect("stock_opname:opname_detail", pk=opname.pk)

    return redirect("stock_opname:opname_detail", pk=opname.pk)


@login_required
@perm_required("stock_opname.change_stockopnameitem")
def opname_input(request, pk):
    """Input actual quantities for a stock opname session."""
    opname = get_object_or_404(
        StockOpname,
        pk=pk,
        status=StockOpname.Status.IN_PROGRESS,
    )

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

    if request.method == "POST":
        updated = 0
        for item in items:
            qty_key = f"qty_{item.pk}"
            notes_key = f"notes_{item.pk}"
            qty_val = request.POST.get(qty_key, "").strip()
            notes_val = request.POST.get(notes_key, "").strip()

            if qty_val:
                try:
                    from decimal import Decimal

                    actual = Decimal(qty_val)
                    item.actual_quantity = actual
                    item.notes = notes_val
                    item.save(update_fields=["actual_quantity", "notes"])
                    updated += 1
                except Exception:
                    pass

        messages.success(request, f"{updated} item berhasil diperbarui.")
        # Redirect back with same location filter
        url = f"/stock-opname/{pk}/input/"
        if location_id:
            url += f"?location={location_id}"
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
def opname_complete(request, pk):
    """Finalize a stock opname session."""
    opname = get_object_or_404(
        StockOpname,
        pk=pk,
        status=StockOpname.Status.IN_PROGRESS,
    )

    if request.method == "POST":
        opname.status = StockOpname.Status.COMPLETED
        opname.completed_at = timezone.now()
        opname.save(update_fields=["status", "completed_at", "updated_at"])
        messages.success(
            request, f"Stock Opname {opname.document_number} telah diselesaikan."
        )
        return redirect("stock_opname:opname_detail", pk=opname.pk)

    return redirect("stock_opname:opname_detail", pk=opname.pk)


@login_required
def opname_print(request, pk):
    """Printable discrepancy report — shows only items where actual ≠ system."""
    opname = get_object_or_404(
        StockOpname.objects.select_related("created_by"),
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
