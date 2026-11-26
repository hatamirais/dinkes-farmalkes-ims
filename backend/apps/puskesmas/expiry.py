"""Explicit operator expiry withdrawals and atomic same-month reallocation."""
import hashlib
import json
import logging
from datetime import date
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, IntegrityError
from django.db.models import Q, Sum
from django.utils import timezone

from apps.lplpo.models import LPLPO
from .consumption_inventory import (assert_operator, assert_period_mutable, latest_revision,
    month_end, snapshot, _post_revision_locked, _change_balance)
from .expiry_models import PuskesmasExpiry, PuskesmasExpiryRevision, PuskesmasExpiryLine
from .inventory import locked_actor, lock_facility, text_value
from .inventory_models import (PuskesmasInventoryAccount, PuskesmasInventoryBalance,
    PuskesmasInventoryMovement, PuskesmasInventoryPosting, PuskesmasConsumptionRevision)
from .models import PuskesmasConsumption

logger = logging.getLogger("core")


def current_revision(document):
    return document.revisions.order_by("-number").first()


def _balances(facility_id):
    balances = list(PuskesmasInventoryBalance.objects.select_for_update(of=("self",)).filter(
        layer__posting__facility_id=facility_id).select_related("layer__posting", "layer__item").order_by("pk"))
    journal = dict(PuskesmasInventoryMovement.objects.filter(layer_id__in=[b.layer_id for b in balances])
        .values("layer_id").annotate(total=Sum("quantity_delta")).values_list("layer_id", "total"))
    if any(b.quantity != journal.get(b.layer_id, 0) for b in balances):
        raise ValidationError("Proyeksi saldo berbeda dari jurnal; rekonsiliasi diperlukan.")
    return {b.layer_id: b for b in balances}


def _reverse(posting, user, balances):
    reversal = PuskesmasInventoryPosting.objects.create(facility_id=posting.facility_id,
        reversal_of=posting, effective_date=posting.effective_date, actor=user, digest=posting.digest)
    for movement in posting.movements.order_by("layer_id"):
        PuskesmasInventoryMovement.objects.create(posting=reversal, layer_id=movement.layer_id,
            quantity_delta=-movement.quantity_delta, unit_price=movement.unit_price)
        _change_balance(balances[movement.layer_id], -movement.quantity_delta)
    return reversal


@transaction.atomic
def post_expiry(*, user, facility_id, effective_date, reference, reason, entries,
                request_key=None, expiry_id=None, expected_digest=None, void=False):
    user = locked_actor(user)
    facility = lock_facility(facility_id)
    assert_operator(user, facility, permission="puskesmas.change_puskesmasexpiry" if expiry_id else "puskesmas.add_puskesmasexpiry")
    document = None
    if expiry_id:
        document = PuskesmasExpiry.objects.select_for_update().filter(pk=expiry_id, facility=facility).first()
        if document is None:
            raise PermissionDenied
    if not isinstance(effective_date, date) or type(effective_date) is not date or not 1000 <= effective_date.year <= 9999 or effective_date > timezone.localdate():
        raise ValidationError("Tanggal penarikan harus tanggal aktual, tidak boleh di masa depan.")
    reference, reason = text_value(reference, 100), text_value(reason, 1000)
    if not reason:
        raise ValidationError("Alasan penandaan/koreksi wajib diisi.")
    account = PuskesmasInventoryAccount.objects.filter(facility=facility).first()
    if not account or effective_date < account.effective_date:
        raise ValidationError("Tanggal penarikan belum tercakup saldo awal terverifikasi.")
    if not isinstance(entries, list) or len(entries) > 100 or any(not isinstance(row, dict) for row in entries):
        raise ValidationError("Rincian penarikan tidak valid (maksimal 100 lapisan).")
    clean, seen = [], set()
    for entry in entries:
        layer_id, quantity = entry.get("layer_id"), entry.get("quantity")
        if type(layer_id) is not int or type(quantity) is not int or not 0 <= quantity <= 2147483647 or layer_id in seen:
            raise ValidationError("Lapisan harus unik dan jumlah harus bilangan bulat nonnegatif.")
        seen.add(layer_id)
        if quantity:
            clean.append(dict(layer_id=layer_id, quantity=quantity))
    clean.sort(key=lambda row: row["layer_id"])
    if void:
        if not expiry_id or clean:
            raise ValidationError("Pembatalan memerlukan dokumen tersimpan tanpa rincian baru.")
    elif not clean:
        raise ValidationError("Pilih sedikitnya satu lapisan dengan jumlah positif.")
    digest = hashlib.sha256(json.dumps([facility.pk, effective_date.isoformat(), reference, reason, clean, void],
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if not expiry_id:
        try:
            request_key = UUID(str(request_key))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValidationError("Kunci permintaan tidak valid; muat ulang formulir.") from exc
        document = PuskesmasExpiry.objects.filter(request_key=request_key).first()
        if document and (document.facility_id != facility.pk or document.created_by_id != user.pk):
            raise PermissionDenied
    previous = current_revision(document) if document else None
    if previous and previous.digest == digest:
        return previous
    if previous:
        if not expiry_id or previous.digest != expected_digest:
            raise ValidationError("Dokumen berubah. Muat ulang sebelum mengoreksi.")
        if previous.void:
            raise ValidationError("Dokumen yang dibatalkan tetap disimpan; buat dokumen baru.")
        if effective_date != previous.effective_date:
            raise ValidationError("Tanggal penarikan dokumen tersimpan tidak dapat dipindahkan.")

    end = month_end(effective_date.year, effective_date.month)
    if PuskesmasConsumptionRevision.objects.filter(consumption__facility=facility, effective_date__gt=end).exists():
        raise ValidationError("Periode berikutnya sudah difinalisasi; pembukaan ulang lintas periode belum tersedia.")
    affected_lplpo = LPLPO.objects.filter(facility=facility).filter(Q(tahun__gt=effective_date.year) |
        Q(tahun=effective_date.year, bulan__gte=effective_date.month))
    if affected_lplpo.exclude(status__in=[LPLPO.Status.DRAFT, LPLPO.Status.REJECTED_PUSKESMAS]).exists():
        raise ValidationError("LPLPO terdampak sudah diajukan; kembalikan melalui alur berwenang dahulu.")
    consumption = PuskesmasConsumption.objects.select_for_update().filter(facility=facility,
        tahun=effective_date.year, bulan=effective_date.month).first()
    consumption_revision = latest_revision(consumption) if consumption else None
    if consumption_revision:
        assert_period_mutable(consumption)
    balances = _balances(facility.pk)
    # Restore use first: expiry precedes undated monthly consumption in accounting.
    if consumption_revision:
        _reverse(consumption_revision.posting, user, balances)
    if previous:
        _reverse(previous.posting, user, balances)
    for entry in clean:
        balance = balances.get(entry["layer_id"])
        if not balance or balance.layer.posting.effective_date > effective_date:
            raise ValidationError("Lapisan berbeda fasilitas atau belum diterima pada tanggal penarikan.")
        if balance.layer.expiry_date is None:
            raise ValidationError("Lapisan tanpa tanggal kedaluwarsa tidak dapat ditandai melalui modul ini.")
        if entry["quantity"] > balance.quantity:
            raise ValidationError(f"{balance.layer.item}: jumlah penarikan melebihi saldo jurnal lapisan.")
    if not document:
        try:
            with transaction.atomic():
                document = PuskesmasExpiry.objects.create(facility=facility, request_key=request_key, created_by=user)
        except IntegrityError:
            if PuskesmasExpiry.objects.filter(request_key=request_key).exists():
                raise PermissionDenied("Kunci permintaan sudah dipakai dokumen lain.")
            raise
    revision = PuskesmasExpiryRevision.objects.create(expiry=document, number=previous.number + 1 if previous else 1,
        effective_date=effective_date, reference=reference, reason=reason, digest=digest, void=void, actor=user)
    posting = PuskesmasInventoryPosting.objects.create(facility=facility, expiry_revision=revision,
        effective_date=effective_date, actor=user, digest=digest)
    for entry in clean:
        balance = balances[entry["layer_id"]]
        PuskesmasExpiryLine.objects.create(revision=revision, layer=balance.layer,
            quantity=entry["quantity"], unit_price=balance.layer.unit_price)
        PuskesmasInventoryMovement.objects.create(posting=posting, layer=balance.layer,
            quantity_delta=-entry["quantity"], unit_price=balance.layer.unit_price)
        _change_balance(balance, -entry["quantity"])
    if consumption_revision:
        _post_revision_locked(consumption=consumption, user=user, data=snapshot(consumption),
            reason=f"Rekalkulasi akibat kedaluwarsa #{document.pk} revisi {revision.number}.",
            expiry_revision=revision, restored_previous=True)
    from .inventory_reporting import sync_inventory_lplpo
    for lplpo in affected_lplpo.filter(inventory_binding__isnull=False).order_by("tahun", "bulan", "pk"):
        sync_inventory_lplpo(lplpo)
    details = {"expiry_id": document.pk, "revision": revision.number,
        "facility_id": facility.pk, "actor_id": user.pk, "event": "VOID" if void else "CORRECT" if previous else "POST"}
    transaction.on_commit(lambda: logger.info("puskesmas_expiry_revision", extra=details))
    return revision
