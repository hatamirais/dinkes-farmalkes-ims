from decimal import Decimal
import logging

from django.db import transaction
from django.utils import timezone

from apps.stock.models import Stock, Transaction

from .models import Distribution, DistributionStaffAssignment


logger = logging.getLogger(__name__)
ZERO_DECIMAL = Decimal("0")


class DistributionWorkflowError(ValueError):
    pass


def _save_distribution(distribution, update_fields):
    distribution.save(update_fields=[*update_fields, "updated_at"])


def _get_distribution_items(distribution, action_label):
    distribution_items = list(
        distribution.items.select_related("item", "stock").order_by("pk")
    )
    if not distribution_items:
        raise DistributionWorkflowError(
            f"Distribusi tidak memiliki item untuk {action_label}."
        )
    return distribution_items


def _lock_stocks_for_distribution_items(distribution_items):
    stock_ids = sorted({item.stock_id for item in distribution_items if item.stock_id})
    if not stock_ids:
        return {}

    return {
        stock.pk: stock
        for stock in Stock.objects.select_for_update().filter(pk__in=stock_ids)
    }


def _get_distribution_item_quantity(distribution_item):
    quantity = distribution_item.quantity_approved
    return quantity if quantity is not None else ZERO_DECIMAL


def _get_distribution_item_reserved_quantity(distribution_item):
    quantity = distribution_item.reserved_quantity
    return quantity if quantity is not None else ZERO_DECIMAL


def _validate_distribution_item_for_stock_workflow(
    distribution_item,
    action_label,
    *,
    stock=None,
    include_existing_reservation=False,
):
    quantity = _get_distribution_item_quantity(distribution_item)
    if quantity <= 0:
        raise DistributionWorkflowError(
            f"Item {distribution_item.item.nama_barang}: jumlah disetujui harus diisi dan lebih dari 0."
        )

    selected_stock = stock or distribution_item.stock
    if selected_stock is None:
        raise DistributionWorkflowError(
            f"Item {distribution_item.item.nama_barang}: batch stok harus dipilih sebelum {action_label}."
        )

    available_quantity = selected_stock.available_quantity
    if include_existing_reservation:
        available_quantity += _get_distribution_item_reserved_quantity(distribution_item)

    if quantity > available_quantity:
        raise DistributionWorkflowError(
            f"Stok tidak cukup untuk {distribution_item.item.nama_barang}. "
            f"Tersedia {available_quantity}, disetujui {quantity}."
        )



def apply_distribution_reservations(distribution, *, distribution_items=None):
    distribution_items = distribution_items or _get_distribution_items(
        distribution,
        "reservasi",
    )
    for distribution_item in distribution_items:
        quantity = _get_distribution_item_quantity(distribution_item)
        if quantity <= 0:
            raise DistributionWorkflowError(
                f"Item {distribution_item.item.nama_barang}: jumlah disetujui harus diisi dan lebih dari 0."
            )
        if distribution_item.stock_id is None:
            raise DistributionWorkflowError(
                f"Item {distribution_item.item.nama_barang}: batch stok harus dipilih sebelum verifikasi."
            )

    reservable_items = [item for item in distribution_items if item.stock_id]
    if not reservable_items:
        return

    locked_stocks = _lock_stocks_for_distribution_items(reservable_items)
    processed_at = timezone.now()
    touched_stocks = []

    for distribution_item in reservable_items:
        stock = locked_stocks.get(distribution_item.stock_id)
        if stock is None:
            raise DistributionWorkflowError(
                f"Batch stok untuk item {distribution_item.item.nama_barang} tidak ditemukan."
            )
        if stock.item_id != distribution_item.item_id:
            raise DistributionWorkflowError(
                f"Batch stok tidak sesuai untuk item {distribution_item.item.nama_barang}."
            )

        _validate_distribution_item_for_stock_workflow(
            distribution_item,
            "verifikasi",
            stock=stock,
            include_existing_reservation=True,
        )

        quantity = _get_distribution_item_quantity(distribution_item)
        reserved_quantity = _get_distribution_item_reserved_quantity(distribution_item)
        delta = quantity - reserved_quantity
        next_reserved = stock.reserved + delta
        if next_reserved < 0:
            raise DistributionWorkflowError(
                f"Reservasi stok untuk {distribution_item.item.nama_barang} tidak valid."
            )

        stock.reserved = next_reserved
        stock.updated_at = processed_at
        distribution_item.reserved_quantity = quantity
        touched_stocks.append(stock)

    if touched_stocks:
        Stock.objects.bulk_update(touched_stocks, ["reserved", "updated_at"])
        distribution.items.model.objects.bulk_update(
            reservable_items,
            ["reserved_quantity"],
        )



def release_distribution_reservations(distribution, *, distribution_items=None):
    distribution_items = distribution_items or _get_distribution_items(
        distribution,
        "pelepasan reservasi",
    )
    reservable_items = [
        item
        for item in distribution_items
        if item.stock_id and _get_distribution_item_reserved_quantity(item) > 0
    ]
    if not reservable_items:
        return

    locked_stocks = _lock_stocks_for_distribution_items(reservable_items)
    processed_at = timezone.now()
    touched_stocks = []

    for distribution_item in reservable_items:
        stock = locked_stocks.get(distribution_item.stock_id)
        if stock is None:
            raise DistributionWorkflowError(
                f"Batch stok untuk item {distribution_item.item.nama_barang} tidak ditemukan."
            )

        release_quantity = _get_distribution_item_reserved_quantity(distribution_item)
        if stock.reserved < release_quantity:
            logger.warning(
                "distribution_reservation_underflow",
                extra={
                    "distribution_id": distribution.pk,
                    "distribution_item_id": distribution_item.pk,
                    "stock_id": stock.pk,
                    "stock_reserved": str(stock.reserved),
                    "release_quantity": str(release_quantity),
                },
            )
            stock.reserved = ZERO_DECIMAL
        else:
            stock.reserved = stock.reserved - release_quantity

        stock.updated_at = processed_at
        distribution_item.reserved_quantity = ZERO_DECIMAL
        touched_stocks.append(stock)

    if touched_stocks:
        Stock.objects.bulk_update(touched_stocks, ["reserved", "updated_at"])
        distribution.items.model.objects.bulk_update(
            reservable_items,
            ["reserved_quantity"],
        )



def assign_default_distribution_staff(distribution, user):
    if distribution is None or user is None:
        return

    DistributionStaffAssignment.objects.get_or_create(
        distribution=distribution,
        user=user,
    )



def execute_distribution_submission(distribution):
    if not distribution.items.exists():
        raise DistributionWorkflowError(
            "Tambahkan minimal 1 item sebelum mengajukan distribusi."
        )

    if not distribution.staff_assignments.exists():
        raise DistributionWorkflowError(
            "Pilih minimal 1 staf terlibat sebelum mengajukan distribusi."
        )

    if distribution.status != Distribution.Status.PREPARED:
        raise DistributionWorkflowError(
            "Hanya distribusi berstatus Disiapkan yang dapat diajukan ke Kepala Instalasi."
        )

    distribution.status = Distribution.Status.SUBMITTED
    _save_distribution(distribution, ["status"])



def execute_distribution_verification(distribution, user):
    distribution_items = _get_distribution_items(distribution, "diverifikasi")

    with transaction.atomic():
        apply_distribution_reservations(
            distribution,
            distribution_items=distribution_items,
        )
        distribution.status = Distribution.Status.VERIFIED
        distribution.verified_by = user
        distribution.verified_at = timezone.now()
        _save_distribution(distribution, ["status", "verified_by", "verified_at"])



def execute_distribution_preparation(distribution):
    allowed_statuses = {Distribution.Status.DRAFT, Distribution.Status.REJECTED}
    if distribution.distribution_type == Distribution.DistributionType.ALLOCATION:
        allowed_statuses = {Distribution.Status.VERIFIED}

    if distribution.status not in allowed_statuses:
        raise DistributionWorkflowError(
            "Status distribusi saat ini tidak dapat ditandai sebagai siap."
        )

    distribution.status = Distribution.Status.PREPARED
    _save_distribution(distribution, ["status"])



def execute_stock_distribution(distribution, user):
    distribution_items = _get_distribution_items(distribution, "didistribusikan")

    processed_at = timezone.now()

    with transaction.atomic():
        locked_stocks = _lock_stocks_for_distribution_items(distribution_items)
        for distribution_item in distribution_items:
            stock = locked_stocks.get(distribution_item.stock_id)
            _validate_distribution_item_for_stock_workflow(
                distribution_item,
                "distribusi",
                stock=stock,
                include_existing_reservation=True,
            )

            quantity = _get_distribution_item_quantity(distribution_item)
            reserved_quantity = _get_distribution_item_reserved_quantity(distribution_item)

            if stock.item_id != distribution_item.item_id:
                raise DistributionWorkflowError(
                    f"Batch stok tidak sesuai untuk item {distribution_item.item.nama_barang}."
                )

            if stock.quantity < quantity:
                raise DistributionWorkflowError(
                    f"Stok fisik tidak cukup untuk {distribution_item.item.nama_barang}. "
                    f"Tersedia {stock.quantity}, disetujui {quantity}."
                )

            if reserved_quantity > stock.reserved:
                raise DistributionWorkflowError(
                    f"Reservasi stok untuk {distribution_item.item.nama_barang} melebihi stok yang dibooking."
                )

            stock.quantity = stock.quantity - quantity
            stock.reserved = stock.reserved - reserved_quantity
            stock.save(update_fields=["quantity", "reserved", "updated_at"])

            distribution_item.issued_batch_lot = stock.batch_lot
            distribution_item.issued_expiry_date = stock.expiry_date
            distribution_item.issued_unit_price = stock.unit_price
            distribution_item.issued_sumber_dana = stock.sumber_dana
            distribution_item.reserved_quantity = ZERO_DECIMAL
            distribution_item.save(
                update_fields=[
                    "issued_batch_lot",
                    "issued_expiry_date",
                    "issued_unit_price",
                    "issued_sumber_dana",
                    "reserved_quantity",
                ]
            )

            Transaction.objects.create(
                transaction_type=Transaction.TransactionType.OUT,
                item=distribution_item.item,
                location=stock.location,
                batch_lot=stock.batch_lot,
                quantity=quantity,
                unit_price=stock.unit_price,
                sumber_dana=stock.sumber_dana,
                reference_type=Transaction.ReferenceType.DISTRIBUTION,
                reference_id=distribution.id,
                user=user,
                notes=(
                    f"Distribusi {distribution.document_number} ke {distribution.facility}: "
                    f"{distribution_item.notes}"
                ).strip(),
            )

        distribution.status = Distribution.Status.DISTRIBUTED
        distribution.approved_by = user
        distribution.approved_at = processed_at
        distribution.distributed_date = processed_at.date()
        _save_distribution(
            distribution,
            [
                "status",
                "approved_by",
                "approved_at",
                "distributed_date",
            ],
        )



def execute_distribution_rejection(distribution):
    distribution.status = Distribution.Status.REJECTED
    _save_distribution(distribution, ["status"])



def execute_distribution_reset_to_draft(distribution):
    with transaction.atomic():
        release_distribution_reservations(distribution)
        distribution.status = Distribution.Status.DRAFT
        distribution.verified_by = None
        distribution.verified_at = None
        distribution.approved_by = None
        distribution.approved_at = None
        distribution.distributed_date = None
        _save_distribution(
            distribution,
            [
                "status",
                "verified_by",
                "verified_at",
                "approved_by",
                "approved_at",
                "distributed_date",
            ],
        )



def get_distribution_step_back_target(distribution):
    previous_status_map = {
        Distribution.Status.PREPARED: Distribution.Status.DRAFT,
        Distribution.Status.SUBMITTED: Distribution.Status.PREPARED,
        Distribution.Status.VERIFIED: Distribution.Status.SUBMITTED,
        Distribution.Status.REJECTED: Distribution.Status.SUBMITTED,
    }
    return previous_status_map.get(distribution.status)



def execute_distribution_step_back(distribution):
    previous_status = get_distribution_step_back_target(distribution)
    if previous_status is None:
        raise DistributionWorkflowError(
            "Status distribusi saat ini tidak memiliki status sebelumnya."
        )

    with transaction.atomic():
        if distribution.status == Distribution.Status.VERIFIED:
            release_distribution_reservations(distribution)

        distribution.status = previous_status
        update_fields = ["status"]

        if previous_status in {Distribution.Status.DRAFT, Distribution.Status.SUBMITTED}:
            distribution.verified_by = None
            distribution.verified_at = None
            update_fields.extend(["verified_by", "verified_at"])

        _save_distribution(distribution, update_fields)
