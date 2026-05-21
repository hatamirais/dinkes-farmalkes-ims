from datetime import date
from decimal import Decimal
import calendar
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.decorators import module_scope_required, perm_required
from apps.distribution.models import Distribution, DistributionItem
from apps.distribution.services import assign_default_distribution_staff
from apps.items.models import Facility, Item
from apps.stock.models import Stock
from apps.users.access import has_module_scope
from apps.users.models import ModuleAccess, User

from .forms import LPLPOCreateForm, LPLPOItemPuskesmasForm, LPLPOItemReviewForm, RejectLPLPOForm
from .models import (
    LPLPO,
    LPLPOItem,
    format_lplpo_period_label,
    get_active_lplpo_year,
    get_next_required_lplpo_period,
    get_penerimaan_for_facility_period,
    get_previous_lplpo,
)

logger = logging.getLogger(__name__)


def _is_super_admin(user):
    return bool(getattr(user, "is_superuser", False))


def _check_facility_access(request, lplpo_obj):
    """
    Returns a redirect response if the current PUSKESMAS user is trying
    to access an LPLPO that belongs to a different facility.
    Returns None if access is allowed.
    """
    if _is_super_admin(request.user) or request.user.role != User.Role.PUSKESMAS:
        return None  # Non-puskesmas roles can see all
    if not request.user.facility:
        messages.error(request, "Akun Anda belum terhubung ke fasilitas.")
        return redirect("lplpo:lplpo_my_list")
    if lplpo_obj.facility_id != request.user.facility_id:
        messages.error(request, "Anda tidak memiliki akses ke LPLPO ini.")
        return redirect("lplpo:lplpo_my_list")
    return None


def _check_instalasi_farmasi_access(request):
    """Reject PUSKESMAS users from review/finalize workflow steps."""
    if request.user.role == User.Role.PUSKESMAS:
        messages.error(
            request,
            "Aksi ini hanya tersedia untuk petugas Instalasi Farmasi.",
        )
        return redirect("lplpo:lplpo_my_list")
    return None


def _has_lplpo_operate_access(user):
    return user.role != User.Role.PUSKESMAS and has_module_scope(
        user, ModuleAccess.Module.LPLPO, ModuleAccess.Scope.OPERATE
    )


def _has_lplpo_approve_access(user):
    return user.role != User.Role.PUSKESMAS and has_module_scope(
        user, ModuleAccess.Module.LPLPO, ModuleAccess.Scope.APPROVE
    )


def _check_puskesmas_creator_access(request):
    """Restrict create flow to PUSKESMAS operators and super admin."""
    if _is_super_admin(request.user):
        return
    if request.user.role != User.Role.PUSKESMAS:
        raise PermissionDenied("Hanya operator Puskesmas yang dapat membuat LPLPO.")


def _check_puskesmas_draft_action_access(request):
    """Restrict draft LPLPO mutations to PUSKESMAS operators and super admin."""
    if _is_super_admin(request.user):
        return
    if request.user.role != User.Role.PUSKESMAS:
        raise PermissionDenied(
            "Hanya operator Puskesmas yang dapat mengubah LPLPO draft."
        )


def _get_submission_month_choices():
    return [(str(month), calendar.month_name[month]) for month in range(1, 13)]


def _resolve_lplpo_create_facility(form, user):
    facility = getattr(user, "facility", None)
    if _is_super_admin(user) or not facility:
        facility = form.cleaned_data.get("facility")
    return facility


def _get_filtered_lplpo_queryset(request, *, submitted_only=True):
    queryset = LPLPO.objects.select_related(
        "facility",
        "created_by",
        "verified_by",
        "reviewed_by",
        "approved_by",
        "distribution",
    )
    if submitted_only:
        queryset = queryset.filter(submitted_at__isnull=False)
    queryset = queryset.order_by("-submitted_at", "-tahun", "-bulan", "facility__name")

    q = request.GET.get("q", "").strip()
    if q:
        queryset = queryset.filter(
            Q(document_number__icontains=q) | Q(facility__name__icontains=q)
        )

    status = request.GET.get("status", "").strip()
    if status:
        queryset = queryset.filter(status=status)

    submitted_month = request.GET.get("submitted_month", "").strip()
    if submitted_month:
        queryset = queryset.filter(submitted_at__month=submitted_month)

    submitted_year = request.GET.get("submitted_year", "").strip()
    if submitted_year:
        queryset = queryset.filter(submitted_at__year=submitted_year)

    return queryset, {
        "search": q,
        "selected_status": status,
        "selected_submitted_month": submitted_month,
        "selected_submitted_year": submitted_year,
        "status_choices": LPLPO.Status.choices,
        "submission_month_choices": _get_submission_month_choices(),
    }


# ══════════════════════════ List Views ══════════════════════════


@login_required
@perm_required("lplpo.view_lplpo")
def lplpo_list(request):
    """LPLPO list for Instalasi Farmasi staff, with super admin access to all statuses."""
    if getattr(request.user, "role", "") == User.Role.PUSKESMAS:
        return redirect("lplpo:lplpo_my_list")

    queryset, filter_context = _get_filtered_lplpo_queryset(
        request,
        submitted_only=not _is_super_admin(request.user),
    )

    paginator = Paginator(queryset, 25)
    page = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "lplpo/lplpo_list.html",
        {
            "lplpos": page,
            **filter_context,
            "is_all": True,
            "can_manage_all_lplpo": _is_super_admin(request.user),
        },
    )


@login_required
@perm_required("lplpo.view_lplpo")
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
    _check_puskesmas_creator_access(request)

    if request.method == "POST":
        form = LPLPOCreateForm(request.POST, user=request.user)
        if form.is_valid():
            bulan = int(form.cleaned_data["bulan"])
            tahun = int(form.cleaned_data["tahun"])

            # Determine facility
            facility = _resolve_lplpo_create_facility(form, request.user)

            if not facility:
                messages.error(
                    request,
                    "Pilih fasilitas puskesmas atau hubungi administrator untuk menghubungkan akun Anda.",
                )
                return render(request, "lplpo/lplpo_create.html", {"form": form})

            with transaction.atomic():
                Facility.objects.select_for_update().get(pk=facility.pk)

                server_date = timezone.localdate()
                active_year = get_active_lplpo_year(server_date)
                expected_year, expected_month = get_next_required_lplpo_period(
                    facility, server_date=server_date
                )
                if expected_month is None:
                    form.add_error(
                        None,
                        f"Semua LPLPO tahun {active_year} untuk {facility.name} sudah dibuat.",
                    )
                    return render(request, "lplpo/lplpo_create.html", {"form": form})

                if tahun != expected_year or bulan != expected_month:
                    required_period = format_lplpo_period_label(
                        expected_month, expected_year
                    )
                    if tahun != expected_year:
                        form.add_error(
                            "tahun",
                            f"LPLPO baru hanya dapat dibuat untuk tahun server aktif {expected_year}.",
                        )
                    if bulan != expected_month:
                        form.add_error(
                            "bulan",
                            f"Periode berikutnya yang wajib dibuat adalah {required_period}.",
                        )
                    return render(request, "lplpo/lplpo_create.html", {"form": form})

                # Check uniqueness after row lock to avoid double-create races.
                if LPLPO.objects.filter(
                    facility=facility, bulan=bulan, tahun=tahun
                ).exists():
                    form.add_error(
                        "bulan",
                        f"LPLPO untuk {facility.name} periode "
                        f"{format_lplpo_period_label(bulan, tahun)} sudah ada.",
                    )
                    return render(request, "lplpo/lplpo_create.html", {"form": form})

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
                    for pi in prev_lplpo.items.only("item_id", "stock_keseluruhan").all():
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
                    stock_awal = prev_stock.get(item.pk, 0)
                    penerimaan = penerimaan_data.get(item.pk, 0)
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

            if _is_super_admin(request.user):
                logger.info(
                    "super_admin_created_lplpo",
                    extra={
                        "user_id": request.user.pk,
                        "facility_id": facility.pk,
                        "lplpo_id": lplpo.pk,
                        "bulan": bulan,
                        "tahun": tahun,
                    },
                )
            messages.success(
                request,
                f"LPLPO {lplpo.document_number} berhasil dibuat dengan {len(lplpo_items)} item.",
            )
            return redirect("lplpo:lplpo_detail", pk=lplpo.pk)
    else:
        form = LPLPOCreateForm(user=request.user)

    return render(request, "lplpo/lplpo_create.html", {"form": form})


@login_required
@perm_required("lplpo.view_lplpo")
def api_prefill_penerimaan(request):
    """AJAX helper returning penerimaan totals for a facility and period."""
    if request.method != "GET":
        return JsonResponse({"detail": "Method not allowed."}, status=405)

    facility = request.user.facility
    if request.user.role != User.Role.PUSKESMAS:
        if not has_module_scope(
            request.user, ModuleAccess.Module.LPLPO, ModuleAccess.Scope.OPERATE
        ):
            return JsonResponse({"detail": "Insufficient permissions."}, status=403)
        facility_id = request.GET.get("facility")
        if facility_id:
            from apps.items.models import Facility

            facility = get_object_or_404(
                Facility,
                pk=facility_id,
                facility_type="PUSKESMAS",
                is_active=True,
            )

    if not facility:
        return JsonResponse(
            {"detail": "Facility is required for penerimaan prefill."},
            status=400,
        )

    try:
        bulan = int(request.GET.get("bulan", ""))
        tahun = int(request.GET.get("tahun", ""))
    except ValueError:
        return JsonResponse({"detail": "Invalid bulan or tahun."}, status=400)

    if bulan < 1 or bulan > 12:
        return JsonResponse({"detail": "Bulan harus antara 1 dan 12."}, status=400)

    data = get_penerimaan_for_facility_period(facility, bulan, tahun)
    return JsonResponse(
        {
            "facility_id": facility.pk,
            "bulan": bulan,
            "tahun": tahun,
            "items": {str(item_id): str(total) for item_id, total in data.items()},
        }
    )


# ══════════════════════════ Detail ══════════════════════════


@login_required
@perm_required("lplpo.view_lplpo")
def lplpo_detail(request, pk):
    """Read-only full view of an LPLPO."""
    lplpo = get_object_or_404(
        LPLPO.objects.select_related(
            "facility",
            "created_by",
            "verified_by",
            "reviewed_by",
            "approved_by",
            "distribution",
        ),
        pk=pk,
    )

    # Enforce facility scope for PUSKESMAS role
    denied = _check_facility_access(request, lplpo)
    if denied:
        return denied

    items = lplpo.items.select_related(
        "item", "item__satuan", "item__kategori"
    ).order_by("item__kategori__sort_order", "item__nama_barang")

    can_review = _has_lplpo_operate_access(request.user)
    can_approve = _has_lplpo_approve_access(request.user)

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
            "can_review": can_review,
            "can_approve": can_approve,
            "can_manage_draft": _is_super_admin(request.user)
            or request.user.role == User.Role.PUSKESMAS,
        },
    )


# ══════════════════════════ Edit (Puskesmas) ══════════════════════════


@login_required
@perm_required("lplpo.change_lplpo")
@module_scope_required(ModuleAccess.Module.LPLPO, ModuleAccess.Scope.OPERATE)
def lplpo_edit(request, pk):
    """Puskesmas fills their columns — only DRAFT or PIC-rejected status."""
    _check_puskesmas_draft_action_access(request)

    lplpo_obj = get_object_or_404(LPLPO.objects.select_related("facility"), pk=pk)

    if lplpo_obj.status not in (
        LPLPO.Status.DRAFT,
        LPLPO.Status.REJECTED_PUSKESMAS,
    ):
        messages.error(
            request,
            "Hanya LPLPO berstatus Draft atau Ditolak yang dapat diedit.",
        )
        return redirect("lplpo:lplpo_detail", pk=pk)

    # Enforce facility scope
    denied = _check_facility_access(request, lplpo_obj)
    if denied:
        return denied

    items_qs = lplpo_obj.items.select_related(
        "item", "item__satuan", "item__kategori"
    ).order_by("item__kategori__sort_order", "item__nama_barang")

    # Check if previous LPLPO exists (to lock stock_awal)
    prev_lplpo = get_previous_lplpo(
        lplpo_obj.facility, lplpo_obj.bulan, lplpo_obj.tahun
    )
    has_prev = prev_lplpo is not None
    has_form_errors = False

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
            updated_objs = []
            for f in forms_data:
                obj = f.save(commit=False)
                obj.compute_fields()
                updated_objs.append(obj)

            if updated_objs:
                LPLPOItem.objects.bulk_update(
                    updated_objs,
                    fields=[
                        "stock_awal",
                        "penerimaan",
                        "pembelian_puskesmas",
                        "pemakaian",
                        "stock_gudang_puskesmas",
                        "waktu_kosong",
                        "permintaan_alasan",
                        "persediaan",
                        "stock_keseluruhan",
                        "stock_optimum",
                        "jumlah_kebutuhan",
                        "permintaan_jumlah",
                    ],
                )

            if _is_super_admin(request.user):
                logger.info(
                    "super_admin_updated_lplpo_draft",
                    extra={
                        "user_id": request.user.pk,
                        "facility_id": lplpo_obj.facility_id,
                        "lplpo_id": lplpo_obj.pk,
                        "status": lplpo_obj.status,
                    },
                )
            messages.success(request, f"LPLPO {lplpo_obj.document_number} berhasil disimpan.")
            return redirect("lplpo:lplpo_detail", pk=pk)

        has_form_errors = True
        messages.error(
            request,
            "Data LPLPO belum tersimpan. Periksa kembali kolom yang bermasalah.",
        )
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
            "has_form_errors": has_form_errors,
        },
    )


# ══════════════════════════ Submit ══════════════════════════


@login_required
@perm_required("lplpo.change_lplpo")
@module_scope_required(ModuleAccess.Module.LPLPO, ModuleAccess.Scope.OPERATE)
def lplpo_submit(request, pk):
    """Transition DRAFT/PIC rejection → SUBMITTED."""
    _check_puskesmas_draft_action_access(request)

    lplpo_obj = get_object_or_404(LPLPO, pk=pk)
    denied = _check_facility_access(request, lplpo_obj)
    if denied:
        return denied
    if request.method != "POST":
        return redirect("lplpo:lplpo_detail", pk=pk)

    if lplpo_obj.status not in (
        LPLPO.Status.DRAFT,
        LPLPO.Status.REJECTED_PUSKESMAS,
    ):
        messages.error(
            request,
            "Hanya LPLPO berstatus Draft atau Ditolak yang dapat diajukan.",
        )
        return redirect("lplpo:lplpo_detail", pk=pk)

    zero_pemakaian_count = lplpo_obj.items.filter(pemakaian=0).count()
    if zero_pemakaian_count:
        messages.warning(
            request,
            f"{zero_pemakaian_count} item memiliki pemakaian 0. Pastikan data sudah benar sebelum diajukan.",
        )

    with transaction.atomic():
        lplpo_obj = LPLPO.objects.select_for_update().get(pk=lplpo_obj.pk)
        lplpo_obj.status = LPLPO.Status.SUBMITTED
        lplpo_obj.rejection_reason = ""
        lplpo_obj.submitted_at = timezone.now()
        lplpo_obj.verified_by = None
        lplpo_obj.verified_at = None
        lplpo_obj.reviewed_by = None
        lplpo_obj.reviewed_at = None
        lplpo_obj.approved_by = None
        lplpo_obj.approved_at = None
        lplpo_obj.save(
            update_fields=[
                "status",
                "rejection_reason",
                "submitted_at",
                "verified_by",
                "verified_at",
                "reviewed_by",
                "reviewed_at",
                "approved_by",
                "approved_at",
                "updated_at",
            ]
        )

    if _is_super_admin(request.user):
        logger.info(
            "super_admin_submitted_lplpo",
            extra={
                "user_id": request.user.pk,
                "facility_id": lplpo_obj.facility_id,
                "lplpo_id": lplpo_obj.pk,
            },
        )
    messages.success(request, f"LPLPO {lplpo_obj.document_number} berhasil diajukan.")
    return redirect("lplpo:lplpo_detail", pk=pk)


@login_required
@perm_required("lplpo.change_lplpo")
@module_scope_required(ModuleAccess.Module.LPLPO, ModuleAccess.Scope.OPERATE)
def lplpo_verify(request, pk):
    """PIC verification gate for submitted LPLPO before detailed review."""
    denied = _check_instalasi_farmasi_access(request)
    if denied:
        return denied

    if request.method != "POST":
        return redirect("lplpo:lplpo_detail", pk=pk)

    with transaction.atomic():
        lplpo_obj = get_object_or_404(
            LPLPO.objects.select_for_update(),
            pk=pk,
        )

        if lplpo_obj.status != LPLPO.Status.SUBMITTED:
            messages.error(
                request,
                "Hanya LPLPO berstatus Diajukan yang dapat diverifikasi oleh PIC.",
            )
            return redirect("lplpo:lplpo_detail", pk=pk)

        lplpo_obj.status = LPLPO.Status.PIC_VERIFIED
        lplpo_obj.verified_by = request.user
        lplpo_obj.verified_at = timezone.now()
        lplpo_obj.rejection_reason = ""
        lplpo_obj.save(
            update_fields=[
                "status",
                "verified_by",
                "verified_at",
                "rejection_reason",
                "updated_at",
            ]
        )

    messages.success(
        request,
        f"LPLPO {lplpo_obj.document_number} berhasil diverifikasi oleh PIC.",
    )
    return redirect("lplpo:lplpo_detail", pk=pk)


@login_required
@perm_required("lplpo.change_lplpo")
def lplpo_reject(request, pk):
    """Reject submitted LPLPO back to Puskesmas or reviewed LPLPO back to PIC."""
    denied = _check_instalasi_farmasi_access(request)
    if denied:
        return denied

    if request.method != "POST":
        return redirect("lplpo:lplpo_detail", pk=pk)

    form = RejectLPLPOForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Alasan penolakan wajib diisi.")
        return redirect("lplpo:lplpo_detail", pk=pk)

    with transaction.atomic():
        lplpo_obj = get_object_or_404(
            LPLPO.objects.select_for_update(),
            pk=pk,
        )

        if lplpo_obj.status == LPLPO.Status.SUBMITTED:
            if not _has_lplpo_operate_access(request.user):
                raise PermissionDenied("Anda tidak memiliki akses untuk menolak LPLPO ini.")
            lplpo_obj.status = LPLPO.Status.REJECTED_PUSKESMAS
            success_message = (
                f"LPLPO {lplpo_obj.document_number} berhasil dikembalikan ke Puskesmas."
            )
        elif lplpo_obj.status == LPLPO.Status.REVIEWED:
            if not _has_lplpo_approve_access(request.user):
                raise PermissionDenied("Anda tidak memiliki akses untuk menolak LPLPO ini.")
            lplpo_obj.status = LPLPO.Status.REJECTED_PIC
            lplpo_obj.approved_by = None
            lplpo_obj.approved_at = None
            success_message = (
                f"LPLPO {lplpo_obj.document_number} berhasil dikembalikan ke PIC."
            )
        else:
            messages.error(
                request,
                "Hanya LPLPO berstatus Diajukan atau Ditinjau PIC yang dapat ditolak.",
            )
            return redirect("lplpo:lplpo_detail", pk=pk)

        lplpo_obj.rejection_reason = form.cleaned_data["rejection_reason"]
        lplpo_obj.save(
            update_fields=[
                "status",
                "rejection_reason",
                "approved_by",
                "approved_at",
                "updated_at",
            ]
        )

    messages.success(request, success_message)
    return redirect("lplpo:lplpo_detail", pk=pk)


# ══════════════════════════ Review (Instalasi Farmasi) ══════════════════════════


@login_required
@perm_required("lplpo.change_lplpo")
@module_scope_required(ModuleAccess.Module.LPLPO, ModuleAccess.Scope.OPERATE)
def lplpo_review(request, pk):
    """PIC fills granted quantities and submits reviewed LPLPO to Kepala."""
    denied = _check_instalasi_farmasi_access(request)
    if denied:
        return denied

    lplpo_obj = get_object_or_404(
        LPLPO.objects.select_related("facility"), pk=pk
    )

    if lplpo_obj.status not in (
        LPLPO.Status.PIC_VERIFIED,
        LPLPO.Status.REJECTED_PIC,
    ):
        messages.error(
            request,
            "Hanya LPLPO yang sudah diverifikasi PIC atau dikembalikan Kepala yang dapat ditinjau.",
        )
        return redirect("lplpo:lplpo_detail", pk=pk)

    items_qs = lplpo_obj.items.select_related(
        "item", "item__satuan", "item__kategori"
    ).order_by("item__kategori__sort_order", "item__nama_barang")

    # Get current warehouse stock for each item
    warehouse_stock = {}
    stock_entries = (
        Stock.objects.filter(item__in=[li.item for li in items_qs])
        .annotate(
            available_quantity=ExpressionWrapper(
                F("quantity") - F("reserved"),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
        )
        .values("item_id")
        .annotate(total_qty=Sum("available_quantity"))
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
                lplpo_obj.rejection_reason = ""
                lplpo_obj.save(
                    update_fields=[
                        "status",
                        "reviewed_by",
                        "reviewed_at",
                        "rejection_reason",
                        "updated_at",
                    ]
                )

            messages.success(
                request,
                f"LPLPO {lplpo_obj.document_number} berhasil ditinjau dan diajukan ke Kepala Instalasi.",
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
    """Approve a reviewed LPLPO and create its draft Distribution."""
    denied = _check_instalasi_farmasi_access(request)
    if denied:
        return denied

    lplpo_obj = get_object_or_404(
        LPLPO.objects.select_related("facility"), pk=pk
    )
    if request.method != "POST":
        return redirect("lplpo:lplpo_detail", pk=pk)

    if lplpo_obj.status != LPLPO.Status.REVIEWED:
        messages.error(
            request, "Hanya LPLPO berstatus Ditinjau PIC yang dapat disetujui."
        )
        return redirect("lplpo:lplpo_detail", pk=pk)

    if lplpo_obj.distribution_id:
        messages.info(
            request,
            "Dokumen distribusi untuk LPLPO ini sudah dibuat sebelumnya.",
        )
        return redirect("distribution:distribution_detail", pk=lplpo_obj.distribution_id)

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
            lplpo_obj = LPLPO.objects.select_for_update().get(pk=lplpo_obj.pk)
            if lplpo_obj.status != LPLPO.Status.REVIEWED:
                messages.error(
                    request, "Hanya LPLPO berstatus Ditinjau PIC yang dapat disetujui."
                )
                return redirect("lplpo:lplpo_detail", pk=pk)
            if lplpo_obj.distribution_id:
                messages.info(
                    request,
                    "Dokumen distribusi untuk LPLPO ini sudah dibuat sebelumnya.",
                )
                return redirect(
                    "distribution:distribution_detail",
                    pk=lplpo_obj.distribution_id,
                )

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
            assign_default_distribution_staff(dist, request.user)

            lplpo_obj.status = LPLPO.Status.APPROVED
            lplpo_obj.approved_by = request.user
            lplpo_obj.approved_at = timezone.now()
            lplpo_obj.rejection_reason = ""
            lplpo_obj.distribution = dist
            lplpo_obj.save(
                update_fields=[
                    "status",
                    "approved_by",
                    "approved_at",
                    "rejection_reason",
                    "distribution",
                    "updated_at",
                ]
            )

    except (IntegrityError, ValueError) as exc:
        messages.error(
            request, f"Terjadi kesalahan saat memfinalisasi LPLPO: {exc}"
        )
        return redirect("lplpo:lplpo_detail", pk=pk)

    messages.success(
        request,
        f"LPLPO {lplpo_obj.document_number} disetujui. "
        f"Distribusi {dist.document_number} telah dibuat sebagai Draft.",
    )
    return redirect("distribution:distribution_detail", pk=dist.pk)


# ══════════════════════════ Print ══════════════════════════


@login_required
@perm_required("lplpo.view_lplpo")
def lplpo_print(request, pk):
    """Print-friendly HTML version of the LPLPO."""
    lplpo_obj = get_object_or_404(
        LPLPO.objects.select_related(
            "facility",
            "created_by",
            "verified_by",
            "reviewed_by",
            "approved_by",
        ),
        pk=pk,
    )
    denied = _check_facility_access(request, lplpo_obj)
    if denied:
        return denied

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


@login_required
@perm_required("lplpo.view_lplpo")
def lplpo_print_report(request):
    """Print-friendly report for submitted LPLPO queue."""
    if getattr(request.user, "role", "") == "PUSKESMAS":
        return redirect("lplpo:lplpo_my_list")

    queryset, filter_context = _get_filtered_lplpo_queryset(request)

    return render(
        request,
        "lplpo/lplpo_report_print.html",
        {
            "lplpos": queryset,
            **filter_context,
        },
    )


# ══════════════════════════ Delete ══════════════════════════


@login_required
@perm_required("lplpo.delete_lplpo")
@module_scope_required(ModuleAccess.Module.LPLPO, ModuleAccess.Scope.OPERATE)
def lplpo_delete(request, pk):
    """Delete a DRAFT LPLPO document."""
    _check_puskesmas_draft_action_access(request)

    lplpo_obj = get_object_or_404(LPLPO, pk=pk)

    if request.method != "POST":
        return redirect("lplpo:lplpo_detail", pk=pk)

    # Enforce facility scope
    denied = _check_facility_access(request, lplpo_obj)
    if denied:
        return denied

    if lplpo_obj.status not in (
        LPLPO.Status.DRAFT,
        LPLPO.Status.REJECTED_PUSKESMAS,
    ):
        messages.error(
            request,
            "Hanya LPLPO berstatus Draft atau Ditolak yang dapat dihapus.",
        )
        return redirect("lplpo:lplpo_detail", pk=pk)

    doc_number = lplpo_obj.document_number
    facility_id = lplpo_obj.facility_id
    lplpo_obj.delete()
    if _is_super_admin(request.user):
        logger.info(
            "super_admin_deleted_lplpo",
            extra={
                "user_id": request.user.pk,
                "facility_id": facility_id,
                "document_number": doc_number,
            },
        )
    messages.success(request, f"LPLPO {doc_number} berhasil dihapus.")

    if request.user.role == User.Role.PUSKESMAS:
        return redirect("lplpo:lplpo_my_list")
    return redirect("lplpo:lplpo_list")
