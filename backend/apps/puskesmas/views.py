from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden
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


# ──────────────────────────── List ────────────────────────────


@login_required
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
        return HttpResponseForbidden(
            "<h1>403 Forbidden</h1>"
            "<p>Operator Puskesmas tidak dapat menyetujui permintaan.</p>"
        )

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
        return HttpResponseForbidden(
            "<h1>403 Forbidden</h1>"
            "<p>Operator Puskesmas tidak dapat menolak permintaan.</p>"
        )

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
