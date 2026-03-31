from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.decorators import module_scope_required, perm_required
from apps.distribution.models import Distribution, DistributionItem
from apps.items.models import Item
from apps.stock.models import Stock
from apps.users.models import ModuleAccess

from .forms import LPLPOCreateForm, LPLPOItemPuskesmasForm, LPLPOItemReviewForm
from .models import LPLPO, LPLPOItem, get_penerimaan_for_facility_period, get_previous_lplpo


# ══════════════════════════ List Views ══════════════════════════


@login_required
def lplpo_list(request):
    """All LPLPOs — for Instalasi Farmasi staff."""
    if getattr(request.user, "role", "") == "PUSKESMAS":
        return redirect("lplpo:lplpo_my_list")

    queryset = LPLPO.objects.select_related("facility", "created_by").order_by(
        "-tahun", "-bulan"
    )

    q = request.GET.get("q", "").strip()
    if q:
        queryset = queryset.filter(
            Q(document_number__icontains=q) | Q(facility__name__icontains=q)
        )

    status = request.GET.get("status", "")
    if status:
        queryset = queryset.filter(status=status)

    tahun = request.GET.get("tahun", "")
    if tahun:
        queryset = queryset.filter(tahun=tahun)

    paginator = Paginator(queryset, 25)
    page = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "lplpo/lplpo_list.html",
        {
            "lplpos": page,
            "search": q,
            "selected_status": status,
            "selected_tahun": tahun,
            "status_choices": LPLPO.Status.choices,
            "is_all": True,
        },
    )


@login_required
def lplpo_my_list(request):
    """Own-facility LPLPOs — for Puskesmas operators."""
    if not request.user.facility:
        messages.warning(
            request,
            "Akun Anda belum terhubung ke fasilitas. Hubungi administrator.",
        )
        return render(
            request,
            "lplpo/lplpo_list.html",
            {"lplpos": [], "is_all": False, "status_choices": LPLPO.Status.choices},
        )

    queryset = LPLPO.objects.filter(facility=request.user.facility).select_related(
        "facility", "created_by"
    ).order_by("-tahun", "-bulan")

    status = request.GET.get("status", "")
    if status:
        queryset = queryset.filter(status=status)

    paginator = Paginator(queryset, 25)
    page = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "lplpo/lplpo_list.html",
        {
            "lplpos": page,
            "selected_status": status,
            "status_choices": LPLPO.Status.choices,
            "is_all": False,
        },
    )


# ══════════════════════════ Create ══════════════════════════


@login_required
@perm_required("lplpo.add_lplpo")
def lplpo_create(request):
    """Create a new LPLPO for a given period. Auto-generates all item lines."""
    if request.method == "POST":
        form = LPLPOCreateForm(request.POST)
        if form.is_valid():
            bulan = int(form.cleaned_data["bulan"])
            tahun = int(form.cleaned_data["tahun"])

            # Determine facility
            facility = request.user.facility
            if not facility:
                facility = form.cleaned_data.get("facility")

            if not facility:
                messages.error(
                    request,
                    "Pilih fasilitas puskesmas atau hubungi administrator untuk menghubungkan akun Anda.",
                )
                return render(request, "lplpo/lplpo_create.html", {"form": form})

            # Check uniqueness
            if LPLPO.objects.filter(
                facility=facility, bulan=bulan, tahun=tahun
            ).exists():
                messages.error(
                    request,
                    f"LPLPO untuk {facility.name} periode {bulan}/{tahun} sudah ada.",
                )
                return render(request, "lplpo/lplpo_create.html", {"form": form})

            with transaction.atomic():
                lplpo = LPLPO.objects.create(
                    facility=facility,
                    bulan=bulan,
                    tahun=tahun,
                    status=LPLPO.Status.DRAFT,
                    created_by=request.user,
                    notes=form.cleaned_data.get("notes", ""),
                )

                # Auto-fill from previous LPLPO
                prev_lplpo = get_previous_lplpo(facility, bulan, tahun)
                prev_stock = {}
                if prev_lplpo:
                    for pi in prev_lplpo.items.all():
                        prev_stock[pi.item_id] = pi.stock_keseluruhan

                # Auto-fill penerimaan from distributions
                penerimaan_data = get_penerimaan_for_facility_period(
                    facility, bulan, tahun
                )

                # Generate one LPLPOItem per active Item
                active_items = Item.objects.filter(is_active=True).order_by(
                    "kategori__sort_order", "nama_barang"
                )

                lplpo_items = []
                for item in active_items:
                    stock_awal = prev_stock.get(item.pk, Decimal("0"))
                    penerimaan = penerimaan_data.get(item.pk, Decimal("0"))
                    has_auto_fill = item.pk in penerimaan_data

                    li = LPLPOItem(
                        lplpo=lplpo,
                        item=item,
                        stock_awal=stock_awal,
                        penerimaan=penerimaan,
                        penerimaan_auto_filled=has_auto_fill,
                    )
                    li.compute_fields()
                    lplpo_items.append(li)

                LPLPOItem.objects.bulk_create(lplpo_items)

            messages.success(
                request,
                f"LPLPO {lplpo.document_number} berhasil dibuat dengan {len(lplpo_items)} item.",
            )
            return redirect("lplpo:lplpo_detail", pk=lplpo.pk)
    else:
        form = LPLPOCreateForm()

    return render(request, "lplpo/lplpo_create.html", {"form": form})


# ══════════════════════════ Detail ══════════════════════════


@login_required
def lplpo_detail(request, pk):
    """Read-only full view of an LPLPO."""
    lplpo = get_object_or_404(
        LPLPO.objects.select_related(
            "facility", "created_by", "reviewed_by", "distribution"
        ),
        pk=pk,
    )

    # Enforce facility scope for PUSKESMAS role
    if (
        request.user.role == "PUSKESMAS"
        and request.user.facility
        and lplpo.facility != request.user.facility
    ):
        messages.error(request, "Anda tidak memiliki akses ke LPLPO ini.")
        return redirect("lplpo:lplpo_my_list")

    items = lplpo.items.select_related(
        "item", "item__satuan", "item__kategori"
    ).order_by("item__kategori__sort_order", "item__nama_barang")

    # Group items by category for display
    grouped_items = {}
    for li in items:
        cat_name = li.item.kategori.name if li.item.kategori else "Lainnya"
        grouped_items.setdefault(cat_name, []).append(li)

    return render(
        request,
        "lplpo/lplpo_detail.html",
        {
            "lplpo": lplpo,
            "grouped_items": grouped_items,
            "items": items,
        },
    )


# ══════════════════════════ Edit (Puskesmas) ══════════════════════════


@login_required
@perm_required("lplpo.change_lplpo")
def lplpo_edit(request, pk):
    """Puskesmas fills their columns — only DRAFT status."""
    lplpo_obj = get_object_or_404(LPLPO.objects.select_related("facility"), pk=pk)

    if lplpo_obj.status != LPLPO.Status.DRAFT:
        messages.error(request, "Hanya LPLPO berstatus Draft yang dapat diedit.")
        return redirect("lplpo:lplpo_detail", pk=pk)

    # Enforce facility scope
    if (
        request.user.role == "PUSKESMAS"
        and request.user.facility
        and lplpo_obj.facility != request.user.facility
    ):
        messages.error(request, "Anda tidak memiliki akses ke LPLPO ini.")
        return redirect("lplpo:lplpo_my_list")

    items_qs = lplpo_obj.items.select_related(
        "item", "item__satuan", "item__kategori"
    ).order_by("item__kategori__sort_order", "item__nama_barang")

    # Check if previous LPLPO exists (to lock stock_awal)
    prev_lplpo = get_previous_lplpo(
        lplpo_obj.facility, lplpo_obj.bulan, lplpo_obj.tahun
    )
    has_prev = prev_lplpo is not None

    if request.method == "POST":
        all_valid = True
        forms_data = []
        for li in items_qs:
            f = LPLPOItemPuskesmasForm(
                request.POST, instance=li, prefix=f"item_{li.pk}"
            )
            if f.is_valid():
                forms_data.append(f)
            else:
                all_valid = False
                forms_data.append(f)

        if all_valid:
            for f in forms_data:
                obj = f.save(commit=False)
                obj.compute_fields()
                # Pre-set pemberian suggestion
                obj.pemberian_jumlah = obj.jumlah_kebutuhan
                obj.save()

            messages.success(request, f"LPLPO {lplpo_obj.document_number} berhasil disimpan.")
            return redirect("lplpo:lplpo_detail", pk=pk)
    else:
        forms_data = [
            LPLPOItemPuskesmasForm(instance=li, prefix=f"item_{li.pk}")
            for li in items_qs
        ]

    # Build (item, form) pairs grouped by category
    item_forms = list(zip(items_qs, forms_data))
    grouped = {}
    for li, f in item_forms:
        cat_name = li.item.kategori.name if li.item.kategori else "Lainnya"
        grouped.setdefault(cat_name, []).append((li, f))

    return render(
        request,
        "lplpo/lplpo_edit.html",
        {
            "lplpo": lplpo_obj,
            "grouped": grouped,
            "has_prev": has_prev,
        },
    )


# ══════════════════════════ Submit ══════════════════════════


@login_required
@perm_required("lplpo.change_lplpo")
def lplpo_submit(request, pk):
    """Transition DRAFT → SUBMITTED."""
    lplpo_obj = get_object_or_404(LPLPO, pk=pk)
    if request.method != "POST":
        return redirect("lplpo:lplpo_detail", pk=pk)

    if lplpo_obj.status != LPLPO.Status.DRAFT:
        messages.error(request, "Hanya LPLPO berstatus Draft yang dapat diajukan.")
        return redirect("lplpo:lplpo_detail", pk=pk)

    lplpo_obj.status = LPLPO.Status.SUBMITTED
    lplpo_obj.submitted_at = timezone.now()
    lplpo_obj.save(update_fields=["status", "submitted_at", "updated_at"])

    messages.success(request, f"LPLPO {lplpo_obj.document_number} berhasil diajukan.")
    return redirect("lplpo:lplpo_detail", pk=pk)


# ══════════════════════════ Review (Instalasi Farmasi) ══════════════════════════


@login_required
@perm_required("lplpo.change_lplpo")
@module_scope_required(ModuleAccess.Module.LPLPO, ModuleAccess.Scope.OPERATE)
def lplpo_review(request, pk):
    """Instalasi Farmasi fills pemberian columns. SUBMITTED → REVIEWED."""
    lplpo_obj = get_object_or_404(
        LPLPO.objects.select_related("facility"), pk=pk
    )

    if lplpo_obj.status != LPLPO.Status.SUBMITTED:
        messages.error(request, "Hanya LPLPO berstatus Diajukan yang dapat ditinjau.")
        return redirect("lplpo:lplpo_detail", pk=pk)

    items_qs = lplpo_obj.items.select_related(
        "item", "item__satuan", "item__kategori"
    ).order_by("item__kategori__sort_order", "item__nama_barang")

    # Get current warehouse stock for each item
    warehouse_stock = {}
    stock_entries = (
        Stock.objects.filter(item__in=[li.item for li in items_qs])
        .values("item_id")
        .annotate(total_qty=Sum("quantity"))
    )
    for entry in stock_entries:
        warehouse_stock[entry["item_id"]] = entry["total_qty"] or Decimal("0")

    if request.method == "POST":
        all_valid = True
        forms_data = []
        for li in items_qs:
            f = LPLPOItemReviewForm(
                request.POST, instance=li, prefix=f"review_{li.pk}"
            )
            if f.is_valid():
                forms_data.append(f)
            else:
                all_valid = False
                forms_data.append(f)

        if all_valid:
            with transaction.atomic():
                for f in forms_data:
                    f.save()

                lplpo_obj.status = LPLPO.Status.REVIEWED
                lplpo_obj.reviewed_by = request.user
                lplpo_obj.reviewed_at = timezone.now()
                lplpo_obj.save(
                    update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"]
                )

            messages.success(
                request,
                f"LPLPO {lplpo_obj.document_number} berhasil ditinjau.",
            )
            return redirect("lplpo:lplpo_detail", pk=pk)
    else:
        forms_data = [
            LPLPOItemReviewForm(instance=li, prefix=f"review_{li.pk}")
            for li in items_qs
        ]

    # Build display data with stock
    item_forms = []
    for li, f in zip(items_qs, forms_data):
        item_forms.append(
            {
                "item_obj": li,
                "form": f,
                "stock_gudang": warehouse_stock.get(li.item_id, Decimal("0")),
            }
        )

    # Group by category
    grouped = {}
    for entry in item_forms:
        cat_name = (
            entry["item_obj"].item.kategori.name
            if entry["item_obj"].item.kategori
            else "Lainnya"
        )
        grouped.setdefault(cat_name, []).append(entry)

    return render(
        request,
        "lplpo/lplpo_review.html",
        {
            "lplpo": lplpo_obj,
            "grouped": grouped,
        },
    )


# ══════════════════════════ Finalize ══════════════════════════


@login_required
@perm_required("lplpo.change_lplpo")
@module_scope_required(ModuleAccess.Module.LPLPO, ModuleAccess.Scope.APPROVE)
def lplpo_finalize(request, pk):
    """Create Distribution from REVIEWED LPLPO. REVIEWED → DISTRIBUTED."""
    lplpo_obj = get_object_or_404(
        LPLPO.objects.select_related("facility"), pk=pk
    )
    if request.method != "POST":
        return redirect("lplpo:lplpo_detail", pk=pk)

    if lplpo_obj.status != LPLPO.Status.REVIEWED:
        messages.error(
            request, "Hanya LPLPO berstatus Ditinjau yang dapat difinalisasi."
        )
        return redirect("lplpo:lplpo_detail", pk=pk)

    items_with_pemberian = list(
        lplpo_obj.items.filter(pemberian_jumlah__gt=0).select_related("item")
    )

    if not items_with_pemberian:
        messages.error(
            request,
            "Tidak ada item dengan pemberian > 0 untuk dibuatkan distribusi.",
        )
        return redirect("lplpo:lplpo_detail", pk=pk)

    try:
        with transaction.atomic():
            dist = Distribution.objects.create(
                distribution_type=Distribution.DistributionType.LPLPO,
                facility=lplpo_obj.facility,
                request_date=date(lplpo_obj.tahun, lplpo_obj.bulan, 1),
                status=Distribution.Status.DRAFT,
                created_by=request.user,
                notes=f"Dibuat otomatis dari LPLPO {lplpo_obj.document_number}.",
            )

            DistributionItem.objects.bulk_create(
                [
                    DistributionItem(
                        distribution=dist,
                        item=li.item,
                        quantity_requested=li.permintaan_jumlah,
                        quantity_approved=li.pemberian_jumlah,
                    )
                    for li in items_with_pemberian
                ]
            )

            lplpo_obj.distribution = dist
            lplpo_obj.status = LPLPO.Status.DISTRIBUTED
            lplpo_obj.save(
                update_fields=["distribution", "status", "updated_at"]
            )

    except Exception as exc:
        messages.error(
            request, f"Terjadi kesalahan saat memfinalisasi LPLPO: {exc}"
        )
        return redirect("lplpo:lplpo_detail", pk=pk)

    messages.success(
        request,
        f"LPLPO {lplpo_obj.document_number} difinalisasi. "
        f"Distribusi {dist.document_number} telah dibuat sebagai Draft.",
    )
    return redirect("lplpo:lplpo_detail", pk=pk)


# ══════════════════════════ Print ══════════════════════════


@login_required
def lplpo_print(request, pk):
    """Print-friendly HTML version of the LPLPO."""
    lplpo_obj = get_object_or_404(
        LPLPO.objects.select_related("facility", "created_by", "reviewed_by"),
        pk=pk,
    )

    items = lplpo_obj.items.select_related(
        "item", "item__satuan", "item__kategori"
    ).order_by("item__kategori__sort_order", "item__nama_barang")

    grouped_items = {}
    for li in items:
        cat_name = li.item.kategori.name if li.item.kategori else "Lainnya"
        grouped_items.setdefault(cat_name, []).append(li)

    return render(
        request,
        "lplpo/lplpo_print.html",
        {
            "lplpo": lplpo_obj,
            "grouped_items": grouped_items,
        },
    )
