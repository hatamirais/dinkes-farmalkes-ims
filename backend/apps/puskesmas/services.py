import logging

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.lplpo.models import LPLPO, sync_sbbk_to_editable_lplpo


logger = logging.getLogger("core")


EDITABLE_LPLPO_STATUSES = {
    LPLPO.Status.DRAFT,
    LPLPO.Status.REJECTED_PUSKESMAS,
}


def assert_sbbk_month_mutable(*, facility, received_date):
    """Ensure SBBK can still change the target facility/month."""
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
            "SBBK untuk periode ini tidak dapat diubah karena LPLPO sudah diajukan atau diproses."
        )
    return lplpo


def sync_sbbk_month(*, facility, received_date):
    """Lock and recompute any editable LPLPO for the target SBBK month."""
    with transaction.atomic():
        return sync_sbbk_to_editable_lplpo(
            facility=facility,
            bulan=received_date.month,
            tahun=received_date.year,
        )


def log_sbbk_event(*, event, sbbk, user, extra=None):
    payload = {
        "event": event,
        "sbbk_id": sbbk.pk,
        "document_number": sbbk.document_number,
        "facility_id": sbbk.facility_id,
        "username": getattr(user, "username", ""),
    }
    if extra:
        payload.update(extra)
    logger.info("puskesmas_sbbk_event", extra=payload)


def raise_sbbk_creator_denied():
    raise PermissionDenied("Hanya operator Puskesmas yang dapat mengelola SBBK.")
