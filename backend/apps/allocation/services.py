from django.db import transaction
from django.utils import timezone

from apps.distribution.models import Distribution, DistributionItem
from apps.distribution.services import (
    DistributionWorkflowError,
    apply_distribution_reservations,
    release_distribution_reservations,
)
from apps.stock.models import Stock, Transaction

from .models import Allocation


class AllocationWorkflowError(ValueError):
    pass


def _save_allocation(allocation, update_fields):
    allocation.save(update_fields=[*update_fields, "updated_at"])


def _get_allocation_items(allocation, action_label):
    allocation_items = list(
        allocation.items.select_related("item", "stock")
        .prefetch_related("facility_allocations__facility")
    )
    if not allocation_items:
        raise AllocationWorkflowError(
            f"Alokasi tidak memiliki item untuk {action_label}."
        )
    return allocation_items


def _validate_submission(allocation, allocation_items):
    """Validate allocation data before submission."""
    if not allocation.selected_facilities.exists():
        raise AllocationWorkflowError(
            "Pilih minimal 1 fasilitas tujuan sebelum mengajukan alokasi."
        )

    if not allocation.staff_assignments.exists():
        raise AllocationWorkflowError(
            "Pilih minimal 1 petugas sebelum mengajukan alokasi."
        )

    for alloc_item in allocation_items:
        if alloc_item.stock is None:
            raise AllocationWorkflowError(
                f"Item {alloc_item.item.nama_barang}: batch stok harus dipilih."
            )

        facility_allocations = list(alloc_item.facility_allocations.all())
        if not facility_allocations:
            raise AllocationWorkflowError(
                f"Item {alloc_item.item.nama_barang}: belum ada alokasi per fasilitas."
            )

        total_allocated = sum(fa.qty_allocated for fa in facility_allocations)
        if total_allocated <= 0:
            raise AllocationWorkflowError(
                f"Item {alloc_item.item.nama_barang}: jumlah alokasi harus lebih dari 0."
            )

        if total_allocated > alloc_item.total_qty_available:
            raise AllocationWorkflowError(
                f"Item {alloc_item.item.nama_barang}: total alokasi ({total_allocated}) "
                f"melebihi stok tersedia ({alloc_item.total_qty_available})."
            )

        for fa in facility_allocations:
            if fa.qty_allocated <= 0:
                raise AllocationWorkflowError(
                    f"Item {alloc_item.item.nama_barang} untuk {fa.facility.name}: "
                    f"jumlah alokasi harus lebih dari 0."
                )



def _validate_stock_at_approval(allocation_items):
    """Re-validate stock availability at approval time (may have changed)."""
    for alloc_item in allocation_items:
        if alloc_item.stock is None:
            raise AllocationWorkflowError(
                f"Item {alloc_item.item.nama_barang}: batch stok belum dipilih."
            )

        total_allocated = sum(
            fa.qty_allocated for fa in alloc_item.facility_allocations.all()
        )

        current_available = alloc_item.stock.available_quantity
        if total_allocated > current_available:
            raise AllocationWorkflowError(
                f"Stok tidak cukup untuk {alloc_item.item.nama_barang}. "
                f"Tersedia {current_available}, dialokasikan {total_allocated}. "
                f"Alokasi dikembalikan ke Draft."
            )



def _generate_distributions(allocation, allocation_items, user):
    """Auto-generate one Distribution per facility from approved allocation.

    Generated distributions start as VERIFIED because the allocation
    approval already validates stock availability, batch selection,
    and approved quantities — equivalent to distribution verification.
    """
    from collections import defaultdict

    now = timezone.now()

    # Group facility allocations by facility
    facility_items = defaultdict(list)
    for alloc_item in allocation_items:
        for fa in alloc_item.facility_allocations.all():
            facility_items[fa.facility_id].append((alloc_item, fa))

    for facility_id, items_list in facility_items.items():
        facility = items_list[0][1].facility

        distribution = Distribution(
            distribution_type=Distribution.DistributionType.ALLOCATION,
            request_date=allocation.allocation_date,
            facility=facility,
            status=Distribution.Status.VERIFIED,
            created_by=user,
            verified_by=user,
            verified_at=now,
            allocation=allocation,
            notes=f"Dibuat otomatis dari alokasi {allocation.document_number}",
        )
        distribution.save()  # Auto-generates document_number

        dist_items = []
        for alloc_item, fa in items_list:
            dist_items.append(
                DistributionItem(
                    distribution=distribution,
                    item=alloc_item.item,
                    stock=alloc_item.stock,
                    quantity_requested=fa.qty_allocated,
                    quantity_approved=fa.qty_allocated,
                    issued_batch_lot=alloc_item.stock.batch_lot if alloc_item.stock else "",
                    issued_expiry_date=alloc_item.stock.expiry_date if alloc_item.stock else None,
                    issued_unit_price=alloc_item.stock.unit_price if alloc_item.stock else None,
                    issued_sumber_dana=alloc_item.stock.sumber_dana if alloc_item.stock else None,
                )
            )
        DistributionItem.objects.bulk_create(dist_items)
        apply_distribution_reservations(distribution)


# ──────────────────────────────────────────────────────────────
# Public service functions
# ──────────────────────────────────────────────────────────────

def execute_allocation_submission(allocation, user):
    allocation_items = _get_allocation_items(allocation, "diajukan")
    _validate_submission(allocation, allocation_items)

    # Re-snapshot available quantities
    for alloc_item in allocation_items:
        if alloc_item.stock:
            alloc_item.total_qty_available = alloc_item.stock.available_quantity
            alloc_item.save(update_fields=["total_qty_available"])

    allocation.status = Allocation.Status.SUBMITTED
    allocation.submitted_by = user
    allocation.submitted_at = timezone.now()
    allocation.rejection_reason = ""
    _save_allocation(
        allocation, ["status", "submitted_by", "submitted_at", "rejection_reason"]
    )



def execute_allocation_approval(allocation, user):
    allocation_items = _get_allocation_items(allocation, "disetujui")

    with transaction.atomic():
        _validate_stock_at_approval(allocation_items)

        allocation.status = Allocation.Status.APPROVED
        allocation.approved_by = user
        allocation.approved_at = timezone.now()
        _save_allocation(allocation, ["status", "approved_by", "approved_at"])

        _generate_distributions(allocation, allocation_items, user)



def execute_allocation_step_back_to_submitted(allocation):
    if allocation.status != Allocation.Status.APPROVED:
        raise AllocationWorkflowError(
            "Hanya alokasi berstatus 'Disetujui' yang dapat dikembalikan ke 'Diajukan'."
        )

    with transaction.atomic():
        for distribution in allocation.distributions.prefetch_related("items").all():
            try:
                release_distribution_reservations(distribution)
            except DistributionWorkflowError as exc:
                raise AllocationWorkflowError(str(exc)) from exc
        allocation.distributions.all().delete()
        allocation.status = Allocation.Status.SUBMITTED
        allocation.approved_by = None
        allocation.approved_at = None
        _save_allocation(allocation, ["status", "approved_by", "approved_at"])



def execute_allocation_rejection(allocation, reason):
    allocation.status = Allocation.Status.DRAFT
    allocation.rejection_reason = reason
    allocation.submitted_by = None
    allocation.submitted_at = None
    _save_allocation(
        allocation,
        ["status", "rejection_reason", "submitted_by", "submitted_at"],
    )



def execute_allocation_reset_to_draft(allocation):
    allocation.status = Allocation.Status.DRAFT
    allocation.submitted_by = None
    allocation.submitted_at = None
    allocation.rejection_reason = ""
    _save_allocation(
        allocation,
        ["status", "submitted_by", "submitted_at", "rejection_reason"],
    )



def execute_distribution_preparation(distribution, user):
    """Mark an allocation-generated distribution as PREPARED."""
    if distribution.status != Distribution.Status.VERIFIED:
        raise AllocationWorkflowError(
            "Hanya distribusi berstatus 'Terverifikasi' yang dapat disiapkan."
        )

    distribution.status = Distribution.Status.PREPARED
    distribution.save(update_fields=["status", "updated_at"])



def execute_distribution_delivery(distribution, user, allocation):
    """Confirm delivery for an allocation-generated distribution.
    Deducts stock and writes Transaction(OUT) for each item.
    Auto-closes parent allocation if all distributions are delivered.
    """
    if distribution.status != Distribution.Status.PREPARED:
        raise AllocationWorkflowError(
            "Hanya distribusi berstatus 'Disiapkan' yang dapat dikirim."
        )

    distribution_items = list(
        distribution.items.select_related("item", "stock").order_by("pk")
    )
    if not distribution_items:
        raise AllocationWorkflowError(
            "Distribusi tidak memiliki item untuk dikirim."
        )

    processed_at = timezone.now()

    with transaction.atomic():
        locked_stocks = {
            stock.pk: stock
            for stock in Stock.objects.select_for_update().filter(
                pk__in=sorted({item.stock_id for item in distribution_items if item.stock_id})
            )
        }

        for dist_item in distribution_items:
            quantity = dist_item.quantity_approved or dist_item.quantity_requested
            if not quantity or quantity <= 0:
                continue

            if dist_item.stock is None:
                raise AllocationWorkflowError(
                    f"Item {dist_item.item.nama_barang}: batch stok belum dipilih."
                )

            stock = locked_stocks.get(dist_item.stock_id)
            if stock is None:
                raise AllocationWorkflowError(
                    f"Batch stok untuk item {dist_item.item.nama_barang} tidak ditemukan."
                )

            available_with_own_reservation = stock.available_quantity + dist_item.reserved_quantity
            if quantity > available_with_own_reservation:
                raise AllocationWorkflowError(
                    f"Stok tidak cukup untuk {dist_item.item.nama_barang}. "
                    f"Tersedia {available_with_own_reservation}, dibutuhkan {quantity}."
                )

            if stock.quantity < quantity:
                raise AllocationWorkflowError(
                    f"Stok fisik tidak cukup untuk {dist_item.item.nama_barang}. "
                    f"Tersedia {stock.quantity}, dibutuhkan {quantity}."
                )

            if dist_item.reserved_quantity > stock.reserved:
                raise AllocationWorkflowError(
                    f"Reservasi stok untuk {dist_item.item.nama_barang} melebihi stok yang dibooking."
                )

            stock.quantity = stock.quantity - quantity
            stock.reserved = stock.reserved - dist_item.reserved_quantity
            stock.save(update_fields=["quantity", "reserved", "updated_at"])

            dist_item.reserved_quantity = 0
            dist_item.save(update_fields=["reserved_quantity"])

            Transaction.objects.create(
                transaction_type=Transaction.TransactionType.OUT,
                item=dist_item.item,
                location=stock.location,
                batch_lot=stock.batch_lot,
                quantity=quantity,
                unit_price=stock.unit_price,
                sumber_dana=stock.sumber_dana,
                reference_type=Transaction.ReferenceType.ALLOCATION,
                reference_id=allocation.id,
                user=user,
                notes=(
                    f"Alokasi {allocation.document_number} → "
                    f"Distribusi {distribution.document_number} "
                    f"ke {distribution.facility}: "
                    f"{dist_item.item.nama_barang}"
                ).strip(),
            )

        distribution.status = Distribution.Status.DISTRIBUTED
        distribution.approved_by = user
        distribution.approved_at = processed_at
        distribution.distributed_date = processed_at.date()
        distribution.save(
            update_fields=[
                "status",
                "approved_by",
                "approved_at",
                "distributed_date",
                "updated_at",
            ]
        )

        # Check auto-close: if all sibling distributions are delivered
        _check_allocation_fulfillment(allocation)



def _check_allocation_fulfillment(allocation):
    """Update allocation status based on delivery progress of child distributions."""
    total = allocation.distributions.count()
    if total == 0:
        return

    delivered = allocation.distributions.filter(
        status=Distribution.Status.DISTRIBUTED
    ).count()

    if delivered == total:
        allocation.status = Allocation.Status.FULFILLED
    elif delivered > 0:
        allocation.status = Allocation.Status.PARTIALLY_FULFILLED
    else:
        return  # Still APPROVED, no change

    _save_allocation(allocation, ["status"])
