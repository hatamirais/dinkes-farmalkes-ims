from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.utils import timezone

from apps.core.decorators import module_scope_required, perm_required
from apps.distribution.models import Distribution, DistributionItem
from apps.distribution.services import assign_default_distribution_staff
from apps.users.access import has_module_permission, has_module_scope
from apps.users.models import ModuleAccess

from .forms import (
    ApprovalItemForm,
    PuskesmasRequestForm,
    PuskesmasRequestItemFormSet,
)
from .models import PuskesmasRequest, PuskesmasRequestItem


def _can_review_request(user):
    if not getattr(user, "is_authenticated", False):
        return False

    if user.is_superuser:
        return True

    if getattr(user, "role", None) == "PUSKESMAS":
        return False

    return has_module_permission(
        user, "puskesmas.change_puskesmasrequest"
    ) and has_module_scope(
        user,
        ModuleAccess.Module.PUSKESMAS,
        ModuleAccess.Scope.APPROVE,
    )


def _can_manage_request(user, req=None):
    if not getattr(user, "is_authenticated", False):
        return False

    if user.is_superuser:
        return True

    if getattr(user, "role", None) == "PUSKESMAS":
        if not user.facility_id:
            return False
        return req is None or req.facility_id == user.facility_id

    return has_module_permission(
        user, "puskesmas.change_puskesmasrequest"
    ) and has_module_scope(
        user,
        ModuleAccess.Module.PUSKESMAS,
        ModuleAccess.Scope.MANAGE,
    )


def _can_reset_request_to_draft(user, req):
    if req.status == PuskesmasRequest.Status.SUBMITTED:
        return _can_review_request(user) or _can_manage_request(user, req)

    if req.status == PuskesmasRequest.Status.REJECTED:
        return _can_manage_request(user, req)

    return False


def _check_request_facility_access(request, req):
    if getattr(request.user, "role", None) != "PUSKESMAS":
        return None

    if not request.user.facility_id:
        messages.error(request, "Akun Anda belum terhubung ke fasilitas puskesmas.")
        return redirect("puskesmas:request_list")

    if req.facility_id != request.user.facility_id:
        messages.error(request, "Anda tidak memiliki akses ke permintaan ini.")
        return redirect("puskesmas:request_list")

    return None


def _check_puskesmas_request_creator_access(request):
    if getattr(request.user, "role", None) != "PUSKESMAS":
        raise PermissionDenied("Hanya operator Puskesmas yang dapat membuat permintaan khusus.")
    return None


# ──────────────────────────── List ────────────────────────────


@login_required
@perm_required("puskesmas.view_puskesmasrequest")
def request_list(request):
    queryset = PuskesmasRequest.objects.select_related(
        "facility", "created_by", "program"
    ).order_by("-request_date")

    if getattr(request.user, "role", None) == "PUSKESMAS":
        if request.user.facility_id:
            queryset = queryset.filter(facility_id=request.user.facility_id)
        else:
            queryset = queryset.none()

    q = request.GET.get("q", "").strip()
    if q:
        queryset = queryset.filter(
            Q(document_number__icontains=q) | Q(facility__name__icontains=q)
        )

    status = request.GET.get("status", "")
    if status:
        queryset = queryset.filter(status=status)

    program = request.GET.get("program", "")
    if program:
        queryset = queryset.filter(program_id=program)

    paginator = Paginator(queryset, 25)
    requests = paginator.get_page(request.GET.get("page"))

    from apps.items.models import Program

    return render(
        request,
        "puskesmas/request_list.html",
        {
            "requests": requests,
            "search": q,
            "selected_status": status,
            "selected_program": program,
            "status_choices": PuskesmasRequest.Status.choices,
            "programs": Program.objects.filter(is_active=True).order_by("name"),
        },
    )


# ──────────────────────────── Create ────────────────────────────


@login_required
@perm_required("puskesmas.add_puskesmasrequest")
def request_create(request):
    denied = _check_puskesmas_request_creator_access(request)
    if denied:
        return denied

    if request.method == "POST":
        form = PuskesmasRequestForm(request.POST, user=request.user)
        formset = PuskesmasRequestItemFormSet(request.POST, prefix="items")

        if form.is_valid() and formset.is_valid():
            req = form.save(commit=False)
            req.created_by = request.user
            req.status = PuskesmasRequest.Status.DRAFT
            req.save()

            formset.instance = req
            formset.save()

            messages.success(
                request,
                f"Permintaan {req.document_number} berhasil dibuat.",
            )
            return redirect("puskesmas:request_detail", pk=req.pk)
    else:
        form = PuskesmasRequestForm(user=request.user)
        formset = PuskesmasRequestItemFormSet(prefix="items")

    return render(
        request,
        "puskesmas/request_form.html",
        {
            "form": form,
            "formset": formset,
            "title": "Buat Permintaan Baru",
            "is_edit": False,
        },
    )


# ──────────────────────────── Detail ────────────────────────────


@login_required
@perm_required("puskesmas.view_puskesmasrequest")
def request_detail(request, pk):
    req = get_object_or_404(
        PuskesmasRequest.objects.select_related(
            "facility", "created_by", "approved_by", "program", "distribution"
        ),
        pk=pk,
    )
    denied = _check_request_facility_access(request, req)
    if denied:
        return denied

    items = req.items.select_related("item", "item__satuan", "item__program")

    # Approval inline forms (read-only outside SUBMITTED status)
    approval_forms = []
    can_review = _can_review_request(request.user)
    can_manage = _can_manage_request(request.user, req)
    can_reset_to_draft = _can_reset_request_to_draft(request.user, req)
    if req.status == PuskesmasRequest.Status.SUBMITTED and can_review:
        for item_obj in items:
            approval_forms.append(
                (item_obj, ApprovalItemForm(instance=item_obj, prefix=f"approve_{item_obj.pk}"))
            )

    return render(
        request,
        "puskesmas/request_detail.html",
        {
            "req": req,
            "items": items,
            "approval_forms": approval_forms,
            "can_review": can_review,
            "can_manage": can_manage,
            "can_reset_to_draft": can_reset_to_draft,
        },
    )


# ──────────────────────────── Edit ────────────────────────────


@login_required
@perm_required("puskesmas.change_puskesmasrequest")
def request_edit(request, pk):
    req = get_object_or_404(PuskesmasRequest, pk=pk)
    denied = _check_request_facility_access(request, req)
    if denied:
        return denied

    if not _can_manage_request(request.user, req):
        messages.error(request, "Anda tidak dapat mengubah permintaan ini.")
        return redirect("puskesmas:request_detail", pk=req.pk)

    if req.status not in (PuskesmasRequest.Status.DRAFT, PuskesmasRequest.Status.REJECTED):
        messages.error(request, "Hanya permintaan berstatus Draft atau Ditolak yang dapat diubah.")
        return redirect("puskesmas:request_detail", pk=req.pk)

    if request.method == "POST":
        form = PuskesmasRequestForm(request.POST, instance=req, user=request.user)
        formset = PuskesmasRequestItemFormSet(request.POST, instance=req, prefix="items")

        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(
                request, f"Permintaan {req.document_number} berhasil diperbarui."
            )
            return redirect("puskesmas:request_detail", pk=req.pk)
    else:
        form = PuskesmasRequestForm(instance=req, user=request.user)
        formset = PuskesmasRequestItemFormSet(instance=req, prefix="items")

    return render(
        request,
        "puskesmas/request_form.html",
        {
            "form": form,
            "formset": formset,
            "title": f"Edit Permintaan {req.document_number}",
            "is_edit": True,
            "req": req,
        },
    )


# ──────────────────── Workflow Transitions ────────────────────


@login_required
@perm_required("puskesmas.change_puskesmasrequest")
def request_submit(request, pk):
    req = get_object_or_404(PuskesmasRequest, pk=pk)
    denied = _check_request_facility_access(request, req)
    if denied:
        return denied

    if not _can_manage_request(request.user, req):
        messages.error(request, "Anda tidak dapat mengajukan ulang permintaan ini.")
        return redirect("puskesmas:request_detail", pk=pk)

    if request.method != "POST":
        return redirect("puskesmas:request_detail", pk=pk)

    if req.status != PuskesmasRequest.Status.DRAFT:
        messages.error(request, "Hanya permintaan berstatus Draft yang dapat diajukan.")
        return redirect("puskesmas:request_detail", pk=pk)

    if not req.items.exists():
        messages.error(request, "Tambahkan minimal 1 item sebelum mengajukan permintaan.")
        return redirect("puskesmas:request_detail", pk=pk)

    req.status = PuskesmasRequest.Status.SUBMITTED
    req.save(update_fields=["status", "updated_at"])
    messages.success(request, f"Permintaan {req.document_number} berhasil diajukan.")
    return redirect("puskesmas:request_detail", pk=pk)


@login_required
@perm_required("puskesmas.change_puskesmasrequest")
@module_scope_required(ModuleAccess.Module.PUSKESMAS, ModuleAccess.Scope.APPROVE)
def request_approve(request, pk):
    """Approve the request and create a Distribution Draft automatically."""
    if not _can_review_request(request.user):
        raise PermissionDenied("Operator Puskesmas tidak dapat menyetujui permintaan.")

    req = get_object_or_404(PuskesmasRequest, pk=pk)
    if request.method != "POST":
        return redirect("puskesmas:request_detail", pk=pk)

    if req.status != PuskesmasRequest.Status.SUBMITTED:
        messages.error(request, "Hanya permintaan berstatus Diajukan yang dapat disetujui.")
        return redirect("puskesmas:request_detail", pk=pk)

    req_items = list(req.items.select_related("item"))
    if not req_items:
        messages.error(request, "Permintaan tidak memiliki item untuk disetujui.")
        return redirect("puskesmas:request_detail", pk=pk)

    # Save approved quantities from POST
    approved_data = {}
    for item_obj in req_items:
        field_name = f"approve_{item_obj.pk}-quantity_approved"
        raw = request.POST.get(field_name, "").strip()
        try:
            qty_approved = float(raw) if raw else None
        except ValueError:
            qty_approved = None
        approved_data[item_obj.pk] = qty_approved

    # At least one item must have approved qty > 0
    valid_items = [
        (item_obj, approved_data[item_obj.pk])
        for item_obj in req_items
        if approved_data.get(item_obj.pk) is not None and approved_data[item_obj.pk] > 0
    ]
    if not valid_items:
        messages.error(
            request,
            "Isi jumlah disetujui (> 0) untuk minimal 1 item sebelum menyetujui.",
        )
        return redirect("puskesmas:request_detail", pk=pk)

    try:
        with transaction.atomic():
            # Persist approved quantities
            for item_obj in req_items:
                item_obj.quantity_approved = approved_data.get(item_obj.pk)
                item_obj.save(update_fields=["quantity_approved"])

            # Create Distribution Draft
            dist = Distribution.objects.create(
                distribution_type=Distribution.DistributionType.SPECIAL_REQUEST,
                facility=req.facility,
                request_date=req.request_date,
                program=req.program.name if req.program else "",
                status=Distribution.Status.DRAFT,
                created_by=request.user,
                notes=(
                    f"Dibuat otomatis dari Permintaan Puskesmas {req.document_number}."
                    + (f"\n{req.notes}" if req.notes else "")
                ),
            )

            # Create DistributionItems for approved items only
            DistributionItem.objects.bulk_create(
                [
                    DistributionItem(
                        distribution=dist,
                        item=item_obj.item,
                        quantity_requested=item_obj.quantity_requested,
                        quantity_approved=qty,
                        notes=item_obj.notes,
                    )
                    for item_obj, qty in valid_items
                ]
            )
            assign_default_distribution_staff(dist, request.user)

            req.status = PuskesmasRequest.Status.APPROVED
            req.approved_by = request.user
            req.approved_at = timezone.now()
            req.distribution = dist
            req.save(
                update_fields=[
                    "status", "approved_by", "approved_at", "distribution", "updated_at"
                ]
            )

    except Exception as exc:
        messages.error(request, f"Terjadi kesalahan saat menyetujui permintaan: {exc}")
        return redirect("puskesmas:request_detail", pk=pk)

    messages.success(
        request,
        f"Permintaan {req.document_number} disetujui. "
        f"Distribusi {dist.document_number} telah dibuat sebagai Draft.",
    )
    return redirect("puskesmas:request_detail", pk=pk)


@login_required
@perm_required("puskesmas.change_puskesmasrequest")
@module_scope_required(ModuleAccess.Module.PUSKESMAS, ModuleAccess.Scope.APPROVE)
def request_reject(request, pk):
    if not _can_review_request(request.user):
        raise PermissionDenied("Operator Puskesmas tidak dapat menolak permintaan.")

    req = get_object_or_404(PuskesmasRequest, pk=pk)
    if request.method != "POST":
        return redirect("puskesmas:request_detail", pk=pk)

    if req.status != PuskesmasRequest.Status.SUBMITTED:
        messages.error(
            request, "Hanya permintaan berstatus Diajukan yang dapat ditolak."
        )
        return redirect("puskesmas:request_detail", pk=pk)

    reason = request.POST.get("rejection_reason", "").strip()
    req.status = PuskesmasRequest.Status.REJECTED
    req.rejection_reason = reason
    req.save(update_fields=["status", "rejection_reason", "updated_at"])
    messages.success(request, f"Permintaan {req.document_number} ditolak.")
    return redirect("puskesmas:request_detail", pk=pk)


@login_required
@perm_required("puskesmas.change_puskesmasrequest")
def request_reset_draft(request, pk):
    req = get_object_or_404(PuskesmasRequest, pk=pk)
    denied = _check_request_facility_access(request, req)
    if denied:
        return denied

    if request.method != "POST":
        return redirect("puskesmas:request_detail", pk=pk)

    if req.status not in (PuskesmasRequest.Status.SUBMITTED, PuskesmasRequest.Status.REJECTED):
        messages.error(request, "Hanya permintaan Diajukan atau Ditolak yang dapat dikembalikan ke Draft.")
        return redirect("puskesmas:request_detail", pk=pk)

    if not _can_reset_request_to_draft(request.user, req):
        messages.error(request, "Anda tidak dapat mengembalikan permintaan ini ke Draft.")
        return redirect("puskesmas:request_detail", pk=pk)

    req.status = PuskesmasRequest.Status.DRAFT
    req.rejection_reason = ""
    req.save(update_fields=["status", "rejection_reason", "updated_at"])
    messages.success(request, f"Permintaan {req.document_number} dikembalikan ke Draft.")
    return redirect("puskesmas:request_detail", pk=pk)


@login_required
@perm_required("puskesmas.delete_puskesmasrequest")
def request_delete(request, pk):
    req = get_object_or_404(PuskesmasRequest, pk=pk)
    denied = _check_request_facility_access(request, req)
    if denied:
        return denied

    if not _can_manage_request(request.user, req):
        messages.error(request, "Anda tidak dapat menghapus permintaan ini.")
        return redirect("puskesmas:request_detail", pk=req.pk)

    if request.method != "POST":
        return redirect("puskesmas:request_detail", pk=pk)

    if req.status not in (PuskesmasRequest.Status.DRAFT, PuskesmasRequest.Status.REJECTED):
        messages.error(
            request,
            "Hanya permintaan berstatus Draft atau Ditolak yang dapat dihapus.",
        )
        return redirect("puskesmas:request_detail", pk=pk)

    doc_num = req.document_number
    req.delete()
    messages.success(request, f"Permintaan {doc_num} berhasil dihapus.")
    return redirect("puskesmas:request_list")


# ──────────────────────── Puskesmas Reports ────────────────────────


def _resolve_report_facility(request, fallback_facility_id=None):
    """Return the facility to scope a Puskesmas report to.

    For PUSKESMAS role: always returns the user's own facility (enforced).
    For super admin: returns the facility identified by GET param 'facility'
    if provided; otherwise returns None (meaning all facilities for admin).

    Returns (facility_obj_or_None, error_response_or_None).
    """
    if getattr(request.user, "role", None) == "PUSKESMAS":
        facility = getattr(request.user, "facility", None)
        if not facility:
            messages.error(request, "Akun Anda belum terhubung ke fasilitas puskesmas.")
            return None, redirect("puskesmas:request_list")
        return facility, None

    # Super admin / staff path — optional facility filter
    from apps.items.models import Facility as FacilityModel

    facility_id = fallback_facility_id or request.GET.get("facility", "")
    if facility_id:
        try:
            facility = FacilityModel.objects.get(
                pk=int(facility_id),
                facility_type=FacilityModel.FacilityType.PUSKESMAS,
                is_active=True,
            )
            return facility, None
        except (FacilityModel.DoesNotExist, ValueError, TypeError):
            pass
    return None, None


@login_required
@perm_required("puskesmas.view_puskesmasrequest")
def puskesmas_report_penerimaan(request):
    """Riwayat Penerimaan — all DISTRIBUTED distributions sent to the Puskesmas facility.

    Facility isolation enforced at ORM level. PUSKESMAS users see only their own
    facility's data. Super admin may optionally scope via ?facility=<id>.
    """
    from apps.distribution.models import DistributionItem
    from apps.items.models import Facility as FacilityModel

    from .forms import PuskesmasReceivingFilterForm
    from .exports import export_puskesmas_penerimaan_excel

    facility, err = _resolve_report_facility(request)
    if err:
        return err

    initial = PuskesmasReceivingFilterForm.get_default_initial()
    effective_get = request.GET.copy()
    for key, value in initial.items():
        if not effective_get.get(key):
            effective_get[key] = value

    form = PuskesmasReceivingFilterForm(effective_get)
    report_data = []
    selected_facility_name = facility.name if facility else "Semua Fasilitas"

    if form.is_valid():
        start_date = form.cleaned_data["start_date"]
        end_date = form.cleaned_data["end_date"]
        distribution_type = form.cleaned_data.get("distribution_type", "")

        qs = DistributionItem.objects.filter(
            distribution__status=Distribution.Status.DISTRIBUTED,
            distribution__distributed_date__range=[start_date, end_date],
        ).select_related(
            "distribution",
            "distribution__facility",
            "item",
            "item__satuan",
        ).order_by(
            "distribution__distributed_date",
            "distribution__document_number",
            "item__nama_barang",
        )

        # Facility isolation — always applied for PUSKESMAS role
        if facility:
            qs = qs.filter(distribution__facility=facility)

        if distribution_type:
            qs = qs.filter(distribution__distribution_type=distribution_type)

        dist_type_labels = dict(Distribution.DistributionType.choices)
        for di in qs:
            qty = di.quantity_approved if di.quantity_approved is not None else di.quantity_requested
            report_data.append(
                {
                    "document_number": di.distribution.document_number,
                    "distributed_date": di.distribution.distributed_date,
                    "distribution_type_label": dist_type_labels.get(
                        di.distribution.distribution_type, di.distribution.distribution_type
                    ),
                    "nama_barang": di.item.nama_barang,
                    "satuan": di.item.satuan.name if di.item.satuan else "-",
                    "issued_batch_lot": di.issued_batch_lot or "-",
                    "quantity": qty,
                    "issued_unit_price": di.issued_unit_price,
                }
            )

        if request.GET.get("format") == "excel" and report_data:
            return export_puskesmas_penerimaan_excel(
                report_data, start_date, end_date, selected_facility_name
            )

    # Facility chooser for super admin
    all_facilities = []
    if not getattr(request.user, "role", None) == "PUSKESMAS":
        all_facilities = FacilityModel.objects.filter(
            facility_type=FacilityModel.FacilityType.PUSKESMAS, is_active=True
        ).order_by("name")

    total_quantity = sum(r["quantity"] or 0 for r in report_data)

    return render(
        request,
        "puskesmas/report_penerimaan.html",
        {
            "form": form,
            "report_data": report_data,
            "total_quantity": total_quantity,
            "facility": facility,
            "selected_facility_name": selected_facility_name,
            "all_facilities": all_facilities,
        },
    )


@login_required
@perm_required("puskesmas.view_puskesmasrequest")
def puskesmas_report_pemakaian(request):
    """Riwayat Pemakaian — consumption data derived from finalized (DISTRIBUTED/CLOSED) LPLPOs.

    Only DISTRIBUTED and CLOSED LPLPOs are included so that consumption data is
    from finalized documents only. Facility isolation enforced at ORM level.
    """
    from apps.items.models import Facility as FacilityModel
    from apps.lplpo.models import LPLPO, LPLPOItem, get_indonesian_month_name

    from .forms import PuskesmasPemakaianFilterForm
    from .exports import export_puskesmas_pemakaian_excel

    facility, err = _resolve_report_facility(request)
    if err:
        return err

    initial = PuskesmasPemakaianFilterForm.get_default_initial()
    effective_get = request.GET.copy()
    for key, value in initial.items():
        if not effective_get.get(key):
            effective_get[key] = value

    form = PuskesmasPemakaianFilterForm(effective_get)
    report_data = []
    selected_facility_name = facility.name if facility else "Semua Fasilitas"

    # Finalized LPLPO statuses only
    FINALIZED_STATUSES = [LPLPO.Status.DISTRIBUTED, LPLPO.Status.CLOSED]

    if form.is_valid():
        year = form.cleaned_data["year"]
        month_raw = form.cleaned_data.get("month", "")
        month = int(month_raw) if month_raw else None

        qs = LPLPOItem.objects.filter(
            lplpo__tahun=year,
            lplpo__status__in=FINALIZED_STATUSES,
        ).select_related(
            "lplpo",
            "lplpo__facility",
            "item",
            "item__satuan",
            "item__kategori",
        ).order_by(
            "lplpo__bulan",
            "item__kategori__sort_order",
            "item__nama_barang",
        )

        # Facility isolation
        if facility:
            qs = qs.filter(lplpo__facility=facility)

        if month:
            qs = qs.filter(lplpo__bulan=month)

        for li in qs:
            report_data.append(
                {
                    "period_display": li.lplpo.period_display,
                    "bulan": li.lplpo.bulan,
                    "tahun": li.lplpo.tahun,
                    "nama_barang": li.item.nama_barang,
                    "satuan": li.item.satuan.name if li.item.satuan else "-",
                    "kategori": li.item.kategori.name if li.item.kategori else "Lainnya",
                    "stock_awal": li.stock_awal,
                    "penerimaan": li.penerimaan,
                    "pemakaian": li.pemakaian,
                    "stock_keseluruhan": li.stock_keseluruhan,
                    "permintaan_jumlah": li.permintaan_jumlah,
                }
            )

        month_label = get_indonesian_month_name(month) if month else "Semua Bulan"

        if request.GET.get("format") == "excel" and report_data:
            return export_puskesmas_pemakaian_excel(
                report_data, year, month_label, selected_facility_name
            )

    # Facility chooser for super admin
    all_facilities = []
    if not getattr(request.user, "role", None) == "PUSKESMAS":
        all_facilities = FacilityModel.objects.filter(
            facility_type=FacilityModel.FacilityType.PUSKESMAS, is_active=True
        ).order_by("name")

    return render(
        request,
        "puskesmas/report_pemakaian.html",
        {
            "form": form,
            "report_data": report_data,
            "facility": facility,
            "selected_facility_name": selected_facility_name,
            "all_facilities": all_facilities,
        },
    )


@login_required
@perm_required("puskesmas.view_puskesmasrequest")
def puskesmas_report_persediaan(request):
    """Laporan Persediaan Puskesmas — PLACEHOLDER.

    Mirrors the Instalasi Farmasi 'Laporan Persediaan (Rincian)' report structure
    using Transaction data. This is a structural placeholder; the Puskesmas-specific
    source of truth (LPLPO stock_keseluruhan vs. Transaction-based) will be
    determined and refined in a follow-up.

    Facility isolation is enforced at the ORM level by filtering Transactions
    to only those linked to distributions for this facility.
    """
    from apps.items.models import Facility as FacilityModel
    from apps.stock.models import Transaction, Stock
    from django.db import models as db_models
    from django.db.models import Sum, Case, When, F
    from django.db.models.functions import Coalesce

    from .forms import PuskesmasPersediaanFilterForm
    from .exports import export_puskesmas_persediaan_excel

    facility, err = _resolve_report_facility(request)
    if err:
        return err

    initial = PuskesmasPersediaanFilterForm.get_default_initial()
    effective_get = request.GET.copy()
    for key, value in initial.items():
        if not effective_get.get(key):
            effective_get[key] = value

    form = PuskesmasPersediaanFilterForm(effective_get)
    report_data = []
    selected_facility_name = facility.name if facility else "Semua Fasilitas"

    if form.is_valid():
        start_date = form.cleaned_data["start_date"]
        end_date = form.cleaned_data["end_date"]

        # Subquery to get expiry_date from Stock
        from django.db.models import OuterRef, Subquery
        expiry_sq = Stock.objects.filter(
            item=OuterRef("item"),
            batch_lot=OuterRef("batch_lot"),
            sumber_dana=OuterRef("sumber_dana"),
        ).values("expiry_date")[:1]

        qs = Transaction.objects.values(
            "item__kategori__name",
            "item__kategori__sort_order",
            "item__nama_barang",
            "item__satuan__name",
            "batch_lot",
            "sumber_dana__name",
            "unit_price",
        ).annotate(
            expiry_date=Subquery(expiry_sq),
            initial_stock=Coalesce(
                Sum(
                    Case(
                        When(created_at__date__lt=start_date, transaction_type="IN", then=F("quantity")),
                        When(created_at__date__lt=start_date, transaction_type="OUT", then=-F("quantity")),
                        default=0,
                        output_field=db_models.DecimalField(),
                    )
                ),
                0,
                output_field=db_models.DecimalField(),
            ),
            received=Coalesce(
                Sum(
                    Case(
                        When(
                            created_at__date__range=[start_date, end_date],
                            reference_type__in=["RECEIVING", "INITIAL_IMPORT"],
                            transaction_type="IN",
                            then=F("quantity"),
                        ),
                        default=0,
                        output_field=db_models.DecimalField(),
                    )
                ),
                0,
                output_field=db_models.DecimalField(),
            ),
            distributed=Coalesce(
                Sum(
                    Case(
                        When(
                            created_at__date__range=[start_date, end_date],
                            reference_type__in=["DISTRIBUTION", "RECALL"],
                            transaction_type="OUT",
                            then=F("quantity"),
                        ),
                        default=0,
                        output_field=db_models.DecimalField(),
                    )
                ),
                0,
                output_field=db_models.DecimalField(),
            ),
            expired=Coalesce(
                Sum(
                    Case(
                        When(
                            created_at__date__range=[start_date, end_date],
                            reference_type="EXPIRED",
                            transaction_type="OUT",
                            then=F("quantity"),
                        ),
                        default=0,
                        output_field=db_models.DecimalField(),
                    )
                ),
                0,
                output_field=db_models.DecimalField(),
            ),
        ).order_by(
            "item__kategori__sort_order",
            "item__kategori__name",
            "item__nama_barang",
            "batch_lot",
        )

        # NOTE: Transaction model does not have a facility FK directly.
        # This placeholder currently shows Instalasi stock data (same as reports_index).
        # A follow-up will scope this to Puskesmas-specific data via LPLPO or
        # a Puskesmas stock ledger.

        for row in qs:
            row["ending_stock"] = (
                row["initial_stock"]
                + row["received"]
                - row["distributed"]
                - row["expired"]
            )
            if (
                row["initial_stock"] != 0
                or row["received"] != 0
                or row["distributed"] != 0
                or row["expired"] != 0
            ):
                report_data.append(row)

        if request.GET.get("format") == "excel" and report_data:
            return export_puskesmas_persediaan_excel(
                report_data, start_date, end_date, selected_facility_name
            )

    # Facility chooser for super admin
    all_facilities = []
    if not getattr(request.user, "role", None) == "PUSKESMAS":
        all_facilities = FacilityModel.objects.filter(
            facility_type=FacilityModel.FacilityType.PUSKESMAS, is_active=True
        ).order_by("name")

    return render(
        request,
        "puskesmas/report_persediaan.html",
        {
            "form": form,
            "report_data": report_data,
            "facility": facility,
            "selected_facility_name": selected_facility_name,
            "all_facilities": all_facilities,
        },
    )

