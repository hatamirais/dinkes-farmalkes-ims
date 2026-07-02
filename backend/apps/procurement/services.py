from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.receiving.models import Receiving, ReceivingOrderItem

from .models import (
    ProcurementAmendment,
    ProcurementAmendmentLine,
    ProcurementContract,
    ProcurementWorkflowError,
)


def _save_model(instance, fields):
    instance.save(update_fields=[*fields, "updated_at"])


def _validate_contract_lines(contract):
    lines = list(contract.lines.select_related("item"))
    if not lines:
        raise ProcurementWorkflowError("Tambahkan minimal 1 baris kontrak sebelum diajukan.")
    return lines


def _get_linked_receiving(contract):
    return (
        Receiving.objects.select_for_update(of=("self",))
        .filter(contract=contract, is_planned=True)
        .select_related("supplier", "sumber_dana")
        .first()
    )


def _build_effective_line_state(contract):
    effective = []
    lines = list(contract.lines.select_related("item").order_by("item__nama_barang", "pk"))
    approved_lines = (
        ProcurementAmendmentLine.objects.select_related(
            "contract_line",
            "amendment",
        )
        .filter(
            contract_line__contract=contract,
            amendment__status=ProcurementAmendment.Status.APPROVED,
        )
        .order_by("contract_line_id", "-amendment__approved_at", "-amendment_id")
    )
    latest_by_line = {}
    for amendment_line in approved_lines:
        latest_by_line.setdefault(amendment_line.contract_line_id, amendment_line)

    for line in lines:
        amendment_line = latest_by_line.get(line.pk)
        effective.append(
            {
                "contract_line": line,
                "quantity": amendment_line.revised_quantity if amendment_line else line.original_quantity,
                "unit_price": amendment_line.revised_unit_price if amendment_line else line.original_unit_price,
                "notes": amendment_line.notes if amendment_line and amendment_line.notes else line.notes,
            }
        )
    return effective


def _receiving_status_from_order_items(receiving):
    order_items = list(receiving.order_items.all())
    if not order_items:
        return Receiving.Status.APPROVED

    has_receipts = any(item.received_quantity > 0 for item in order_items)
    has_remaining = any(
        not item.is_cancelled and item.planned_quantity > item.received_quantity
        for item in order_items
    )
    if not has_remaining:
        return Receiving.Status.RECEIVED
    if has_receipts:
        return Receiving.Status.PARTIAL
    return Receiving.Status.APPROVED


def synchronize_contract_receiving_plan(contract, *, approved_by):
    now = timezone.now()
    receiving = _get_linked_receiving(contract)
    effective_lines = _build_effective_line_state(contract)

    if receiving and receiving.status == Receiving.Status.CLOSED:
        raise ProcurementWorkflowError(
            "Rencana penerimaan kontrak ini sudah ditutup dan tidak dapat disinkronkan lagi."
        )

    if receiving is None:
        receiving = Receiving(
            contract=contract,
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=timezone.localdate(),
            is_planned=True,
            supplier=contract.supplier,
            sumber_dana=contract.sumber_dana,
            status=Receiving.Status.APPROVED,
            created_by=contract.created_by,
            approved_by=approved_by,
            approved_at=now,
            notes=f"Dibuat otomatis dari kontrak {contract.document_number}",
        )
        receiving.save()
    else:
        receiving.supplier = contract.supplier
        receiving.sumber_dana = contract.sumber_dana
        receiving.approved_by = approved_by
        receiving.approved_at = now
        if receiving.status in {Receiving.Status.DRAFT, Receiving.Status.SUBMITTED}:
            receiving.status = Receiving.Status.APPROVED
        receiving.save(
            update_fields=[
                "supplier",
                "sumber_dana",
                "approved_by",
                "approved_at",
                "status",
                "updated_at",
            ]
        )

    existing_order_items = {
        item.contract_line_id: item
        for item in ReceivingOrderItem.objects.select_for_update(of=("self",))
        .filter(receiving=receiving)
        .select_related("item")
    }

    for effective in effective_lines:
        contract_line = effective["contract_line"]
        order_item = existing_order_items.get(contract_line.pk)
        if order_item is None:
            ReceivingOrderItem.objects.create(
                receiving=receiving,
                contract_line=contract_line,
                item=contract_line.item,
                planned_quantity=effective["quantity"],
                received_quantity=0,
                unit_price=effective["unit_price"],
                notes=effective["notes"],
            )
            continue

        if order_item.received_quantity > effective["quantity"]:
            raise ProcurementWorkflowError(
                f"Amandemen untuk {contract_line.item.nama_barang} menghasilkan jumlah kontrak di bawah jumlah yang sudah diterima."
            )

        order_item.item = contract_line.item
        order_item.planned_quantity = effective["quantity"]
        order_item.unit_price = effective["unit_price"]
        order_item.notes = effective["notes"]
        order_item.contract_line = contract_line
        order_item.save(
            update_fields=[
                "item",
                "planned_quantity",
                "unit_price",
                "notes",
                "contract_line",
                "updated_at",
            ]
        )

    receiving.refresh_from_db()
    receiving.status = _receiving_status_from_order_items(receiving)
    receiving.save(update_fields=["status", "updated_at"])
    return receiving


def submit_contract(contract, user):
    _validate_contract_lines(contract)
    contract.status = ProcurementContract.Status.SUBMITTED
    contract.submitted_by = user
    contract.submitted_at = timezone.now()
    _save_model(contract, ["status", "submitted_by", "submitted_at"])


def approve_contract(contract, user):
    with transaction.atomic():
        contract = ProcurementContract.objects.select_for_update().get(pk=contract.pk)
        _validate_contract_lines(contract)
        contract.status = ProcurementContract.Status.APPROVED
        contract.approved_by = user
        contract.approved_at = timezone.now()
        _save_model(contract, ["status", "approved_by", "approved_at"])
        synchronize_contract_receiving_plan(contract, approved_by=user)


def close_contract(contract, user):
    with transaction.atomic():
        contract = ProcurementContract.objects.select_for_update().get(pk=contract.pk)
        receiving = _get_linked_receiving(contract)
        if receiving is None:
            raise ProcurementWorkflowError("Kontrak belum memiliki rencana penerimaan untuk ditutup.")
        remaining_exists = receiving.order_items.filter(is_cancelled=False).exclude(
            planned_quantity__lte=F("received_quantity")
        ).exists()
        if remaining_exists:
            raise ProcurementWorkflowError(
                "Rencana penerimaan masih memiliki sisa aktif. Tutup sisa atau selesaikan penerimaan terlebih dahulu."
            )
        contract.status = ProcurementContract.Status.CLOSED
        contract.closed_by = user
        contract.closed_at = timezone.now()
        _save_model(contract, ["status", "closed_by", "closed_at"])
        if receiving.status != Receiving.Status.CLOSED:
            receiving.status = Receiving.Status.CLOSED
            receiving.closed_by = user
            receiving.closed_at = timezone.now()
            receiving.closed_reason = f"Kontrak {contract.document_number} ditutup"
            receiving.save(
                update_fields=[
                    "status",
                    "closed_by",
                    "closed_at",
                    "closed_reason",
                    "updated_at",
                ]
            )


def submit_amendment(amendment, user):
    lines = list(amendment.lines.select_related("contract_line", "contract_line__item"))
    if not lines:
        raise ProcurementWorkflowError("Tambahkan minimal 1 baris amandemen sebelum diajukan.")
    if amendment.contract.status != ProcurementContract.Status.APPROVED:
        raise ProcurementWorkflowError("Hanya kontrak yang sudah disetujui yang dapat diajukan amandemennya.")
    amendment.status = ProcurementAmendment.Status.SUBMITTED
    amendment.submitted_by = user
    amendment.submitted_at = timezone.now()
    _save_model(amendment, ["status", "submitted_by", "submitted_at"])


def approve_amendment(amendment, user):
    with transaction.atomic():
        amendment = (
            ProcurementAmendment.objects.select_for_update()
            .select_related("contract")
            .get(pk=amendment.pk)
        )
        contract = ProcurementContract.objects.select_for_update().get(pk=amendment.contract_id)
        if contract.status != ProcurementContract.Status.APPROVED:
            raise ProcurementWorkflowError("Kontrak harus berstatus disetujui sebelum amandemen dapat disetujui.")
        if contract.closed_at is not None:
            raise ProcurementWorkflowError("Kontrak yang sudah ditutup tidak dapat diamandemen.")

        receiving = _get_linked_receiving(contract)
        received_by_line = {}
        if receiving is not None:
            received_by_line = {
                item.contract_line_id: item.received_quantity
                for item in ReceivingOrderItem.objects.select_for_update()
                .filter(receiving=receiving)
                .only("contract_line_id", "received_quantity")
            }

        lines = list(
            amendment.lines.select_for_update()
            .select_related("contract_line", "contract_line__item")
        )
        if not lines:
            raise ProcurementWorkflowError("Tambahkan minimal 1 baris amandemen sebelum disetujui.")

        for line in lines:
            received_quantity = received_by_line.get(line.contract_line_id, 0)
            if line.revised_quantity < received_quantity:
                raise ProcurementWorkflowError(
                    f"Jumlah revisi untuk {line.contract_line.item.nama_barang} tidak boleh lebih kecil dari jumlah yang sudah diterima ({received_quantity})."
                )

        amendment.status = ProcurementAmendment.Status.APPROVED
        amendment.approved_by = user
        amendment.approved_at = timezone.now()
        _save_model(amendment, ["status", "approved_by", "approved_at"])
        synchronize_contract_receiving_plan(contract, approved_by=user)


def build_contract_summary_rows(contract):
    linked_receiving = (
        Receiving.objects.filter(contract=contract, is_planned=True)
        .prefetch_related("order_items__item", "order_items__contract_line")
        .first()
    )
    order_items_by_line = {}
    if linked_receiving is not None:
        order_items_by_line = {
            item.contract_line_id: item
            for item in linked_receiving.order_items.all()
            if item.contract_line_id
        }

    rows = []
    for effective in _build_effective_line_state(contract):
        contract_line = effective["contract_line"]
        order_item = order_items_by_line.get(contract_line.pk)
        received_quantity = order_item.received_quantity if order_item else 0
        cancelled_quantity = 0
        remaining_quantity = 0
        if order_item:
            remaining_quantity = max(order_item.planned_quantity - order_item.received_quantity, 0)
            if order_item.is_cancelled:
                cancelled_quantity = remaining_quantity
                remaining_quantity = 0
        rows.append(
            {
                "contract_line": contract_line,
                "original_quantity": contract_line.original_quantity,
                "original_unit_price": contract_line.original_unit_price,
                "current_quantity": effective["quantity"],
                "current_unit_price": effective["unit_price"],
                "received_quantity": received_quantity,
                "received_value": received_quantity * effective["unit_price"],
                "remaining_quantity": remaining_quantity,
                "cancelled_quantity": cancelled_quantity,
            }
        )
    return rows, linked_receiving
