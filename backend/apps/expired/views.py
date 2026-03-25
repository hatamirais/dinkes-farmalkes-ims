from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import DecimalField, Exists, ExpressionWrapper, F, OuterRef, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from datetime import timedelta

from apps.core.decorators import module_scope_required, perm_required
from apps.stock.models import Stock, Transaction
from apps.items.models import Location
from apps.users.models import ModuleAccess

from .forms import ExpiredForm, ExpiredItemFormSet
from .models import Expired, ExpiredItem


@login_required
def expired_list(request):
    queryset = Expired.objects.select_related("created_by").order_by("-report_date")

    search = request.GET.get("q", "").strip()
    if search:
        queryset = queryset.filter(document_number__icontains=search)

    status = request.GET.get("status")
    if status:
        queryset = queryset.filter(status=status)

    paginator = Paginator(queryset, 25)
    items = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "expired/expired_list.html",
        {
            "expired_items": items,
            "search": search,
            "selected_status": status or "",
            "status_draft": "selected" if status == Expired.Status.DRAFT else "",
            "status_submitted": "selected"
            if status == Expired.Status.SUBMITTED
            else "",
            "status_verified": "selected" if status == Expired.Status.VERIFIED else "",
            "status_disposed": "selected" if status == Expired.Status.DISPOSED else "",
        },
    )


@login_required
@perm_required("expired.add_expired")
def expired_create(request):
    if request.method == "POST":
        form = ExpiredForm(request.POST)
        formset = ExpiredItemFormSet(request.POST, prefix="items")

        if form.is_valid() and formset.is_valid():
            expired_doc = form.save(commit=False)
            expired_doc.created_by = request.user
            expired_doc.status = Expired.Status.DRAFT
            expired_doc.save()

            formset.instance = expired_doc
            formset.save()

            messages.success(
                request,
                f"Dokumen expired {expired_doc.document_number} berhasil dibuat.",
            )
            return redirect("expired:expired_detail", pk=expired_doc.pk)
    else:
        form = ExpiredForm()
        stock_ids_param = request.GET.get("stocks", "").strip()
        initial_rows = []
        if stock_ids_param:
            try:
                stock_ids = [
                    int(v) for v in stock_ids_param.split(",") if v.strip().isdigit()
                ]
            except ValueError:
                stock_ids = []

            selected_stocks = (
                Stock.objects.filter(pk__in=stock_ids)
                .select_related("item")
                .filter(quantity__gt=F("reserved"))
            )
            for stock in selected_stocks:
                initial_rows.append(
                    {
                        "item": stock.item_id,
                        "stock": stock.id,
                        "quantity": stock.available_quantity,
                    }
                )

        formset = ExpiredItemFormSet(prefix="items", initial=initial_rows)

    return render(
        request,
        "expired/expired_form.html",
        {
            "form": form,
            "formset": formset,
            "title": "Buat Dokumen Expired",
            "is_edit": False,
        },
    )


@login_required
def expired_alerts(request):
    """Monitoring stok kedaluwarsa/mendekati kedaluwarsa yang belum diproses."""
    today = timezone.now().date()
    threshold = today + timedelta(days=90)

    queryset = (
        Stock.objects.select_related(
            "item", "item__kategori", "location", "sumber_dana"
        )
        .filter(quantity__gt=F("reserved"))
        .filter(expiry_date__lte=threshold)
    )

    processed_subquery = ExpiredItem.objects.filter(
        stock_id=OuterRef("pk"),
        expired__status__in=[
            Expired.Status.SUBMITTED,
            Expired.Status.VERIFIED,
            Expired.Status.DISPOSED,
        ],
    )
    queryset = queryset.annotate(
        is_processed=Exists(processed_subquery),
        available_qty=ExpressionWrapper(
            F("quantity") - F("reserved"),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
    )

    search = request.GET.get("q", "").strip()
    if search:
        queryset = queryset.filter(
            Q(item__kode_barang__icontains=search)
            | Q(item__nama_barang__icontains=search)
            | Q(item__kategori__name__icontains=search)
            | Q(batch_lot__icontains=search)
        )

    location = request.GET.get("location", "").strip()
    if location:
        queryset = queryset.filter(location_id=location)

    level = request.GET.get("level", "all").strip()
    if level == "expired":
        queryset = queryset.filter(expiry_date__lt=today)
    elif level == "near":
        queryset = queryset.filter(expiry_date__gte=today, expiry_date__lte=threshold)

    pending_only = request.GET.get("pending", "1") == "1"
    if pending_only:
        queryset = queryset.filter(is_processed=False)

    sort = request.GET.get("sort", "expiry").strip()
    direction = request.GET.get("dir", "asc").strip().lower()
    sort_map = {
        "code": "item__kode_barang",
        "name": "item__nama_barang",
        "category": "item__kategori__name",
        "batch": "batch_lot",
        "location": "location__name",
        "expiry": "expiry_date",
        "available": "available_qty",
        "processed": "is_processed",
    }
    sort_field = sort_map.get(sort, "expiry_date")
    if direction == "desc":
        sort_field = f"-{sort_field}"

    queryset = queryset.order_by(
        sort_field, "expiry_date", "item__nama_barang", "batch_lot"
    )

    base_params = request.GET.copy()

    def _build_sort_url(sort_key):
        params = base_params.copy()
        params.pop("page", None)
        if sort == sort_key:
            params["dir"] = "desc" if direction == "asc" else "asc"
        else:
            params["sort"] = sort_key
            params["dir"] = "asc"
        return f"?{params.urlencode()}"

    sort_urls = {
        "code": _build_sort_url("code"),
        "name": _build_sort_url("name"),
        "category": _build_sort_url("category"),
        "batch": _build_sort_url("batch"),
        "location": _build_sort_url("location"),
        "expiry": _build_sort_url("expiry"),
        "available": _build_sort_url("available"),
        "processed": _build_sort_url("processed"),
    }

    rows = []
    for stock in queryset:
        days_to_expiry = (stock.expiry_date - today).days
        if stock.expiry_date < today:
            expiry_status = "expired"
        elif days_to_expiry <= 30:
            expiry_status = "near-critical"
        else:
            expiry_status = "near"
        rows.append(
            {
                "stock": stock,
                "available": stock.available_quantity,
                "days_to_expiry": days_to_expiry,
                "expiry_status": expiry_status,
            }
        )

    paginator = Paginator(rows, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    locations = []
    for loc in Location.objects.filter(is_active=True).order_by("code"):
        locations.append(
            {
                "id": loc.id,
                "name": loc.name,
                "selected": "selected" if location == str(loc.id) else "",
            }
        )

    return render(
        request,
        "expired/expired_alerts.html",
        {
            "items": page_obj,
            "search": search,
            "locations": locations,
            "selected_location": location,
            "selected_level": level,
            "pending_only": pending_only,
            "selected_sort": sort,
            "selected_dir": direction,
            "sort_urls": sort_urls,
            "today": today,
        },
    )


@login_required
@perm_required("expired.change_expired")
def expired_edit(request, pk):
    expired_doc = get_object_or_404(Expired, pk=pk)
    if expired_doc.status not in (Expired.Status.DRAFT, Expired.Status.SUBMITTED):
        messages.error(request, "Hanya dokumen Draft/Diajukan yang dapat diubah.")
        return redirect("expired:expired_detail", pk=expired_doc.pk)

    if request.method == "POST":
        form = ExpiredForm(request.POST, instance=expired_doc)
        formset = ExpiredItemFormSet(request.POST, instance=expired_doc, prefix="items")

        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(
                request, f"Dokumen {expired_doc.document_number} berhasil diperbarui."
            )
            return redirect("expired:expired_detail", pk=expired_doc.pk)
    else:
        form = ExpiredForm(instance=expired_doc)
        formset = ExpiredItemFormSet(instance=expired_doc, prefix="items")

    return render(
        request,
        "expired/expired_form.html",
        {
            "form": form,
            "formset": formset,
            "title": f"Edit Dokumen {expired_doc.document_number}",
            "is_edit": True,
            "expired_doc": expired_doc,
        },
    )


@login_required
def expired_detail(request, pk):
    expired_doc = get_object_or_404(
        Expired.objects.select_related("created_by", "verified_by", "disposed_by"),
        pk=pk,
    )
    items = expired_doc.items.select_related(
        "item",
        "item__satuan",
        "stock",
        "stock__location",
        "stock__sumber_dana",
    )

    return render(
        request,
        "expired/expired_detail.html",
        {
            "expired_doc": expired_doc,
            "items": items,
        },
    )


@login_required
@perm_required("expired.change_expired")
def expired_submit(request, pk):
    expired_doc = get_object_or_404(Expired, pk=pk)
    if request.method != "POST":
        return redirect("expired:expired_detail", pk=pk)

    if expired_doc.status != Expired.Status.DRAFT:
        messages.error(request, "Hanya dokumen Draft yang dapat diajukan.")
        return redirect("expired:expired_detail", pk=pk)

    if not expired_doc.items.exists():
        messages.error(request, "Tambahkan minimal 1 item sebelum mengajukan dokumen.")
        return redirect("expired:expired_detail", pk=pk)

    expired_doc.status = Expired.Status.SUBMITTED
    expired_doc.save(update_fields=["status", "updated_at"])
    messages.success(
        request, f"Dokumen {expired_doc.document_number} berhasil diajukan."
    )
    return redirect("expired:expired_detail", pk=pk)


@login_required
@perm_required("expired.change_expired")
@module_scope_required(ModuleAccess.Module.EXPIRED, ModuleAccess.Scope.APPROVE)
def expired_verify(request, pk):
    expired_doc = get_object_or_404(Expired, pk=pk)
    if request.method != "POST":
        return redirect("expired:expired_detail", pk=pk)

    if expired_doc.status != Expired.Status.SUBMITTED:
        messages.error(
            request, "Hanya dokumen berstatus Diajukan yang dapat diverifikasi."
        )
        return redirect("expired:expired_detail", pk=pk)

    expired_items = list(expired_doc.items.select_related("item", "stock"))
    if not expired_items:
        messages.error(request, "Dokumen tidak memiliki item untuk diverifikasi.")
        return redirect("expired:expired_detail", pk=pk)

    try:
        with transaction.atomic():
            for expired_item in expired_items:
                stock = Stock.objects.select_for_update().get(pk=expired_item.stock_id)

                if stock.item_id != expired_item.item_id:
                    raise ValueError(
                        f"Batch stok tidak sesuai untuk item {expired_item.item.nama_barang}."
                    )

                if expired_item.quantity > stock.available_quantity:
                    raise ValueError(
                        f"Stok tidak cukup untuk {expired_item.item.nama_barang}. "
                        f"Tersedia {stock.available_quantity}, diminta {expired_item.quantity}."
                    )

                stock.quantity = stock.quantity - expired_item.quantity
                stock.save(update_fields=["quantity", "updated_at"])

                Transaction.objects.create(
                    transaction_type=Transaction.TransactionType.OUT,
                    item=expired_item.item,
                    location=stock.location,
                    batch_lot=stock.batch_lot,
                    quantity=expired_item.quantity,
                    unit_price=stock.unit_price,
                    sumber_dana=stock.sumber_dana,
                    reference_type=Transaction.ReferenceType.EXPIRED,
                    reference_id=expired_doc.id,
                    user=request.user,
                    notes=f"Expired {expired_doc.document_number}: {expired_item.notes}".strip(),
                )

            expired_doc.status = Expired.Status.VERIFIED
            expired_doc.verified_by = request.user
            expired_doc.verified_at = timezone.now()
            expired_doc.save(
                update_fields=["status", "verified_by", "verified_at", "updated_at"]
            )

    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("expired:expired_detail", pk=pk)

    messages.success(
        request,
        f"Dokumen {expired_doc.document_number} berhasil diverifikasi dan stok diperbarui.",
    )
    return redirect("expired:expired_detail", pk=pk)


@login_required
@perm_required("expired.change_expired")
@module_scope_required(ModuleAccess.Module.EXPIRED, ModuleAccess.Scope.APPROVE)
def expired_dispose(request, pk):
    expired_doc = get_object_or_404(Expired, pk=pk)
    if request.method != "POST":
        return redirect("expired:expired_detail", pk=pk)

    if expired_doc.status != Expired.Status.VERIFIED:
        messages.error(
            request, "Hanya dokumen terverifikasi yang dapat ditandai dimusnahkan."
        )
        return redirect("expired:expired_detail", pk=pk)

    expired_doc.status = Expired.Status.DISPOSED
    expired_doc.disposed_by = request.user
    expired_doc.disposed_at = timezone.now()
    expired_doc.save(
        update_fields=["status", "disposed_by", "disposed_at", "updated_at"]
    )
    messages.success(
        request, f"Dokumen {expired_doc.document_number} ditandai dimusnahkan."
    )
    return redirect("expired:expired_detail", pk=pk)


@login_required
@perm_required("expired.delete_expired")
def expired_delete(request, pk):
    expired_doc = get_object_or_404(Expired, pk=pk)
    if request.method != "POST":
        return redirect("expired:expired_detail", pk=pk)

    if expired_doc.status != Expired.Status.DRAFT:
        messages.error(request, "Hanya dokumen Draft yang dapat dihapus.")
        return redirect("expired:expired_detail", pk=pk)

    doc_number = expired_doc.document_number
    expired_doc.delete()
    messages.success(request, f"Dokumen {doc_number} berhasil dihapus.")
    return redirect("expired:expired_list")
