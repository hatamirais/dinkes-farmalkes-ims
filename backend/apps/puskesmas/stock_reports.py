"""Shared report source selection; legacy arithmetic retained outside inventory coverage."""
from decimal import Decimal
from datetime import date
import calendar
import logging
from django.db.models import Count, F, Sum, Value, Window
from django.db.models.functions import Coalesce, RowNumber
from apps.lplpo.models import LPLPO, LPLPOItem, format_lplpo_period_label, get_indonesian_month_name
from .models import PuskesmasReceiptConfirmation, PuskesmasReceiptConfirmationItem, PuskesmasConsumptionEntry
from apps.core.decimal_validation import multiply_decimals, sum_decimals
from apps.items.models import Item
from .inventory_reporting import KINDS, period_rows, category_totals
from .inventory_models import PuskesmasConsumptionRevision, PuskesmasOpeningVerification

logger = logging.getLogger(__name__)
USABLE_STATUSES = [LPLPO.Status.DRAFT, LPLPO.Status.SUBMITTED, LPLPO.Status.PIC_VERIFIED,
    LPLPO.Status.REVIEWED, LPLPO.Status.APPROVED, LPLPO.Status.DISTRIBUTED, LPLPO.Status.CLOSED]


def legacy_stock(scoped_facilities, year, end_month, *, is_aggregate):
    """Historical LPLPO baseline plus later receipts/use, unchanged arithmetic."""
    facility_ids = [facility.pk for facility in scoped_facilities]
    report_data = []
    # --- Dynamic stock calculation ---
    # For each facility, find the latest usable LPLPO in or before the requested
    # period, then apply only the canonical Puskesmas-side ledgers after it:
    # confirmed receipt confirmations minus detailed consumption.
    item_stock_map = {}

    latest_lplpos = (
        LPLPO.objects.filter(
            facility_id__in=facility_ids,
            tahun=year,
            status__in=USABLE_STATUSES,
            bulan__lte=end_month,
        )
        .annotate(
            latest_month=Window(
                expression=RowNumber(),
                partition_by=[F("facility_id")],
                order_by=F("bulan").desc(),
            )
        )
        .filter(latest_month=1)
    )
    latest_lplpo_by_facility = {
        lplpo.facility_id: lplpo for lplpo in latest_lplpos
    }
    latest_lplpo_ids = [lplpo.pk for lplpo in latest_lplpo_by_facility.values()]
    coverage_by_facility = {}
    for entry in scoped_facilities:
        baseline = latest_lplpo_by_facility.get(entry.pk)
        adjustment_period = ""
        if baseline:
            if baseline.bulan == end_month:
                adjustment_period = "Tidak ada bulan setelah baseline sampai batas laporan"
            else:
                adjustment_period = (
                    f"{get_indonesian_month_name(baseline.bulan + 1)}–"
                    f"{get_indonesian_month_name(end_month)} {year}"
                )
        coverage_by_facility[entry.pk] = {
            "facility_id": entry.pk,
            "facility_name": entry.name,
            "baseline_period": (
                format_lplpo_period_label(baseline.bulan, year) if baseline else ""
            ),
            "baseline_status": baseline.get_status_display() if baseline else "",
            "adjustment_period": adjustment_period,
            "receipt_row_count": 0,
            "consumption_row_count": 0,
        }

    if latest_lplpo_ids:
        lplpo_items = (
            LPLPOItem.objects.filter(lplpo_id__in=latest_lplpo_ids)
            .select_related("lplpo", "item", "item__satuan", "item__kategori")
            .order_by()
        )
        for li in lplpo_items:
            key = (
                li.lplpo.facility_id,
                li.item_id,
                li.item.nama_barang,
                li.item.satuan.name if li.item.satuan else "-",
                li.item.kategori.name if li.item.kategori else "Lainnya",
                li.item.kategori.sort_order if li.item.kategori else 9999,
            )
            item_stock_map[key] = item_stock_map.get(key, 0) + li.stock_keseluruhan

    baseline_facility_ids = list(latest_lplpo_by_facility.keys())
    if baseline_facility_ids:
        receipt_rows = (
            PuskesmasReceiptConfirmationItem.objects.filter(
                sbbk__facility_id__in=baseline_facility_ids,
                sbbk__received_date__year=year,
                sbbk__received_date__month__lte=end_month,
                sbbk__status=PuskesmasReceiptConfirmation.ReceiptStatus.CONFIRMED,
            )
            .values(
                "sbbk__facility_id",
                "sbbk__received_date__month",
                "item_id",
                "item__nama_barang",
                "item__satuan__name",
                "item__kategori__name",
                "item__kategori__sort_order",
            )
            .annotate(
                total_received=Coalesce(Sum("quantity"), Value(Decimal("0"))),
                entry_count=Count("pk"),
            )
            .order_by()
        )
        for receipt in receipt_rows:
            facility_id = receipt["sbbk__facility_id"]
            if receipt["sbbk__received_date__month"] <= latest_lplpo_by_facility[facility_id].bulan:
                continue
            coverage_by_facility[facility_id]["receipt_row_count"] += receipt["entry_count"]
            sort_order = receipt["item__kategori__sort_order"]
            key = (
                facility_id,
                receipt["item_id"],
                receipt["item__nama_barang"],
                receipt["item__satuan__name"] or "-",
                receipt["item__kategori__name"] or "Lainnya",
                9999 if sort_order is None else sort_order,
            )
            item_stock_map[key] = item_stock_map.get(key, 0) + int(
                (receipt["total_received"] or Decimal("0")).to_integral_value()
            )

        consumption_rows = (
            PuskesmasConsumptionEntry.objects.filter(
                consumption__facility_id__in=baseline_facility_ids,
                consumption__tahun=year,
                consumption__bulan__lte=end_month,
            )
            .values(
                "consumption__facility_id",
                "consumption__bulan",
                "item_id",
                "item__nama_barang",
                "item__satuan__name",
                "item__kategori__name",
                "item__kategori__sort_order",
            )
            .annotate(
                total_consumption=Coalesce(Sum("quantity"), Value(0)),
                entry_count=Count("pk"),
            )
            .order_by()
        )
        for consumption in consumption_rows:
            facility_id = consumption["consumption__facility_id"]
            if consumption["consumption__bulan"] <= latest_lplpo_by_facility[facility_id].bulan:
                continue
            coverage_by_facility[facility_id]["consumption_row_count"] += consumption["entry_count"]
            sort_order = consumption["item__kategori__sort_order"]
            key = (
                facility_id,
                consumption["item_id"],
                consumption["item__nama_barang"],
                consumption["item__satuan__name"] or "-",
                consumption["item__kategori__name"] or "Lainnya",
                9999 if sort_order is None else sort_order,
            )
            item_stock_map[key] = item_stock_map.get(key, 0) - int(
                consumption["total_consumption"] or 0
            )

    for missing_facility_id in set(facility_ids) - set(latest_lplpo_by_facility.keys()):
        logger.info(
            "puskesmas_report_persediaan: no usable LPLPO found for facility=%s year=%s month=%s; "
            "skipping stock calculation because no LPLPO baseline exists.",
            missing_facility_id,
            year,
            end_month,
        )

    aggregated_stock_map = {}
    for key, stock_qty in item_stock_map.items():
        _, item_id, nama_barang, satuan, kategori, sort_order = key
        output_key = (item_id, nama_barang, satuan, kategori, sort_order)
        aggregated_stock_map[output_key] = (
            aggregated_stock_map.get(output_key, 0) + stock_qty
        )

    # Build sorted report_data list
    for key, stock_qty in sorted(
        aggregated_stock_map.items(),
        key=lambda x: (x[0][4], x[0][3], x[0][1]),
    ):
        _, nama_barang, satuan, kategori, _ = key
        report_data.append({
            "nama_barang": nama_barang,
            "satuan": satuan,
            "kategori": kategori,
            "stock_keseluruhan": stock_qty,
        })

    report_metadata = {
        "source_description": (
            "Stok Akhir Digital = stok keseluruhan pada LPLPO terakhir yang dapat dipakai "
            "dalam tahun terpilih sampai bulan batas laporan + konfirmasi penerimaan "
            "CONFIRMED setelah bulan baseline − pemakaian rinci setelah bulan baseline. "
            "Penyesuaian hanya mencakup tahun yang sama sampai bulan batas laporan."
        ),
        "baseline_note": (
            "LPLPO Draft dapat menjadi baseline; LPLPO berstatus ditolak tidak digunakan. "
            "Periode menunjukkan posisi stok sampai akhir bulan batas, bukan mutasi "
            "hanya selama triwulan atau semester."
        ),
        "period_end_label": format_lplpo_period_label(end_month, year),
        "item_count": len(report_data),
        "negative_item_count": sum(row["stock_keseluruhan"] < 0 for row in report_data),
        "facility_count": len(scoped_facilities),
        "baseline_count": len(latest_lplpo_by_facility),
        "missing_baseline_count": len(scoped_facilities) - len(latest_lplpo_by_facility),
        "coverage": list(coverage_by_facility.values()),
        "is_aggregate": is_aggregate,
    }
    if not scoped_facilities:
        report_metadata["empty_message"] = (
            "Tidak ada Puskesmas aktif dalam cakupan laporan. Periksa filter fasilitas "
            "dan status aktif fasilitas."
        )
    elif not latest_lplpo_by_facility:
        report_metadata["empty_message"] = (
            "Belum ada baseline LPLPO yang dapat dipakai sampai bulan batas laporan "
            "pada tahun terpilih. Periksa periode dan status LPLPO fasilitas. "
            "Konfirmasi penerimaan dan pemakaian rinci saja tidak membentuk saldo "
            "tanpa baseline; hasil kosong tidak berarti stok nol."
        )
    elif not report_data:
        report_metadata["empty_message"] = (
            "Baseline LPLPO tersedia, tetapi tidak ada baris barang untuk ditampilkan. "
            "Periksa rincian barang LPLPO, konfirmasi penerimaan CONFIRMED, dan "
            "pemakaian rinci dalam rentang penyesuaian."
        )
    return item_stock_map, report_metadata


def _legacy_values(facility_ids, year, start_month, end_month):
    """Retain historical per-document prices; never invent original-price layers."""
    values = {}
    lines = LPLPOItem.objects.filter(lplpo__facility_id__in=facility_ids,
        lplpo__tahun=year, lplpo__bulan__gte=start_month, lplpo__bulan__lte=end_month,
        lplpo__status__in=USABLE_STATUSES).select_related("lplpo").order_by("lplpo__bulan", "pk")
    for line in lines:
        row = values.setdefault((line.lplpo.facility_id, line.item_id),
            {f"{kind}_value": Decimal(0) for kind in KINDS})
        for kind, quantity in (("opening", line.stock_awal if line.lplpo.bulan == start_month else 0),
                               ("receipts", line.penerimaan), ("consumption", line.pemakaian)):
            key = f"{kind}_value"
            row[key] = sum_decimals([row[key], multiply_decimals(quantity, line.harga_satuan)])
        row["closing_value"] = multiply_decimals(line.stock_keseluruhan, line.harga_satuan)
    return values


def stock_report_snapshot(facilities, year, start_month, end_month, *, is_aggregate=False):
    """One source per facility/interval, independent of LPLPO inventory adoption.

    Journal coverage wins only when it covers the interval start. Legacy quantity
    and price semantics remain explicitly labelled outside that coverage.
    """
    facilities = list(facilities)
    by_id = {facility.pk: facility for facility in facilities}
    rows, accounts = period_rows(list(by_id), year, end_month, start_month)
    inventory_ids = {account.facility_id for account in accounts}
    legacy_facilities = [facility for facility in facilities if facility.pk not in inventory_ids]
    legacy_stock_rows, metadata = legacy_stock(legacy_facilities, year, end_month, is_aggregate=is_aggregate)
    legacy_values = _legacy_values([facility.pk for facility in legacy_facilities], year, start_month, end_month)
    item_ids = {key[1] for key in legacy_stock_rows} | {key[1] for key in legacy_values}
    items = Item.objects.select_related("satuan", "kategori").in_bulk(item_ids)
    legacy_by_key = {}
    for key, quantity in legacy_stock_rows.items():
        facility_id, item_id = key[:2]
        legacy_by_key[(facility_id, item_id)] = dict(facility_id=facility_id, item=items[item_id],
            layers=[], closing_quantity=Decimal(quantity),
            opening_quantity=None, receipts_quantity=None, consumption_quantity=None, expiry_quantity=None, adjustment_quantity=None,
            **{f"{kind}_value": None for kind in KINDS})
    for key, values in legacy_values.items():
        row = legacy_by_key.setdefault(key, dict(facility_id=key[0], item=items[key[1]], layers=[],
            closing_quantity=None, opening_quantity=None, receipts_quantity=None, consumption_quantity=None,
            expiry_quantity=None, adjustment_quantity=None))
        row.update(values)
    rows.extend(legacy_by_key.values())
    for row in rows:
        row["facility_name"] = by_id[row["facility_id"]].name
        row["is_inventory"] = row["facility_id"] in inventory_ids
        if not row["is_inventory"]:
            row["adjustment_value"] = None
        row["has_valuation"] = row["opening_value"] is not None
        row["source_label"] = "Jurnal saldo awal terverifikasi" if row["is_inventory"] else "LPLPO historis"
    rows.sort(key=lambda row: (row["item"].kategori.sort_order if row["item"].kategori else 9999,
        row["item"].kategori.name if row["item"].kategori else "Lainnya", row["item"].nama_barang, row["facility_name"]))

    openings = {opening.facility_id: opening for opening in PuskesmasOpeningVerification.objects.filter(
        facility_id__in=inventory_ids, status="POSTED")}
    finalized = set(PuskesmasConsumptionRevision.objects.filter(consumption__facility_id__in=inventory_ids,
        effective_date__lte=date(year, end_month, calendar.monthrange(year, end_month)[1]))
        .values_list("consumption__facility_id", "consumption__tahun", "consumption__bulan"))
    coverage = {row["facility_id"]: row for row in metadata["coverage"]}
    for row in coverage.values():
        row.update(source_label="LPLPO historis" if row["baseline_period"] else "Tanpa sumber saldo",
            consumption_coverage="Historis: pemakaian rinci tersimpan; bukan finalisasi jurnal.", opening_id=None)
    for account in accounts:
        first_index = account.effective_date.year * 12 + account.effective_date.month - 1
        end_index = year * 12 + end_month - 1
        completed = {y * 12 + m - 1 for facility_id, y, m in finalized
                     if facility_id == account.facility_id and first_index <= y * 12 + m - 1 <= end_index}
        missing_count = end_index - first_index + 1 - len(completed)
        missing = []
        if missing_count:
            for index in range(first_index, end_index + 1):
                if index not in completed:
                    y, m = divmod(index, 12)
                    missing.append(format_lplpo_period_label(m + 1, y))
                    if len(missing) == 6:
                        break
        opening = openings[account.facility_id]
        consumption_coverage = (f"Belum difinalisasi: {missing_count} bulan (" + ", ".join(missing) +
            (", …" if missing_count > 6 else "") + "). Nilai 0 diposting bukan bukti pemakaian nihil.") if missing_count else "Semua bulan tercakup telah difinalisasi, termasuk pemakaian nihil."
        coverage[account.facility_id] = dict(facility_id=account.facility_id, facility_name=account.facility.name,
            source_label="Jurnal saldo awal terverifikasi", opening_id=opening.pk,
            baseline_period=f"Saldo awal {account.effective_date:%d/%m/%Y} · {opening.reference}",
            baseline_status="Diposting", adjustment_period=f"Sampai {format_lplpo_period_label(end_month, year)}",
            receipt_row_count=None, consumption_row_count=None, consumption_coverage=consumption_coverage,
            missing_month_count=missing_count)
    metadata["coverage"] = [coverage[facility.pk] for facility in facilities]
    metadata["facility_count"] = len(facilities)
    metadata["baseline_count"] += len(accounts)
    metadata["inventory_count"] = len(accounts)
    metadata["legacy_count"] = sum(bool(row["baseline_period"]) for row in metadata["coverage"] if not row["opening_id"])
    metadata["missing_finalization_count"] = sum(row.get("missing_month_count", 0) for row in metadata["coverage"])
    metadata["has_inventory"] = bool(accounts)
    metadata["has_adjustments"] = any(row.get("adjustment_occurred") for row in rows)
    metadata["baseline_note"] += " Nilai historis memakai harga LPLPO per dokumen; rincian lapisan asli dan rekonsiliasi nilai mutasi tidak tersedia."
    if accounts:
        metadata["source_description"] = "Stok Akhir Digital memakai jurnal saldo awal terverifikasi + penerimaan bersih − pemakaian difinalisasi − kedaluwarsa diposting − penyesuaian opname untuk fasilitas yang tercakup. Fasilitas di luar cakupan memakai baseline LPLPO historis + penerimaan CONFIRMED − pemakaian rinci setelah baseline. Sumber dipilih per fasilitas, tanpa menghitung ganda."
        metadata["baseline_note"] = "Pemilihan jurnal berdasarkan cakupan saldo awal, tidak memerlukan LPLPO. Nilai jurnal memakai harga asli tiap lapisan. Nilai historis tetap memakai harga LPLPO dan dapat berbeda dari rekonsiliasi mutasi. Kedaluwarsa ditampilkan sebagai pengeluaran terpisah pada jurnal; mutasi historis kedaluwarsa di luar cakupan belum diketahui. Saldo bukan hasil hitung fisik."
    rincian = {}
    for row in rows:
        if row["closing_quantity"] is None:
            continue  # Historical valuation alone cannot invent a quantity baseline.
        item = row["item"]
        result = rincian.setdefault(item.pk, dict(item_id=item.pk, nama_barang=item.nama_barang,
            satuan=item.satuan.name if item.satuan else "-", kategori=item.kategori.name if item.kategori else "Lainnya",
            stock_keseluruhan=Decimal(0)))
        result["stock_keseluruhan"] += row["closing_quantity"]
    report_data = list(rincian.values())
    metadata["item_count"] = len(report_data)
    metadata["negative_item_count"] = sum(row["stock_keseluruhan"] < 0 for row in report_data)
    if accounts:
        metadata.pop("empty_message", None)
        if not rows:
            metadata["empty_message"] = "Sumber saldo tersedia, tetapi tidak ada baris barang. Hasil kosong tidak berarti stok nol."
    return dict(rows=rows, accounts=accounts, report_data=report_data, metadata=metadata,
                categories=report_category_totals(rows))


def report_category_totals(rows):
    # A historical quantity baseline without valuation rows in the interval is
    # unvalued, not a zero-cost holding. Retain the old empty Rekap behavior.
    return category_totals([row for row in rows if row["has_valuation"]])


def report_links(year, start_month, end_month, facility_id=None):
    from urllib.parse import urlencode
    from django.urls import reverse
    params = dict(year=year, period="custom", start_month=start_month, end_month=end_month)
    if facility_id:
        params["facility"] = facility_id
    inventory_params = dict(year=year, start_month=start_month, month=end_month)
    if facility_id:
        inventory_params["facility"] = facility_id
    return {"inventory_url": reverse("puskesmas:inventory_report") + "?" + urlencode(inventory_params),
        "rincian_url": reverse("puskesmas:report_persediaan") + "?" + urlencode(params),
        "rekap_url": reverse("puskesmas:report_rekap_persediaan") + "?" + urlencode(params)}
