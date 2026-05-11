from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
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


def _is_special_request(distribution):
    return (
        distribution.distribution_type
        == Distribution.DistributionType.SPECIAL_REQUEST
    )


def _render_distribution_list(
    request,
    *,
    queryset,
    page_title,
    list_title,
    reset_url_name,
    empty_state_text,
    active_pengeluaran_submenu,
    create_url_name=None,
    create_button_label=None,
    show_type_filter=True,
    report_url_name=None,
    report_button_label=None,
):
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
    if show_type_filter and d_type:
        queryset = queryset.filter(distribution_type=d_type)
    else:
        d_type = ""

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
            "page_title": page_title,
            "list_title": list_title,
            "create_url_name": create_url_name,
            "create_button_label": create_button_label,
            "detail_url_name": "distribution:distribution_detail",
            "reset_url_name": reset_url_name,
            "show_type_filter": show_type_filter,
            "module_icon": "bi-send",
            "empty_state_text": empty_state_text,
            "report_url_name": report_url_name,
            "report_button_label": report_button_label,
            "active_pengeluaran_submenu": active_pengeluaran_submenu,
        },
    )


def _build_distribution_form_context(
    *, title, back_url_name, active_pengeluaran_submenu, document_number_warning_enabled=False
):
    return {
        "title": title,
        "page_title": title,
        "show_distribution_type": False,
        "show_approved_quantity": True,
        "quantity_label": "Kuantitas Diminta",
        "item_error_colspan": 6,
        "back_url_name": back_url_name,
        "active_pengeluaran_submenu": active_pengeluaran_submenu,
        "document_number_warning_enabled": document_number_warning_enabled,
    }


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
@perm_required("distribution.view_distribution")
def distribution_list(request):
    queryset = (
        Distribution.objects.select_related("facility", "created_by")
        .exclude(distribution_type__in=["BORROW_RS", "SWAP_RS"])
        .order_by("-request_date")
    )

    return _render_distribution_list(
        request,
        queryset=queryset,
        page_title="Distribusi Barang",
        list_title="Riwayat Pengeluaran",
        reset_url_name="distribution:distribution_list",
        empty_state_text="Belum ada riwayat pengeluaran",
        active_pengeluaran_submenu="distribution_history",
        show_type_filter=True,
        report_url_name="reports:pengeluaran",
        report_button_label="Laporan Pengeluaran",
    )


@login_required
@perm_required("distribution.view_distribution")
def special_request_list(request):
    queryset = (
        Distribution.objects.select_related("facility", "created_by")
        .filter(distribution_type=Distribution.DistributionType.SPECIAL_REQUEST)
        .order_by("-request_date")
    )

    return _render_distribution_list(
        request,
        queryset=queryset,
        page_title="Permintaan Khusus",
        list_title="Daftar Permintaan Khusus",
        reset_url_name="distribution:special_request_list",
        empty_state_text="Belum ada permintaan khusus",
        active_pengeluaran_submenu="special_request",
        create_url_name="distribution:special_request_create",
        create_button_label="Buat Permintaan Khusus",
        show_type_filter=False,
    )


@login_required
@perm_required("distribution.add_distribution")
def distribution_create(request):
    return _save_special_request(request)


@login_required
@perm_required("distribution.add_distribution")
def special_request_create(request):
    return _save_special_request(request)


def _save_special_request(request):
    if request.method == "POST":
        form = DistributionForm(
            request.POST,
            user=request.user,
            forced_distribution_type=Distribution.DistributionType.SPECIAL_REQUEST,
        )
        formset = DistributionItemFormSet(request.POST, prefix="items")

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                dist = form.save(commit=False)
                dist.distribution_type = Distribution.DistributionType.SPECIAL_REQUEST
                dist.created_by = request.user
                dist.status = Distribution.Status.DRAFT
                dist.save()
                sync_distribution_staff_assignments(
                    dist, form.cleaned_data.get("assigned_staff", [])
                )

                formset.instance = dist
                formset.save()

            messages.success(
                request,
                f"Permintaan khusus {dist.document_number} berhasil dibuat.",
            )
            return redirect("distribution:distribution_detail", pk=dist.pk)
    else:
        form = DistributionForm(
            user=request.user,
            forced_distribution_type=Distribution.DistributionType.SPECIAL_REQUEST,
        )
        formset = DistributionItemFormSet(prefix="items")

    return render(
        request,
        "distribution/distribution_form.html",
        {
            "form": form,
            "formset": formset,
            "is_edit": False,
            **_build_distribution_form_context(
                title="Buat Permintaan Khusus",
                back_url_name="distribution:special_request_list",
                active_pengeluaran_submenu="special_request",
                document_number_warning_enabled=True,
            ),
        },
    )


@login_required
@perm_required("distribution.change_distribution")
def distribution_edit(request, pk):
    dist = get_object_or_404(Distribution, pk=pk)
    if dist.status not in (Distribution.Status.DRAFT, Distribution.Status.SUBMITTED):
        messages.error(request, "Hanya distribusi Draft/Diajukan yang dapat diubah.")
        return redirect("distribution:distribution_detail", pk=dist.pk)

    is_special_request = _is_special_request(dist)
    forced_distribution_type = (
        Distribution.DistributionType.SPECIAL_REQUEST if is_special_request else None
    )

    if request.method == "POST":
        form = DistributionForm(
            request.POST,
            instance=dist,
            user=request.user,
            forced_distribution_type=forced_distribution_type,
        )
        formset = DistributionItemFormSet(request.POST, instance=dist, prefix="items")

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                dist = form.save(commit=False)
                if forced_distribution_type:
                    dist.distribution_type = forced_distribution_type
                dist.save()
                sync_distribution_staff_assignments(
                    dist, form.cleaned_data.get("assigned_staff", [])
                )
                formset.save()
            messages.success(
                request,
                (
                    f"Permintaan khusus {dist.document_number} berhasil diperbarui."
                    if is_special_request
                    else f"Distribusi {dist.document_number} berhasil diperbarui."
                ),
            )
            return redirect("distribution:distribution_detail", pk=dist.pk)
    else:
        form = DistributionForm(
            instance=dist,
            user=request.user,
            forced_distribution_type=forced_distribution_type,
        )
        formset = DistributionItemFormSet(instance=dist, prefix="items")

    return render(
        request,
        "distribution/distribution_form.html",
        {
            "form": form,
            "formset": formset,
            "is_edit": True,
            "distribution": dist,
            **_build_distribution_form_context(
                title=(
                    f"Edit Permintaan Khusus {dist.document_number}"
                    if is_special_request
                    else f"Edit Distribusi {dist.document_number}"
                ),
                back_url_name=(
                    "distribution:special_request_list"
                    if is_special_request
                    else "distribution:distribution_list"
                ),
                active_pengeluaran_submenu=(
                    "special_request"
                    if is_special_request
                    else "distribution_history"
                ),
                document_number_warning_enabled=is_special_request,
            ),
        },
    )


@login_required
@perm_required("distribution.view_distribution")
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

    is_allocation = (
        dist.distribution_type == Distribution.DistributionType.ALLOCATION
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
            "is_allocation": is_allocation,
            "page_title": (
                "Detail Permintaan Khusus"
                if _is_special_request(dist)
                else "Detail Distribusi"
            ),
            "module_label": (
                "Permintaan Khusus"
                if _is_special_request(dist)
                else "Distribusi"
            ),
            "module_back_url_name": (
                "distribution:special_request_list"
                if _is_special_request(dist)
                else "distribution:distribution_list"
            ),
            "active_pengeluaran_submenu": (
                "special_request"
                if _is_special_request(dist)
                else "distribution_history"
            ),
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
@module_scope_required(ModuleAccess.Module.DISTRIBUTION, ModuleAccess.Scope.APPROVE)
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
    redirect_url_name = (
        "distribution:special_request_list"
        if _is_special_request(dist)
        else "distribution:distribution_list"
    )
    dist.delete()
    messages.success(request, f"Distribusi {document_number} berhasil dihapus.")
    return redirect(redirect_url_name)
