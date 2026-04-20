from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.decorators import module_scope_required, perm_required
from apps.users.models import ModuleAccess, User

from .forms import (
    DistributionForm,
    DistributionItemFormSet,
)
from .models import Distribution, DistributionItem, DistributionStaffAssignment
from .services import (
    DistributionWorkflowError,
    execute_distribution_preparation,
    execute_distribution_rejection,
    execute_distribution_reset_to_draft,
    execute_distribution_step_back,
    execute_distribution_submission,
    execute_distribution_verification,
    execute_stock_distribution,
    get_distribution_step_back_target,
)


def _redirect_distribution_detail(pk):
    return redirect("distribution:distribution_detail", pk=pk)


def sync_distribution_staff_assignments(distribution, staff_users):
    selected_users = list(staff_users)
    selected_ids = {user.id for user in selected_users}

    distribution.staff_assignments.exclude(user_id__in=selected_ids).delete()

    existing_ids = set(
        distribution.staff_assignments.filter(user_id__in=selected_ids).values_list(
            "user_id", flat=True
        )
    )

    DistributionStaffAssignment.objects.bulk_create(
        [
            DistributionStaffAssignment(distribution=distribution, user=user)
            for user in selected_users
            if user.id not in existing_ids
        ]
    )


@login_required
def distribution_list(request):
    queryset = (
        Distribution.objects.select_related("facility", "created_by")
        .exclude(distribution_type__in=["BORROW_RS", "SWAP_RS"])
        .order_by("-request_date")
    )

    search = request.GET.get("q", "").strip()
    if search:
        queryset = queryset.filter(
            Q(document_number__icontains=search)
            | Q(facility__name__icontains=search)
            | Q(program__icontains=search)
        )

    status = request.GET.get("status")
    if status:
        queryset = queryset.filter(status=status)

    d_type = request.GET.get("type")
    if d_type:
        queryset = queryset.filter(distribution_type=d_type)

    paginator = Paginator(queryset, 25)
    distributions = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "distribution/distribution_list.html",
        {
            "distributions": distributions,
            "search": search,
            "selected_status": status or "",
            "selected_type": d_type or "",
            "status_choices": Distribution.Status.choices,
            "type_choices": Distribution.DistributionType.choices,
            "page_title": "Distribusi Barang",
            "list_title": "Daftar Distribusi",
            "create_url_name": "distribution:distribution_create",
            "create_button_label": "Buat Distribusi",
            "detail_url_name": "distribution:distribution_detail",
            "reset_url_name": "distribution:distribution_list",
            "show_type_filter": True,
            "module_icon": "bi-send",
            "empty_state_text": "Belum ada data distribusi",
        },
    )


@login_required
@perm_required("distribution.add_distribution")
def distribution_create(request):
    if request.method == "POST":
        form = DistributionForm(request.POST, user=request.user)
        formset = DistributionItemFormSet(request.POST, prefix="items")

        if form.is_valid() and formset.is_valid():
            dist = form.save(commit=False)
            dist.created_by = request.user
            dist.status = Distribution.Status.DRAFT
            dist.save()
            sync_distribution_staff_assignments(
                dist, form.cleaned_data.get("assigned_staff", [])
            )

            formset.instance = dist
            formset.save()

            messages.success(
                request, f"Distribusi {dist.document_number} berhasil dibuat."
            )
            return redirect("distribution:distribution_detail", pk=dist.pk)
    else:
        form = DistributionForm(user=request.user)
        formset = DistributionItemFormSet(prefix="items")

    return render(
        request,
        "distribution/distribution_form.html",
        {
            "form": form,
            "formset": formset,
            "title": "Buat Distribusi Baru",
            "is_edit": False,
            "show_distribution_type": True,
            "show_approved_quantity": True,
            "quantity_label": "Kuantitas Diminta",
            "item_error_colspan": 6,
            "back_url_name": "distribution:distribution_list",
        },
    )


@login_required
@perm_required("distribution.change_distribution")
def distribution_edit(request, pk):
    dist = get_object_or_404(Distribution, pk=pk)
    if dist.status not in (Distribution.Status.DRAFT, Distribution.Status.SUBMITTED):
        messages.error(request, "Hanya distribusi Draft/Diajukan yang dapat diubah.")
        return redirect("distribution:distribution_detail", pk=dist.pk)

    if request.method == "POST":
        form = DistributionForm(request.POST, instance=dist, user=request.user)
        formset = DistributionItemFormSet(request.POST, instance=dist, prefix="items")

        if form.is_valid() and formset.is_valid():
            form.save()
            sync_distribution_staff_assignments(
                dist, form.cleaned_data.get("assigned_staff", [])
            )
            formset.save()
            messages.success(
                request, f"Distribusi {dist.document_number} berhasil diperbarui."
            )
            return redirect("distribution:distribution_detail", pk=dist.pk)
    else:
        form = DistributionForm(instance=dist, user=request.user)
        formset = DistributionItemFormSet(instance=dist, prefix="items")

    return render(
        request,
        "distribution/distribution_form.html",
        {
            "form": form,
            "formset": formset,
            "title": f"Edit Distribusi {dist.document_number}",
            "is_edit": True,
            "distribution": dist,
            "show_distribution_type": True,
            "show_approved_quantity": True,
            "quantity_label": "Kuantitas Diminta",
            "item_error_colspan": 6,
            "back_url_name": "distribution:distribution_list",
        },
    )


@login_required
def distribution_detail(request, pk):
    dist = get_object_or_404(
        Distribution.objects.select_related(
            "facility", "created_by", "verified_by", "approved_by"
        )
        .prefetch_related("staff_assignments__user")
        .exclude(distribution_type__in=["BORROW_RS", "SWAP_RS"]),
        pk=pk,
    )
    items = dist.items.select_related("item", "item__satuan", "stock")
    assigned_staff = [assignment.user for assignment in dist.staff_assignments.all()]
    kepala_instalasi = (
        User.objects.filter(
            role=User.Role.KEPALA,
            is_active=True,
        )
        .order_by("full_name", "username")
        .first()
    )

    printable_items = []
    total_quantity = Decimal("0")
    grand_total = Decimal("0")
    for di in items:
        quantity = (
            di.quantity_approved
            if di.quantity_approved is not None
            else di.quantity_requested
        )
        unit_price = di.stock.unit_price if di.stock else None
        line_total = None
        if quantity is not None and unit_price is not None:
            line_total = quantity * unit_price

        if quantity is not None:
            total_quantity += quantity
        if line_total is not None:
            grand_total += line_total

        printable_items.append(
            {
                "line": di,
                "quantity": quantity,
                "unit_price": unit_price,
                "line_total": line_total,
            }
        )

    return render(
        request,
        "distribution/distribution_detail.html",
        {
            "distribution": dist,
            "items": items,
            "printable_items": printable_items,
            "total_quantity": total_quantity,
            "grand_total": grand_total,
            "assigned_staff": assigned_staff,
            "kepala_instalasi": kepala_instalasi,
            "page_title": "Detail Distribusi",
            "module_label": "Distribusi",
            "module_back_url_name": "distribution:distribution_list",
        },
    )


# ---------- Workflow transitions ----------


@login_required
@perm_required("distribution.change_distribution")
def distribution_submit(request, pk):
    dist = get_object_or_404(Distribution, pk=pk)
    if request.method != "POST":
        return _redirect_distribution_detail(pk)

    if dist.status != Distribution.Status.DRAFT:
        messages.error(request, "Hanya distribusi Draft yang dapat diajukan.")
        return _redirect_distribution_detail(pk)

    try:
        execute_distribution_submission(dist)
    except DistributionWorkflowError as exc:
        messages.error(request, str(exc))
        return _redirect_distribution_detail(pk)

    messages.success(request, f"Distribusi {dist.document_number} berhasil diajukan.")
    return _redirect_distribution_detail(pk)


@login_required
@perm_required("distribution.change_distribution")
@module_scope_required(ModuleAccess.Module.DISTRIBUTION, ModuleAccess.Scope.APPROVE)
def distribution_verify(request, pk):
    dist = get_object_or_404(Distribution, pk=pk)
    if request.method != "POST":
        return _redirect_distribution_detail(pk)

    if dist.status != Distribution.Status.SUBMITTED:
        messages.error(
            request, "Hanya distribusi berstatus Diajukan yang dapat diverifikasi."
        )
        return _redirect_distribution_detail(pk)

    try:
        execute_distribution_verification(dist, request.user)
    except DistributionWorkflowError as exc:
        messages.error(request, str(exc))
        return _redirect_distribution_detail(pk)

    messages.success(
        request, f"Distribusi {dist.document_number} berhasil diverifikasi."
    )
    return _redirect_distribution_detail(pk)


@login_required
@perm_required("distribution.change_distribution")
def distribution_prepare(request, pk):
    dist = get_object_or_404(Distribution, pk=pk)
    if request.method != "POST":
        return _redirect_distribution_detail(pk)

    if dist.status != Distribution.Status.VERIFIED:
        messages.error(request, "Hanya distribusi terverifikasi yang dapat disiapkan.")
        return _redirect_distribution_detail(pk)

    execute_distribution_preparation(dist)
    messages.success(request, f"Distribusi {dist.document_number} ditandai disiapkan.")
    return _redirect_distribution_detail(pk)


@login_required
@perm_required("distribution.change_distribution")
def distribution_distribute(request, pk):
    """Final step: deduct stock and create Transaction(OUT) records."""
    dist = get_object_or_404(Distribution, pk=pk)
    if request.method != "POST":
        return _redirect_distribution_detail(pk)

    if dist.status != Distribution.Status.PREPARED:
        messages.error(
            request, "Hanya distribusi berstatus Disiapkan yang dapat didistribusikan."
        )
        return _redirect_distribution_detail(pk)

    try:
        execute_stock_distribution(dist, request.user)
    except DistributionWorkflowError as exc:
        messages.error(request, str(exc))
        return _redirect_distribution_detail(pk)

    messages.success(
        request,
        f"Distribusi {dist.document_number} berhasil didistribusikan dan stok diperbarui.",
    )
    return _redirect_distribution_detail(pk)


@login_required
@perm_required("distribution.change_distribution")
@module_scope_required(ModuleAccess.Module.DISTRIBUTION, ModuleAccess.Scope.APPROVE)
def distribution_reject(request, pk):
    dist = get_object_or_404(Distribution, pk=pk)
    if request.method != "POST":
        return _redirect_distribution_detail(pk)

    if dist.status != Distribution.Status.SUBMITTED:
        messages.error(
            request, "Hanya distribusi berstatus Diajukan yang dapat ditolak."
        )
        return _redirect_distribution_detail(pk)

    execute_distribution_rejection(dist)
    messages.success(request, f"Distribusi {dist.document_number} ditolak.")
    return _redirect_distribution_detail(pk)


@login_required
@perm_required("distribution.change_distribution")
def distribution_reset_to_draft(request, pk):
    dist = get_object_or_404(Distribution, pk=pk)
    if request.method != "POST":
        return _redirect_distribution_detail(pk)

    resettable_statuses = {
        Distribution.Status.SUBMITTED,
        Distribution.Status.VERIFIED,
        Distribution.Status.PREPARED,
        Distribution.Status.REJECTED,
    }

    if dist.status not in resettable_statuses:
        if dist.status == Distribution.Status.DISTRIBUTED:
            messages.error(
                request,
                "Distribusi yang sudah didistribusikan tidak dapat dikembalikan ke Draft.",
            )
        else:
            messages.error(
                request,
                "Status distribusi saat ini tidak dapat dikembalikan ke Draft.",
            )
        return _redirect_distribution_detail(pk)

    execute_distribution_reset_to_draft(dist)
    messages.success(
        request, f"Distribusi {dist.document_number} dikembalikan ke Draft."
    )
    return _redirect_distribution_detail(pk)


@login_required
@perm_required("distribution.change_distribution")
def distribution_step_back(request, pk):
    dist = get_object_or_404(Distribution, pk=pk)
    if request.method != "POST":
        return _redirect_distribution_detail(pk)

    previous_status = get_distribution_step_back_target(dist)
    if previous_status is None:
        if dist.status == Distribution.Status.DISTRIBUTED:
            messages.error(
                request,
                "Distribusi yang sudah didistribusikan tidak dapat dikembalikan ke status sebelumnya.",
            )
        else:
            messages.error(
                request,
                "Status distribusi saat ini tidak memiliki status sebelumnya.",
            )
        return _redirect_distribution_detail(pk)

    execute_distribution_step_back(dist)
    messages.success(
        request,
        f"Distribusi {dist.document_number} dikembalikan ke status {dist.get_status_display()}.",
    )
    return _redirect_distribution_detail(pk)


@login_required
@perm_required("distribution.delete_distribution")
def distribution_delete(request, pk):
    dist = get_object_or_404(Distribution, pk=pk)
    if request.method != "POST":
        return _redirect_distribution_detail(pk)

    deletable_statuses = {
        Distribution.Status.DRAFT,
        Distribution.Status.REJECTED,
    }

    if dist.status not in deletable_statuses:
        messages.error(
            request,
            "Hanya distribusi berstatus Draft atau Ditolak yang dapat dihapus.",
        )
        return _redirect_distribution_detail(pk)

    document_number = dist.document_number
    dist.delete()
    messages.success(request, f"Distribusi {document_number} berhasil dihapus.")
    return redirect("distribution:distribution_list")
