from decimal import Decimal
import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.utils import timezone

from apps.core.decorators import module_scope_required, perm_required
from apps.core.rate_limits import puskesmas_sbbk_mutation_ratelimit
from apps.distribution.models import Distribution, DistributionItem
from apps.distribution.services import assign_default_distribution_staff
from apps.lplpo.models import LPLPO
from apps.users.access import has_module_permission, has_module_scope
from apps.users.models import ModuleAccess, User

from .forms import (
    ApprovalItemForm,
    PuskesmasRequestForm,
    PuskesmasRequestItemFormSet,
    PuskesmasSBBKForm,
    PuskesmasSBBKItemFormSet,
)
from .models import (
    PuskesmasRequest,
    PuskesmasRequestItem,
    PuskesmasSBBK,
    PuskesmasSBBKItem,
)
from .services import (
    assert_sbbk_month_mutable,
    log_sbbk_event,
    raise_sbbk_creator_denied,
    sync_sbbk_month,
)


logger = logging.getLogger(__name__)


def _is_super_admin(user):
    return bool(getattr(user, "is_superuser", False)) or getattr(user, "role", None) == User.Role.ADMIN


def _get_required_facility(user):
    if _is_super_admin(user):
        return None

    facility = getattr(user, "facility", None)
    if not facility:
        raise PermissionDenied(
            "Akun Anda belum terhubung ke fasilitas puskesmas."
        )
    return facility


def _can_review_request(user):
    if not getattr(user, "is_authenticated", False):
        return False

    if _is_super_admin(user):
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

    if _is_super_admin(user):
        return True

    facility = getattr(user, "facility", None)
    if not facility:
        return False

    if req is not None and req.facility_id != facility.pk:
        return False

    if getattr(user, "role", None) == "PUSKESMAS":
        return True

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
    if _is_super_admin(request.user):
        return None

    facility = _get_required_facility(request.user)
    if req.facility_id != facility.pk:
        raise PermissionDenied("Anda tidak memiliki akses ke permintaan ini.")

    return None


def _check_puskesmas_request_creator_access(request):
    if getattr(request.user, "role", None) != "PUSKESMAS":
        raise PermissionDenied("Hanya operator Puskesmas yang dapat membuat permintaan khusus.")
    return None


def _check_puskesmas_sbbk_creator_access(request):
    if _is_super_admin(request.user):
        return None
    if getattr(request.user, "role", None) != User.Role.PUSKESMAS:
        raise_sbbk_creator_denied()
    return None


def _check_sbbk_facility_access(request, sbbk):
    if _is_super_admin(request.user):
        return None

    facility = _get_required_facility(request.user)
    if sbbk.facility_id != facility.pk:
        raise PermissionDenied("Anda tidak memiliki akses ke dokumen SBBK ini.")
    return None


# ──────────────────────────── SBBK CRUD ────────────────────────────


@login_required
@perm_required("puskesmas.view_puskesmassbbk")
def receiving_list(request):
    queryset = PuskesmasSBBK.objects.select_related("facility", "created_by").order_by(
        "-received_date", "-created_at"
    )

    if not _is_super_admin(request.user):
        facility = _get_required_facility(request.user)
        queryset = queryset.filter(facility_id=facility.pk)

    q = request.GET.get("q", "").strip()
    if q:
        queryset = queryset.filter(
            Q(document_number__icontains=q) | Q(facility__name__icontains=q)
        )

    paginator = Paginator(queryset, 25)
    receivings = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "puskesmas/receiving_list.html",
        {
            "receivings": receivings,
            "search": q,
        },
    )


@login_required
@perm_required("puskesmas.add_puskesmassbbk")
@puskesmas_sbbk_mutation_ratelimit
def receiving_create(request):
    _check_puskesmas_sbbk_creator_access(request)

    if request.method == "POST":
        form = PuskesmasSBBKForm(request.POST, user=request.user)
        formset = PuskesmasSBBKItemFormSet(request.POST, prefix="items")

        if form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    sbbk = form.save(commit=False)
                    assert_sbbk_month_mutable(
                        facility=sbbk.facility,
                        received_date=sbbk.received_date,
                    )
                    sbbk.created_by = request.user
                    sbbk.save()
                    formset.instance = sbbk
                    formset.save()
                    sync_sbbk_month(
                        facility=sbbk.facility,
                        received_date=sbbk.received_date,
                    )
                    log_sbbk_event(event="created", sbbk=sbbk, user=request.user)
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(
                    request, f"Penerimaan SBBK {sbbk.document_number} berhasil dibuat."
                )
                return redirect("puskesmas:receiving_detail", pk=sbbk.pk)
    else:
        form = PuskesmasSBBKForm(user=request.user)
        formset = PuskesmasSBBKItemFormSet(prefix="items")

    return render(
        request,
        "puskesmas/receiving_form.html",
        {
            "form": form,
            "formset": formset,
            "title": "Buat Penerimaan SBBK",
            "is_edit": False,
        },
    )


@login_required
@perm_required("puskesmas.view_puskesmassbbk")
def receiving_detail(request, pk):
    sbbk = get_object_or_404(
        PuskesmasSBBK.objects.select_related("facility", "created_by"),
        pk=pk,
    )
    _check_sbbk_facility_access(request, sbbk)
    items = sbbk.items.select_related("item", "item__satuan", "item__program")
    can_manage = _is_super_admin(request.user) or request.user.role == User.Role.PUSKESMAS

    locked_lplpo = LPLPO.objects.filter(
        facility=sbbk.facility,
        bulan=sbbk.received_date.month,
        tahun=sbbk.received_date.year,
    ).exclude(status__in=["DRAFT", "REJECTED_PUSKESMAS"]).first()

    return render(
        request,
        "puskesmas/receiving_detail.html",
        {
            "sbbk": sbbk,
            "items": items,
            "can_manage": can_manage,
            "locked_lplpo": locked_lplpo,
        },
    )


@login_required
@perm_required("puskesmas.change_puskesmassbbk")
@puskesmas_sbbk_mutation_ratelimit
def receiving_edit(request, pk):
    _check_puskesmas_sbbk_creator_access(request)

    sbbk = get_object_or_404(PuskesmasSBBK, pk=pk)
    _check_sbbk_facility_access(request, sbbk)

    if request.method == "POST":
        form = PuskesmasSBBKForm(request.POST, instance=sbbk, user=request.user)
        formset = PuskesmasSBBKItemFormSet(request.POST, instance=sbbk, prefix="items")

        if form.is_valid() and formset.is_valid():
            original_date = sbbk.received_date
            original_facility = sbbk.facility
            original_facility_id = sbbk.facility_id
            try:
                with transaction.atomic():
                    updated_sbbk = form.save(commit=False)
                    assert_sbbk_month_mutable(
                        facility=original_facility,
                        received_date=original_date,
                    )
                    assert_sbbk_month_mutable(
                        facility=updated_sbbk.facility,
                        received_date=updated_sbbk.received_date,
                    )
                    updated_sbbk.save()
                    formset.save()
                    sync_sbbk_month(
                        facility=original_facility,
                        received_date=original_date,
                    )
                    if (
                        updated_sbbk.facility_id != original_facility_id
                        or updated_sbbk.received_date != original_date
                    ):
                        sync_sbbk_month(
                            facility=updated_sbbk.facility,
                            received_date=updated_sbbk.received_date,
                        )
                    log_sbbk_event(
                        event="updated",
                        sbbk=updated_sbbk,
                        user=request.user,
                    )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(
                    request,
                    f"Penerimaan SBBK {updated_sbbk.document_number} berhasil diperbarui.",
                )
                return redirect("puskesmas:receiving_detail", pk=updated_sbbk.pk)
    else:
        form = PuskesmasSBBKForm(instance=sbbk, user=request.user)
        formset = PuskesmasSBBKItemFormSet(instance=sbbk, prefix="items")

    return render(
        request,
        "puskesmas/receiving_form.html",
        {
            "form": form,
            "formset": formset,
            "title": f"Edit Penerimaan SBBK {sbbk.document_number}",
            "is_edit": True,
            "sbbk": sbbk,
        },
    )


@login_required
@perm_required("puskesmas.delete_puskesmassbbk")
@puskesmas_sbbk_mutation_ratelimit
def receiving_delete(request, pk):
    _check_puskesmas_sbbk_creator_access(request)

    sbbk = get_object_or_404(PuskesmasSBBK, pk=pk)
    _check_sbbk_facility_access(request, sbbk)

    if request.method != "POST":
        return redirect("puskesmas:receiving_detail", pk=pk)

    try:
        with transaction.atomic():
            assert_sbbk_month_mutable(
                facility=sbbk.facility,
                received_date=sbbk.received_date,
            )
            facility = sbbk.facility
            received_date = sbbk.received_date
            doc_num = sbbk.document_number
            sbbk.delete()
            sync_sbbk_month(facility=facility, received_date=received_date)
            logger.info(
                "puskesmas_sbbk_deleted",
                extra={
                    "document_number": doc_num,
                    "facility_id": facility.pk,
                    "username": request.user.username,
                },
            )
    except ValidationError as exc:
        messages.error(request, str(exc))
        return redirect("puskesmas:receiving_detail", pk=pk)

    messages.success(request, f"Penerimaan SBBK {doc_num} berhasil dihapus.")
    return redirect("puskesmas:receiving_list")


# ──────────────────────────── List ────────────────────────────


@login_required
@perm_required("puskesmas.view_puskesmasrequest")
def request_list(request):
    queryset = PuskesmasRequest.objects.select_related(
        "facility", "created_by", "program"
    ).order_by("-request_date")

    if not _is_super_admin(request.user):
        facility = _get_required_facility(request.user)
        queryset = queryset.filter(facility_id=facility.pk)

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
    denied = _check_request_facility_access(request, req)
    if denied:
        return denied
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
    denied = _check_request_facility_access(request, req)
    if denied:
        return denied
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
    For any other non-superuser role: always returns the user's linked
    facility and never allows query-driven widening to all facilities.

    Returns (facility_obj_or_None, error_response_or_None).
    """
    if getattr(request.user, "is_superuser", False):
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

    if getattr(request.user, "role", None) == "PUSKESMAS":
        facility = getattr(request.user, "facility", None)
        if not facility:
            raise PermissionDenied(
                "Akun Anda belum terhubung ke fasilitas puskesmas."
            )
        return facility, None

    facility = getattr(request.user, "facility", None)
    if not facility:
        raise PermissionDenied(
            "Akun Anda belum terhubung ke fasilitas puskesmas."
        )
    return facility, None


@login_required
@perm_required("reports.view_reports")
def puskesmas_report_penerimaan(request):
    """Riwayat Penerimaan — SBBK receipts recorded by Puskesmas."""
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

        qs = PuskesmasSBBKItem.objects.filter(
            sbbk__received_date__range=[start_date, end_date],
        ).select_related(
            "sbbk",
            "sbbk__facility",
            "item",
            "item__satuan",
        ).order_by(
            "sbbk__received_date",
            "sbbk__document_number",
            "item__nama_barang",
        )

        if facility:
            qs = qs.filter(sbbk__facility=facility)

        for sbbk_item in qs:
            report_data.append(
                {
                    "document_number": sbbk_item.sbbk.document_number,
                    "received_date": sbbk_item.sbbk.received_date,
                    "nama_barang": sbbk_item.item.nama_barang,
                    "satuan": sbbk_item.item.satuan.name if sbbk_item.item.satuan else "-",
                    "quantity": sbbk_item.quantity,
                    "unit_price": sbbk_item.unit_price,
                    "notes": sbbk_item.notes or sbbk_item.sbbk.notes,
                }
            )

        if request.GET.get("format") == "excel" and report_data:
            return export_puskesmas_penerimaan_excel(
                report_data, start_date, end_date, selected_facility_name
            )

    # Facility chooser for super admin
    all_facilities = []
    if _is_super_admin(request.user):
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
@perm_required("reports.view_reports")
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
    if _is_super_admin(request.user):
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
@perm_required("reports.view_reports")
def puskesmas_report_persediaan(request):
    """Rincian Laporan Persediaan Puskesmas — LPLPO-based with dynamic stock calculation.

    Stock for each item is computed as:
      stock_keseluruhan from the latest non-rejected LPLPO for the facility
      in or before the requested period, plus any additional distributions
      received after that LPLPO's closing month up to the end of the
      requested period.

    Facility isolation is strictly enforced: PUSKESMAS users only see their
    own facility; super admin may optionally scope via ?facility=<id>.
    """
    from apps.distribution.models import Distribution, DistributionItem
    from apps.items.models import Facility as FacilityModel
    from apps.lplpo.models import LPLPO, LPLPOItem
    from django.db.models import Sum

    from .forms import PuskesmasPersediaanFilterForm
    from .exports import export_puskesmas_persediaan_excel

    import logging
    logger = logging.getLogger(__name__)

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
    period_label = ""

    # Statuses that represent a non-rejected, usable LPLPO
    USABLE_STATUSES = [
        LPLPO.Status.DRAFT,
        LPLPO.Status.SUBMITTED,
        LPLPO.Status.PIC_VERIFIED,
        LPLPO.Status.REVIEWED,
        LPLPO.Status.APPROVED,
        LPLPO.Status.DISTRIBUTED,
        LPLPO.Status.CLOSED,
    ]

    if form.is_valid():
        year = form.cleaned_data["year"]
        period = form.cleaned_data["period"]
        _start_month, end_month, period_label = (
            PuskesmasPersediaanFilterForm.get_period_bounds(period)
        )

        # Resolve which facilities to query
        facilities_to_query = [facility] if facility else list(
            FacilityModel.objects.filter(
                facility_type=FacilityModel.FacilityType.PUSKESMAS, is_active=True
            )
        )

        # --- Dynamic stock calculation ---
        # For each facility, find the latest usable LPLPO in or before the
        # requested period, then add distributions that arrived after it.
        item_stock_map = {}  # {(item_id, item_name, satuan_name, kategori_name, sort_order): stock}

        for fac in facilities_to_query:
            # Get the most recent usable LPLPO up to the selected period end.
            lplpo_qs = LPLPO.objects.filter(
                facility=fac,
                tahun=year,
                status__in=USABLE_STATUSES,
            )
            lplpo_qs = lplpo_qs.filter(bulan__lte=end_month)

            latest_lplpo = lplpo_qs.order_by("-bulan").first()

            if latest_lplpo:
                # Collect stock_keseluruhan per item from this LPLPO
                lplpo_items = LPLPOItem.objects.filter(
                    lplpo=latest_lplpo
                ).select_related(
                    "item", "item__satuan", "item__kategori"
                )

                for li in lplpo_items:
                    key = (
                        li.item_id,
                        li.item.nama_barang,
                        li.item.satuan.name if li.item.satuan else "-",
                        li.item.kategori.name if li.item.kategori else "Lainnya",
                        li.item.kategori.sort_order if li.item.kategori else 9999,
                    )
                    item_stock_map[key] = item_stock_map.get(key, 0) + li.stock_keseluruhan

                # Add distributions received AFTER the LPLPO's closing month
                # (i.e., month > latest_lplpo.bulan, same year or next year)
                # Only count DISTRIBUTED distributions
                newer_dist_filter = {
                    "distribution__facility": fac,
                    "distribution__status": Distribution.Status.DISTRIBUTED,
                }
                # Distributions in the same year, strictly after LPLPO month,
                # up to and including the selected period end month.
                newer_dist_filter["distribution__distributed_date__year"] = year
                newer_dist_filter["distribution__distributed_date__month__gt"] = latest_lplpo.bulan
                newer_dist_filter["distribution__distributed_date__month__lte"] = end_month

                newer_items = (
                    DistributionItem.objects.filter(**newer_dist_filter)
                    .select_related(
                        "item", "item__satuan", "item__kategori"
                    )
                    .values(
                        "item_id",
                        "item__nama_barang",
                        "item__satuan__name",
                        "item__kategori__name",
                        "item__kategori__sort_order",
                    )
                    .annotate(total_received=Sum("quantity_approved"))
                )

                for di in newer_items:
                    key = (
                        di["item_id"],
                        di["item__nama_barang"],
                        di["item__satuan__name"] or "-",
                        di["item__kategori__name"] or "Lainnya",
                        di["item__kategori__sort_order"] or 9999,
                    )
                    extra = int(di["total_received"] or 0)
                    item_stock_map[key] = item_stock_map.get(key, 0) + extra

            else:
                # No LPLPO found: fall back to distribution-only data for the period
                logger.info(
                    "puskesmas_report_persediaan: no usable LPLPO found for facility=%s year=%s month=%s; "
                    "using distribution-only fallback.",
                    fac.pk, year, end_month,
                )
                dist_filter = {
                    "distribution__facility": fac,
                    "distribution__status": Distribution.Status.DISTRIBUTED,
                    "distribution__distributed_date__year": year,
                }
                dist_filter["distribution__distributed_date__month__lte"] = end_month

                fallback_items = (
                    DistributionItem.objects.filter(**dist_filter)
                    .select_related("item", "item__satuan", "item__kategori")
                    .values(
                        "item_id",
                        "item__nama_barang",
                        "item__satuan__name",
                        "item__kategori__name",
                        "item__kategori__sort_order",
                    )
                    .annotate(total_received=Sum("quantity_approved"))
                )
                for di in fallback_items:
                    key = (
                        di["item_id"],
                        di["item__nama_barang"],
                        di["item__satuan__name"] or "-",
                        di["item__kategori__name"] or "Lainnya",
                        di["item__kategori__sort_order"] or 9999,
                    )
                    item_stock_map[key] = item_stock_map.get(key, 0) + int(di["total_received"] or 0)

        # Build sorted report_data list
        for key, stock_qty in sorted(item_stock_map.items(), key=lambda x: (x[0][4], x[0][3], x[0][1])):
            _, nama_barang, satuan, kategori, _ = key
            report_data.append({
                "nama_barang": nama_barang,
                "satuan": satuan,
                "kategori": kategori,
                "stock_keseluruhan": stock_qty,
            })

        if request.GET.get("format") == "excel" and report_data:
            return export_puskesmas_persediaan_excel(
                report_data, year, period_label, selected_facility_name
            )

    # Facility chooser for super admin
    all_facilities = []
    if _is_super_admin(request.user):
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
            "period_label": period_label,
        },
    )



@login_required
@perm_required("reports.view_reports")
def puskesmas_report_rekap_persediaan(request):
    """Rekap Laporan Persediaan Puskesmas — year-to-date valuation by category.

    The report summarizes LPLPO valuation into category rows (`Uraian`) for
    the requested year and selected period:
      - Saldo Awal   : opening month stock_awal * opening month harga_satuan
      - Nilai Terima : accumulated penerimaan within the selected period
      - Nilai Keluar : accumulated pemakaian within the selected period
      - Saldo Akhir  : latest stock_keseluruhan * latest harga_satuan in period

    Facility isolation: PUSKESMAS role always sees their own facility only.
    """
    from apps.items.models import Facility as FacilityModel
    from apps.lplpo.models import LPLPO, LPLPOItem

    from .exports import export_puskesmas_rekap_persediaan_excel
    from .forms import PuskesmasPersediaanFilterForm

    facility, err = _resolve_report_facility(request)
    if err:
        return err

    initial = PuskesmasPersediaanFilterForm.get_default_initial()
    effective_get = request.GET.copy()
    for key, value in initial.items():
        if not effective_get.get(key):
            effective_get[key] = value

    form = PuskesmasPersediaanFilterForm(effective_get)
    rekap_data = []
    totals = {
        "saldo_awal": Decimal("0"),
        "nilai_terima": Decimal("0"),
        "nilai_keluar": Decimal("0"),
        "saldo_akhir": Decimal("0"),
    }
    selected_facility_name = facility.name if facility else "Semua Fasilitas"
    period_label = ""

    USABLE_STATUSES = [
        LPLPO.Status.DRAFT,
        LPLPO.Status.SUBMITTED,
        LPLPO.Status.PIC_VERIFIED,
        LPLPO.Status.REVIEWED,
        LPLPO.Status.APPROVED,
        LPLPO.Status.DISTRIBUTED,
        LPLPO.Status.CLOSED,
    ]

    if form.is_valid():
        year = form.cleaned_data["year"]
        period = form.cleaned_data["period"]
        start_month, end_month, period_label = (
            PuskesmasPersediaanFilterForm.get_period_bounds(period)
        )

        facilities_to_query = FacilityModel.objects.filter(
            facility_type=FacilityModel.FacilityType.PUSKESMAS,
            is_active=True,
        )
        if facility:
            facilities_to_query = facilities_to_query.filter(pk=facility.pk)
        facilities_to_query = list(facilities_to_query)

        facility_item_map = {}
        lplpo_items_qs = (
            LPLPOItem.objects.filter(
                lplpo__facility__in=facilities_to_query,
                lplpo__tahun=year,
                lplpo__status__in=USABLE_STATUSES,
            )
            .select_related("lplpo", "item", "item__satuan", "item__kategori")
            .order_by(
                "lplpo__facility_id",
                "item__kategori__sort_order",
                "item__nama_barang",
                "lplpo__bulan",
            )
        )
        lplpo_items_qs = lplpo_items_qs.filter(
            lplpo__bulan__gte=start_month,
            lplpo__bulan__lte=end_month,
        )

        for li in lplpo_items_qs:
            key = (li.lplpo.facility_id, li.item_id)
            row = facility_item_map.setdefault(
                key,
                {
                    "nama_barang": li.item.nama_barang,
                    "satuan": li.item.satuan.name if li.item.satuan else "-",
                    "kategori": li.item.kategori.name if li.item.kategori else "Lainnya",
                    "sort_order": li.item.kategori.sort_order
                    if li.item.kategori
                    else 9999,
                    "stok_awal": 0,
                    "penerimaan": 0,
                    "pemakaian": 0,
                    "nilai_stok_awal": Decimal("0"),
                    "nilai_penerimaan": Decimal("0"),
                    "nilai_pemakaian": Decimal("0"),
                    "latest_month": 0,
                    "latest_harga_satuan": Decimal("0"),
                    "latest_stok_akhir": 0,
                    "nilai_stok_akhir": Decimal("0"),
                },
            )

            harga_satuan = li.harga_satuan or Decimal("0")
            if li.lplpo.bulan == start_month:
                row["stok_awal"] += li.stock_awal
                row["nilai_stok_awal"] += Decimal(li.stock_awal or 0) * harga_satuan

            row["penerimaan"] += li.penerimaan
            row["pemakaian"] += li.pemakaian
            row["nilai_penerimaan"] += Decimal(li.penerimaan or 0) * harga_satuan
            row["nilai_pemakaian"] += Decimal(li.pemakaian or 0) * harga_satuan

            if li.lplpo.bulan >= row["latest_month"]:
                row["latest_month"] = li.lplpo.bulan
                row["latest_harga_satuan"] = harga_satuan
                row["latest_stok_akhir"] = li.stock_keseluruhan
                row["nilai_stok_akhir"] = (
                    Decimal(li.stock_keseluruhan or 0) * harga_satuan
                )

        category_map = {}
        for row in facility_item_map.values():
            key = row["kategori"], row["sort_order"]
            aggregated = category_map.setdefault(
                key,
                {
                    "kategori": row["kategori"],
                    "sort_order": row["sort_order"],
                    "saldo_awal": Decimal("0"),
                    "nilai_terima": Decimal("0"),
                    "nilai_keluar": Decimal("0"),
                    "saldo_akhir": Decimal("0"),
                },
            )
            aggregated["saldo_awal"] += row["nilai_stok_awal"]
            aggregated["nilai_terima"] += row["nilai_penerimaan"]
            aggregated["nilai_keluar"] += row["nilai_pemakaian"]
            aggregated["saldo_akhir"] += row["nilai_stok_akhir"]

        for _key, row in sorted(
            category_map.items(),
            key=lambda x: (x[1]["sort_order"], x[1]["kategori"]),
        ):
            entry = {
                "kategori": row["kategori"],
                "saldo_awal": row["saldo_awal"],
                "nilai_terima": row["nilai_terima"],
                "nilai_keluar": row["nilai_keluar"],
                "saldo_akhir": row["saldo_akhir"],
            }
            rekap_data.append(entry)
            totals["saldo_awal"] += row["saldo_awal"]
            totals["nilai_terima"] += row["nilai_terima"]
            totals["nilai_keluar"] += row["nilai_keluar"]
            totals["saldo_akhir"] += row["saldo_akhir"]

        if request.GET.get("format") == "excel" and rekap_data:
            return export_puskesmas_rekap_persediaan_excel(
                rekap_data, totals, year, period_label, selected_facility_name
            )

    all_facilities = []
    if _is_super_admin(request.user):
        all_facilities = FacilityModel.objects.filter(
            facility_type=FacilityModel.FacilityType.PUSKESMAS, is_active=True
        ).order_by("name")

    return render(
        request,
        "puskesmas/report_rekap_persediaan.html",
        {
            "form": form,
            "rekap_data": rekap_data,
            "totals": totals,
            "facility": facility,
            "selected_facility_name": selected_facility_name,
            "all_facilities": all_facilities,
            "period_label": period_label,
        },
    )
