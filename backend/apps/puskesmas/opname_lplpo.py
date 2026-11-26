"""Facility rollout and the LPLPO checkpoint for current reconciled evidence."""
from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q

from apps.lplpo.models import LPLPO, LPLPOItem, get_previous_lplpo
from .consumption_inventory import month_end
from .inventory import lock_facility, locked_actor
from .inventory_models import PuskesmasOpeningVerification
from .opname import compare_revision, current_revision, cutoff_snapshot
from .opname_models import FacilityOpname, LPLPOOpnameLink, OpnameActivation, OpnameRevision


def is_gated(facility_id, year, month):
    return OpnameActivation.objects.filter(facility_id=facility_id,
        first_month__lte=date(year, month, 1)).exists()


def supports_inventory_binding(facility, year, month):
    existing = LPLPO.objects.filter(facility=facility, tahun=year, bulan=month).first()
    if existing:
        return existing.inventory_backed
    if month == 1:
        if PuskesmasOpeningVerification.objects.filter(facility=facility, year=year, status="POSTED").exists():
            return True
    previous = get_previous_lplpo(facility, month, year)
    return bool(previous and previous.inventory_backed)


@transaction.atomic
def activate(*, user, facility_id, year, month):
    actor = locked_actor(user)
    if not actor.is_active or not actor.is_superuser:
        raise PermissionDenied
    facility = lock_facility(facility_id)
    cutoff = month_end(year, month)
    first_month = cutoff.replace(day=1)
    previous = OpnameActivation.objects.filter(facility=facility).first()
    if previous:
        if previous.first_month == first_month:
            return previous
        raise ValidationError("Bulan pertama Stock Opname tidak dapat diubah.")
    if not supports_inventory_binding(facility, year, month):
        raise ValidationError("LPLPO bulan pertama belum memiliki jalur pengikatan jurnal.")
    coverage = cutoff_snapshot(facility.pk, cutoff)
    if coverage["barriers"]:
        raise ValidationError(coverage["barriers"])
    existing = LPLPO.objects.filter(facility=facility).filter(Q(tahun__gt=year) | Q(tahun=year, bulan__gte=month))
    if existing.exclude(
        status__in=(LPLPO.Status.DRAFT, LPLPO.Status.REJECTED_PUSKESMAS),
    ).exists():
        raise ValidationError("Pilih bulan pertama setelah LPLPO yang sudah diajukan.")
    if existing.filter(inventory_binding__isnull=True).exists():
        raise ValidationError("LPLPO yang sudah ada dalam periode aktivasi harus terikat ke jurnal inventaris.")
    return OpnameActivation.objects.create(facility=facility, first_month=first_month, actor=actor)


def require_reconciled_count(facility_id, year, month):
    """Call under the facility mutex. Return None for months outside rollout."""
    if not is_gated(facility_id, year, month):
        return None
    count = FacilityOpname.objects.select_for_update().filter(facility_id=facility_id, cutoff=month_end(year, month)).first()
    if not count:
        raise ValidationError("Buat dan rekonsiliasi Stock Opname bulan ini sebelum melanjutkan LPLPO.")
    revision = current_revision(count)
    if revision.state == OpnameRevision.State.COUNTING:
        raise ValidationError("Selesaikan hitungan dan rekonsiliasi Stock Opname bulan ini.")
    if revision.state == OpnameRevision.State.CLOSED_OPEN:
        raise ValidationError("Selesaikan kasus selisih Stock Opname dengan operator atau peninjau Gudang yang ditugaskan.")
    comparison = compare_revision(count, revision)
    if (comparison["digest"] != revision.comparison["digest"] or comparison["barriers"]
            or any(row["open"] for row in comparison["rows"])):
        raise ValidationError("Bukti Stock Opname tidak lagi terkini. Tinjau dan rekonsiliasi ulang sebelum melanjutkan.")
    return revision


def link_count(lplpo, revision, actor):
    if revision is None:
        return
    # January adoption can create the binding through a different ORM instance.
    lplpo._state.fields_cache.pop("inventory_binding", None)
    if not lplpo.inventory_backed:
        raise ValidationError("LPLPO bulan Stock Opname harus terikat ke jurnal inventaris.")
    if (revision.count.facility_id != lplpo.facility_id
            or revision.count.cutoff != month_end(lplpo.tahun, lplpo.bulan)):
        raise PermissionDenied
    previous = lplpo.opname_links.order_by("-pk").first()
    if previous and previous.revision_id == revision.pk:
        return
    LPLPOOpnameLink.objects.create(lplpo=lplpo, revision=revision, actor=actor)
    warehouse = revision.comparison["warehouse"]
    lines = list(lplpo.items.all())
    for line in lines:
        line.stock_gudang_puskesmas = warehouse.get(str(line.item_id), 0)
    LPLPOItem.objects.bulk_update(lines, ["stock_gudang_puskesmas"])
