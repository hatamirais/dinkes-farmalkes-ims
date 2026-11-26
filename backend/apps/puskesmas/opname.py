"""Monthly facility count and cutoff comparison."""
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.decimal_validation import multiply_decimals
from apps.items.models import Item
from apps.users.access import has_module_scope
from apps.users.models import ModuleAccess, User
from .consumption_inventory import latest_revision, month_end, snapshot, snapshot_digest
from .inventory import lock_facility, locked_actor, text_value
from .inventory_models import (
    PuskesmasConsumptionRevision, PuskesmasInventoryAccount, PuskesmasInventoryLayer,
    PuskesmasInventoryMovement, PuskesmasOpeningVerification,
)
from .models import PuskesmasConsumption, PuskesmasReceiptConfirmation, PuskesmasSubunit
from .opname_models import FacilityOpname, OpnameAuthority, OpnameCaseNote, OpnameRevision

WAREHOUSE = "warehouse"
MAX_QUANTITY = 2147483647
EDITABLE_LPLPO_STATUSES = ("DRAFT", "REJECTED_PUSKESMAS")
CONDITIONS = {"": "Layak", "DAMAGED": "Rusak", "EXPIRED": "Kedaluwarsa", "HELD": "Dalam penyimpanan terpisah"}


def digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def required_text(value, limit=1000):
    result = text_value(value, limit)
    if not result:
        raise ValidationError("Alasan dan bukti yang diminta wajib diisi.")
    return result


def operator(user, facility_id):
    return (
        user.is_active and facility_id is not None and user.role == User.Role.PUSKESMAS and user.facility_id == facility_id
        and has_module_scope(user, ModuleAccess.Module.PUSKESMAS, ModuleAccess.Scope.OPERATE)
    )


def authority(user, facility_id, action, *, lock=False):
    if not user.is_active:
        return False
    grants = OpnameAuthority.objects.filter(user=user, facility_id=facility_id, **{action: True})
    if lock:
        grants = grants.select_for_update()
    if action == "review_count":
        return user.role == User.Role.GUDANG and grants.exists()
    return has_module_scope(user, ModuleAccess.Module.LPLPO, ModuleAccess.Scope.OPERATE) and grants.exists()


def visible_counts(user):
    if not user.is_active:
        return FacilityOpname.objects.none()
    facility_ids = set()
    if operator(user, user.facility_id):
        facility_ids.add(user.facility_id)
    grants = OpnameAuthority.objects.filter(user=user)
    if user.role == User.Role.GUDANG:
        facility_ids.update(grants.filter(review_count=True).values_list("facility_id", flat=True))
    if has_module_scope(user, ModuleAccess.Module.LPLPO, ModuleAccess.Scope.OPERATE):
        from django.db.models import Q
        facility_ids.update(grants.filter(
            Q(approve_adjustment=True) | Q(correct_receipt=True) | Q(reopen_count=True)
        ).values_list("facility_id", flat=True))
    return FacilityOpname.objects.filter(facility_id__in=facility_ids)


def cutoff_snapshot(facility_id, cutoff):
    """Compare the dated journal with its live projection and report coverage separately."""
    account = PuskesmasInventoryAccount.objects.filter(facility_id=facility_id, effective_date__lte=cutoff).first()
    opening = PuskesmasOpeningVerification.objects.filter(facility_id=facility_id, status="POSTED").first() if account else None
    barriers = []
    if not opening:
        return {"opening": None, "layers": [], "barriers": ["Saldo awal terverifikasi belum tersedia."],
                "digest": digest([facility_id, cutoff.isoformat(), "no-opening"]), "usage": None}
    latest_use = {}
    for year, month, revision_id in PuskesmasConsumptionRevision.objects.filter(
        consumption__facility_id=facility_id, effective_date__lte=cutoff,
        effective_date__gte=account.effective_date,
    ).order_by("number").values_list("consumption__tahun", "consumption__bulan", "pk"):
        latest_use[(year, month)] = revision_id
    first = account.effective_date.year * 12 + account.effective_date.month
    end = cutoff.year * 12 + cutoff.month
    if len(latest_use) != end - first + 1:
        barriers.append("Finalisasi pemakaian belum lengkap sampai akhir bulan, termasuk pemakaian nihil.")
    use = PuskesmasConsumption.objects.filter(facility_id=facility_id, tahun=cutoff.year, bulan=cutoff.month).first()
    used = snapshot(use) if use else None
    revision = latest_revision(use) if use else None
    if use and revision and revision.digest != snapshot_digest(use, used):
        barriers.append("Finalisasi pemakaian tidak sesuai dengan rincian saat ini.")
    receipts = PuskesmasReceiptConfirmation.objects.filter(
        facility_id=facility_id, received_date__range=(account.effective_date, cutoff),
        inventory_posting__isnull=True,
    )
    if receipts.filter(status="CONFIRMED").exists():
        barriers.append("Ada penerimaan terkonfirmasi yang belum diposting.")
    if receipts.filter(status="DRAFT").exists():
        barriers.append("Ada draf penerimaan yang belum diselesaikan hingga tanggal batas.")
    layers = PuskesmasInventoryLayer.objects.filter(
        posting__facility_id=facility_id, posting__effective_date__lte=cutoff,
    ).select_related("balance", "item__satuan").order_by("pk")
    balances = {layer.pk: layer for layer in layers}
    moves = PuskesmasInventoryMovement.objects.filter(layer_id__in=balances).order_by("pk").values_list(
        "pk", "layer_id", "quantity_delta", "posting__effective_date", "posting__facility_id",
    )
    live = defaultdict(Decimal)
    dated = defaultdict(Decimal)
    movement_ids = []
    for pk, layer_id, quantity, effective, posting_facility in moves:
        live[layer_id] += quantity
        if effective <= cutoff:
            dated[layer_id] += quantity
            movement_ids.append(pk)
        if posting_facility != facility_id:
            barriers.append("Ada mutasi dengan fasilitas berbeda dari lapisan.")
    if any(not hasattr(layer, "balance") or layer.balance.quantity != live[layer.pk]
           or dated[layer.pk] < 0 for layer in balances.values()):
        barriers.append("Saldo lapisan tidak sesuai dengan jurnal.")
    expected = []
    for layer in balances.values():
        price = layer.unit_price
        expected.append({
            "layer": layer.pk, "item": layer.item_id, "name": layer.item.nama_barang,
            "unit": layer.item.satuan.name, "batch": layer.batch_lot,
            "expiry": layer.expiry_date.isoformat() if layer.expiry_date else "",
            "funding": layer.sumber_dana_id, "source": layer.source_document_number,
            "quantity": str(dated[layer.pk]), "price": str(price),
            "value": str(multiply_decimals(dated[layer.pk], price)),
        })
    return {
        "opening": opening.pk, "layers": expected, "barriers": list(dict.fromkeys(barriers)),
        "digest": digest([opening.pk, movement_ids, sorted(latest_use.values())]),
        "usage": {"reported": used, "revision": revision.pk if revision else None},
    }


def group_key(row):
    return row["item"], row["batch"], row["expiry"]


def revision_roster(count, revision):
    return revision.comparison.get("roster", count.roster)


def compare(count, observations, journal=None, *, roster=None):
    journal = journal if journal is not None else cutoff_snapshot(count.facility_id, count.cutoff)
    roster = count.roster if roster is None else roster
    groups = {}
    by_layer = {row["layer"]: row for row in journal["layers"]}

    def row_for(row):
        key = group_key(row)
        return groups.setdefault(key, dict(key=digest(key), item=row["item"], name=row["name"],
            unit=row["unit"], batch=row["batch"], expiry=row["expiry"], expected=Decimal(0),
            physical=Decimal(0), layers=[], attributed=defaultdict(Decimal), unattached=Decimal(0),
            damaged=0, damaged_by_layer=defaultdict(int)))

    warehouse = defaultdict(int)
    for layer in journal["layers"]:
        row = row_for(layer)
        row["expected"] += Decimal(layer["quantity"])
        if Decimal(layer["quantity"]):
            row["layers"].append(layer["layer"])
    for key, location in observations.items():
        for line in location["lines"]:
            row = row_for(line)
            quantity = line["cutoff_quantity"] if not line["excluded_posting"] else 0
            row["physical"] += quantity
            if key == WAREHOUSE:
                warehouse[str(line["item"])] += quantity
            if line["layer"]:
                row["attributed"][line["layer"]] += quantity
            else:
                row["unattached"] += quantity
            if line.get("condition") == "DAMAGED" and quantity:
                row["damaged"] += quantity
                if line["layer"]:
                    row["damaged_by_layer"][str(line["layer"])] += quantity
    for row in groups.values():
        row["delta"] = row["physical"] - row["expected"]
        row["attribution_limited"] = len(row["layers"]) > 1 and row["unattached"] > 0
        row["layer_mismatch"] = any(
            layer not in by_layer or quantity > Decimal(by_layer[layer]["quantity"])
            for layer, quantity in row["attributed"].items() if quantity
        )
        row["open"] = bool(row["delta"] or row["layer_mismatch"] or row["damaged"])
        row.update({key: str(row[key]) for key in ("physical", "expected", "delta")})
        del row["attributed"], row["unattached"]
    pending = [location["name"] for location in roster
               if not observations.get(location["key"], {}).get("confirmed")]
    barriers = journal["barriers"][:]
    if pending:
        barriers.append("Lokasi belum dikonfirmasi: " + ", ".join(pending))
    if count.cutoff >= timezone.localdate():
        barriers.append("Rekonsiliasi dapat ditutup setelah akhir hari terakhir bulan.")
    if any(quantity > MAX_QUANTITY for quantity in warehouse.values()):
        barriers.append("Jumlah fisik gudang melampaui kapasitas LPLPO.")
    excluded = defaultdict(int)
    for observation in observations.values():
        for line in observation["lines"]:
            if line["excluded_posting"]:
                excluded[(line["excluded_posting"], line["layer"])] += line["cutoff_quantity"]
    for (posting_id, layer_id), quantity in excluded.items():
        movement = PuskesmasInventoryMovement.objects.filter(
            posting_id=posting_id, layer_id=layer_id, posting__facility_id=count.facility_id,
            posting__effective_date__lte=count.cutoff, posting__reversal__isnull=True, quantity_delta__lt=0,
        ).select_related("posting__opname_action").first()
        if not movement or quantity > -movement.quantity_delta or not (
            movement.posting.expiry_revision_id or (
                movement.posting.opname_action_id and movement.posting.opname_action.kind == "ADJUST"
            )
        ):
            barriers.append("Bukti penarikan untuk stok yang masih disimpan tidak sah atau tidak mencukupi.")
            break
    return {
        **journal, "barriers": barriers, "warehouse": dict(warehouse), "roster": roster,
        "rows": sorted(groups.values(), key=lambda row: (row["name"], row["batch"], row["expiry"])),
    }


def current_revision(count):
    return count.revisions.order_by("-number").first()


def compare_revision(count, revision):
    return compare(count, revision.observations, roster=revision_roster(count, revision))


def save_revision(count, previous, actor, observations, comparison, state, reason=""):
    return OpnameRevision.objects.create(count=count, number=previous.number + 1 if previous else 1,
        actor=actor, actor_label=(actor.get_full_name() or actor.get_username())[:255],
        observations=observations, comparison=comparison, state=state, reason=reason)


def lock_count(user, count_id, expected_revision=None):
    actor = locked_actor(user)
    count = visible_counts(actor).filter(pk=count_id).first()
    if not count:
        raise PermissionDenied
    lock_facility(count.facility_id)
    count = FacilityOpname.objects.select_for_update().get(pk=count_id)
    revision = current_revision(count)
    if expected_revision is not None and (not revision or revision.pk != expected_revision):
        raise ValidationError("Hitungan telah berubah. Muat ulang sebelum melanjutkan.")
    return actor, count, revision


@transaction.atomic
def start_count(*, user, year, month, inactive_ids=()):
    actor = locked_actor(user)
    if not operator(actor, actor.facility_id) or not actor.facility_id:
        raise PermissionDenied
    facility = lock_facility(actor.facility_id)
    cutoff = month_end(year, month)
    today = timezone.localdate()
    if (year, month) > (today.year, today.month):
        raise ValidationError("Periode hitung belum dimulai.")
    existing = FacilityOpname.objects.filter(facility=facility, cutoff=cutoff).first()
    if existing:
        return existing
    inactive_ids = set(inactive_ids)
    subunits = list(PuskesmasSubunit.objects.filter(facility=facility).order_by("sort_order", "pk"))
    if inactive_ids - {subunit.pk for subunit in subunits if not subunit.is_active}:
        raise ValidationError("Lokasi nonaktif tidak valid.")
    roster = [{"key": WAREHOUSE, "name": "Gudang Puskesmas"}]
    roster += [{"key": str(subunit.pk), "name": subunit.name, "type": subunit.subunit_type}
               for subunit in subunits if subunit.is_active or subunit.pk in inactive_ids]
    count = FacilityOpname.objects.create(facility=facility, cutoff=cutoff, roster=roster,
        initial_comparison=cutoff_snapshot(facility.pk, cutoff), created_by=actor)
    save_revision(count, None, actor, {}, compare(count, {}, count.initial_comparison), OpnameRevision.State.COUNTING)
    return count


@transaction.atomic
def save_location(*, user, count_id, expected_revision, location_key, counted_at, evidence, lines, confirmed):
    actor, count, previous = lock_count(user, count_id, expected_revision)
    if not operator(actor, count.facility_id):
        raise PermissionDenied
    if previous.state != OpnameRevision.State.COUNTING:
        raise ValidationError("Revisi ini telah ditutup. Ajukan pembukaan ulang untuk mengubah hitungan.")
    roster = revision_roster(count, previous)
    if location_key not in {location["key"] for location in roster}:
        raise ValidationError("Lokasi di luar cakupan hitung.")
    if not isinstance(counted_at, datetime) or timezone.is_naive(counted_at) or counted_at > timezone.now():
        raise ValidationError("Waktu penghitungan aktual diperlukan.")
    cutoff_boundary = timezone.make_aware(datetime.combine(count.cutoff + timedelta(days=1), time.min))
    evidence = text_value(evidence, 1000)
    if confirmed and counted_at != cutoff_boundary and not evidence:
        raise ValidationError("Catat bukti penyesuaian mutasi atau konfirmasi tidak ada mutasi sampai batas bulan.")
    items = Item.objects.select_related("satuan").in_bulk({line["item"] for line in lines})
    source_layers = PuskesmasInventoryLayer.objects.filter(
        pk__in=[line.get("layer") for line in lines], posting__facility_id=count.facility_id,
        posting__effective_date__lte=count.cutoff,
    ).in_bulk()
    clean = []
    for line in lines:
        item = items.get(line["item"])
        batch = text_value(line.get("batch"), 100)
        expiry = line.get("expiry")
        if not item or (item.requires_expiry_date and not expiry):
            raise ValidationError("Barang atau tanggal kedaluwarsa tidak lengkap.")
        if expiry and (type(expiry) is not date or not 1000 <= expiry.year <= 9999):
            raise ValidationError("Tanggal kedaluwarsa tidak valid.")
        layer = source_layers.get(line.get("layer"))
        if line.get("layer") and (not layer or (layer.item_id, layer.batch_lot, layer.expiry_date) != (item.pk, batch, expiry)):
            raise ValidationError("Lapisan tidak sesuai dengan barang, batch, kedaluwarsa atau fasilitas.")
        observed = line["observed"]
        factor = Decimal(1) if line.get("factor") is None else line["factor"]
        delta = line.get("delta") or 0
        unit = text_value(line.get("observed_unit"), 100)
        conversion = text_value(line.get("conversion"), 255)
        if not isinstance(factor, Decimal) or not factor.is_finite() or factor <= 0:
            raise ValidationError("Konversi satuan tidak valid.")
        if type(observed) is not int or type(delta) is not int or not 0 <= observed <= MAX_QUANTITY:
            raise ValidationError("Jumlah hasil hitung harus bilangan bulat nonnegatif.")
        converted = multiply_decimals(observed, factor)
        quantity = converted + delta
        if converted != converted.to_integral_value() or not 0 <= quantity <= MAX_QUANTITY:
            raise ValidationError("Jumlah hitung pada tanggal batas harus bilangan bulat nonnegatif.")
        if (factor != 1 or (unit and unit != item.satuan.name)) and (not unit or not conversion):
            raise ValidationError("Satuan pengamatan dan bukti konversi wajib diisi.")
        movement_evidence = text_value(line.get("movement_evidence"), 255)
        if delta and (not movement_evidence or counted_at == cutoff_boundary):
            raise ValidationError("Selisih waktu hitung harus didukung bukti mutasi.")
        excluded = line.get("excluded_posting")
        condition = text_value(line.get("condition"), 255)
        if condition not in CONDITIONS:
            raise ValidationError("Kondisi stok tidak valid.")
        if excluded and (not layer or not condition):
            raise ValidationError("Stok ditarik yang masih disimpan memerlukan lapisan dan kondisi fisik.")
        clean.append({
            "item": item.pk, "name": item.nama_barang, "unit": item.satuan.name,
            "batch": batch, "expiry": expiry.isoformat() if expiry else "", "layer": layer.pk if layer else None,
            "observed": observed, "observed_unit": unit or item.satuan.name, "factor": str(factor),
            "conversion": conversion, "delta": delta, "movement_evidence": movement_evidence,
            "condition": condition, "condition_label": CONDITIONS[condition], "excluded_posting": excluded,
            "cutoff_quantity": int(quantity),
        })
    observations = {**previous.observations, location_key: dict(
        confirmed=confirmed, counted_at=counted_at.isoformat(), evidence=evidence, lines=clean)}
    return save_revision(count, previous, actor, observations, compare(count, observations, roster=roster),
                         OpnameRevision.State.COUNTING)


@transaction.atomic
def close_count(*, user, count_id, expected_revision, expected_journal):
    actor, count, previous = lock_count(user, count_id, expected_revision)
    comparison = compare_revision(count, previous)
    if comparison["digest"] != expected_journal:
        raise ValidationError("Jurnal berubah. Tinjau perbandingan terbaru sebelum menutup hitungan.")
    if comparison["barriers"]:
        raise ValidationError(comparison["barriers"])
    if previous.state == OpnameRevision.State.RECONCILED and previous.comparison["digest"] == expected_journal:
        return previous
    has_cases = any(row["open"] for row in comparison["rows"])
    if has_cases:
        if actor.pk == count.created_by_id or not authority(actor, count.facility_id, "review_count", lock=True):
            raise PermissionDenied("Selisih terbuka hanya dapat ditutup oleh peninjau Gudang yang ditugaskan.")
    elif not operator(actor, count.facility_id):
        raise PermissionDenied
    state = OpnameRevision.State.CLOSED_OPEN if has_cases else OpnameRevision.State.RECONCILED
    if previous.state == state and previous.comparison == comparison:
        return previous
    return save_revision(count, previous, actor, previous.observations, comparison, state)


@transaction.atomic
def add_case_evidence(*, user, count_id, expected_revision, case_key, evidence):
    actor, count, previous = lock_count(user, count_id, expected_revision)
    if not (operator(actor, count.facility_id) or authority(actor, count.facility_id, "review_count", lock=True)):
        raise PermissionDenied
    if not any(row["key"] == case_key and row["open"] for row in compare_revision(count, previous)["rows"]):
        raise ValidationError("Selisih tidak ditemukan dalam perbandingan saat ini.")
    return OpnameCaseNote.objects.create(count=count, revision=previous, case_key=case_key,
                                         evidence=required_text(evidence), actor=actor)
