"""Authorized count reopening and layer-specific inventory corrections."""
from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum

from apps.lplpo.models import LPLPO
from .consumption_inventory import _change_balance, _post_revision_locked, latest_revision, snapshot
from .expiry import _balances, _reverse
from .inventory import text_value
from .inventory_models import (
    PuskesmasConsumptionRevision, PuskesmasInventoryLayer, PuskesmasInventoryMovement,
    PuskesmasInventoryPosting,
)
from .models import PuskesmasConsumption, PuskesmasSubunit
from .opname import (
    EDITABLE_LPLPO_STATUSES, MAX_QUANTITY, authority, compare, compare_revision, digest, group_key,
    lock_count, operator, required_text, revision_roster, save_revision,
)
from .opname_models import OpnameAction, OpnameDecision, OpnameRevision

Kind = OpnameAction.Kind
APPROVAL = {
    Kind.ADJUST: "approve_adjustment",
    Kind.RECEIPT: "correct_receipt",
    Kind.REVERSE: "approve_adjustment",
    Kind.REOPEN: "reopen_count",
}


def affected_lplpos(count):
    cutoff = count.cutoff
    return LPLPO.objects.filter(facility_id=count.facility_id).filter(
        Q(tahun__gt=cutoff.year) | Q(tahun=cutoff.year, bulan__gte=cutoff.month))


def assert_period_mutable(count):
    if affected_lplpos(count).exclude(status__in=EDITABLE_LPLPO_STATUSES).exists():
        raise ValidationError("LPLPO terdampak sudah diajukan. Gunakan alur pengembalian LPLPO terlebih dahulu.")
    if PuskesmasConsumptionRevision.objects.filter(
        consumption__facility_id=count.facility_id, effective_date__gt=count.cutoff,
    ).exists():
        raise ValidationError("Pemakaian periode berikutnya sudah difinalisasi.")


def _remaining_damage(count, revision, layer, observed):
    if not observed:
        return 0
    recorded_withdrawals = defaultdict(int)
    for location in revision.observations.values():
        for line in location["lines"]:
            if line["layer"] == layer.pk and line["excluded_posting"]:
                recorded_withdrawals[line["excluded_posting"]] += line["cutoff_quantity"]

    prior_adjustments = count.actions.filter(
        kind=Kind.ADJUST, layer=layer, posting__isnull=False, posting__reversal__isnull=True,
    ).select_related("revision", "posting")
    outstanding = 0
    for action in prior_adjustments:
        prior_comparison = action.revision.comparison
        prior_row = next((row for row in prior_comparison["rows"] if row["key"] == action.case_key), None)
        if prior_row is None:
            damage_applied = action.quantity
        elif prior_comparison["digest"] == action.journal_digest:
            prior_shortage = max(0, -Decimal(prior_row["delta"]))
            damage_applied = max(0, action.quantity - prior_shortage)
        else:
            # The frozen observations still prove how much damage could have
            # supported the posting, but the saved journal delta is stale.
            damage_applied = min(action.quantity, prior_row["damaged_by_layer"].get(str(layer.pk), 0))
        outstanding += max(0, damage_applied - recorded_withdrawals[action.posting.pk])
    return max(0, observed - outstanding)


def eligible_case(count, revision, comparison, layer, case_key, quantity, *, kind):
    key = (layer.item_id, layer.batch_lot, layer.expiry_date.isoformat() if layer.expiry_date else "")
    row = next((row for row in comparison["rows"] if row["key"] == case_key and row["item"] == layer.item_id), None)
    if not row or not row["open"]:
        raise ValidationError("Pilih selisih terbuka untuk barang yang sama.")
    if kind == Kind.RECEIPT:
        # A fully allocated receipt can cause a shortage on a different batch
        # of the same item. The source line, not the comparison delta, caps the correction.
        if Decimal(row["delta"]) >= 0 and not row["layer_mismatch"]:
            raise ValidationError("Pilih selisih kekurangan atau atribusi lapisan yang belum sesuai.")
        return
    if group_key(row) != key:
        raise ValidationError("Pengurangan melebihi kekurangan terhitung pada barang dan batch ini.")
    shortage = max(0, -Decimal(row["delta"]))
    if quantity > shortage:
        observed_damage = row["damaged_by_layer"].get(str(layer.pk), 0)
        remaining_damage = _remaining_damage(count, revision, layer, observed_damage)
        if quantity - shortage > remaining_damage:
            raise ValidationError(
                "Pengurangan melebihi kekurangan dan jumlah rusak yang belum disesuaikan pada lapisan ini."
            )


@transaction.atomic
def request_action(*, user, count_id, expected_revision, key, kind, reason, reference,
                   expected_change="", case_key="", layer_id=None, quantity=None,
                   incident_date=None, reverse_id=None, add_location_id=None):
    actor, count, revision = lock_count(user, count_id)
    if not operator(actor, count.facility_id):
        raise PermissionDenied
    if kind not in APPROVAL:
        raise ValidationError("Tindakan rekonsiliasi tidak valid.")
    reason = required_text(reason)
    reference = required_text(reference, 255)
    expected_change = required_text(expected_change) if kind == Kind.REOPEN else ""
    try:
        key = UUID(str(key))
    except (TypeError, ValueError) as exc:
        raise ValidationError("Kunci permintaan tidak valid.") from exc
    existing = OpnameAction.objects.filter(key=key).first()
    if existing:
        if existing.count_id != count.pk or existing.preparer_id != actor.pk:
            raise PermissionDenied
        if (existing.revision_id, existing.kind, existing.reason, existing.reference, existing.expected_change,
                existing.case_key, existing.layer_id, existing.quantity, existing.incident_date,
                existing.reverses_id, existing.add_location_id) != (
                expected_revision, kind, reason, reference, expected_change, case_key,
                layer_id, quantity, incident_date, reverse_id, add_location_id):
            raise ValidationError("Kunci permintaan sudah digunakan dengan bukti berbeda.")
        return existing
    if revision.pk != expected_revision:
        raise ValidationError("Tindakan atau revisi hitung sudah tidak berlaku.")
    comparison = compare_revision(count, revision)
    layer = None
    original = None
    if kind in (Kind.ADJUST, Kind.RECEIPT):
        layer = PuskesmasInventoryLayer.objects.filter(pk=layer_id, posting__facility_id=count.facility_id,
            posting__effective_date__lte=count.cutoff).select_related("posting", "receipt_line").first()
        if not layer or type(quantity) is not int or not 0 < quantity <= MAX_QUANTITY:
            raise ValidationError("Pilih lapisan fasilitas dan jumlah positif.")
        if kind == Kind.RECEIPT:
            if not layer.receipt_line_id or (layer.posting.effective_date.year, layer.posting.effective_date.month) != (
                count.cutoff.year, count.cutoff.month,
            ):
                raise ValidationError("Koreksi hanya tersedia untuk penerimaan diposting pada bulan hitung.")
        elif comparison["barriers"]:
            raise ValidationError(comparison["barriers"])
        eligible_case(count, revision, comparison, layer, case_key, quantity, kind=kind)
    elif kind == Kind.REVERSE:
        original = count.actions.filter(pk=reverse_id, kind=Kind.ADJUST, decision__approved=True).first()
        if not original or hasattr(original.posting, "reversal"):
            raise ValidationError("Penyesuaian asli belum diposting atau sudah dibalik.")
    elif revision.state == OpnameRevision.State.COUNTING:
        raise ValidationError("Hitungan masih terbuka.")
    if incident_date and (kind != Kind.ADJUST or incident_date > count.cutoff or incident_date.year < 1000):
        raise ValidationError("Tanggal kejadian di luar batas hitung.")
    if add_location_id and (kind != Kind.REOPEN
            or str(add_location_id) in {row["key"] for row in revision_roster(count, revision)}
            or not PuskesmasSubunit.objects.filter(pk=add_location_id, facility_id=count.facility_id).exists()):
        raise ValidationError("Lokasi tambahan tidak valid untuk permintaan ini.")
    action, created = OpnameAction.objects.get_or_create(key=key, defaults={
        "count": count, "revision": revision, "kind": kind, "reason": reason,
        "reference": reference, "expected_change": expected_change, "case_key": text_value(case_key, 64),
        "layer": layer, "quantity": quantity if layer else None, "incident_date": incident_date,
        "reverses": original, "add_location_id": add_location_id, "preparer": actor,
        "journal_digest": comparison["digest"],
    })
    if not created:
        raise PermissionDenied
    return action


def _write_reduction(action, actor, balance, effective):
    posting = PuskesmasInventoryPosting.objects.create(facility_id=action.count.facility_id,
        opname_action=action, actor=actor, effective_date=effective,
        digest=digest([action.pk, action.journal_digest]))
    PuskesmasInventoryMovement.objects.create(posting=posting, layer=action.layer,
        quantity_delta=-action.quantity, unit_price=action.layer.unit_price)
    _change_balance(balance, -action.quantity)
    return posting


def _correct_receipt(action, actor, balances):
    count, layer = action.count, action.layer
    corrected = PuskesmasInventoryMovement.objects.filter(
        layer=layer, posting__opname_action__kind=Kind.RECEIPT,
    ).aggregate(total=Sum("quantity_delta", default=0))["total"]
    if action.quantity > layer.receipt_line.quantity + corrected:
        raise ValidationError("Koreksi melebihi jumlah tersisa pada baris penerimaan asli.")
    consumption = PuskesmasConsumption.objects.select_for_update().filter(
        facility_id=count.facility_id, tahun=count.cutoff.year, bulan=count.cutoff.month).first()
    previous_use = latest_revision(consumption) if consumption else None
    if previous_use:
        _reverse(previous_use.posting, actor, balances)
    posting = _write_reduction(action, actor, balances[layer.pk], layer.posting.effective_date)
    if previous_use:
        _post_revision_locked(consumption=consumption, user=actor, data=snapshot(consumption),
            reason=f"Koreksi penerimaan #{action.pk}", receipt_correction=action, restored_previous=True)
    days = PuskesmasInventoryMovement.objects.filter(layer=layer).values(
        "posting__effective_date").annotate(net=Sum("quantity_delta")).order_by("posting__effective_date")
    balance = 0
    for day in days:
        balance += day["net"]
        if balance < 0:
            raise ValidationError("Koreksi akan membuat saldo historis lapisan negatif.")
    return posting


@transaction.atomic
def decide_action(*, user, count_id, action_id, approve, reason=""):
    actor, count, revision = lock_count(user, count_id)
    action = count.actions.select_related("layer__posting", "layer__receipt_line", "reverses", "add_location").filter(pk=action_id).first()
    if not action or actor.pk == action.preparer_id or not authority(
        actor, count.facility_id, APPROVAL[action.kind], lock=True,
    ):
        raise PermissionDenied
    existing = OpnameDecision.objects.filter(action=action).first()
    if existing:
        if existing.approver_id == actor.pk and existing.approved == approve:
            return existing
        raise ValidationError("Permintaan sudah diputuskan.")
    if not approve:
        return OpnameDecision.objects.create(action=action, approved=False, approver=actor, reason=required_text(reason))
    comparison = compare_revision(count, revision)
    if action.revision_id != revision.pk or action.journal_digest != comparison["digest"]:
        raise ValidationError("Bukti hitung atau jurnal berubah. Ajukan permintaan baru.")
    assert_period_mutable(count)
    posting = None
    if action.kind == Kind.REOPEN:
        if revision.state == OpnameRevision.State.COUNTING:
            raise ValidationError("Hitungan sudah terbuka.")
        if action.add_location_id:
            location = action.add_location
            if location.facility_id != count.facility_id:
                raise ValidationError("Lokasi tambahan bukan milik Puskesmas ini.")
            roster = [*revision_roster(count, revision), {
                "key": str(location.pk), "name": location.name, "type": location.subunit_type,
            }]
            comparison = compare(count, revision.observations, roster=roster)
        save_revision(count, revision, actor, revision.observations, comparison,
                      OpnameRevision.State.COUNTING, action.reason)
    else:
        balances = _balances(count.facility_id)
        if action.kind == Kind.RECEIPT:
            posting = _correct_receipt(action, actor, balances)
        elif action.kind == Kind.REVERSE:
            original = action.reverses.posting
            if hasattr(original, "reversal"):
                raise ValidationError("Penyesuaian sudah dibalik.")
            posting = _reverse(original, actor, balances)
        else:
            if comparison["barriers"]:
                raise ValidationError(comparison["barriers"])
            eligible_case(count, revision, comparison, action.layer, action.case_key, action.quantity, kind=action.kind)
            expected = next(row for row in comparison["layers"] if row["layer"] == action.layer_id)
            if action.quantity > Decimal(expected["quantity"]):
                raise ValidationError("Jumlah melebihi saldo lapisan pada batas bulan.")
            posting = _write_reduction(action, actor, balances[action.layer_id], count.cutoff)
        from .inventory_reporting import sync_inventory_lplpo
        for lplpo in affected_lplpos(count).filter(inventory_binding__isnull=False).order_by("tahun", "bulan", "pk"):
            sync_inventory_lplpo(lplpo)
    return OpnameDecision.objects.create(action=action, approved=True, approver=actor,
                                         reason=text_value(reason, 1000), posting=posting)
