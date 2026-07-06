
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.decorators import module_scope_required, perm_required
from apps.stock.models import Stock
from apps.users.models import ModuleAccess

from .forms import AllocationForm, AllocationItemFormSet
from .models import Allocation, AllocationItemFacility
from .services import (
    AllocationWorkflowError,
    execute_allocation_approval,
    execute_allocation_rejection,
    execute_allocation_submission,
    execute_allocation_step_back_to_submitted,
    execute_distribution_delivery,
    execute_distribution_preparation,
)


def _redirect_allocation_detail(pk):
    return redirect("allocation:allocation_detail", pk=pk)




def _build_allocation_stock_catalog():
    available_stocks = (
        Stock.objects.select_related("item")
        .filter(quantity__gt=F("reserved"))
        .order_by(F("expiry_date").asc(nulls_last=True), "item_id", "batch_lot")
    )
    return [
        {
            "id": stock.pk,
            "itemId": stock.item_id,
            "label": (
                f"{stock.batch_lot} | Tersedia: {stock.available_quantity}"
                f" | Exp: {stock.expiry_date_display}"
            ),
            "availableQty": float(stock.available_quantity),
        }
        for stock in available_stocks
    ]


def _build_picker_metadata(form):
    facility_meta = {
        str(facility.pk): {
            "title": facility.name,
            "description": f"{facility.code} | {facility.get_facility_type_display()}",
        }
        for facility in form.fields["selected_facilities"].queryset
    }
    staff_meta = {}
    for user in form.fields["assigned_staff"].queryset.select_related("facility"):
        description_parts = [user.get_role_display()]
        if user.facility:
            description_parts.append(user.facility.name)
        else:
            description_parts.append(user.username)
        staff_meta[str(user.pk)] = {
            "title": user.full_name or user.username,
            "description": " | ".join(description_parts),
        }
    return facility_meta, staff_meta


def sync_allocation_staff_assignments(allocation, staff_users):
    selected_users = list(staff_users)
    selected_ids = {user.id for user in selected_users}

    allocation.staff_assignments.exclude(user_id__in=selected_ids).delete()

    existing_ids = set(
        allocation.staff_assignments.filter(user_id__in=selected_ids).values_list(
            "user_id", flat=True
        )
    )

    allocation.staff_assignments.model.objects.bulk_create(
        [
            allocation.staff_assignments.model(allocation=allocation, user=user)
            for user in selected_users
            if user.id not in existing_ids
        ]
    )


def sync_allocation_selected_facilities(allocation, facilities):
    selected_facilities = list(facilities)
    selected_ids = {facility.id for facility in selected_facilities}

    allocation.selected_facilities.exclude(facility_id__in=selected_ids).delete()

    existing_ids = set(
        allocation.selected_facilities.filter(
            facility_id__in=selected_ids
        ).values_list("facility_id", flat=True)
    )

    allocation.selected_facilities.model.objects.bulk_create(
        [
            allocation.selected_facilities.model(
                allocation=allocation, facility=facility
            )
            for facility in selected_facilities
            if facility.id not in existing_ids
        ]
    )


def _save_facility_allocations(allocation, request):
    """Parse and save the facility allocation matrix from POST data.

    The matrix data is submitted as hidden inputs with the naming convention:
    ``alloc_<item_pk>_<facility_pk>`` with the allocated quantity as value.
    """
    prefix = "alloc_"

    # Clear existing facility allocations for items in this allocation
    AllocationItemFacility.objects.filter(
        allocation_item__allocation=allocation
    ).delete()

    items_by_pk = {
        item.pk: item for item in allocation.items.select_related("stock")
    }

    to_create = []
    for key, value in request.POST.items():
        if not key.startswith(prefix):
            continue
        parts = key[len(prefix):].split("_")
        if len(parts) != 2:
            continue
        try:
            item_pk = int(parts[0])
            facility_pk = int(parts[1])
            qty = int(value) if value else 0
        except (TypeError, ValueError):
            continue

        if qty <= 0:
            continue

        alloc_item = items_by_pk.get(item_pk)
        if alloc_item is None:
            continue

        to_create.append(
            AllocationItemFacility(
                allocation_item=alloc_item,
                facility_id=facility_pk,
                qty_allocated=qty,
            )
        )

    if to_create:
        AllocationItemFacility.objects.bulk_create(to_create)


# ──────────────────────────────────────────────────────────────
# List
# ──────────────────────────────────────────────────────────────

@login_required
@perm_required("allocation.view_allocation")
def allocation_list(request):

    queryset = (
        Allocation.objects.select_related("created_by")
        .annotate(
            facility_count=Count("selected_facilities", distinct=True),
            staff_count=Count("staff_assignments", distinct=True),
            item_count=Count("items", distinct=True),
        )
        .order_by("-allocation_date", "-created_at")
    )

    search = request.GET.get("q", "").strip()
    if search:
        queryset = queryset.filter(
            Q(document_number__icontains=search)
            | Q(notes__icontains=search)
            | Q(created_by__username__icontains=search)
            | Q(created_by__full_name__icontains=search)
            | Q(selected_facilities__facility__name__icontains=search)
            | Q(items__item__nama_barang__icontains=search)
        ).distinct()

    status = request.GET.get("status", "").strip()
    if status:
        queryset = queryset.filter(status=status)

    allocations = Paginator(queryset, 25).get_page(request.GET.get("page"))

    return render(
        request,
        "allocation/allocation_list.html",
        {
            "allocations": allocations,
            "search": search,
            "selected_status": status,
            "status_choices": Allocation.Status.choices,
            "page_title": "Alokasi Barang",
        },
    )


# ──────────────────────────────────────────────────────────────
# Detail (also serves as approval view + distribution tracking)
# ──────────────────────────────────────────────────────────────

@login_required
@perm_required("allocation.view_allocation")
def allocation_detail(request, pk):

    allocation = get_object_or_404(
        Allocation.objects.select_related(
            "created_by",
            "submitted_by",
            "approved_by",
        ).prefetch_related(
            "selected_facilities__facility",
            "staff_assignments__user",
            "items__item",
            "items__item__satuan",
            "items__stock",
            "items__facility_allocations__facility",
        ),
        pk=pk,
    )

    # Prepare facility allocation matrix for display
    items_with_allocations = []
    for alloc_item in allocation.items.all():
        facility_qtys = {
            fa.facility_id: fa.qty_allocated
            for fa in alloc_item.facility_allocations.all()
        }
        items_with_allocations.append(
            {
                "item": alloc_item,
                "facility_qtys": facility_qtys,
                "total_allocated": alloc_item.total_qty_allocated,
            }
        )

    selected_facilities = [
        entry.facility for entry in allocation.selected_facilities.all()
    ]

    # Post-approval: distribution tracking
    distributions = []
    if allocation.status in (
        Allocation.Status.APPROVED,
        Allocation.Status.PARTIALLY_FULFILLED,
        Allocation.Status.FULFILLED,
    ):
        distributions = list(
            allocation.distributions.select_related("facility")
            .prefetch_related("items__item")
            .order_by("facility__name")
        )

    delivered, total = allocation.delivery_progress

    return render(
        request,
        "allocation/allocation_detail.html",
        {
            "allocation": allocation,
            "selected_facilities": selected_facilities,
            "assigned_staff": [
                entry.user for entry in allocation.staff_assignments.all()
            ],
            "items_with_allocations": items_with_allocations,
            "distributions": distributions,
            "delivery_delivered": delivered,
            "delivery_total": total,
            "page_title": "Detail Alokasi",
        },
    )


# ──────────────────────────────────────────────────────────────
# Create
# ──────────────────────────────────────────────────────────────

@login_required
@perm_required("allocation.add_allocation")
def allocation_create(request):

    if request.method == "POST":
        form = AllocationForm(request.POST)
        formset = AllocationItemFormSet(request.POST, prefix="items")

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                allocation = form.save(commit=False)
                allocation.created_by = request.user
                allocation.status = Allocation.Status.DRAFT
                allocation.save()

                sync_allocation_selected_facilities(
                    allocation, form.cleaned_data.get("selected_facilities", [])
                )
                sync_allocation_staff_assignments(
                    allocation, form.cleaned_data.get("assigned_staff", [])
                )

                formset.instance = allocation
                formset.save()

                # Save facility allocation matrix
                _save_facility_allocations(allocation, request)

            messages.success(
                request,
                f"Alokasi {allocation.document_number} berhasil dibuat.",
            )
            return redirect("allocation:allocation_detail", pk=allocation.pk)
    else:
        form = AllocationForm(
            initial={"allocation_date": timezone.now().date()}
        )
        formset = AllocationItemFormSet(prefix="items")

    facility_picker_meta, staff_picker_meta = _build_picker_metadata(form)

    return render(
        request,
        "allocation/allocation_form.html",
        {
            "title": "Buat Alokasi Baru",
            "page_title": "Buat Alokasi Baru",
            "form": form,
            "formset": formset,
            "is_edit": False,
            "facility_picker_meta": facility_picker_meta,
            "staff_picker_meta": staff_picker_meta,
            "stock_catalog": _build_allocation_stock_catalog(),
        },
    )


# ──────────────────────────────────────────────────────────────
# Edit (DRAFT only)
# ──────────────────────────────────────────────────────────────

@login_required
@perm_required("allocation.change_allocation")
def allocation_edit(request, pk):

    allocation = get_object_or_404(Allocation, pk=pk)
    if allocation.status != Allocation.Status.DRAFT:
        messages.error(request, "Hanya alokasi Draft yang dapat diubah.")
        return redirect("allocation:allocation_detail", pk=allocation.pk)

    if request.method == "POST":
        form = AllocationForm(request.POST, instance=allocation)
        formset = AllocationItemFormSet(
            request.POST, instance=allocation, prefix="items"
        )

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                form.save()
                sync_allocation_selected_facilities(
                    allocation,
                    form.cleaned_data.get("selected_facilities", []),
                )
                sync_allocation_staff_assignments(
                    allocation,
                    form.cleaned_data.get("assigned_staff", []),
                )
                formset.save()

                # Save facility allocation matrix
                _save_facility_allocations(allocation, request)

            messages.success(
                request,
                f"Alokasi {allocation.document_number} berhasil diperbarui.",
            )
            return redirect("allocation:allocation_detail", pk=allocation.pk)
    else:
        form = AllocationForm(instance=allocation)
        formset = AllocationItemFormSet(instance=allocation, prefix="items")

    # Build existing facility allocations as JSON for the matrix
    existing_allocations = {}
    for alloc_item in allocation.items.prefetch_related("facility_allocations"):
        for fa in alloc_item.facility_allocations.all():
            existing_allocations[f"{alloc_item.pk}_{fa.facility_id}"] = float(
                fa.qty_allocated
            )

    facility_picker_meta, staff_picker_meta = _build_picker_metadata(form)

    return render(
        request,
        "allocation/allocation_form.html",
        {
            "title": f"Edit Alokasi {allocation.document_number}",
            "page_title": "Edit Alokasi",
            "allocation": allocation,
            "form": form,
            "formset": formset,
            "is_edit": True,
            "facility_picker_meta": facility_picker_meta,
            "staff_picker_meta": staff_picker_meta,
            "stock_catalog": _build_allocation_stock_catalog(),
            "existing_allocations": existing_allocations,
        },
    )


# ──────────────────────────────────────────────────────────────
# Workflow actions
# ──────────────────────────────────────────────────────────────

@login_required
@perm_required("allocation.change_allocation")
def allocation_submit(request, pk):

    allocation = get_object_or_404(Allocation, pk=pk)
    if request.method != "POST":
        return _redirect_allocation_detail(pk)

    if allocation.status != Allocation.Status.DRAFT:
        messages.error(request, "Hanya alokasi Draft yang dapat diajukan.")
        return _redirect_allocation_detail(pk)

    try:
        execute_allocation_submission(allocation, request.user)
    except AllocationWorkflowError as exc:
        messages.error(request, str(exc))
        return _redirect_allocation_detail(pk)

    messages.success(
        request, f"Alokasi {allocation.document_number} berhasil diajukan."
    )
    return _redirect_allocation_detail(pk)


@login_required
@perm_required("allocation.change_allocation")
@module_scope_required(ModuleAccess.Module.ALLOCATION, ModuleAccess.Scope.APPROVE)
def allocation_approve(request, pk):

    allocation = get_object_or_404(Allocation, pk=pk)
    if request.method != "POST":
        return _redirect_allocation_detail(pk)

    if allocation.status != Allocation.Status.SUBMITTED:
        messages.error(
            request, "Hanya alokasi berstatus Diajukan yang dapat disetujui."
        )
        return _redirect_allocation_detail(pk)

    try:
        execute_allocation_approval(allocation, request.user)
    except AllocationWorkflowError as exc:
        messages.error(request, str(exc))
        return _redirect_allocation_detail(pk)

    messages.success(
        request,
        f"Alokasi {allocation.document_number} disetujui. "
        f"Distribusi per fasilitas berhasil dibuat otomatis.",
    )
    return _redirect_allocation_detail(pk)


@login_required
@perm_required("allocation.change_allocation")
@module_scope_required(ModuleAccess.Module.ALLOCATION, ModuleAccess.Scope.APPROVE)
def allocation_reject(request, pk):

    allocation = get_object_or_404(Allocation, pk=pk)
    if request.method != "POST":
        return _redirect_allocation_detail(pk)

    if allocation.status != Allocation.Status.SUBMITTED:
        messages.error(
            request, "Hanya alokasi berstatus Diajukan yang dapat ditolak."
        )
        return _redirect_allocation_detail(pk)

    reason = request.POST.get("rejection_reason", "").strip()
    if not reason:
        messages.error(request, "Alasan penolakan wajib diisi.")
        return _redirect_allocation_detail(pk)

    execute_allocation_rejection(allocation, reason)
    messages.success(
        request, f"Alokasi {allocation.document_number} ditolak dan dikembalikan ke Draft."
    )
    return _redirect_allocation_detail(pk)


@login_required
@perm_required("allocation.change_allocation")
@module_scope_required(ModuleAccess.Module.ALLOCATION, ModuleAccess.Scope.APPROVE)
def allocation_step_back(request, pk):

    allocation = get_object_or_404(Allocation, pk=pk)
    if request.method != "POST":
        return _redirect_allocation_detail(pk)

    if allocation.status != Allocation.Status.APPROVED:
        messages.error(
            request,
            "Hanya alokasi berstatus Disetujui yang dapat dikembalikan ke Diajukan.",
        )
        return _redirect_allocation_detail(pk)

    try:
        execute_allocation_step_back_to_submitted(allocation)
    except AllocationWorkflowError as exc:
        messages.error(request, str(exc))
        return _redirect_allocation_detail(pk)

    messages.success(
        request,
        f"Alokasi {allocation.document_number} dikembalikan ke status Diajukan.",
    )
    return _redirect_allocation_detail(pk)


@login_required
@perm_required("allocation.change_allocation")
def allocation_reset_to_draft(request, pk):

    allocation = get_object_or_404(Allocation, pk=pk)
    if request.method != "POST":
        return _redirect_allocation_detail(pk)

    # Only SUBMITTED and REJECTED can return to draft
    # After approval, distributions are generated and cannot be undone
    resettable_statuses = {
        Allocation.Status.SUBMITTED,
        Allocation.Status.REJECTED,
    }

    if allocation.status not in resettable_statuses:
        messages.error(
            request,
            "Status alokasi saat ini tidak dapat dikembalikan ke Draft.",
        )
        return _redirect_allocation_detail(pk)

    from .services import execute_allocation_reset_to_draft

    execute_allocation_reset_to_draft(allocation)
    messages.success(
        request,
        f"Alokasi {allocation.document_number} dikembalikan ke Draft.",
    )
    return _redirect_allocation_detail(pk)


@login_required
@perm_required("allocation.delete_allocation")
def allocation_delete(request, pk):

    allocation = get_object_or_404(Allocation, pk=pk)
    if request.method != "POST":
        return _redirect_allocation_detail(pk)

    if allocation.status not in {
        Allocation.Status.DRAFT,
        Allocation.Status.REJECTED,
    }:
        messages.error(
            request,
            "Hanya alokasi berstatus Draft atau Ditolak yang dapat dihapus.",
        )
        return _redirect_allocation_detail(pk)

    document_number = allocation.document_number
    allocation.delete()
    messages.success(request, f"Alokasi {document_number} berhasil dihapus.")
    return redirect("allocation:allocation_list")


# ──────────────────────────────────────────────────────────────
# Per-distribution actions (prepare + deliver)
# ──────────────────────────────────────────────────────────────

@login_required
@perm_required("allocation.change_allocation")
def allocation_distribution_prepare(request, pk, dist_pk):

    allocation = get_object_or_404(Allocation, pk=pk)
    distribution = get_object_or_404(
        allocation.distributions, pk=dist_pk
    )

    if request.method != "POST":
        return _redirect_allocation_detail(pk)

    try:
        execute_distribution_preparation(distribution, request.user)
    except AllocationWorkflowError as exc:
        messages.error(request, str(exc))
        return _redirect_allocation_detail(pk)

    messages.success(
        request,
        f"Distribusi {distribution.document_number} ke {distribution.facility} "
        f"ditandai disiapkan.",
    )
    return _redirect_allocation_detail(pk)


@login_required
@perm_required("allocation.change_allocation")
def allocation_distribution_deliver(request, pk, dist_pk):

    allocation = get_object_or_404(Allocation, pk=pk)
    distribution = get_object_or_404(
        allocation.distributions, pk=dist_pk
    )

    if request.method != "POST":
        return _redirect_allocation_detail(pk)

    try:
        execute_distribution_delivery(distribution, request.user, allocation)
    except AllocationWorkflowError as exc:
        messages.error(request, str(exc))
        return _redirect_allocation_detail(pk)

    messages.success(
        request,
        f"Distribusi {distribution.document_number} ke {distribution.facility} "
        f"berhasil dikirim. Stok telah dikurangi.",
    )
    return _redirect_allocation_detail(pk)
