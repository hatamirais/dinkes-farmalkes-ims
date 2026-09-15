from decimal import Decimal
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import (
    Case,
    DecimalField,
    ExpressionWrapper,
    F,
    IntegerField,
    Q,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.decimal_validation import multiply_decimals, sum_decimals
from apps.core.decorators import module_scope_required, perm_required
from apps.lplpo.forms import RejectLPLPOForm
from apps.lplpo.models import LPLPO
from apps.reports.views import (
    _PENGELUARAN_REPORT_TAB_URL_NAMES,
    render_pengeluaran_report,
)
from apps.stock.models import Stock
from apps.users.access import (
    can_approve_workflow,
    has_module_permission,
    has_module_scope,
)
from apps.users.models import ModuleAccess, User

from .forms import (
    DistributionForm,
    DistributionItemFormSet,
    LockedLPLPODistributionItemFormSet,
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
    release_distribution_reservations,
)

logger = logging.getLogger(__name__)


_DISTRIBUTION_REPORT_TAB_URL_NAMES = {
    **_PENGELUARAN_REPORT_TAB_URL_NAMES,
    "": "distribution:distribution_report",
    Distribution.DistributionType.SPECIAL_REQUEST: "distribution:distribution_report_special_request",
    Distribution.DistributionType.ALLOCATION: "distribution:distribution_report_allocation",
    Distribution.DistributionType.LPLPO: "distribution:distribution_report_lplpo",
}


def _order_distribution_queue(queryset):
    return queryset.annotate(
        queue_status_order=Case(
            When(status=Distribution.Status.DISTRIBUTED, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        )
    ).order_by("queue_status_order", "-created_at", "-request_date", "-pk")


def _redirect_distribution_detail(pk):
    return redirect("distribution:distribution_detail", pk=pk)


def _is_special_request(distribution):
    return (
        distribution.distribution_type
        == Distribution.DistributionType.SPECIAL_REQUEST
    )


def _is_distribution_preparer(user, distribution):
    if getattr(user, "is_superuser", False):
        return True
    return distribution.staff_assignments.filter(user_id=user.pk).exists()


def _can_manage_distribution_preparation(user, distribution):
    if _is_distribution_preparer(user, distribution):
        return True
    if not distribution.staff_assignments.exists():
        return has_module_scope(
            user,
            ModuleAccess.Module.DISTRIBUTION,
            ModuleAccess.Scope.APPROVE,
        )
    return False


def _can_return_generated_lplpo_to_puskesmas(user, distribution):
    return (
        distribution.is_generated_lplpo_distribution
        and distribution.status != Distribution.Status.DISTRIBUTED
        and _can_manage_distribution_preparation(user, distribution)
        and has_module_scope(
            user,
            ModuleAccess.Module.LPLPO,
            ModuleAccess.Scope.OPERATE,
        )
    )


def _can_view_reports(user):
    return user.is_superuser or user.has_perm("reports.view_reports") or has_module_permission(
        user, "reports.view_reports"
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
        "item_error_colspan": 7,
        "back_url_name": back_url_name,
        "active_pengeluaran_submenu": active_pengeluaran_submenu,
        "document_number_warning_enabled": document_number_warning_enabled,
    }


def _build_distribution_stock_catalog():
    available_quantity_expression = ExpressionWrapper(
        F("quantity") - F("reserved"),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )
    available_stocks = (
        Stock.objects.select_related("item", "sumber_dana")
        .filter(quantity__gt=F("reserved"))
        .annotate(available_qty=available_quantity_expression)
        .order_by(F("expiry_date").asc(nulls_last=True), "item_id", "batch_lot")
    )
    return [
        {
            "id": stock.pk,
            "itemId": stock.item_id,
            "label": stock.picker_label,
            "availableQty": float(stock.available_qty),
        }
        for stock in available_stocks
    ]


def _split_requested_quantities(requested_quantity, approved_splits):
    requested_quantity = Decimal(requested_quantity or 0)
    approved_total = sum(approved_splits, Decimal("0"))
    if requested_quantity == approved_total:
        return approved_splits
    if approved_total <= 0:
        return [Decimal("0") for _split in approved_splits]

    requested_splits = []
    remaining_requested = requested_quantity
    remaining_approved = approved_total
    for approved_quantity in approved_splits[:-1]:
        if remaining_requested <= 0 or remaining_approved <= 0:
            requested_split = Decimal("0")
        else:
            requested_split = (
                remaining_requested * approved_quantity / remaining_approved
            ).quantize(Decimal("0.01"))
            requested_split = min(requested_split, remaining_requested)
        requested_split = requested_split if requested_split > 0 else Decimal("0")
        requested_splits.append(requested_split)
        remaining_requested -= requested_split
        remaining_approved -= approved_quantity
    requested_splits.append(
        remaining_requested if remaining_requested > 0 else Decimal("0")
    )
    return requested_splits


def _allocate_current_stock_layers(item, approved_quantity):
    remaining_quantity = Decimal(approved_quantity or 0)
    allocations = []
    if remaining_quantity <= 0:
        return allocations

    stock_layers = (
        Stock.objects.select_related("item", "sumber_dana")
        .filter(item=item, quantity__gt=F("reserved"))
        .filter(
            Q(expiry_date__isnull=True) | Q(expiry_date__gt=timezone.localdate())
        )
        .order_by(
            F("expiry_date").asc(nulls_last=True),
            "item__nama_barang",
            "batch_lot",
            "source_document_number",
            "pk",
        )
    )
    for stock in stock_layers:
        available_quantity = stock.available_quantity
        if available_quantity <= 0:
            continue
        allocated_quantity = min(remaining_quantity, available_quantity)
        allocations.append((stock, allocated_quantity))
        remaining_quantity -= allocated_quantity
        if remaining_quantity <= 0:
            break

    if remaining_quantity > 0:
        raise ValueError(
            f"Stok gudang tidak cukup untuk {item.nama_barang}. "
            f"Dibutuhkan {approved_quantity}, kurang {remaining_quantity}."
        )

    return allocations


def _locked_lplpo_formset_structure_matches_post(distribution, post_data, prefix):
    existing_ids = set(distribution.items.values_list("pk", flat=True))
    try:
        total_forms = int(post_data.get(f"{prefix}-TOTAL_FORMS", ""))
        initial_forms = int(post_data.get(f"{prefix}-INITIAL_FORMS", ""))
    except ValueError:
        return False

    if total_forms != initial_forms or total_forms != len(existing_ids):
        return False

    submitted_ids = set()
    for index in range(total_forms):
        if post_data.get(f"{prefix}-{index}-DELETE"):
            return False
        try:
            submitted_ids.add(int(post_data.get(f"{prefix}-{index}-id", "")))
        except ValueError:
            return False

    return submitted_ids == existing_ids


def _locked_lplpo_formset_has_only_availability_errors(formset):
    if formset.non_form_errors():
        return False

    has_availability_error = False
    for form in formset.forms:
        form_error_fields = set(form.errors)
        if not form_error_fields:
            continue
        if not form_error_fields.issubset({"quantity_approved", "stock"}):
            return False
        if "stock" in form_error_fields:
            stock_errors = form.errors.as_data().get("stock", [])
            if any(error.code != "invalid_choice" for error in stock_errors):
                return False
        has_availability_error = True

    return has_availability_error


def _rebuild_generated_lplpo_item_rows(distribution, formset, post_data, prefix="items"):
    existing_items = list(
        distribution.items.select_related("item").order_by("item_id", "pk")
    )
    ordered_existing_items = list(distribution.items.order_by("pk"))
    notes_by_existing_id = {
        existing.pk: post_data.get(f"{prefix}-{index}-notes", existing.notes)
        for index, existing in enumerate(ordered_existing_items)
    }
    failing_item_ids = {
        form.instance.item_id
        for form in formset.forms
        if form.errors and form.instance.item_id
    }

    replacement_items = []
    for form in formset.forms:
        if form.errors or form.instance.item_id in failing_item_ids:
            continue
        cleaned_data = form.cleaned_data
        replacement_items.append(
            DistributionItem(
                distribution=distribution,
                item=cleaned_data["item"],
                quantity_requested=cleaned_data["quantity_requested"],
                quantity_approved=cleaned_data["quantity_approved"],
                stock=cleaned_data.get("stock"),
                notes=cleaned_data.get("notes", ""),
            )
        )

    grouped = {}
    for existing in existing_items:
        if existing.item_id not in failing_item_ids:
            continue
        group = grouped.setdefault(
            existing.item_id,
            {
                "item": existing.item,
                "quantity_requested": Decimal("0"),
                "quantity_approved": Decimal("0"),
                "notes": [],
            },
        )
        group["quantity_requested"] += Decimal(existing.quantity_requested or 0)
        group["quantity_approved"] += Decimal(existing.quantity_approved or 0)
        submitted_note = notes_by_existing_id.get(existing.pk, existing.notes)
        if submitted_note and submitted_note not in group["notes"]:
            group["notes"].append(submitted_note)

    for group in grouped.values():
        allocations = _allocate_current_stock_layers(
            group["item"],
            group["quantity_approved"],
        )
        requested_splits = _split_requested_quantities(
            group["quantity_requested"],
            [allocated_quantity for _stock, allocated_quantity in allocations],
        )
        for (stock, allocated_quantity), requested_quantity in zip(
            allocations,
            requested_splits,
        ):
            replacement_items.append(
                DistributionItem(
                    distribution=distribution,
                    item=group["item"],
                    quantity_requested=requested_quantity,
                    quantity_approved=allocated_quantity,
                    stock=stock,
                    notes="\n".join(group["notes"]),
                )
            )

    distribution.items.all().delete()
    DistributionItem.objects.bulk_create(replacement_items)


def _build_distribution_item_rows(formset):
    zero_decimal = Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))
    available_quantity_expression = ExpressionWrapper(
        F("quantity") - F("reserved"),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )
    rows = []
    item_ids = set()

    for item_form in formset.forms:
        raw_item_id = item_form["item"].value() or getattr(item_form.instance, "item_id", None)
        try:
            item_id = int(raw_item_id) if raw_item_id else None
        except (TypeError, ValueError):
            item_id = None
        if item_id:
            item_ids.add(item_id)
        rows.append({"form": item_form, "item_id": item_id})

    available_by_item = {}
    if item_ids:
        stock_rows = (
            Stock.objects.filter(item_id__in=item_ids)
            .values("item_id")
            .annotate(
                total_available=Coalesce(Sum(available_quantity_expression), zero_decimal),
            )
        )
        available_by_item = {row["item_id"]: row["total_available"] for row in stock_rows}

    for row in rows:
        row["available_stock_total"] = available_by_item.get(row["item_id"])

    return rows


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
    queryset = _order_distribution_queue(
        Distribution.objects.select_related("facility", "created_by").exclude(
            distribution_type__in=["BORROW_RS", "SWAP_RS"]
        )
    )
    can_view_reports = _can_view_reports(request.user)

    return _render_distribution_list(
        request,
        queryset=queryset,
        page_title="Distribusi Barang",
        list_title="Riwayat Pengeluaran",
        reset_url_name="distribution:distribution_list",
        empty_state_text="Belum ada riwayat pengeluaran",
        active_pengeluaran_submenu="distribution_history",
        show_type_filter=True,
        report_url_name="distribution:distribution_report" if can_view_reports else None,
        report_button_label="Laporan Pengeluaran" if can_view_reports else None,
    )


@login_required
@perm_required("reports.view_reports")
def distribution_report(request):
    return render_pengeluaran_report(
        request,
        base_report_url_name="distribution:distribution_report",
        tab_url_names=_DISTRIBUTION_REPORT_TAB_URL_NAMES,
    )


@login_required
@perm_required("reports.view_reports")
def distribution_report_special_request(request):
    return render_pengeluaran_report(
        request,
        forced_distribution_type=Distribution.DistributionType.SPECIAL_REQUEST,
        base_report_url_name="distribution:distribution_report",
        tab_url_names=_DISTRIBUTION_REPORT_TAB_URL_NAMES,
    )


@login_required
@perm_required("reports.view_reports")
def distribution_report_allocation(request):
    return render_pengeluaran_report(
        request,
        forced_distribution_type=Distribution.DistributionType.ALLOCATION,
        base_report_url_name="distribution:distribution_report",
        tab_url_names=_DISTRIBUTION_REPORT_TAB_URL_NAMES,
    )


@login_required
@perm_required("reports.view_reports")
def distribution_report_lplpo(request):
    return render_pengeluaran_report(
        request,
        forced_distribution_type=Distribution.DistributionType.LPLPO,
        base_report_url_name="distribution:distribution_report",
        tab_url_names=_DISTRIBUTION_REPORT_TAB_URL_NAMES,
    )


@login_required
@perm_required("distribution.view_distribution")
def special_request_list(request):
    queryset = _order_distribution_queue(
        Distribution.objects.select_related("facility", "created_by").filter(
            distribution_type=Distribution.DistributionType.SPECIAL_REQUEST
        )
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


@login_required
@perm_required("distribution.add_distribution")
def manual_lplpo_create(request):
    return _save_manual_lplpo_distribution(request)


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
            "item_rows": _build_distribution_item_rows(formset),
            "stock_catalog": _build_distribution_stock_catalog(),
            "is_edit": False,
            "allow_item_row_mutation": True,
            **_build_distribution_form_context(
                title="Buat Permintaan Khusus",
                back_url_name="distribution:special_request_list",
                active_pengeluaran_submenu="special_request",
                document_number_warning_enabled=True,
            ),
        },
    )


def _save_manual_lplpo_distribution(request):
    if request.method == "POST":
        form = DistributionForm(
            request.POST,
            user=request.user,
            forced_distribution_type=Distribution.DistributionType.LPLPO,
        )
        formset = DistributionItemFormSet(request.POST, prefix="items")

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                dist = form.save(commit=False)
                dist.distribution_type = Distribution.DistributionType.LPLPO
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
                f"Distribusi LPLPO {dist.document_number} berhasil dibuat.",
            )
            return redirect("distribution:distribution_detail", pk=dist.pk)
    else:
        form = DistributionForm(
            user=request.user,
            forced_distribution_type=Distribution.DistributionType.LPLPO,
        )
        formset = DistributionItemFormSet(prefix="items")

    return render(
        request,
        "distribution/distribution_form.html",
        {
            "form": form,
            "formset": formset,
            "item_rows": _build_distribution_item_rows(formset),
            "stock_catalog": _build_distribution_stock_catalog(),
            "is_edit": False,
            "allow_item_row_mutation": True,
            **_build_distribution_form_context(
                title="Buat Distribusi LPLPO",
                back_url_name="distribution:distribution_list",
                active_pengeluaran_submenu="distribution_history",
            ),
        },
    )


@login_required
@perm_required("distribution.change_distribution")
def distribution_edit(request, pk):
    dist = get_object_or_404(Distribution, pk=pk)
    if dist.status not in (Distribution.Status.DRAFT, Distribution.Status.REJECTED):
        messages.error(request, "Hanya distribusi Draft/Ditolak yang dapat diubah.")
        return redirect("distribution:distribution_detail", pk=dist.pk)

    if not _can_manage_distribution_preparation(request.user, dist):
        raise PermissionDenied(
            "Hanya petugas yang ditugaskan yang dapat mengubah distribusi ini."
        )

    if dist.distribution_type == Distribution.DistributionType.ALLOCATION:
        messages.error(request, "Distribusi alokasi tidak dapat diubah dari modul ini.")
        return redirect("distribution:distribution_detail", pk=dist.pk)

    is_special_request = _is_special_request(dist)
    is_generated_lplpo_distribution = dist.is_generated_lplpo_distribution
    forced_distribution_type = (
        Distribution.DistributionType.SPECIAL_REQUEST if is_special_request else None
    )
    formset_class = (
        LockedLPLPODistributionItemFormSet
        if is_generated_lplpo_distribution
        else DistributionItemFormSet
    )
    formset_kwargs = {"prefix": "items"}
    if is_generated_lplpo_distribution:
        formset_kwargs["form_kwargs"] = {"lock_quantity_fields": True}

    if request.method == "POST":
        form = DistributionForm(
            request.POST,
            instance=dist,
            user=request.user,
            forced_distribution_type=forced_distribution_type,
        )
        formset = formset_class(request.POST, instance=dist, **formset_kwargs)
        formset_is_valid = formset.is_valid()
        should_rebuild_generated_lplpo_rows = (
            is_generated_lplpo_distribution
            and not formset_is_valid
            and _locked_lplpo_formset_structure_matches_post(
                dist,
                request.POST,
                formset_kwargs["prefix"],
            )
            and _locked_lplpo_formset_has_only_availability_errors(formset)
        )

        if form.is_valid() and (formset_is_valid or should_rebuild_generated_lplpo_rows):
            try:
                with transaction.atomic():
                    dist = form.save(commit=False)
                    if forced_distribution_type:
                        dist.distribution_type = forced_distribution_type
                    dist.save()
                    sync_distribution_staff_assignments(
                        dist, form.cleaned_data.get("assigned_staff", [])
                    )
                    if should_rebuild_generated_lplpo_rows:
                        _rebuild_generated_lplpo_item_rows(
                            dist,
                            formset,
                            request.POST,
                            formset_kwargs["prefix"],
                        )
                    else:
                        formset.save()
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
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
        formset = formset_class(instance=dist, **formset_kwargs)

    return render(
        request,
        "distribution/distribution_form.html",
        {
            "form": form,
            "formset": formset,
            "item_rows": _build_distribution_item_rows(formset),
            "stock_catalog": _build_distribution_stock_catalog(),
            "is_edit": True,
            "distribution": dist,
            "is_generated_lplpo_distribution": is_generated_lplpo_distribution,
            "allow_item_row_mutation": not is_generated_lplpo_distribution,
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
            line_total = multiply_decimals(quantity, unit_price)

        if quantity is not None:
            total_quantity += quantity
        if line_total is not None:
            grand_total = sum_decimals([grand_total, line_total])

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
    can_prepare_distribution = (
        not is_allocation
        and dist.status in {Distribution.Status.DRAFT, Distribution.Status.REJECTED}
        and _can_manage_distribution_preparation(request.user, dist)
    )
    can_submit_distribution = (
        not is_allocation
        and dist.status == Distribution.Status.PREPARED
        and _can_manage_distribution_preparation(request.user, dist)
    )
    can_edit_distribution = (
        not is_allocation
        and dist.status in {Distribution.Status.DRAFT, Distribution.Status.REJECTED}
        and _can_manage_distribution_preparation(request.user, dist)
    )
    can_verify_distribution = (
        not is_allocation
        and dist.status == Distribution.Status.SUBMITTED
        and can_approve_workflow(
            request.user,
            ModuleAccess.Module.DISTRIBUTION,
        )
    )
    can_reject_distribution = can_verify_distribution
    can_distribute_distribution = (
        not is_allocation
        and dist.status == Distribution.Status.VERIFIED
        and _can_manage_distribution_preparation(request.user, dist)
    )
    can_return_lplpo_to_puskesmas = _can_return_generated_lplpo_to_puskesmas(
        request.user, dist
    )
    can_print_sbbk = (
        dist.status in {Distribution.Status.VERIFIED, Distribution.Status.PREPARED}
        or bool(dist.approved_by)
    )
    can_reset_to_draft_distribution = (
        not is_allocation
        and dist.status
        in {
            Distribution.Status.SUBMITTED,
            Distribution.Status.VERIFIED,
            Distribution.Status.PREPARED,
            Distribution.Status.REJECTED,
        }
        and _can_manage_distribution_preparation(request.user, dist)
    )
    can_step_back_distribution = (
        not is_allocation
        and dist.status
        in {
            Distribution.Status.SUBMITTED,
            Distribution.Status.VERIFIED,
            Distribution.Status.PREPARED,
            Distribution.Status.REJECTED,
        }
        and _can_manage_distribution_preparation(request.user, dist)
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
            "can_edit_distribution": can_edit_distribution,
            "can_prepare_distribution": can_prepare_distribution,
            "can_submit_distribution": can_submit_distribution,
            "can_verify_distribution": can_verify_distribution,
            "can_reject_distribution": can_reject_distribution,
            "can_distribute_distribution": can_distribute_distribution,
            "can_return_lplpo_to_puskesmas": can_return_lplpo_to_puskesmas,
            "can_print_sbbk": can_print_sbbk,
            "can_reset_to_draft_distribution": can_reset_to_draft_distribution,
            "can_step_back_distribution": can_step_back_distribution,
            "active_pengeluaran_submenu": (
                "special_request"
                if _is_special_request(dist)
                else "distribution_history"
            ),
            "is_generated_lplpo_distribution": dist.is_generated_lplpo_distribution,
        },
    )


# ---------- Workflow transitions ----------


@login_required
@perm_required("distribution.change_distribution")
def distribution_submit(request, pk):
    dist = get_object_or_404(Distribution, pk=pk)
    if request.method != "POST":
        return _redirect_distribution_detail(pk)

    if not _can_manage_distribution_preparation(request.user, dist):
        raise PermissionDenied(
            "Hanya petugas yang ditugaskan yang dapat mengajukan distribusi ini."
        )

    if dist.status != Distribution.Status.PREPARED:
        messages.error(request, "Hanya distribusi berstatus Disiapkan yang dapat diajukan.")
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
    if not can_approve_workflow(
        request.user,
        ModuleAccess.Module.DISTRIBUTION,
    ):
        raise PermissionDenied(
            "Hanya Kepala Instalasi atau Admin yang dapat menyetujui distribusi."
        )

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

    if not _can_manage_distribution_preparation(request.user, dist):
        raise PermissionDenied(
            "Hanya petugas yang ditugaskan yang dapat menyiapkan distribusi ini."
        )

    allowed_statuses = {Distribution.Status.DRAFT, Distribution.Status.REJECTED}
    error_message = "Hanya distribusi Draft atau Ditolak yang dapat ditandai siap."
    if dist.distribution_type == Distribution.DistributionType.ALLOCATION:
        allowed_statuses = {Distribution.Status.VERIFIED}
        error_message = (
            "Hanya distribusi alokasi berstatus Diverifikasi yang dapat ditandai siap."
        )

    if dist.status not in allowed_statuses:
        messages.error(request, error_message)
        return _redirect_distribution_detail(pk)

    execute_distribution_preparation(dist)
    messages.success(request, f"Distribusi {dist.document_number} ditandai siap diajukan.")
    return _redirect_distribution_detail(pk)


@login_required
@perm_required("distribution.change_distribution")
@module_scope_required(ModuleAccess.Module.DISTRIBUTION, ModuleAccess.Scope.OPERATE)
def distribution_distribute(request, pk):
    """Final step: deduct stock and create Transaction(OUT) records."""
    dist = get_object_or_404(Distribution, pk=pk)
    if request.method != "POST":
        return _redirect_distribution_detail(pk)

    if not _can_manage_distribution_preparation(request.user, dist):
        raise PermissionDenied(
            "Anda tidak memiliki akses untuk mendistribusikan dokumen ini."
        )

    allowed_statuses = {Distribution.Status.VERIFIED}
    error_message = (
        "Hanya distribusi berstatus Diverifikasi yang dapat didistribusikan."
    )
    if dist.distribution_type == Distribution.DistributionType.ALLOCATION:
        allowed_statuses = {Distribution.Status.PREPARED}
        error_message = (
            "Hanya distribusi alokasi berstatus Disiapkan yang dapat didistribusikan."
        )

    if dist.status not in allowed_statuses:
        messages.error(request, error_message)
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
    if not can_approve_workflow(
        request.user,
        ModuleAccess.Module.DISTRIBUTION,
    ):
        raise PermissionDenied(
            "Hanya Kepala Instalasi atau Admin yang dapat menolak distribusi."
        )

    dist = get_object_or_404(Distribution, pk=pk)
    if request.method != "POST":
        return _redirect_distribution_detail(pk)

    if dist.status != Distribution.Status.SUBMITTED:
        messages.error(
            request, "Hanya distribusi berstatus Diajukan yang dapat ditolak."
        )
        return _redirect_distribution_detail(pk)

    try:
        execute_distribution_rejection(dist)
    except DistributionWorkflowError as exc:
        messages.error(request, str(exc))
        return _redirect_distribution_detail(pk)
    messages.success(request, f"Distribusi {dist.document_number} ditolak.")
    return _redirect_distribution_detail(pk)


@login_required
@perm_required("distribution.change_distribution")
def distribution_reset_to_draft(request, pk):
    dist = get_object_or_404(Distribution, pk=pk)
    if request.method != "POST":
        return _redirect_distribution_detail(pk)
    if not _can_manage_distribution_preparation(request.user, dist):
        raise PermissionDenied(
            "Anda tidak memiliki akses untuk mengubah distribusi ini."
        )

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

    try:
        execute_distribution_reset_to_draft(dist)
    except DistributionWorkflowError as exc:
        messages.error(request, str(exc))
        return _redirect_distribution_detail(pk)

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
    if not _can_manage_distribution_preparation(request.user, dist):
        raise PermissionDenied(
            "Anda tidak memiliki akses untuk mengubah distribusi ini."
        )

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

    try:
        execute_distribution_step_back(dist)
    except DistributionWorkflowError as exc:
        messages.error(request, str(exc))
        return _redirect_distribution_detail(pk)

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
    if not _can_manage_distribution_preparation(request.user, dist):
        raise PermissionDenied(
            "Anda tidak memiliki akses untuk mengubah distribusi ini."
        )

    if dist.is_generated_lplpo_distribution:
        messages.error(
            request,
            (
                "Distribusi hasil generate LPLPO tidak dapat dihapus. "
                "Gunakan aksi 'Batalkan & Kembalikan ke Puskesmas'."
            ),
        )
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
    with transaction.atomic():
        dist = get_object_or_404(Distribution.objects.select_for_update(), pk=pk)
        release_distribution_reservations(dist)
        redirect_url_name = (
        "distribution:special_request_list"
        if _is_special_request(dist)
        else "distribution:distribution_list"
        )
        dist.delete()
    messages.success(request, f"Distribusi {document_number} berhasil dihapus.")
    return redirect(redirect_url_name)


@login_required
@perm_required("distribution.change_distribution")
@module_scope_required(ModuleAccess.Module.LPLPO, ModuleAccess.Scope.OPERATE)
def distribution_return_lplpo_to_puskesmas(request, pk):
    if request.method != "POST":
        return _redirect_distribution_detail(pk)

    form = RejectLPLPOForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Alasan penolakan wajib diisi.")
        return _redirect_distribution_detail(pk)

    with transaction.atomic():
        dist = get_object_or_404(Distribution.objects.select_for_update(), pk=pk)

        if not _can_return_generated_lplpo_to_puskesmas(request.user, dist):
            raise PermissionDenied(
                "Distribusi ini tidak dapat dikembalikan ke Puskesmas."
            )

        lplpo_obj = (
            LPLPO.objects.select_for_update()
            .filter(
                distribution_id=dist.pk,
                status=LPLPO.Status.APPROVED,
            )
            .first()
        )
        if lplpo_obj is None:
            messages.error(
                request,
                "Hanya distribusi LPLPO yang masih menunggu proses distribusi yang dapat dikembalikan ke Puskesmas.",
            )
            return _redirect_distribution_detail(pk)

        distribution_document_number = dist.document_number
        release_distribution_reservations(dist)

        lplpo_obj.status = LPLPO.Status.REJECTED_PUSKESMAS
        lplpo_obj.verified_by = None
        lplpo_obj.verified_at = None
        lplpo_obj.reviewed_by = None
        lplpo_obj.reviewed_at = None
        lplpo_obj.approved_by = None
        lplpo_obj.approved_at = None
        lplpo_obj.distribution = None
        lplpo_obj.rejection_reason = form.cleaned_data["rejection_reason"]
        lplpo_obj.save(
            update_fields=[
                "status",
                "verified_by",
                "verified_at",
                "reviewed_by",
                "reviewed_at",
                "approved_by",
                "approved_at",
                "distribution",
                "rejection_reason",
                "updated_at",
            ]
        )
        dist.delete()

    logger.info(
        "distribution_returned_lplpo_to_puskesmas",
        extra={
            "user_id": request.user.pk,
            "distribution_id": pk,
            "lplpo_id": lplpo_obj.pk,
        },
    )
    messages.success(
        request,
        (
            f"Distribusi {distribution_document_number} dibatalkan. "
            f"LPLPO {lplpo_obj.document_number} dikembalikan ke Puskesmas."
        ),
    )
    if request.user.is_superuser or getattr(request.user, "role", None) == User.Role.ADMIN:
        return redirect("lplpo:lplpo_detail", pk=lplpo_obj.pk)
    return redirect("distribution:distribution_list")
