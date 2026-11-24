"""Costed monthly consumption with explicit expiry withdrawals and corrections."""
import calendar
import hashlib
import json
import logging
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.items.models import Item
from apps.lplpo.models import LPLPO
from apps.users.access import has_module_scope, is_super_admin
from apps.users.models import ModuleAccess, User
from .inventory import lock_facility, locked_actor, text_value
from .inventory_models import (
    PuskesmasConsumptionAllocation, PuskesmasConsumptionAudit,
    PuskesmasConsumptionRevision, PuskesmasInventoryAccount,
    PuskesmasInventoryBalance, PuskesmasInventoryMovement,
    PuskesmasInventoryPosting,
)
from .models import PuskesmasConsumption, PuskesmasSubunit

logger = logging.getLogger("core")
EXPIRY_GATE_MESSAGE = "Selesaikan penarikan kedaluwarsa yang diketahui sebelum finalisasi. Pemakaian dialokasikan pada akhir bulan; ini bukan bukti tanggal penggunaan batch."


def expiry_integration_ready():
    # Code integration, not a setting/checkbox bypass or completeness claim.
    return True


def require_expiry_integration():
    if not expiry_integration_ready():
        raise ValidationError(EXPIRY_GATE_MESSAGE)


def month_end(year, month):
    if not 1000 <= year <= 9999 or not 1 <= month <= 12:
        raise ValidationError("Periode pemakaian tidak valid.")
    return date(year, month, calendar.monthrange(year, month)[1])


def snapshot(consumption):
    return {
        "notes": consumption.notes,
        "entries": list(consumption.entries.order_by("item_id", "subunit_id").values(
            "item_id", "subunit_id", "quantity")),
    }


def snapshot_digest(consumption, data):
    payload = [consumption.pk, consumption.facility_id, consumption.tahun, consumption.bulan, data]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def latest_revision(consumption):
    return consumption.inventory_revisions.order_by("-number").first()


def audit(consumption, user, event, before, after):
    event_row = PuskesmasConsumptionAudit.objects.create(
        facility_id=consumption.facility_id, consumption_id_snapshot=consumption.pk,
        actor=user, event=event, before=before, after=after)
    details = {
        "event": event, "audit_id": event_row.pk, "consumption_id": consumption.pk,
        "facility_id": consumption.facility_id, "actor_id": user.pk,
    }
    transaction.on_commit(lambda: logger.info("puskesmas_consumption_revision", extra=details))


def assert_operator(user, facility, *, permission="puskesmas.change_puskesmasconsumption",
                    module=ModuleAccess.Module.PUSKESMAS):
    if not user.is_active:
        raise PermissionDenied
    if is_super_admin(user):
        return
    if not (user.role == User.Role.PUSKESMAS and user.facility_id == facility.pk and (
        user.has_perm(permission) or has_module_scope(
            user, module, ModuleAccess.Scope.OPERATE))):
        raise PermissionDenied("Pemakaian hanya dapat dikelola operator fasilitas sendiri.")


def assert_period_mutable(consumption):
    from .services import assert_consumption_month_mutable
    assert_consumption_month_mutable(facility=consumption.facility,
        bulan=consumption.bulan, tahun=consumption.tahun, lock=True)
    if PuskesmasConsumptionRevision.objects.filter(
        consumption__facility_id=consumption.facility_id,
        effective_date__gt=month_end(consumption.tahun, consumption.bulan),
    ).exists():
        raise ValidationError("Bulan berikutnya sudah difinalisasi; pembukaan ulang lintas periode belum tersedia.")


def _validate_snapshot(consumption, data):
    notes = text_value(data.get("notes", ""), 1000)
    entries = data.get("entries", [])
    subunits = PuskesmasSubunit.objects.in_bulk({row["subunit_id"] for row in entries})
    items = Item.objects.in_bulk({row["item_id"] for row in entries})
    seen = set()
    clean = []
    for row in entries:
        key = (row["item_id"], row["subunit_id"])
        quantity = row["quantity"]
        if key in seen or key[0] not in items or key[1] not in subunits:
            raise ValidationError("Barang/subunit tidak valid atau duplikat.")
        if subunits[key[1]].facility_id != consumption.facility_id:
            raise PermissionDenied("Subunit berbeda fasilitas.")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not 0 <= quantity <= 2147483647:
            raise ValidationError("Pemakaian harus bilangan bulat nonnegatif dalam batas penyimpanan.")
        seen.add(key)
        if quantity:
            clean.append(dict(item_id=key[0], subunit_id=key[1], quantity=quantity))
    return {"notes": notes, "entries": sorted(clean, key=lambda row: (row["item_id"], row["subunit_id"]))}


def _change_balance(balance, delta):
    """The sole consumption projection writer; origins/journal stay immutable."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("Inventory projection requires a locked transaction.")
    quantity = balance.quantity + delta
    if quantity < 0:
        raise ValidationError("Saldo lapisan tidak mencukupi.")
    models.QuerySet.update(PuskesmasInventoryBalance.objects.filter(pk=balance.pk), quantity=quantity)
    balance.quantity = quantity


def _post_revision_locked(*, consumption, user, data, reason="", expected_digest=None,
                          expiry_revision=None, restored_previous=False):
    """Internal engine. Caller holds actor/facility/document locks in that order."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("Consumption posting requires a locked transaction.")
    assert_operator(user, consumption.facility)
    assert_period_mutable(consumption)
    effective = month_end(consumption.tahun, consumption.bulan)
    if effective > timezone.localdate():
        raise ValidationError("Pemakaian belum dapat difinalisasi sebelum hari terakhir bulan.")
    account = PuskesmasInventoryAccount.objects.filter(facility_id=consumption.facility_id).first()
    if not account or effective < account.effective_date:
        raise ValidationError("Saldo awal terverifikasi untuk periode ini belum tersedia.")
    data = _validate_snapshot(consumption, data)
    digest = snapshot_digest(consumption, data)
    previous = latest_revision(consumption)
    if previous and previous.digest == digest and expiry_revision is None:
        return previous
    if restored_previous and (not previous or expiry_revision is None or
                              not hasattr(previous.posting, "reversal")):
        raise ValidationError("Pemulihan revisi pemakaian tidak valid.")
    current = snapshot_digest(consumption, snapshot(consumption))
    if not previous and digest != current:
        raise ValidationError("Simpan draf pemakaian terlebih dahulu sebelum finalisasi.")
    if expected_digest is not None and expected_digest != current:
        raise ValidationError("Pemakaian berubah. Muat ulang sebelum menyimpan.")
    reason = text_value(reason, 1000)
    if previous and not reason:
        raise ValidationError("Alasan koreksi wajib diisi.")
    # An absent document is never proof of a completed zero-use month.
    cursor = account.effective_date
    covered = set(PuskesmasConsumptionRevision.objects.filter(
        consumption__facility_id=consumption.facility_id,
        effective_date__lt=effective).values_list("effective_date", flat=True))
    while cursor < date(consumption.tahun, consumption.bulan, 1):
        if month_end(cursor.year, cursor.month) not in covered:
            raise ValidationError(f"Pemakaian {cursor.month:02d}/{cursor.year} belum difinalisasi, termasuk bila nihil.")
        cursor = date(cursor.year + 1, 1, 1) if cursor.month == 12 else date(cursor.year, cursor.month + 1, 1)
    # Every in-coverage confirmed receipt must have a supported posting.
    from .models import PuskesmasReceiptConfirmation
    if PuskesmasReceiptConfirmation.objects.filter(
        facility_id=consumption.facility_id, status="CONFIRMED",
        received_date__gte=account.effective_date, received_date__lte=effective,
        inventory_posting__isnull=True).exists():
        raise ValidationError("Ada penerimaan terkonfirmasi yang belum diposting ke inventaris.")
    balances = list(PuskesmasInventoryBalance.objects.select_for_update(of=("self",))
        .filter(layer__posting__facility_id=consumption.facility_id,
                layer__posting__effective_date__lte=effective)
        .select_related("layer__posting", "layer__item").order_by("pk"))
    by_layer = {balance.layer_id: balance for balance in balances}
    journal = dict(PuskesmasInventoryMovement.objects.filter(layer_id__in=by_layer)
        .values("layer_id").annotate(total=Sum("quantity_delta")).values_list("layer_id", "total"))
    if any(balance.quantity != journal.get(balance.layer_id, Decimal(0)) for balance in balances):
        raise ValidationError("Proyeksi saldo berbeda dari jurnal; rekonsiliasi diperlukan.")
    original_movements = list(previous.posting.movements.all()) if previous else []
    dated_journal = dict(PuskesmasInventoryMovement.objects.filter(layer_id__in=by_layer,
        posting__effective_date__lte=effective).values("layer_id").annotate(total=Sum("quantity_delta"))
        .values_list("layer_id", "total"))
    if previous and not restored_previous:
        for movement in original_movements:
            dated_journal[movement.layer_id] = dated_journal.get(movement.layer_id, 0) - movement.quantity_delta
    for balance in balances:
        layer = balance.layer
        if layer.expiry_date and layer.expiry_date <= effective and dated_journal.get(layer.pk, 0) > 0:
            raise ValidationError(f"{layer.item}: batch {layer.batch_lot or '—'} kedaluwarsa {layer.expiry_date}; selesaikan aturan/alur kedaluwarsa dengan mencatat jumlah penarikan pada periode ini. Tidak ada pengurangan otomatis.")
    # The live projection includes later withdrawals. Do not let those outflows
    # choose this month's FEFO layers/costs; cross-period reallocation is deferred.
    item_ids = {entry["item_id"] for entry in data["entries"]}
    allocation_layers = [key for key, balance in by_layer.items() if balance.layer.item_id in item_ids]
    later_expiry = PuskesmasInventoryMovement.objects.filter(layer_id__in=allocation_layers,
        posting__effective_date__gt=effective).filter(
            Q(posting__expiry_revision__isnull=False) |
            Q(posting__reversal_of__expiry_revision__isnull=False))
    if later_expiry.values("layer_id").annotate(total=Sum("quantity_delta")).exclude(total=0).exists():
        raise ValidationError("Penarikan kedaluwarsa periode berikutnya memengaruhi lapisan barang ini. Selesaikan koreksi penarikan tersebut sebelum finalisasi/koreksi bulan ini; rekalkulasi lintas periode belum tersedia.")
    quantities = {key: balance.quantity for key, balance in by_layer.items()}
    if not restored_previous:
        for movement in original_movements:
            quantities[movement.layer_id] -= movement.quantity_delta
    ordered = sorted(balances, key=lambda balance: (
        balance.layer.expiry_date is None, balance.layer.expiry_date or date.max,
        balance.layer.posting.effective_date, balance.layer.posting_id, balance.layer_id))
    planned = []
    for entry in data["entries"]:
        needed = entry["quantity"]
        for balance in ordered:
            layer = balance.layer
            if layer.item_id != entry["item_id"] or quantities[layer.pk] <= 0:
                continue
            # Monthly totals cannot prove pre-expiry use dates. Expired-by-cutoff
            # stock requires explicit operator withdrawal before allocation.
            if layer.expiry_date is not None and layer.expiry_date <= effective:
                raise ValidationError(f"{layer.item}: batch {layer.batch_lot or '—'} kedaluwarsa {layer.expiry_date}; aturan/alur kedaluwarsa perlu diselesaikan.")
            if layer.item.requires_expiry_date and layer.expiry_date is None:
                raise ValidationError(f"{layer.item}: kedaluwarsa wajib belum tersedia.")
            take = min(Decimal(needed), quantities[layer.pk])
            if take != take.to_integral_value():
                raise ValidationError("Saldo lapisan bukan bilangan bulat.")
            planned.append((entry, balance, int(take)))
            quantities[layer.pk] -= take
            needed -= int(take)
            if not needed:
                break
        if needed:
            raise ValidationError(f"Barang #{entry['item_id']}: pemakaian {entry['quantity']}, kekurangan {needed}. Draf tetap tersedia.")
    before = previous.snapshot if previous else snapshot(consumption)
    revision = PuskesmasConsumptionRevision.objects.create(consumption=consumption,
        number=previous.number + 1 if previous else 1, effective_date=effective,
        digest=digest, snapshot=data, reason=reason, actor=user, expiry_revision=expiry_revision)
    if previous and not restored_previous:
        reversal = PuskesmasInventoryPosting.objects.create(facility_id=consumption.facility_id,
            reversal_of=previous.posting, effective_date=effective, actor=user, digest=previous.digest)
        for movement in original_movements:
            PuskesmasInventoryMovement.objects.create(posting=reversal, layer_id=movement.layer_id,
                quantity_delta=-movement.quantity_delta, unit_price=movement.unit_price)
            _change_balance(by_layer[movement.layer_id], -movement.quantity_delta)
    posting = PuskesmasInventoryPosting.objects.create(facility_id=consumption.facility_id,
        consumption_revision=revision, effective_date=effective, actor=user, digest=digest)
    per_layer = defaultdict(int)
    for entry, balance, quantity in planned:
        PuskesmasConsumptionAllocation.objects.create(revision=revision, layer=balance.layer,
            subunit_id=entry["subunit_id"], quantity=quantity, unit_price=balance.layer.unit_price)
        per_layer[balance.layer_id] += quantity
    for layer_id, quantity in per_layer.items():
        balance = by_layer[layer_id]
        PuskesmasInventoryMovement.objects.create(posting=posting, layer_id=layer_id,
            quantity_delta=-quantity, unit_price=balance.layer.unit_price)
        _change_balance(balance, -quantity)
    if previous:
        from .models import PuskesmasConsumptionEntry
        models.QuerySet.delete(consumption.entries.all())
        for entry in data["entries"]:
            models.Model.save(PuskesmasConsumptionEntry(consumption=consumption, **entry), force_insert=True)
        models.QuerySet.update(PuskesmasConsumption.objects.filter(pk=consumption.pk),
            notes=data["notes"], updated_by=user, updated_at=timezone.now())
        consumption.refresh_from_db()
    audit(consumption, user, "CORRECT" if previous else "FINALIZE", before,
          {**data, "revision": revision.number, "digest": digest, "reason": reason})
    from .services import sync_consumption_to_editable_lplpo
    sync_consumption_to_editable_lplpo(facility=consumption.facility,
        tahun=consumption.tahun, bulan=consumption.bulan)
    return revision


@transaction.atomic
def finalize_consumption(*, user, consumption_id, digest, data=None, reason=""):
    user = locked_actor(user)
    facility_id = PuskesmasConsumption.objects.values_list("facility_id", flat=True).get(pk=consumption_id)
    facility = lock_facility(facility_id)
    assert_operator(user, facility)
    consumption = PuskesmasConsumption.objects.select_for_update().get(pk=consumption_id)
    assert_period_mutable(consumption)
    require_expiry_integration()
    return _post_revision_locked(consumption=consumption, user=user,
        data=snapshot(consumption) if data is None else data, reason=reason, expected_digest=digest)
