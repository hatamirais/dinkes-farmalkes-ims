"""Shared exact layer accounting for inventory HTML/print/XLSX and enrolled LPLPO."""
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.core.decimal_validation import multiply_decimals, sum_decimals
from apps.lplpo.models import LPLPO, LPLPOItem
from .inventory_models import (
    PuskesmasConsumptionRevision, PuskesmasInventoryAccount,
    PuskesmasInventoryMovement, PuskesmasOpeningVerification,
    PuskesmasLPLPOInventoryBinding,
)


def period_rows(facility_ids, year, month, start_month=None):
    from .consumption_inventory import month_end
    start, end = date(year, start_month or month, 1), month_end(year, month)
    if start > end:
        raise ValidationError("Bulan awal harus sebelum atau sama dengan bulan batas.")
    rows = {}
    layers = {}
    accounts = list(PuskesmasInventoryAccount.objects.filter(facility_id__in=facility_ids,
        effective_date__lte=start).select_related("facility"))
    covered_ids = [account.facility_id for account in accounts]
    movements = PuskesmasInventoryMovement.objects.filter(
        posting__facility_id__in=covered_ids, posting__effective_date__lte=end
    ).select_related("posting", "layer__item__satuan", "layer__item__kategori", "layer__posting", "layer__sumber_dana").order_by("pk")
    for movement in movements:
        layer, posting = movement.layer, movement.posting
        key = (posting.facility_id, layer.item_id)
        if key not in rows:
            rows[key] = dict(facility_id=key[0], item=layer.item,
                **{f"{kind}_{unit}": Decimal(0) for kind in ("opening", "receipts", "consumption", "closing")
                   for unit in ("quantity", "value")}, layers=[])
        row = rows[key]
        quantity = movement.quantity_delta
        value = multiply_decimals(quantity, movement.unit_price)
        # Initial Jan-1 verification is the boundary, never January receipt income.
        if posting.effective_date < start or (posting.opening_id and posting.effective_date == start):
            kind, sign = "opening", 1
        elif posting.receipt_id:
            kind, sign = "receipts", 1
        else:
            kind, sign = "consumption", -1
        row[f"{kind}_quantity"] += sign * quantity
        row[f"{kind}_value"] = sum_decimals([row[f"{kind}_value"], multiply_decimals(sign, value)])
        row["closing_quantity"] += quantity
        row["closing_value"] = sum_decimals([row["closing_value"], value])
        if layer.pk not in layers:
            detail = {"layer": layer, "quantity": Decimal(0), "value": Decimal(0)}
            layers[layer.pk] = detail
            row["layers"].append(detail)
        layers[layer.pk]["quantity"] += quantity
        layers[layer.pk]["value"] = sum_decimals([layers[layer.pk]["value"], value])
    return sorted(rows.values(), key=lambda row: (row["item"].nama_barang, row["facility_id"])), accounts


def category_totals(rows):
    categories = {}
    for row in rows:
        category = row["item"].kategori
        name = category.name if category else "Lainnya"
        totals = categories.setdefault(name, {"name": name, **{
            f"{kind}_value": Decimal(0) for kind in ("opening", "receipts", "consumption", "closing")}})
        for kind in ("opening", "receipts", "consumption", "closing"):
            key = f"{kind}_value"
            totals[key] = sum_decimals([totals[key], row[key]])
    return list(categories.values())


def lplpo_values(lplpo):
    return [{key: str(value) if isinstance(value, Decimal) else value
             for key, value in row.items()} for row in lplpo.items.order_by("item_id").values(
        "item_id", "stock_awal", "penerimaan", "pemakaian", "harga_satuan", "stock_keseluruhan")]


def adoption_digest(lplpo):
    import hashlib
    import json
    return hashlib.sha256(json.dumps([lplpo.pk, lplpo.status, lplpo_values(lplpo)],
                                    sort_keys=True).encode()).hexdigest()


@transaction.atomic
def adopt_opening(*, user, lplpo_id, digest):
    from apps.users.access import has_module_scope
    from apps.users.models import ModuleAccess
    from django.core.exceptions import PermissionDenied
    from .consumption_inventory import assert_operator, assert_period_mutable
    from .inventory import locked_actor, lock_facility
    user = locked_actor(user)
    facility_id = LPLPO.objects.values_list("facility_id", flat=True).get(pk=lplpo_id)
    facility = lock_facility(facility_id)
    assert_operator(user, facility, permission="lplpo.change_lplpo", module=ModuleAccess.Module.LPLPO)
    if not user.is_superuser and not has_module_scope(user, ModuleAccess.Module.LPLPO, ModuleAccess.Scope.OPERATE):
        raise PermissionDenied
    if not (user.is_superuser or user.has_perm("lplpo.change_lplpo") or has_module_scope(
            user, ModuleAccess.Module.LPLPO, ModuleAccess.Scope.OPERATE)):
        raise PermissionDenied
    lplpo = LPLPO.objects.select_for_update().get(pk=lplpo_id)
    if lplpo.status not in {LPLPO.Status.DRAFT, LPLPO.Status.REJECTED_PUSKESMAS}:
        raise ValidationError("LPLPO harus dikembalikan melalui alur berwenang sebelum adopsi.")
    if hasattr(lplpo, "inventory_binding"):
        return lplpo.inventory_binding
    if adoption_digest(lplpo) != digest:
        raise ValidationError("Isi LPLPO berubah. Muat ulang perbandingan.")
    if PuskesmasConsumptionRevision.objects.filter(consumption__facility=facility,
            effective_date__gt=date(lplpo.tahun, lplpo.bulan, 1)).exclude(
            consumption__tahun=lplpo.tahun, consumption__bulan=lplpo.bulan).exists():
        raise ValidationError("Ada periode berikutnya yang sudah difinalisasi.")
    opening = PuskesmasOpeningVerification.objects.filter(facility=facility, year=lplpo.tahun,
                                                          status="POSTED").first()
    if not opening or lplpo.bulan != 1:
        raise ValidationError("Adopsi pertama memerlukan saldo awal Januari terverifikasi untuk tahun yang sama.")
    previous = lplpo_values(lplpo)
    binding = PuskesmasLPLPOInventoryBinding.objects.create(lplpo=lplpo, opening=opening,
        previous_values=previous, actor=user)
    # Clear the reverse OneToOne cache populated by hasattr before creation.
    lplpo._state.fields_cache.pop("inventory_binding", None)
    sync_inventory_lplpo(lplpo)
    from .consumption_inventory import logger
    logger.info("puskesmas_lplpo_opening_adopted", extra={"binding_id": binding.pk,
        "lplpo_id": lplpo.pk, "actor_id": user.pk, "facility_id": facility.pk})
    return binding


def sync_inventory_lplpo(lplpo):
    """Caller owns facility lock. No form values or average price drive accounting."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("Inventory LPLPO synchronization requires a transaction.")
    if not hasattr(lplpo, "inventory_binding"):
        return
    lplpo = LPLPO.objects.select_for_update().get(pk=lplpo.pk)
    if lplpo.status not in {LPLPO.Status.DRAFT, LPLPO.Status.REJECTED_PUSKESMAS}:
        raise ValidationError("LPLPO sudah diajukan; perlu pengembalian berwenang.")
    rows, _ = period_rows([lplpo.facility_id], lplpo.tahun, lplpo.bulan)
    by_item = {row["item"].pk: row for row in rows}
    existing = {line.item_id: line for line in lplpo.items.all()}
    updated = []
    for item_id in set(existing) | set(by_item):
        row = by_item.get(item_id)
        line = existing.get(item_id) or LPLPOItem(lplpo=lplpo, item_id=item_id)
        line.stock_awal = int(row["opening_quantity"]) if row else 0
        line.penerimaan = int(row["receipts_quantity"]) if row else 0
        line.pemakaian = int(row["consumption_quantity"]) if row else 0
        line.penerimaan_auto_filled = True
        line.compute_fields()
        if line.pk:
            updated.append(line)
        else:
            line.save()
    if updated:
        LPLPOItem.objects.bulk_update(updated, ["stock_awal", "penerimaan", "pemakaian",
            "penerimaan_auto_filled", "persediaan", "stock_keseluruhan", "stock_optimum", "jumlah_kebutuhan"])


def assert_inventory_submission(lplpo):
    if not hasattr(lplpo, "inventory_binding"):
        return
    from .consumption_inventory import require_expiry_integration, snapshot, snapshot_digest
    require_expiry_integration()
    from .models import PuskesmasConsumption
    consumption = PuskesmasConsumption.objects.filter(facility_id=lplpo.facility_id,
        tahun=lplpo.tahun, bulan=lplpo.bulan).first()
    revision = consumption.inventory_revisions.order_by("-number").first() if consumption else None
    if not revision or revision.digest != snapshot_digest(consumption, snapshot(consumption)):
        raise ValidationError("Finalisasi pemakaian bulan ini harus diselesaikan sebelum LPLPO diajukan.")
    sync_inventory_lplpo(lplpo)
