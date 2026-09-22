import json
import logging
from datetime import datetime, time
from pathlib import PurePath

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q, F
from django.http import FileResponse, Http404, JsonResponse
from django.views.decorators.http import require_POST
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from apps.core.decorators import module_scope_required, perm_required
from apps.core.decimal_validation import format_price_exact
from apps.core.models import DocumentNumberRule
from apps.core.numbering import issue_document_number, void_document_number
from apps.core.rate_limits import item_mutation_ratelimit, receiving_mutation_ratelimit
from apps.core.upload_validation import sanitize_uploaded_filename
from apps.stock.models import Stock, Transaction
from apps.users.access import has_module_scope
from apps.users.models import ModuleAccess, User
from .models import (
    Receiving,
    ReceivingDocument,
    ReceivingItem,
    ReceivingOrderItem,
    ReceivingTypeOption,
    increment_receiving_stock,
    resolve_receiving_source_document_number,
)
from .forms import (
    build_planned_receipt_item_formset,
    ReceivingCancelForm,
    ReceivingCloseForm,
    ReceivingEditForm,
    ReceivingForm,
    ReceivingItemFormSet,
    ReceivingOrderCloseItemFormSet,
    ReceivingQuickCreateFundingSourceForm,
    ReceivingQuickCreateReceivingTypeForm,
    ReceivingQuickCreateSupplierForm,
    ReceivingReceiptItemFormSet,
)

logger = logging.getLogger("security")


def _json_form_errors(form):
    errors = []
    for field_errors in form.errors.values():
        errors.extend(field_errors)
    return " ".join(errors) or "Data tidak valid."


def _safe_download_filename(document):
    try:
        return sanitize_uploaded_filename(document.file_name)
    except ValidationError:
        return PurePath(document.file.name).name or f"receiving-{document.pk}"


class PlannedReceiptQuantityConflict(ValueError):
    def __init__(self, order_item_id, message):
        super().__init__(message)
        self.order_item_id = order_item_id


class ReceivingCorrectionError(ValueError):
    pass


def _can_correct_regular_receiving(user):
    return bool(
        getattr(user, "is_superuser", False)
        or getattr(user, "role", None)
        in {User.Role.ADMIN, User.Role.GUDANG, User.Role.KEPALA}
    )


def _has_regular_receiving_correction_access(user):
    return bool(
        _can_correct_regular_receiving(user)
        and (
            getattr(user, "is_superuser", False)
            or has_module_scope(
                user,
                ModuleAccess.Module.RECEIVING,
                ModuleAccess.Scope.OPERATE,
            )
        )
    )


def _require_regular_receiving_correction_role(user):
    if not _can_correct_regular_receiving(user):
        raise PermissionDenied(
            "Anda tidak memiliki akses untuk mengoreksi penerimaan ini."
        )


def _stock_identity_filters(item):
    return {
        "item": item.item,
        "location": item.location,
        "batch_lot": item.batch_lot,
    }


def _matching_original_receiving_transaction_filters(receiving, item):
    return {
        "reference_type": Transaction.ReferenceType.RECEIVING,
        "reference_id": receiving.pk,
        "transaction_type": Transaction.TransactionType.IN,
        "item": item.item,
        "location": item.location,
        "batch_lot": item.batch_lot,
        "quantity": item.quantity,
        "unit_price": item.unit_price,
    }


def _filter_stocks_by_item_metadata(stocks, item):
    return [
        stock
        for stock in stocks
        if stock.expiry_date == item.expiry_date and stock.unit_price == item.unit_price
    ]


def _filter_current_stock_candidates(stocks, item):
    return [
        stock
        for stock in stocks
        if stock.quantity > 0 and stock.quantity >= item.quantity
    ]


def _select_single_stock_candidate(receiving, item, stocks):
    if len(stocks) == 1:
        return stocks[0]

    if item.posted_sumber_dana_id or item.posted_source_document_number:
        posted_matches = [
            stock
            for stock in stocks
            if (
                not item.posted_sumber_dana_id
                or stock.sumber_dana_id == item.posted_sumber_dana_id
            )
            and (
                not item.posted_source_document_number
                or stock.source_document_number == item.posted_source_document_number
            )
        ]
        if len(posted_matches) == 1:
            return posted_matches[0]

    metadata_matches = _filter_stocks_by_item_metadata(stocks, item)
    if len(metadata_matches) == 1:
        return metadata_matches[0]

    current_matches = _filter_current_stock_candidates(metadata_matches, item)
    if len(current_matches) == 1:
        return current_matches[0]

    current_matches = _filter_current_stock_candidates(stocks, item)
    if len(current_matches) == 1:
        return current_matches[0]

    transaction_layer = (
        Transaction.objects.filter(
            **_matching_original_receiving_transaction_filters(receiving, item)
        )
        .exclude(sumber_dana__isnull=True)
        .values_list("sumber_dana_id", "source_document_number")
        .distinct()
    )
    transaction_layers = list(transaction_layer)
    if len(transaction_layers) == 1:
        funding_id, source_document_number = transaction_layers[0]
        transaction_matches = [
            stock
            for stock in stocks
            if stock.sumber_dana_id == funding_id
            and stock.source_document_number == source_document_number
        ]
        if len(transaction_matches) == 1:
            return transaction_matches[0]

    return None


def _get_original_receiving_stock(receiving, item):
    source_document_number = item.posted_source_document_number or (
        resolve_receiving_source_document_number(
            receiving,
            item=item.item,
            location=item.location,
            batch_lot=item.batch_lot,
            sumber_dana=item.posted_sumber_dana,
        )
    )
    stock_filters = {
        **_stock_identity_filters(item),
        "source_document_number": source_document_number,
    }
    if item.posted_sumber_dana_id:
        stock_filters["sumber_dana_id"] = item.posted_sumber_dana_id
    candidates = list(
        Stock.objects.select_for_update(of=("self",))
        .select_related("sumber_dana")
        .filter(receiving_ref=receiving, **stock_filters)
    )
    if not candidates:
        transaction_layers = list(
            Transaction.objects.filter(
                **_matching_original_receiving_transaction_filters(receiving, item),
                source_document_number=source_document_number,
            )
            .exclude(sumber_dana__isnull=True)
            .values_list("sumber_dana_id", "source_document_number")
            .distinct()
        )
        if len(transaction_layers) == 1:
            funding_id, source_document_number = transaction_layers[0]
            candidates = list(
                Stock.objects.select_for_update(of=("self",))
                .select_related("sumber_dana")
                .filter(
                    **stock_filters,
                    sumber_dana_id=funding_id,
                )
            )

    stock = _select_single_stock_candidate(receiving, item, candidates)
    if stock is None and candidates:
        raise ReceivingCorrectionError(
            (
                f"Lapisan stok untuk {item.item} batch {item.batch_lot} ambigu. "
                "Periksa sumber dana stok sebelum koreksi."
            )
        )
    return stock


def _reverse_regular_receiving_stock(receiving, items, user, reason, *, action_label):
    transactions = []
    for item in items:
        stock = _get_original_receiving_stock(receiving, item)
        if stock is None:
            raise ReceivingCorrectionError(
                f"Stok untuk {item.item} batch {item.batch_lot} tidak ditemukan."
            )
        remaining_quantity = stock.quantity - item.quantity
        if remaining_quantity < stock.reserved:
            raise ReceivingCorrectionError(
                (
                    f"Stok {item.item} batch {item.batch_lot} tidak cukup untuk "
                    "dikoreksi karena sudah dipakai atau direservasi."
                )
            )
        stock.quantity = remaining_quantity
        stock.save(update_fields=["quantity", "updated_at"])
        transactions.append(
            Transaction(
                transaction_type=Transaction.TransactionType.OUT,
                item=item.item,
                location=item.location,
                batch_lot=item.batch_lot,
                quantity=item.quantity,
                unit_price=item.unit_price,
                source_document_number=stock.source_document_number,
                sumber_dana=stock.sumber_dana,
                reference_type=Transaction.ReferenceType.RECEIVING,
                reference_id=receiving.pk,
                user=user,
                notes=(
                    f"Koreksi {action_label} penerimaan {receiving.document_number}: "
                    f"{reason}"
                ),
            )
        )
    if transactions:
        Transaction.objects.bulk_create(transactions)


def _post_regular_receiving_stock(receiving, items, user, reason):
    transactions = []
    for item in items:
        posted_sumber_dana = item.posted_sumber_dana or receiving.sumber_dana
        source_document_number = item.posted_source_document_number or (
            resolve_receiving_source_document_number(
                receiving,
                item=item.item,
                location=item.location,
                batch_lot=item.batch_lot,
                sumber_dana=posted_sumber_dana,
            )
        )
        item.posted_sumber_dana = posted_sumber_dana
        item.posted_source_document_number = source_document_number
        increment_receiving_stock(
            item=item.item,
            location=item.location,
            batch_lot=item.batch_lot,
            sumber_dana=posted_sumber_dana,
            expiry_date=item.expiry_date,
            quantity=item.quantity,
            unit_price=item.unit_price,
            receiving_ref=receiving,
            source_document_number=source_document_number,
            allow_zero_layer_metadata_update=True,
        )
        transactions.append(
            Transaction(
                transaction_type=Transaction.TransactionType.IN,
                item=item.item,
                location=item.location,
                batch_lot=item.batch_lot,
                quantity=item.quantity,
                unit_price=item.unit_price,
                source_document_number=source_document_number,
                sumber_dana=posted_sumber_dana,
                reference_type=Transaction.ReferenceType.RECEIVING,
                reference_id=receiving.pk,
                user=user,
                notes=f"Koreksi ulang penerimaan {receiving.document_number}: {reason}",
            )
        )
    if transactions:
        Transaction.objects.bulk_create(transactions)


def _effective_received_at(receiving, original_received_at=None):
    if not receiving.receiving_date:
        return original_received_at or timezone.now()
    receipt_time = time.min
    if original_received_at:
        receipt_time = timezone.localtime(original_received_at).time()
    received_at = datetime.combine(receiving.receiving_date, receipt_time)
    if timezone.is_naive(received_at):
        return timezone.make_aware(received_at, timezone.get_current_timezone())
    return received_at


def _replacement_items_from_formset(receiving, formset, user, *, original_received_at=None):
    items = []
    received_at = _effective_received_at(
        receiving,
        original_received_at=original_received_at,
    )
    for form in formset.forms:
        cleaned = getattr(form, "cleaned_data", None)
        if not cleaned or cleaned.get("DELETE"):
            continue
        if not cleaned.get("item"):
            continue
        items.append(
            ReceivingItem(
                receiving=receiving,
                item=cleaned["item"],
                quantity=cleaned["quantity"],
                batch_lot=cleaned["batch_lot"],
                expiry_date=cleaned.get("expiry_date"),
                unit_price=cleaned["unit_price"],
                location=cleaned["location"],
                posted_sumber_dana=receiving.sumber_dana,
                posted_source_document_number=resolve_receiving_source_document_number(
                    receiving,
                    item=cleaned["item"],
                    location=cleaned["location"],
                    batch_lot=cleaned["batch_lot"],
                    sumber_dana=receiving.sumber_dana,
                ),
                received_by=user,
                received_at=received_at,
            )
        )
    if not items:
        raise ReceivingCorrectionError("Tambahkan minimal 1 item penerimaan.")
    return items


def _get_locked_planned_receiving_order_items(order_item_ids):
    return {
        order_item.pk: order_item
        for order_item in ReceivingOrderItem.objects.select_for_update(of=("self",))
        .select_related("item")
        .filter(pk__in=order_item_ids)
        .order_by("pk")
    }


def _add_planned_receipt_form_error(formset, order_item_id, message):
    for form in formset.forms:
        cleaned = getattr(form, "cleaned_data", None)
        if not cleaned or cleaned.get("DELETE"):
            continue
        order_item = cleaned.get("order_item")
        quantity = cleaned.get("quantity")
        if (
            order_item
            and order_item.pk == order_item_id
            and quantity is not None
            and quantity > 0
        ):
            form.add_error("quantity", message)


def _create_verified_receiving(request, form, formset):
    with transaction.atomic():
        receiving = form.save(commit=False)
        receiving.created_by = request.user
        receiving.status = Receiving.Status.VERIFIED
        receiving.verified_by = request.user
        receiving.verified_at = timezone.now()
        receiving.save()
        issue_document_number(
            DocumentNumberRule.Key.RECEIVING,
            business_date=receiving.receiving_date,
            target=receiving,
            actor=request.user,
        )

        formset.instance = receiving
        receipt_items = formset.save(commit=False)
        if not receipt_items:
            raise ValueError("Tambahkan minimal 1 item penerimaan.")

        pending_transactions = []
        for item in receipt_items:
            item.receiving = receiving
            item.received_by = request.user
            item.received_at = timezone.now()
            source_document_number = resolve_receiving_source_document_number(
                receiving,
                item=item.item,
                location=item.location,
                batch_lot=item.batch_lot,
                sumber_dana=receiving.sumber_dana,
            )
            item.posted_sumber_dana = receiving.sumber_dana
            item.posted_source_document_number = source_document_number
            item.save()

            increment_receiving_stock(
                item=item.item,
                location=item.location,
                batch_lot=item.batch_lot,
                sumber_dana=receiving.sumber_dana,
                expiry_date=item.expiry_date,
                quantity=item.quantity,
                unit_price=item.unit_price,
                receiving_ref=receiving,
                source_document_number=source_document_number,
            )

            pending_transactions.append(
                Transaction(
                    transaction_type=Transaction.TransactionType.IN,
                    item=item.item,
                    location=item.location,
                    batch_lot=item.batch_lot,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    source_document_number=source_document_number,
                    sumber_dana=receiving.sumber_dana,
                    reference_type=Transaction.ReferenceType.RECEIVING,
                    reference_id=receiving.pk,
                    user=request.user,
                    notes=f"Penerimaan reguler {receiving.document_number}",
                )
            )

        if pending_transactions:
            Transaction.objects.bulk_create(pending_transactions)

        for deleted_form in formset.deleted_forms:
            if deleted_form.instance.pk:
                deleted_form.instance.delete()

    return receiving


def _receiving_type_options_and_label_map():
    receiving_type_options = list(ReceivingTypeOption.objects.filter(is_active=True))
    receiving_type_labels = {
        option.code: option.name for option in receiving_type_options
    }
    receiving_type_labels.update(
        {
            code: label
            for code, label in Receiving.ReceivingType.choices
            if code not in receiving_type_labels
        }
    )
    return receiving_type_options, receiving_type_labels


def _attach_receiving_type_labels(receivings, receiving_type_labels):
    for receiving in receivings:
        receiving.receiving_type_display_label = receiving_type_labels.get(
            receiving.receiving_type,
            receiving.receiving_type,
        )


@login_required
@perm_required("receiving.view_receiving")
def receiving_list(request):
    receiving_type_options, receiving_type_labels = (
        _receiving_type_options_and_label_map()
    )
    queryset = (
        Receiving.objects.select_related("supplier", "sumber_dana", "created_by", "contract")
        .filter(is_planned=False)
        .exclude(receiving_type="RETURN_RS")
        .order_by("-receiving_date")
    )

    search = request.GET.get("q", "").strip()
    if search:
        queryset = queryset.filter(
            Q(document_number__icontains=search) | Q(supplier__name__icontains=search)
        )

    r_type = request.GET.get("type")
    if r_type:
        queryset = queryset.filter(receiving_type=r_type)

    paginator = Paginator(queryset, 25)
    receivings = paginator.get_page(request.GET.get("page"))
    _attach_receiving_type_labels(receivings, receiving_type_labels)

    return render(
        request,
        "receiving/receiving_list.html",
        {
            "receivings": receivings,
            "search": search,
            "selected_type": r_type or "",
            "receiving_type_options": receiving_type_options,
        },
    )


@login_required
@perm_required("receiving.view_receiving")
def receiving_plan_list(request):
    receiving_type_options, receiving_type_labels = (
        _receiving_type_options_and_label_map()
    )
    queryset = (
        Receiving.objects.select_related("supplier", "sumber_dana", "created_by", "contract")
        .filter(is_planned=True)
        .order_by("-receiving_date")
    )

    search = request.GET.get("q", "").strip()
    if search:
        queryset = queryset.filter(
            Q(document_number__icontains=search) | Q(supplier__name__icontains=search)
        )

    status = request.GET.get("status")
    if status:
        queryset = queryset.filter(status=status)

    r_type = request.GET.get("type")
    if r_type:
        queryset = queryset.filter(receiving_type=r_type)

    paginator = Paginator(queryset, 25)
    receivings = paginator.get_page(request.GET.get("page"))
    _attach_receiving_type_labels(receivings, receiving_type_labels)

    return render(
        request,
        "receiving/receiving_plan_list.html",
        {
            "receivings": receivings,
            "search": search,
            "selected_status": status or "",
            "selected_type": r_type or "",
            "status_draft": "selected" if status == Receiving.Status.DRAFT else "",
            "status_submitted": "selected"
            if status == Receiving.Status.SUBMITTED
            else "",
            "status_approved": "selected"
            if status == Receiving.Status.APPROVED
            else "",
            "status_partial": "selected" if status == Receiving.Status.PARTIAL else "",
            "status_received": "selected"
            if status == Receiving.Status.RECEIVED
            else "",
            "status_closed": "selected" if status == Receiving.Status.CLOSED else "",
            "status_cancelled": "selected"
            if status == Receiving.Status.CANCELLED
            else "",
            "receiving_type_options": receiving_type_options,
        },
    )


@login_required
@perm_required("receiving.add_receiving")
def receiving_create(request):
    if request.method == "POST":
        form = ReceivingForm(request.POST)
        formset = ReceivingItemFormSet(request.POST, prefix="items")

        if form.is_valid() and formset.is_valid():
            try:
                receiving = _create_verified_receiving(request, form, formset)

            except (ValueError, ValidationError, ProtectedError) as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request, f"Penerimaan {receiving.document_number} berhasil dibuat."
                )
                return redirect("receiving:receiving_detail", pk=receiving.pk)
    else:
        form = ReceivingForm()
        formset = ReceivingItemFormSet(prefix="items")

    return render(
        request,
        "receiving/receiving_form.html",
        {
            "form": form,
            "formset": formset,
            "title": "Buat Penerimaan Baru",
        },
    )


@login_required
@perm_required("receiving.change_receiving")
@module_scope_required(ModuleAccess.Module.RECEIVING, ModuleAccess.Scope.OPERATE)
@receiving_mutation_ratelimit
def receiving_edit(request, pk):
    _require_regular_receiving_correction_role(request.user)
    receiving = get_object_or_404(
        Receiving.objects.exclude(receiving_type="RETURN_RS"),
        pk=pk,
        is_planned=False,
    )
    if receiving.status != Receiving.Status.VERIFIED:
        messages.error(request, "Hanya penerimaan terverifikasi yang dapat dikoreksi.")
        return redirect("receiving:receiving_detail", pk=pk)

    if request.method == "POST":
        form = ReceivingEditForm(request.POST, instance=receiving)
        formset = ReceivingItemFormSet(request.POST, instance=receiving, prefix="items")
        if form.is_valid() and formset.is_valid():
            reason = form.cleaned_data["correction_reason"]
            try:
                with transaction.atomic():
                    locked_receiving = get_object_or_404(
                        Receiving.objects.select_for_update(of=("self",))
                        .exclude(receiving_type="RETURN_RS"),
                        pk=pk,
                        is_planned=False,
                    )
                    if locked_receiving.status != Receiving.Status.VERIFIED:
                        raise ReceivingCorrectionError(
                            "Status penerimaan sudah berubah dan tidak dapat dikoreksi."
                        )
                    old_items = list(
                        locked_receiving.items.select_related(
                            "item",
                            "location",
                            "posted_sumber_dana",
                        )
                        .order_by("pk")
                    )
                    original_received_at = (
                        old_items[0].received_at if old_items else None
                    )
                    _reverse_regular_receiving_stock(
                        locked_receiving,
                        old_items,
                        request.user,
                        reason,
                        action_label="edit",
                    )

                    for field_name in ReceivingForm.Meta.fields:
                        setattr(
                            locked_receiving,
                            field_name,
                            form.cleaned_data[field_name],
                        )
                    locked_receiving.status = Receiving.Status.VERIFIED
                    locked_receiving.full_clean()
                    locked_receiving.save()

                    ReceivingItem.objects.filter(receiving=locked_receiving).delete()
                    replacement_items = _replacement_items_from_formset(
                        locked_receiving,
                        formset,
                        request.user,
                        original_received_at=original_received_at,
                    )
                    ReceivingItem.objects.bulk_create(replacement_items)
                    _post_regular_receiving_stock(
                        locked_receiving,
                        replacement_items,
                        request.user,
                        reason,
                    )
            except (ValueError, ValidationError, ProtectedError) as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request,
                    f"Penerimaan {receiving.document_number} berhasil dikoreksi.",
                )
                return redirect("receiving:receiving_detail", pk=pk)
    else:
        form = ReceivingEditForm(instance=receiving)
        formset = ReceivingItemFormSet(instance=receiving, prefix="items")

    return render(
        request,
        "receiving/receiving_form.html",
        {
            "form": form,
            "formset": formset,
            "title": f"Edit Penerimaan {receiving.document_number}",
            "cancel_url": "receiving:receiving_detail",
            "cancel_url_pk": receiving.pk,
        },
    )


@login_required
@perm_required("receiving.delete_receiving")
@module_scope_required(ModuleAccess.Module.RECEIVING, ModuleAccess.Scope.OPERATE)
@receiving_mutation_ratelimit
def receiving_delete(request, pk):
    _require_regular_receiving_correction_role(request.user)
    receiving = get_object_or_404(
        Receiving.objects.exclude(receiving_type="RETURN_RS"),
        pk=pk,
        is_planned=False,
    )
    if receiving.status != Receiving.Status.VERIFIED:
        messages.error(request, "Hanya penerimaan terverifikasi yang dapat dibatalkan.")
        return redirect("receiving:receiving_detail", pk=pk)

    if request.method == "POST":
        form = ReceivingCancelForm(request.POST)
        if form.is_valid():
            reason = form.cleaned_data["cancel_reason"]
            try:
                with transaction.atomic():
                    locked_receiving = get_object_or_404(
                        Receiving.objects.select_for_update(of=("self",))
                        .exclude(receiving_type="RETURN_RS"),
                        pk=pk,
                        is_planned=False,
                    )
                    if locked_receiving.status != Receiving.Status.VERIFIED:
                        raise ReceivingCorrectionError(
                            "Status penerimaan sudah berubah dan tidak dapat dibatalkan."
                        )
                    old_items = list(
                        locked_receiving.items.select_related(
                            "item",
                            "location",
                            "posted_sumber_dana",
                        )
                        .order_by("pk")
                    )
                    _reverse_regular_receiving_stock(
                        locked_receiving,
                        old_items,
                        request.user,
                        reason,
                        action_label="pembatalan",
                    )
                    locked_receiving.status = Receiving.Status.CANCELLED
                    locked_receiving.cancelled_by = request.user
                    locked_receiving.cancelled_at = timezone.now()
                    locked_receiving.cancel_reason = reason
                    void_document_number(
                        locked_receiving,
                        actor=request.user,
                        reason=reason,
                    )
                    locked_receiving.save(
                        update_fields=[
                            "status",
                            "cancelled_by",
                            "cancelled_at",
                            "cancel_reason",
                            "updated_at",
                        ]
                    )
            except (ReceivingCorrectionError, ProtectedError) as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request,
                    f"Penerimaan {receiving.document_number} berhasil dibatalkan.",
                )
                return redirect("receiving:receiving_detail", pk=pk)
    else:
        form = ReceivingCancelForm()

    return render(
        request,
        "receiving/receiving_confirm_delete.html",
        {
            "form": form,
            "receiving": receiving,
        },
    )


@login_required
@perm_required("receiving.add_receiving")
def receiving_plan_create(request):
    messages.info(
        request,
        "Rencana penerimaan pengadaan baru dibuat melalui SPJ / Pengadaan.",
    )
    return redirect("procurement:contract_create")


@login_required
@perm_required("receiving.view_receiving")
def receiving_detail(request, pk):
    receiving = get_object_or_404(
        Receiving.objects.select_related(
            "supplier",
            "facility",
            "sumber_dana",
            "created_by",
            "verified_by",
            "cancelled_by",
        )
        .prefetch_related("documents")
        .exclude(receiving_type="RETURN_RS"),
        pk=pk,
        is_planned=False,
    )
    items = list(receiving.items.select_related("item", "item__satuan"))
    for item in items:
        item.unit_price_display = format_price_exact(item.unit_price)
    documents = receiving.documents.all()

    return render(
        request,
        "receiving/receiving_detail.html",
        {
            "documents": documents,
            "receiving": receiving,
            "items": items,
            "can_correct_receiving": (
                receiving.status == Receiving.Status.VERIFIED
                and _has_regular_receiving_correction_access(request.user)
            ),
        },
    )


@login_required
@perm_required("receiving.view_receiving")
def receiving_document_download(request, pk, document_pk):
    document = get_object_or_404(
        ReceivingDocument.objects.select_related("receiving"),
        pk=document_pk,
        receiving_id=pk,
        receiving__is_planned=False,
    )

    if not document.file.name:
        raise Http404("Lampiran tidak ditemukan.")

    try:
        file_handle = document.file.open("rb")
    except FileNotFoundError as exc:
        raise Http404("Lampiran tidak ditemukan.") from exc

    logger.info(
        json.dumps(
            {
                "document_id": document.pk,
                "event": "receiving_document_download_succeeded",
                "filename": document.file_name,
                "mime_type": document.file_type,
                "receiving_id": document.receiving_id,
                "username": request.user.username,
            },
            sort_keys=True,
        )
    )
    return FileResponse(
        file_handle,
        as_attachment=True,
        filename=_safe_download_filename(document),
        content_type=document.file_type or None,
    )


@login_required
@perm_required("receiving.view_receiving")
def receiving_plan_detail(request, pk):
    receiving = get_object_or_404(
        Receiving.objects.select_related(
            "supplier", "sumber_dana", "created_by", "approved_by", "contract"
        ),
        pk=pk,
        is_planned=True,
    )
    order_items = receiving.order_items.select_related("item", "item__satuan")
    receipt_items = receiving.items.select_related("item", "location")

    return render(
        request,
        "receiving/receiving_plan_detail.html",
        {
            "receiving": receiving,
            "order_items": order_items,
            "receipt_items": receipt_items,
        },
    )


@login_required
@perm_required("receiving.change_receiving")
def receiving_plan_submit(request, pk):
    receiving = get_object_or_404(Receiving, pk=pk, is_planned=True)
    if request.method != "POST":
        return redirect("receiving:receiving_plan_detail", pk=pk)

    if receiving.status != Receiving.Status.DRAFT:
        messages.error(request, "Hanya rencana penerimaan Draft yang dapat diajukan.")
        return redirect("receiving:receiving_plan_detail", pk=pk)

    if receiving.contract_id:
        messages.error(
            request,
            "Rencana penerimaan yang berasal dari SPJ disetujui melalui modul SPJ / Pengadaan.",
        )
        return redirect("receiving:receiving_plan_detail", pk=pk)

    if not receiving.order_items.exists():
        messages.error(request, "Tambahkan minimal 1 item rencana sebelum diajukan.")
        return redirect("receiving:receiving_plan_detail", pk=pk)

    try:
        with transaction.atomic():
            receiving = Receiving.objects.select_for_update().get(pk=receiving.pk)
            issue_document_number(
                DocumentNumberRule.Key.RECEIVING,
                business_date=receiving.receiving_date,
                target=receiving,
                actor=request.user,
            )
            receiving.status = Receiving.Status.SUBMITTED
            receiving.save(update_fields=["status", "updated_at"])
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("receiving:receiving_plan_detail", pk=pk)
    messages.success(
        request, f"Rencana penerimaan {receiving.document_number} berhasil diajukan."
    )
    return redirect("receiving:receiving_plan_detail", pk=pk)


@login_required
@perm_required("receiving.change_receiving")
@module_scope_required(ModuleAccess.Module.RECEIVING, ModuleAccess.Scope.APPROVE)
def receiving_plan_approve(request, pk):
    receiving = get_object_or_404(Receiving, pk=pk, is_planned=True)
    if request.method != "POST":
        return redirect("receiving:receiving_plan_detail", pk=pk)

    if receiving.status != Receiving.Status.SUBMITTED:
        messages.error(
            request, "Hanya rencana penerimaan Diajukan yang dapat disetujui."
        )
        return redirect("receiving:receiving_plan_detail", pk=pk)

    if receiving.contract_id:
        messages.error(
            request,
            "Rencana penerimaan yang berasal dari SPJ tidak memerlukan persetujuan terpisah.",
        )
        return redirect("receiving:receiving_plan_detail", pk=pk)

    receiving.status = Receiving.Status.APPROVED
    receiving.approved_by = request.user
    receiving.approved_at = timezone.now()
    receiving.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    messages.success(
        request, f"Rencana penerimaan {receiving.document_number} disetujui."
    )
    return redirect("receiving:receiving_plan_detail", pk=pk)


@login_required
@perm_required("receiving.change_receiving")
def receiving_plan_close(request, pk):
    receiving = get_object_or_404(Receiving, pk=pk, is_planned=True)
    if request.method != "POST":
        return redirect("receiving:receiving_plan_detail", pk=pk)

    if receiving.status not in [Receiving.Status.APPROVED, Receiving.Status.PARTIAL]:
        messages.error(
            request, "Hanya rencana penerimaan disetujui/parsial yang dapat ditutup."
        )
        return redirect("receiving:receiving_plan_detail", pk=pk)

    return redirect("receiving:receiving_plan_close_items", pk=pk)


@login_required
@perm_required("receiving.change_receiving")
def receiving_plan_close_items(request, pk):
    receiving = get_object_or_404(Receiving, pk=pk, is_planned=True)
    if receiving.contract_id:
        messages.info(
            request,
            "Rencana penerimaan dari SPJ harus ditutup melalui amandemen pengadaan.",
        )
        return redirect("procurement:amendment_create", pk=receiving.contract_id)

    if receiving.status not in [Receiving.Status.APPROVED, Receiving.Status.PARTIAL]:
        messages.error(
            request, "Hanya rencana penerimaan disetujui/parsial yang dapat ditutup."
        )
        return redirect("receiving:receiving_plan_detail", pk=pk)

    if request.method == "POST":
        formset = ReceivingOrderCloseItemFormSet(
            request.POST,
            instance=receiving,
        )
        if formset.is_valid():
            formset.save()
            unresolved = (
                receiving.order_items.filter(is_cancelled=False)
                .exclude(planned_quantity__lte=F("received_quantity"))
                .exists()
            )
            if unresolved:
                messages.error(
                    request,
                    "Masih ada item bersisa yang belum dibatalkan. Tandai item tersebut untuk menutup rencana.",
                )
                return redirect("receiving:receiving_plan_close_items", pk=pk)

            receiving.status = Receiving.Status.CLOSED
            receiving.closed_by = request.user
            receiving.closed_at = timezone.now()
            receiving.closed_reason = "Sisa dibatalkan melalui penutupan rencana"
            receiving.save(
                update_fields=[
                    "status",
                    "closed_by",
                    "closed_at",
                    "closed_reason",
                    "updated_at",
                ]
            )
            messages.success(
                request, f"Rencana penerimaan {receiving.document_number} ditutup."
            )
            return redirect("receiving:receiving_plan_detail", pk=pk)

        messages.error(request, "Periksa isian penutupan sisa.")
    else:
        formset = ReceivingOrderCloseItemFormSet(instance=receiving)

    return render(
        request,
        "receiving/receiving_plan_close_items.html",
        {
            "receiving": receiving,
            "formset": formset,
        },
    )


@login_required
@perm_required("receiving.add_receiving")
def receiving_plan_receive(request, pk):
    receiving = get_object_or_404(Receiving, pk=pk, is_planned=True)
    if receiving.status not in [Receiving.Status.APPROVED, Receiving.Status.PARTIAL]:
        messages.error(
            request, "Rencana penerimaan belum disetujui atau sudah selesai."
        )
        return redirect("receiving:receiving_plan_detail", pk=pk)

    planned_order_items = [
        order_item
        for order_item in receiving.order_items.filter(is_cancelled=False).select_related(
            "item"
        )
        if order_item.remaining_quantity > 0
    ]
    if not planned_order_items:
        messages.error(request, "Rencana tidak memiliki item aktif untuk diterima.")
        return redirect("receiving:receiving_plan_detail", pk=pk)

    initial_rows = []
    for order_item in planned_order_items:
        initial_rows.append(
            {
                "order_item": order_item.pk,
                "quantity": 0,
                "unit_price": order_item.unit_price,
            }
        )
    planned_receipt_formset_class = build_planned_receipt_item_formset(
        extra_forms=len(initial_rows)
    )

    if request.method == "POST":
        formset = planned_receipt_formset_class(
            request.POST,
            prefix="items",
            instance=receiving,
            form_kwargs={"receiving": receiving, "lock_order_item": True},
            queryset=ReceivingItem.objects.none(),
        )
        if not formset.is_valid():
            messages.error(request, "Periksa kembali isian penerimaan.")
            return render(
                request,
                "receiving/receiving_plan_receive.html",
                {
                    "receiving": receiving,
                    "formset": formset,
                },
                status=200,
            )

        totals = {}
        has_receipt_row = False
        for form in formset.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            order_item = form.cleaned_data.get("order_item")
            quantity = form.cleaned_data.get("quantity")
            if not order_item or quantity is None or quantity <= 0:
                continue
            has_receipt_row = True
            totals[order_item.pk] = totals.get(order_item.pk, 0) + quantity

        if not has_receipt_row:
            messages.info(
                request,
                "Belum ada item dengan jumlah diterima di atas 0 untuk disimpan.",
            )
            return redirect("receiving:receiving_plan_receive", pk=pk)

        if totals:
            order_items = ReceivingOrderItem.objects.filter(pk__in=totals.keys())
            for order_item in order_items:
                if order_item.remaining_quantity < totals[order_item.pk]:
                    messages.error(
                        request,
                        f"Jumlah penerimaan untuk {order_item.item} melebihi sisa pesanan.",
                    )
                    return render(
                        request,
                        "receiving/receiving_plan_receive.html",
                        {
                            "receiving": receiving,
                            "formset": formset,
                        },
                        status=200,
                    )

        receipt_forms = []
        for form in formset.forms:
            cleaned = form.cleaned_data
            if not cleaned:
                continue
            quantity = cleaned.get("quantity")
            if quantity is None or quantity <= 0:
                continue
            receipt_forms.append(form)

        try:
            with transaction.atomic():
                locked_receiving = get_object_or_404(
                    Receiving.objects.select_for_update(of=("self",)),
                    pk=pk,
                    is_planned=True,
                )
                if locked_receiving.status not in [
                    Receiving.Status.APPROVED,
                    Receiving.Status.PARTIAL,
                ]:
                    raise ValueError(
                        "Status rencana penerimaan sudah berubah dan tidak dapat menerima barang."
                    )

                locked_order_items = _get_locked_planned_receiving_order_items(
                    totals.keys()
                )
                for order_item_id, total_quantity in totals.items():
                    order_item = locked_order_items.get(order_item_id)
                    if order_item is None or order_item.is_cancelled:
                        raise PlannedReceiptQuantityConflict(
                            order_item_id,
                            "Item pesanan ini sudah dibatalkan.",
                        )
                    if order_item.remaining_quantity < total_quantity:
                        raise PlannedReceiptQuantityConflict(
                            order_item_id,
                            "Jumlah melebihi sisa pesanan.",
                        )

                pending_transactions = []
                for form in receipt_forms:
                    item = form.save(commit=False)
                    order_item = locked_order_items[item.order_item_id]
                    item.receiving = locked_receiving
                    item.received_by = request.user
                    item.received_at = timezone.now()
                    item.item = order_item.item
                    source_document_number = resolve_receiving_source_document_number(
                        locked_receiving,
                        item=item.item,
                        location=item.location,
                        batch_lot=item.batch_lot,
                        sumber_dana=locked_receiving.sumber_dana,
                    )
                    item.posted_sumber_dana = locked_receiving.sumber_dana
                    item.posted_source_document_number = source_document_number
                    item.save()

                    order_item.received_quantity = (
                        order_item.received_quantity + item.quantity
                    )
                    order_item.save(update_fields=["received_quantity", "updated_at"])

                    increment_receiving_stock(
                        item=item.item,
                        location=item.location,
                        batch_lot=item.batch_lot,
                        sumber_dana=locked_receiving.sumber_dana,
                        expiry_date=item.expiry_date,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        receiving_ref=locked_receiving,
                        source_document_number=source_document_number,
                    )

                    pending_transactions.append(
                        Transaction(
                            transaction_type=Transaction.TransactionType.IN,
                            item=item.item,
                            location=item.location,
                            batch_lot=item.batch_lot,
                            quantity=item.quantity,
                            unit_price=item.unit_price,
                            source_document_number=source_document_number,
                            sumber_dana=locked_receiving.sumber_dana,
                            reference_type=Transaction.ReferenceType.RECEIVING,
                            reference_id=locked_receiving.pk,
                            user=request.user,
                            notes=f"Penerimaan dari rencana {locked_receiving.document_number}",
                        )
                    )

                if pending_transactions:
                    Transaction.objects.bulk_create(pending_transactions)

                remaining = (
                    locked_receiving.order_items.filter(is_cancelled=False)
                    .exclude(planned_quantity__lte=F("received_quantity"))
                    .exists()
                )
                locked_receiving.status = (
                    Receiving.Status.PARTIAL if remaining else Receiving.Status.RECEIVED
                )
                locked_receiving.save(update_fields=["status", "updated_at"])

        except PlannedReceiptQuantityConflict as exc:
            _add_planned_receipt_form_error(formset, exc.order_item_id, str(exc))
            messages.error(request, str(exc))
            return render(
                request,
                "receiving/receiving_plan_receive.html",
                {
                    "receiving": receiving,
                    "formset": formset,
                },
                status=200,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(
                request,
                "receiving/receiving_plan_receive.html",
                {
                    "receiving": receiving,
                    "formset": formset,
                },
                status=200,
            )

        messages.success(
            request, f"Penerimaan {receiving.document_number} berhasil dicatat."
        )
        return redirect("receiving:receiving_plan_detail", pk=pk)
    else:
        formset = planned_receipt_formset_class(
            prefix="items",
            instance=receiving,
            form_kwargs={"receiving": receiving, "lock_order_item": True},
            queryset=ReceivingItem.objects.none(),
            initial=initial_rows,
        )

    return render(
        request,
        "receiving/receiving_plan_receive.html",
        {
            "receiving": receiving,
            "formset": formset,
        },
    )


# ── AJAX Quick-Create Views ────────────────────────────────


@login_required
@perm_required("receiving.add_receiving")
@item_mutation_ratelimit
@require_POST
def quick_create_supplier(request):
    """AJAX endpoint to create a new Supplier."""
    form = ReceivingQuickCreateSupplierForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"error": _json_form_errors(form)}, status=400)

    supplier = form.save()
    return JsonResponse({"id": supplier.pk, "text": str(supplier)})


@login_required
@perm_required("receiving.add_receiving")
@item_mutation_ratelimit
@require_POST
def quick_create_funding_source(request):
    """AJAX endpoint to create a new FundingSource."""
    form = ReceivingQuickCreateFundingSourceForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"error": _json_form_errors(form)}, status=400)

    source = form.save()
    return JsonResponse({"id": source.pk, "text": str(source)})


@login_required
@perm_required("receiving.add_receiving")
@item_mutation_ratelimit
@require_POST
def quick_create_receiving_type(request):
    """AJAX endpoint to create a new custom receiving type."""
    form = ReceivingQuickCreateReceivingTypeForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"error": _json_form_errors(form)}, status=400)

    option = form.save()
    return JsonResponse({"id": option.code, "text": option.name})
