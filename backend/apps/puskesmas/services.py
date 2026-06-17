import logging

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce

from apps.lplpo.models import LPLPO, sync_receiving_to_editable_lplpo
from apps.puskesmas.models import PuskesmasConsumptionEntry


logger = logging.getLogger("core")


EDITABLE_LPLPO_STATUSES = {
    LPLPO.Status.DRAFT,
    LPLPO.Status.REJECTED_PUSKESMAS,
}


def assert_receiving_month_mutable(*, facility, received_date):
    """Ensure receipt confirmation can still change the target facility/month."""
    lplpo = (
        LPLPO.objects.filter(
            facility=facility,
            bulan=received_date.month,
            tahun=received_date.year,
        )
        .only("status", "document_number")
        .first()
    )
    if lplpo and lplpo.status not in EDITABLE_LPLPO_STATUSES:
        raise ValidationError(
            "Konfirmasi penerimaan untuk periode ini tidak dapat diubah karena LPLPO sudah diajukan atau diproses."
        )
    return lplpo


def sync_receiving_month(*, facility, received_date):
    """Lock and recompute any editable LPLPO for the target receipt month."""
    with transaction.atomic():
        return sync_receiving_to_editable_lplpo(
            facility=facility,
            bulan=received_date.month,
            tahun=received_date.year,
        )


def assert_consumption_month_mutable(*, facility, bulan, tahun, lock=False):
    """Ensure detailed consumption can still change the target facility/month."""
    queryset = LPLPO.objects.filter(
            facility=facility,
            bulan=bulan,
            tahun=tahun,
        )
    if lock:
        queryset = queryset.select_for_update()
    lplpo = queryset.only("status", "document_number").first()
    if lplpo and lplpo.status not in EDITABLE_LPLPO_STATUSES:
        raise ValidationError(
            "Pemakaian untuk periode ini tidak dapat diubah karena LPLPO sudah diajukan atau diproses."
        )
    return lplpo


def get_consumption_for_facility_period(*, facility, bulan, tahun):
    """Return aggregated consumption totals per item for one facility/month."""
    rows = (
        PuskesmasConsumptionEntry.objects.filter(
            consumption__facility=facility,
            consumption__bulan=bulan,
            consumption__tahun=tahun,
        )
        .values("item_id")
        .annotate(total=Coalesce(Sum("quantity"), 0))
    )
    return {row["item_id"]: int(row["total"] or 0) for row in rows}


def sync_consumption_to_editable_lplpo(*, facility, bulan, tahun):
    """Recompute editable LPLPO pemakaian totals from detailed consumption rows."""
    lplpo = (
        LPLPO.objects.select_for_update()
        .filter(
            facility=facility,
            bulan=bulan,
            tahun=tahun,
            status__in=EDITABLE_LPLPO_STATUSES,
        )
        .first()
    )
    if not lplpo:
        return None

    pemakaian_data = get_consumption_for_facility_period(
        facility=facility,
        bulan=bulan,
        tahun=tahun,
    )

    items_to_update = []
    for line in lplpo.items.all():
        line.pemakaian = pemakaian_data.get(line.item_id, 0)
        line.compute_fields()
        items_to_update.append(line)

    if items_to_update:
        lplpo.items.model.objects.bulk_update(
            items_to_update,
            [
                "pemakaian",
                "stock_keseluruhan",
                "stock_optimum",
                "jumlah_kebutuhan",
            ],
        )

    return lplpo


def sync_consumption_month(*, facility, bulan, tahun):
    """Lock and recompute any editable LPLPO for the target consumption period."""
    with transaction.atomic():
        return sync_consumption_to_editable_lplpo(
            facility=facility,
            bulan=bulan,
            tahun=tahun,
        )


def log_receiving_event(*, event, receipt_confirmation, user, extra=None):
    payload = {
        "event": event,
        "receipt_confirmation_id": receipt_confirmation.pk,
        "document_number": receipt_confirmation.document_number,
        "facility_id": receipt_confirmation.facility_id,
        "distribution_id": receipt_confirmation.distribution_id,
        "username": getattr(user, "username", ""),
    }
    if extra:
        payload.update(extra)
    logger.info("puskesmas_receipt_confirmation_event", extra=payload)


def log_consumption_event(*, event, consumption, user, extra=None):
    payload = {
        "event": event,
        "consumption_id": consumption.pk,
        "facility_id": consumption.facility_id,
        "bulan": consumption.bulan,
        "tahun": consumption.tahun,
        "username": getattr(user, "username", ""),
    }
    if extra:
        payload.update(extra)
    logger.info("puskesmas_consumption_event", extra=payload)


def raise_receiving_creator_denied():
    raise PermissionDenied(
        "Hanya operator Puskesmas yang dapat mengelola konfirmasi penerimaan."
    )


def raise_consumption_creator_denied():
    raise PermissionDenied(
        "Hanya operator Puskesmas yang dapat mengelola pemakaian rinci."
    )


# Temporary compatibility aliases while views/forms/tests are migrated.
assert_sbbk_month_mutable = assert_receiving_month_mutable
sync_sbbk_month = sync_receiving_month
log_sbbk_event = log_receiving_event
raise_sbbk_creator_denied = raise_receiving_creator_denied
