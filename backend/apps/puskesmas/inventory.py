"""Explicit, facility-serialized inventory checkpoints; no consumption posting."""
import csv
import hashlib
import io
import logging
import json
import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from itertools import islice
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.utils import timezone

from apps.core.decimal_validation import (
    PRICE_MAX_DIGITS, PRICE_DECIMAL_PLACES, validate_decimal_precision,
)
from apps.core.csv_exports import escape_csv_formula
from django.db.models import Q
from apps.items.models import Facility, FundingSource, Item
from apps.users.access import has_module_scope, is_super_admin
from apps.users.models import ModuleAccess, User
from .models import (
    PuskesmasInventoryAccount, PuskesmasInventoryPosting,
    PuskesmasInventoryLayer, PuskesmasInventoryBalance, PuskesmasInventoryMovement,
    PuskesmasOpeningVerification, PuskesmasOpeningVerificationLine,
    PuskesmasReceiptConfirmation,
)

HEADERS = (
    "line_key", "item_code", "quantity", "unit_price", "batch_lot", "expiry_date",
    "sumber_dana_code", "source_document_number", "provenance_note",
)
LEGACY_WORKSHEET_HEADERS = HEADERS[:2] + ("item_name", "unit") + HEADERS[2:]
WORKSHEET_HEADERS = tuple(field for field in LEGACY_WORKSHEET_HEADERS if field != "source_document_number")
MAX_ROWS = 10000
MAX_BYTES = 5 * 1024 * 1024
logger = logging.getLogger(__name__)


def text_value(value, limit):
    value = unicodedata.normalize("NFC", str(value or "")).strip()
    if "\x00" in value or len(value) > limit:
        raise ValidationError(f"Teks mengandung null byte atau melebihi {limit} karakter.")
    return value


def decimal_value(value, *, price=False):
    try:
        number = str(value).strip()
        if price:
            number = number.removeprefix("'")
        result = Decimal(number.replace(",", "."))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError("Angka tidak valid.") from exc
    if not result.is_finite():
        raise ValidationError("NaN dan Infinity tidak diperbolehkan.")
    validate_decimal_precision(result, max_digits=PRICE_MAX_DIGITS if price else 12,
                               decimal_places=PRICE_DECIMAL_PLACES if price else 2)
    if result < 0 or (not price and (result <= 0 or result != result.to_integral_value())):
        raise ValidationError("Jumlah harus bilangan bulat positif; harga tidak boleh negatif.")
    return result


def can_verify(user):
    return bool(user.is_active and (user.is_superuser or (
        user.role == User.Role.GUDANG and has_module_scope(
            user, ModuleAccess.Module.LPLPO, ModuleAccess.Scope.OPERATE))))


def can_prepare(user):
    return bool(user.is_active and (user.is_superuser or (
        user.role == User.Role.PUSKESMAS and (
            user.has_perm("puskesmas.add_puskesmasopeningverification") or
            has_module_scope(user, ModuleAccess.Module.PUSKESMAS, ModuleAccess.Scope.OPERATE)))))


def can_inspect_openings(user):
    """Kepala oversight grants reads only, independently of posting authority."""
    return bool(user.is_active and user.role == User.Role.KEPALA and has_module_scope(
        user, ModuleAccess.Module.LPLPO, ModuleAccess.Scope.VIEW))


def pending_openings(user):
    """Only submitted openings this actor may independently review."""
    qs = PuskesmasOpeningVerification.objects.all()
    if not can_verify(user):
        return qs.none()
    return qs.filter(
        status=PuskesmasOpeningVerification.Status.SUBMITTED,
        facility__is_active=True,
        facility__facility_type=Facility.FacilityType.PUSKESMAS,
    ).exclude(created_by=user)


def opening_notification_queryset(user):
    """Reviewers get actionable work; Kepala gets read-only submitted notices."""
    if can_verify(user):
        return pending_openings(user)
    qs = PuskesmasOpeningVerification.objects.all()
    if can_inspect_openings(user):
        return qs.filter(status=PuskesmasOpeningVerification.Status.SUBMITTED,
                         facility__is_active=True, facility__facility_type=Facility.FacilityType.PUSKESMAS)
    return qs.none()


def locked_actor(user):
    actor = User.objects.select_for_update().get(pk=user.pk)
    list(ModuleAccess.objects.select_for_update().filter(user=actor).order_by("pk"))
    return actor


def lock_facility(facility_id):
    facility = Facility.objects.select_for_update().filter(pk=facility_id).first()
    if facility is None:
        raise ValidationError("Fasilitas tidak ditemukan.")
    if not facility.is_active or facility.facility_type != Facility.FacilityType.PUSKESMAS:
        raise ValidationError("Pilih fasilitas Puskesmas aktif.")
    return facility


def assert_preparer(user, facility):
    if not can_prepare(user) or (not user.is_superuser and user.facility_id != facility.pk):
        raise PermissionDenied("Saldo awal hanya dapat disiapkan untuk Puskesmas sendiri.")


def candidate_sources(*, facility_id, year):
    from apps.distribution.models import DistributionItem
    cutoff = date(year, 1, 1)
    return DistributionItem.objects.filter(
        distribution__facility_id=facility_id, distribution__status="DISTRIBUTED",
        distribution__distributed_date__lt=cutoff, item__is_active=True,
    ).exclude(
        Q(distribution__receipt_confirmation__status="CONFIRMED") &
        Q(distribution__receipt_confirmation__received_date__gte=cutoff)
    ).select_related("distribution", "item", "item__satuan", "issued_sumber_dana", "stock").order_by(
        "item__kode_barang", "distribution__distributed_date", "pk")


def source_snapshot(source):
    return dict(item=source.item, unit_price=source.issued_unit_price,
        batch_lot=source.issued_batch_lot or "", expiry_date=source.issued_expiry_date,
        sumber_dana=source.issued_sumber_dana,
        source_document_number=source.stock.source_document_number if source.stock_id else "")


def warehouse_candidates():
    from apps.stock.models import Stock
    # Zero quantities remain useful identities for stock still held at facilities.
    return Stock.objects.filter(item__is_active=True, sumber_dana__is_active=True).select_related(
        "item", "item__satuan", "sumber_dana").order_by("item__kode_barang", "pk")


def warehouse_snapshot(source):
    return dict(item=source.item, unit_price=source.unit_price, batch_lot=source.batch_lot,
                expiry_date=source.expiry_date, sumber_dana=source.sumber_dana,
                source_document_number=source.source_document_number)


def identity(snapshot):
    return (snapshot["item"].pk, snapshot["unit_price"], snapshot["batch_lot"],
            snapshot["expiry_date"], snapshot["sumber_dana"].pk if snapshot["sumber_dana"] else None,
            snapshot["source_document_number"])


def worksheet_text(value):
    """Preserve source codes and exact prices when spreadsheets open the CSV."""
    if re.fullmatch(r"[0-9][0-9.,eE+/\-: ]*", value):
        return f"'{value}"
    return escape_csv_formula(value)


def validate_identity_snapshot(line, snapshot):
    fields = ("item_id", "unit_price", "batch_lot", "expiry_date", "sumber_dana_id", "source_document_number")
    errors = []
    for field, expected in zip(fields, identity(snapshot)):
        actual = getattr(line, field)
        if actual != expected:
            errors.append(
                f"{field} pada {line.line_key} berbeda (pengajuan {str(actual)!r}, sumber {str(expected)!r}). "
                "Periksa nilai sumber atau unduh ulang template. Buka kolom kode dan batch sebagai Teks."
            )
    if errors:
        raise ValidationError(errors)


def worksheet_rows(*, facility_id, year):
    seen = set()
    for source in candidate_sources(facility_id=facility_id, year=year).iterator(chunk_size=500):
        snapshot = source_snapshot(source)
        seen.add(identity(snapshot))
        yield [f"DIST-{source.pk}", worksheet_text(source.item.kode_barang), source.item.nama_barang,
               source.item.satuan.name if source.item.satuan_id else "", "",
               worksheet_text(str(source.issued_unit_price)) if source.issued_unit_price is not None else "",
               worksheet_text(source.issued_batch_lot or ""), source.issued_expiry_date.isoformat() if source.issued_expiry_date else "",
               worksheet_text(source.issued_sumber_dana.code) if source.issued_sumber_dana_id else "",
               ""]
    for source in warehouse_candidates().iterator(chunk_size=500):
        snapshot = warehouse_snapshot(source)
        if identity(snapshot) in seen:
            continue
        seen.add(identity(snapshot))
        yield [f"STOCK-{source.pk}", worksheet_text(source.item.kode_barang), source.item.nama_barang,
               source.item.satuan.name if source.item.satuan_id else "", "", worksheet_text(str(source.unit_price)),
               worksheet_text(source.batch_lot), source.expiry_date.isoformat() if source.expiry_date else "",
               worksheet_text(source.sumber_dana.code), ""]


def validate_source_line(line, *, facility_id, year, lock=False):
    if line.source_stock_id:
        if line.source_distribution_item_id:
            raise ValidationError("Baris tidak boleh memiliki dua jenis sumber.")
        qs = warehouse_candidates()
        if lock:
            qs = qs.select_for_update(of=("self",))
        source = qs.filter(pk=line.source_stock_id).first()
        if source is None or line.line_key != f"STOCK-{source.pk}":
            raise ValidationError("Referensi identitas Instalasi Farmasi tidak valid.")
        validate_identity_snapshot(line, warehouse_snapshot(source))
        return
    if line.line_key.startswith("STOCK-"):
        raise ValidationError("Penanda STOCK- hanya untuk identitas Instalasi Farmasi dari template.")
    if not line.source_distribution_item_id:
        if line.line_key.startswith("DIST-"):
            raise ValidationError("Penanda DIST- hanya untuk baris distribusi dari template.")
        return
    qs = candidate_sources(facility_id=facility_id, year=year)
    if lock:
        qs = qs.select_for_update(of=("self",))
    source = qs.filter(pk=line.source_distribution_item_id).first()
    if source is None or line.line_key != f"DIST-{source.pk}":
        raise ValidationError("Baris sumber tidak sesuai Puskesmas/tahun saldo awal.")
    validate_identity_snapshot(line, source_snapshot(source))


def csv_reference_maps(raw_rows, *, facility_id, year):
    """Load selected-row references once per parse, with the usual scope filters."""
    source_ids = {"DIST": set(), "STOCK": set()}
    item_codes, funding_codes = set(), set()
    for raw in raw_rows:
        if None in raw or any(value is None for value in raw.values()) or not raw["quantity"].strip():
            continue
        try:
            key = text_value(raw["line_key"], 100)
            item_codes.add(text_value(raw["item_code"], 51))
            funding_codes.add(text_value(raw["sumber_dana_code"], 21))
        except ValidationError:
            # The normal row-validation pass reports malformed values with row numbers.
            continue
        prefix, _, raw_id = key.partition("-")
        if prefix in source_ids and raw_id.isascii() and raw_id.isdigit() and len(raw_id) <= 19:
            source_id = int(raw_id)
            if 0 < source_id <= 9223372036854775807:
                source_ids[prefix].add(source_id)
    distributions = {}
    if facility_id is not None and year is not None:
        distributions = candidate_sources(facility_id=facility_id, year=year).in_bulk(source_ids["DIST"])
    stocks = warehouse_candidates().in_bulk(source_ids["STOCK"])
    # Protected CSV text may differ from the original catalog code. Include the
    # actual linked source codes so the row pass can restore and resolve them.
    for source in distributions.values():
        item_codes.add(source.item.kode_barang)
        if source.issued_sumber_dana_id:
            funding_codes.add(source.issued_sumber_dana.code)
    for source in stocks.values():
        item_codes.add(source.item.kode_barang)
        funding_codes.add(source.sumber_dana.code)
    items = Item.objects.filter(is_active=True).in_bulk(item_codes, field_name="kode_barang")
    funding = FundingSource.objects.filter(is_active=True).in_bulk(funding_codes - {""}, field_name="code")
    return distributions, stocks, items, funding


def parse_csv(decoded, *, facility_id=None, year=None):
    if "\x00" in decoded:
        raise ValidationError("CSV mengandung null byte.")
    first = decoded.splitlines()[0] if decoded.splitlines() else ""
    reader = csv.DictReader(io.StringIO(decoded), delimiter=";" if first.count(";") > first.count(",") else ",", strict=True)
    try:
        fieldnames = reader.fieldnames
    except csv.Error as exc:
        raise ValidationError("Header CSV tidak valid.") from exc
    if fieldnames not in (list(HEADERS), list(LEGACY_WORKSHEET_HEADERS), list(WORKSHEET_HEADERS)):
        raise ValidationError("Header CSV harus sesuai template dan urutannya.")
    includes_source_document = "source_document_number" in fieldnames
    try:
        raw_rows = list(islice(reader, MAX_ROWS + 1))
    except csv.Error as exc:
        raise ValidationError("CSV tidak valid.") from exc
    if len(raw_rows) > MAX_ROWS:
        raise ValidationError(f"Maksimal {MAX_ROWS} baris.")
    distributions, stocks, items, funding_sources = csv_reference_maps(raw_rows, facility_id=facility_id, year=year)
    rows, keys, errors = [], set(), []
    try:
        for number, row in enumerate(raw_rows, start=2):
            try:
                if None in row or any(v is None for v in row.values()):
                    raise ValidationError("Jumlah kolom tidak sesuai.")
                limits = {"provenance_note": 1000, "item_code": 51, "item_name": 256, "unit": 101,
                          "sumber_dana_code": 21, "batch_lot": 101, "source_document_number": 101, "expiry_date": 10}
                row = {k: text_value(v, limits.get(k, 100)) for k, v in row.items()}
                row.setdefault("source_document_number", "")
                if not row["quantity"]:
                    continue
                key = row["line_key"] or f"MANUAL-{uuid4().hex}"
                if key in keys:
                    raise ValidationError("line_key tidak boleh duplikat.")
                keys.add(key)
                source = None
                stock_source = None
                if key.startswith("DIST-"):
                    if facility_id is None or year is None or not key[5:].isascii() or not key[5:].isdigit():
                        raise ValidationError("Baris DIST- memerlukan Puskesmas dan tahun yang sesuai.")
                    source = distributions.get(int(key[5:]))
                    if source is None or key != f"DIST-{source.pk}":
                        raise ValidationError("Baris sumber tidak sesuai Puskesmas/tahun saldo awal.")
                    originals = {"item_code": source.item.kode_barang, "batch_lot": source.issued_batch_lot or "",
                        "sumber_dana_code": source.issued_sumber_dana.code if source.issued_sumber_dana_id else "",
                        "source_document_number": source.stock.source_document_number if source.stock_id else ""}
                    if not includes_source_document:
                        row["source_document_number"] = originals["source_document_number"]
                    for field, original in originals.items():
                        if row[field] in (escape_csv_formula(original), worksheet_text(original)):
                            row[field] = original
                elif key.startswith("STOCK-"):
                    if facility_id is None or year is None or not key[6:].isascii() or not key[6:].isdigit():
                        raise ValidationError("Baris STOCK- memerlukan Puskesmas dan tahun saldo awal.")
                    stock_source = stocks.get(int(key[6:]))
                    if stock_source is None or key != f"STOCK-{stock_source.pk}":
                        raise ValidationError("Identitas Instalasi Farmasi tidak ditemukan atau tidak aktif.")
                    originals = {"item_code": stock_source.item.kode_barang, "batch_lot": stock_source.batch_lot,
                        "sumber_dana_code": stock_source.sumber_dana.code,
                        "source_document_number": stock_source.source_document_number}
                    if not includes_source_document:
                        row["source_document_number"] = originals["source_document_number"]
                    for field, original in originals.items():
                        if row[field] in (escape_csv_formula(original), worksheet_text(original)):
                            row[field] = original
                for field, limit in (("item_code", 50), ("batch_lot", 100), ("sumber_dana_code", 20), ("source_document_number", 100)):
                    text_value(row[field], limit)
                item = items.get(row["item_code"])
                if item is None:
                    raise Item.DoesNotExist
                funding = funding_sources.get(row["sumber_dana_code"]) if row["sumber_dana_code"] else None
                if row["sumber_dana_code"] and funding is None:
                    raise FundingSource.DoesNotExist
                expiry = date.fromisoformat(row["expiry_date"]) if row["expiry_date"] else None
                if expiry and not 1000 <= expiry.year <= 9999:
                    raise ValidationError("Tahun kedaluwarsa tidak valid.")
                # Keep the operator worksheet blank; record factual source provenance
                # internally when no operator note was supplied. This is not verification.
                if not row["provenance_note"] and (source or stock_source):
                    missing = [label for field, label in (("batch_lot", "batch"),
                        ("sumber_dana_code", "sumber dana"), ("source_document_number", "dokumen asal")) if not row[field]]
                    note = "Identitas dari Instalasi Farmasi; kepemilikan dan jumlah stok Puskesmas harus diverifikasi." if stock_source else ""
                    if missing:
                        note += (" " if note else "") + "Tidak tercatat pada sumber: " + ", ".join(missing) + "."
                    row["provenance_note"] = note
                if any(not row[k] for k in ("batch_lot", "sumber_dana_code", "source_document_number")) and not row["provenance_note"]:
                    raise ValidationError("Provenance yang tidak diketahui wajib dijelaskan pada provenance_note.")
                values = dict(line_key=key, item=item, quantity=decimal_value(row["quantity"]),
                    unit_price=decimal_value(row["unit_price"], price=True) if row["unit_price"] else None,
                    batch_lot=row["batch_lot"], expiry_date=expiry, sumber_dana=funding,
                    source_document_number=row["source_document_number"], provenance_note=row["provenance_note"],
                    source_distribution_item=source, source_stock=stock_source)
                line = PuskesmasOpeningVerificationLine(**values)
                if source:
                    validate_identity_snapshot(line, source_snapshot(source))
                elif stock_source:
                    validate_identity_snapshot(line, warehouse_snapshot(stock_source))
                rows.append(values)
            except (ValidationError, Item.DoesNotExist, FundingSource.DoesNotExist, ValueError) as exc:
                message = "; ".join(exc.messages) if isinstance(exc, ValidationError) else "Barang/sumber dana/tanggal tidak valid."
                errors.append(f"Baris {number}: {message}")
                if len(errors) >= 50:
                    break
    except csv.Error as exc:
        raise ValidationError("CSV tidak valid.") from exc
    if errors:
        raise ValidationError(errors)
    if not rows:
        raise ValidationError("CSV harus berisi setidaknya satu baris dengan jumlah stok positif. Baris quantity kosong dilewati.")
    return rows


def opening_digest(opening):
    lines = list(opening.lines.order_by("pk").values("line_key", "item_id", "quantity", "unit_price",
                "batch_lot", "expiry_date", "sumber_dana_id", "source_document_number", "provenance_note", "source_distribution_item_id", "source_stock_id"))
    # Keep historical digests stable for manually entered, unlinked documents.
    for line in lines:
        if line["source_distribution_item_id"] is None:
            del line["source_distribution_item_id"]
        if line["source_stock_id"] is None:
            del line["source_stock_id"]
    data = [opening.facility_id, opening.year, opening.reference, opening.notes, opening.zero_stock,
            lines]
    return hashlib.sha256(json.dumps(data, default=str, sort_keys=True).encode()).hexdigest()


def line_errors(line):
    errors = []
    if line.unit_price is None:
        errors.append("Harga asli belum diverifikasi.")
    else:
        decimal_value(line.unit_price, price=True)
    decimal_value(line.quantity)
    if not line.item.is_active:
        errors.append("Barang tidak aktif.")
    if line.item.requires_expiry_date and line.expiry_date is None:
        errors.append("Tanggal kedaluwarsa wajib diverifikasi.")
    if line.sumber_dana_id and not line.sumber_dana.is_active:
        errors.append("Sumber dana tidak aktif.")
    return errors


@transaction.atomic
def prepare_opening(*, user, facility_id, year, reference, notes, rows, zero_stock=False):
    user = locked_actor(user)
    facility = lock_facility(facility_id)
    assert_preparer(user, facility)
    if not 1000 <= year <= timezone.localdate().year:
        raise ValidationError("Tahun saldo awal tidak valid atau berada di masa depan.")
    if PuskesmasInventoryAccount.objects.filter(facility=facility).exists():
        raise ValidationError("Saldo awal pertama sudah diposting. Rekonsiliasi tahunan belum tersedia.")
    reference = text_value(reference, 100)
    if not reference:
        raise ValidationError("Referensi verifikasi wajib diisi.")
    if zero_stock or not rows:
        raise ValidationError("Saldo awal memerlukan setidaknya satu baris stok positif; pengajuan nihil tidak tersedia.")
    opening = PuskesmasOpeningVerification.objects.create(facility=facility, year=year,
        reference=reference, notes=text_value(notes, 1000), zero_stock=zero_stock,
        created_by=user, expires_at=timezone.now() + timedelta(hours=24))
    for row in rows:
        line = PuskesmasOpeningVerificationLine(opening=opening, **row)
        validate_source_line(line, facility_id=facility.pk, year=year, lock=True)
        line.full_clean()
        line.save()
    opening.digest = opening_digest(opening)
    opening.save(update_fields=["digest"])
    return opening


@transaction.atomic
def submit_opening(*, user, opening_id, digest):
    user = locked_actor(user)
    facility_id = PuskesmasOpeningVerification.objects.values_list("facility_id", flat=True).get(pk=opening_id)
    facility = lock_facility(facility_id)
    assert_preparer(user, facility)
    opening = PuskesmasOpeningVerification.objects.select_for_update().get(pk=opening_id)
    if opening.created_by_id != user.pk or opening.status != "DRAFT" or opening.expires_at <= timezone.now():
        raise ValidationError("Pratinjau kedaluwarsa atau bukan milik Anda. Unggah ulang.")
    if digest != opening.digest or opening_digest(opening) != digest:
        raise ValidationError("Isi pratinjau berubah. Unggah ulang.")
    if opening.zero_stock or not opening.lines.exists():
        raise ValidationError("Pengajuan harus memiliki setidaknya satu baris stok positif.")
    opening.status = "SUBMITTED"
    opening.submitted_at = timezone.now()
    opening.save(update_fields=["status", "submitted_at"])
    logger.info("puskesmas_opening_submitted", extra={"opening_id": opening.pk, "facility_id": facility.pk, "actor_id": user.pk})
    return opening


@transaction.atomic
def cancel_opening(*, user, opening_id, digest):
    user = locked_actor(user)
    facility_id = PuskesmasOpeningVerification.objects.values_list("facility_id", flat=True).get(pk=opening_id)
    facility = lock_facility(facility_id)
    assert_preparer(user, facility)
    opening = PuskesmasOpeningVerification.objects.select_for_update().get(pk=opening_id)
    if opening.created_by_id != user.pk:
        raise PermissionDenied("Hanya penyiap pratinjau yang dapat membatalkannya.")
    if digest != opening.digest or opening_digest(opening) != digest:
        raise ValidationError("Isi pratinjau berubah. Muat ulang halaman sebelum membatalkan.")
    if opening.status == "CANCELLED":
        return opening
    if opening.status != "DRAFT":
        raise ValidationError("Hanya pratinjau yang belum diajukan dapat dibatalkan.")
    opening.status = "CANCELLED"
    opening.cancelled_at = timezone.now()
    opening.cancelled_by = user
    opening.save(update_fields=["status", "cancelled_at", "cancelled_by"])
    logger.info("puskesmas_opening_cancelled", extra={"opening_id": opening.pk, "facility_id": facility.pk, "actor_id": user.pk})
    return opening


def _append_layer(posting, *, line, receipt=False, funding=None, source=""):
    layer = PuskesmasInventoryLayer(
        posting=posting, receipt_line=line if receipt else None,
        opening_line=None if receipt else line, item=line.item,
        batch_lot=line.batch_lot, expiry_date=line.expiry_date, unit_price=line.unit_price,
        sumber_dana=funding if receipt else line.sumber_dana,
        source_document_number=source if receipt else line.source_document_number,
        provenance_note=line.notes if receipt else line.provenance_note)
    layer.full_clean()
    layer.save()
    PuskesmasInventoryBalance.objects.create(layer=layer, quantity=line.quantity)
    PuskesmasInventoryMovement.objects.create(posting=posting, layer=layer,
        quantity_delta=line.quantity, unit_price=layer.unit_price)


@transaction.atomic
def review_opening(*, user, opening_id, digest, reject_reason=None):
    user = locked_actor(user)
    if not can_verify(user):
        raise PermissionDenied("Verifikasi memerlukan Superuser atau GUDANG dengan akses LPLPO OPERATE.")
    facility_id = PuskesmasOpeningVerification.objects.values_list("facility_id", flat=True).get(pk=opening_id)
    facility = lock_facility(facility_id)
    opening = PuskesmasOpeningVerification.objects.select_for_update().get(pk=opening_id)
    if user.pk == opening.created_by_id:
        raise PermissionDenied("Penyiap tidak boleh memverifikasi pengajuannya sendiri.")
    if opening.digest != digest or opening_digest(opening) != digest:
        raise ValidationError("Isi dokumen berubah. Muat ulang tinjauan.")
    if opening.status == "POSTED" and reject_reason is None:
        return opening
    if opening.status != "SUBMITTED":
        raise ValidationError("Hanya pengajuan yang dapat diverifikasi.")
    if reject_reason is not None:
        reason = text_value(reject_reason, 1000)
        if not reason:
            raise ValidationError("Alasan penolakan wajib diisi.")
        models.QuerySet.update(PuskesmasOpeningVerification.objects.filter(pk=opening.pk),
            status="REJECTED", rejection_reason=reason, reviewed_by=user, reviewed_at=timezone.now())
        opening.refresh_from_db()
        logger.info("puskesmas_opening_rejected", extra={"opening_id": opening.pk, "facility_id": facility.pk, "actor_id": user.pk})
        return opening
    if PuskesmasInventoryAccount.objects.filter(facility=facility).exists():
        raise ValidationError("Saldo awal pertama sudah diposting. Rekonsiliasi tahunan ditunda.")
    lines = list(opening.lines.select_related("item", "sumber_dana").order_by("pk"))
    list(Item.objects.select_for_update().filter(pk__in=[line.item_id for line in lines]).order_by("pk"))
    list(FundingSource.objects.select_for_update().filter(pk__in=[line.sumber_dana_id for line in lines if line.sumber_dana_id]).order_by("pk"))
    # Reload catalog policy after acquiring its locks.
    lines = list(opening.lines.select_related("item", "sumber_dana").order_by("pk"))
    if not lines or opening.zero_stock:
        raise ValidationError("Rincian saldo awal kosong.")
    for line in lines:
        validate_source_line(line, facility_id=facility.pk, year=opening.year, lock=True)
        errors = line_errors(line)
        if errors:
            raise ValidationError([f"{line.line_key}: {error}" for error in errors])
    effective = date(opening.year, 1, 1)
    PuskesmasInventoryAccount.objects.create(facility=facility, effective_date=effective)
    posting = PuskesmasInventoryPosting.objects.create(facility=facility, opening=opening,
        effective_date=effective, actor=user, digest=digest)
    for line in lines:
        _append_layer(posting, line=line)
    # Existing confirmed receipts are real source records, never reconstructed layers.
    # Any unsupported source aborts the whole opening, with no partial inventory.
    for receipt in PuskesmasReceiptConfirmation.objects.select_for_update().filter(
            facility=facility, status="CONFIRMED", received_date__gte=effective).order_by("pk"):
        post_receipt(receipt=receipt, user=user)
    models.QuerySet.update(PuskesmasOpeningVerification.objects.filter(pk=opening.pk),
        status="POSTED", reviewed_by=user, reviewed_at=timezone.now())
    opening.refresh_from_db()
    logger.info("puskesmas_opening_posted", extra={"opening_id": opening.pk, "facility_id": facility.pk, "actor_id": user.pk})
    return opening


@transaction.atomic
def post_receipt(*, receipt, user):
    """Called only after checklist confirmation; also used by initial opening catch-up."""
    user = locked_actor(user)
    # Receipt administrators retain their existing authority; this does not grant
    # the separate, narrower initial-opening verification checkpoint.
    if not user.is_active or not (is_super_admin(user) or can_verify(user) or (
            user.role == User.Role.PUSKESMAS and user.facility_id == receipt.facility_id and
            (has_module_scope(user, ModuleAccess.Module.PUSKESMAS, ModuleAccess.Scope.OPERATE) or
             user.has_perm("puskesmas.change_puskesmasreceiptconfirmation") or
             user.has_perm("puskesmas.add_puskesmasreceiptconfirmation") or
             user.has_perm("puskesmas.change_puskesmassbbk") or
             user.has_perm("puskesmas.add_puskesmassbbk")))):
        raise PermissionDenied("Tidak berwenang memposting penerimaan fasilitas ini.")
    facility = lock_facility(receipt.facility_id)
    receipt = PuskesmasReceiptConfirmation.objects.select_for_update().get(pk=receipt.pk)
    account = PuskesmasInventoryAccount.objects.filter(facility=facility).first()
    if not account or receipt.received_date < account.effective_date or receipt.status != "CONFIRMED":
        return None
    existing = PuskesmasInventoryPosting.objects.filter(receipt=receipt).first()
    if existing:
        return existing
    from .inventory_models import PuskesmasConsumptionRevision
    if PuskesmasConsumptionRevision.objects.filter(consumption__facility=facility,
            effective_date__gte=receipt.received_date).exists():
        raise ValidationError("Tanggal penerimaan memengaruhi pemakaian yang sudah difinalisasi; perlu rekonsiliasi/pembukaan ulang.")
    if receipt.received_date > timezone.localdate() or not receipt.distribution_id:
        raise ValidationError("Penerimaan inventaris memerlukan tanggal aktual dan distribusi sumber.")
    from apps.distribution.models import Distribution, DistributionItem
    distribution = Distribution.objects.select_for_update().get(pk=receipt.distribution_id)
    if distribution.status != "DISTRIBUTED" or distribution.facility_id != facility.pk:
        raise ValidationError("Distribusi sumber belum selesai atau berbeda fasilitas.")
    sources = {row.pk: row for row in DistributionItem.objects.select_for_update().filter(
        distribution=distribution).order_by("pk")}
    lines = list(receipt.items.select_for_update(of=("self",)).select_related("item").order_by("pk"))
    list(Item.objects.select_for_update().filter(pk__in=[line.item_id for line in lines]).order_by("pk"))
    lines = list(receipt.items.select_related("item").order_by("pk"))
    if not sources or len(lines) != len(sources) or {line.distribution_item_id for line in lines} != set(sources):
        raise ValidationError("Rincian penerimaan harus lengkap dan terhubung ke setiap baris distribusi.")
    snapshots = []
    for line in lines:
        source = sources[line.distribution_item_id]
        quantity = source.quantity_approved if source.quantity_approved is not None else source.quantity_requested
        if source.issued_unit_price is None:
            raise ValidationError("Harga asli pada distribusi belum tersedia; tidak boleh dianggap nol.")
        decimal_value(line.quantity)
        decimal_value(source.issued_unit_price, price=True)
        if (line.item_id != source.item_id or line.quantity != quantity or
                line.unit_price != source.issued_unit_price or line.batch_lot != source.issued_batch_lot or
                line.expiry_date != source.issued_expiry_date):
            raise ValidationError("Rincian penerimaan berbeda dari snapshot distribusi.")
        if line.item.requires_expiry_date and line.expiry_date is None:
            raise ValidationError("Kedaluwarsa penerimaan wajib diverifikasi.")
        # The protected warehouse link carries source identity, never today's price.
        source_number = source.stock.source_document_number if source.stock_id else ""
        snapshots.append([line.pk, line.item_id, str(line.quantity), str(line.unit_price),
                          line.batch_lot, str(line.expiry_date), source.issued_sumber_dana_id, source_number])
    digest = hashlib.sha256(json.dumps([receipt.pk, str(receipt.received_date), snapshots]).encode()).hexdigest()
    posting = PuskesmasInventoryPosting.objects.create(facility=facility, receipt=receipt,
        effective_date=receipt.received_date, actor=user, digest=digest)
    for line in lines:
        source = sources[line.distribution_item_id]
        _append_layer(posting, line=line, receipt=True, funding=source.issued_sumber_dana,
                      source=source.stock.source_document_number if source.stock_id else "")
    logger.info("puskesmas_receipt_inventory_posted", extra={"receipt_id": receipt.pk, "posting_id": posting.pk, "facility_id": facility.pk, "actor_id": user.pk})
    return posting
