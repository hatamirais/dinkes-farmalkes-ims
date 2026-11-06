"""Excel export helpers for the puskesmas reports module."""
from decimal import Decimal

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter

from apps.core.decimal_validation import multiply_decimals, sum_decimals
from apps.core.xlsx_exports import escape_xlsx_formula


# Shared styles (mirrors reports/exports.py style)
HEADER_FONT = Font(bold=True, size=11)
HEADER_FILL = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
TOTAL_FILL = PatternFill(start_color="FFF3CD", end_color="FFF3CD", fill_type="solid")
THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)
IDR_FORMAT = "#,##0.00"
TEXT_FORMAT = "@"
NUMBER_FORMAT = "#,##0"


def _cell_value(value):
    return escape_xlsx_formula(value)


def _decimal_text(value, *, decimal_places):
    decimal_value = Decimal(str(value or 0))
    label = format(decimal_value, "f")
    if "." in label:
        whole, fractional = label.split(".", 1)
        fractional = fractional[:decimal_places].rstrip("0")
        return f"{whole}.{fractional}" if fractional else whole
    return label


def _set_decimal_text(cell, value, *, decimal_places):
    cell.value = _decimal_text(value, decimal_places=decimal_places)
    cell.number_format = TEXT_FORMAT
    cell.alignment = Alignment(horizontal="right")
    return cell


def _apply_header_row(ws, row_num, values, col_widths=None):
    """Apply header styling to a row."""
    for col_idx, val in enumerate(values, 1):
        cell = ws.cell(row=row_num, column=col_idx, value=_cell_value(val))
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER
    if col_widths:
        for col_idx, w in enumerate(col_widths, 1):
            ws.column_dimensions[get_column_letter(col_idx)].width = w


def _apply_border(ws, row_num, col_count):
    """Apply borders to all cells in a row."""
    for col_idx in range(1, col_count + 1):
        ws.cell(row=row_num, column=col_idx).border = THIN_BORDER


def _make_response(wb, filename):
    """Return an HttpResponse streaming the workbook as .xlsx."""
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response


def export_puskesmas_penerimaan_excel(report_data, start_date, end_date, facility_name):
    """Export confirmed Puskesmas receipt history to Excel.

    Args:
        report_data: list of dicts with keys:
            document_number, distribution_document_number, received_date,
            nama_barang, satuan, quantity, unit_price, batch_lot, expiry_date, notes
        start_date, end_date: date objects
        facility_name: str — name of the Puskesmas facility
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Riwayat Penerimaan"

    headers = [
        "No",
        "Tanggal Terima",
        "No. Konfirmasi",
        "No. Distribusi",
        "Nama Barang",
        "Satuan",
        "Jumlah Diterima",
        "Harga Satuan (Rp)",
        "Batch/Lot",
        "Kedaluwarsa",
        "Total Nilai (Rp)",
        "Keterangan",
    ]
    col_widths = [6, 18, 24, 24, 32, 10, 16, 20, 18, 16, 22, 28]
    col_count = len(headers)
    last_col = get_column_letter(col_count)

    # Title rows
    ws.merge_cells(f"A1:{last_col}1")
    title_cell = ws.cell(
        row=1,
        column=1,
        value=_cell_value("RIWAYAT KONFIRMASI PENERIMAAN PUSKESMAS"),
    )
    title_cell.font = Font(bold=True, size=14)
    title_cell.alignment = Alignment(horizontal="center")

    ws.merge_cells(f"A2:{last_col}2")
    period_cell = ws.cell(
        row=2,
        column=1,
        value=_cell_value(f"Fasilitas: {facility_name} | Periode: {start_date} s/d {end_date}"),
    )
    period_cell.font = Font(bold=True, size=11)
    period_cell.alignment = Alignment(horizontal="center")

    _apply_header_row(ws, 4, headers, col_widths)

    row_num = 5
    total_qty = Decimal("0")
    total_value = Decimal("0")

    for idx, row in enumerate(report_data, 1):
        received_date = row.get("received_date")
        received_date_str = received_date.strftime("%d/%m/%Y") if received_date else "-"
        qty = Decimal(str(row.get("quantity", 0) or 0))
        unit_price = Decimal(str(row.get("unit_price", 0) or 0))
        total_price = multiply_decimals(qty, unit_price)

        values = [
            idx,
            received_date_str,
            row.get("document_number", ""),
            row.get("distribution_document_number", ""),
            row.get("nama_barang", ""),
            row.get("satuan", ""),
            qty,
            unit_price,
            row.get("batch_lot", "") or "-",
            row.get("expiry_date").strftime("%d/%m/%Y")
            if row.get("expiry_date")
            else "-",
            total_price,
            row.get("notes", "") or "-",
        ]
        for col_idx, val in enumerate(values, 1):
            cell = ws.cell(row=row_num, column=col_idx, value=_cell_value(val))
            cell.border = THIN_BORDER
            if col_idx == 1:
                cell.alignment = Alignment(horizontal="center")
            elif col_idx == 7:
                cell.number_format = NUMBER_FORMAT
                cell.alignment = Alignment(horizontal="right")
            elif col_idx == 8:
                _set_decimal_text(cell, val, decimal_places=10)
            elif col_idx == 11:
                _set_decimal_text(cell, val, decimal_places=12)

        total_qty += qty
        total_value = sum_decimals([total_value, total_price])
        row_num += 1

    # Total row
    for col_idx in range(1, col_count + 1):
        cell = ws.cell(row=row_num, column=col_idx)
        cell.font = Font(bold=True)
        cell.fill = TOTAL_FILL
        cell.border = THIN_BORDER
    ws.cell(row=row_num, column=3, value=_cell_value("TOTAL")).font = Font(bold=True)
    qty_cell = ws.cell(row=row_num, column=7, value=total_qty)
    qty_cell.number_format = NUMBER_FORMAT
    qty_cell.alignment = Alignment(horizontal="right")
    qty_cell.font = Font(bold=True)
    val_cell = ws.cell(row=row_num, column=11, value=total_value)
    _set_decimal_text(val_cell, total_value, decimal_places=12)
    val_cell.font = Font(bold=True)

    filename = f"Riwayat_Penerimaan_{facility_name}_{start_date}_{end_date}.xlsx"
    return _make_response(wb, filename)


def export_puskesmas_pemakaian_excel(report_data, year, month_label, facility_name):
    """Export Riwayat Pemakaian Puskesmas report to Excel.

    Args:
        report_data: list of dicts with keys:
            period_display, nama_barang, satuan, stock_awal, penerimaan,
            pemakaian, stock_keseluruhan, permintaan_jumlah
        year: int
        month_label: str — e.g. "Semua Bulan" or "Januari"
        facility_name: str
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Riwayat Pemakaian"

    headers = [
        "No",
        "Periode",
        "Nama Barang",
        "Satuan",
        "Stok Awal",
        "Penerimaan",
        "Pemakaian",
        "Stok Akhir",
        "Permintaan",
    ]
    col_widths = [6, 18, 32, 10, 14, 14, 14, 14, 14]
    col_count = len(headers)
    last_col = get_column_letter(col_count)

    # Title rows
    ws.merge_cells(f"A1:{last_col}1")
    title_cell = ws.cell(
        row=1,
        column=1,
        value=_cell_value("RIWAYAT PEMAKAIAN PUSKESMAS (DARI DATA LPLPO)"),
    )
    title_cell.font = Font(bold=True, size=14)
    title_cell.alignment = Alignment(horizontal="center")

    ws.merge_cells(f"A2:{last_col}2")
    period_cell = ws.cell(
        row=2,
        column=1,
        value=_cell_value(f"Fasilitas: {facility_name} | Tahun: {year} | Bulan: {month_label}"),
    )
    period_cell.font = Font(bold=True, size=11)
    period_cell.alignment = Alignment(horizontal="center")

    _apply_header_row(ws, 4, headers, col_widths)

    row_num = 5
    for idx, row in enumerate(report_data, 1):
        values = [
            idx,
            row.get("period_display", ""),
            row.get("nama_barang", ""),
            row.get("satuan", ""),
            int(row.get("stock_awal", 0) or 0),
            int(row.get("penerimaan", 0) or 0),
            int(row.get("pemakaian", 0) or 0),
            int(row.get("stock_keseluruhan", 0) or 0),
            int(row.get("permintaan_jumlah", 0) or 0),
        ]
        for col_idx, val in enumerate(values, 1):
            cell = ws.cell(row=row_num, column=col_idx, value=_cell_value(val))
            cell.border = THIN_BORDER
            if col_idx == 1:
                cell.alignment = Alignment(horizontal="center")
            elif col_idx >= 5:
                cell.number_format = NUMBER_FORMAT
                cell.alignment = Alignment(horizontal="right")
        row_num += 1

    filename = f"Riwayat_Pemakaian_{facility_name}_{year}.xlsx"
    return _make_response(wb, filename)


def export_puskesmas_persediaan_excel(
    report_data, year, period_label, facility_name, *, report_metadata,
):
    """Export Rincian Laporan Persediaan Puskesmas report to Excel.

    Stock is the latest usable same-year LPLPO balance plus later CONFIRMED
    receipt confirmations minus later detailed consumption, through the selected
    end month. The source/coverage sheet uses the same metadata as HTML/print.
    Batch/lot, expiry, funding source, and unit price are excluded from this report.

    Args:
        report_data: list of dicts with keys:
            nama_barang, satuan, kategori, stock_keseluruhan
        year: int
        period_label: str — e.g. "Tahunan" or "Triwulan I"
        facility_name: str
        report_metadata: source, cutoff, summary, and per-facility baseline coverage
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Rincian Persediaan"

    headers = [
        "No",
        "Kategori",
        "Nama Barang",
        "Satuan",
        "Stok Akhir Digital",
    ]
    col_widths = [6, 24, 36, 10, 20]
    col_count = len(headers)
    last_col = get_column_letter(col_count)

    # Title rows
    ws.merge_cells(f"A1:{last_col}1")
    title_cell = ws.cell(
        row=1,
        column=1,
        value=_cell_value("RINCIAN LAPORAN PERSEDIAAN OBAT DAN PERBEKALAN KESEHATAN — PUSKESMAS"),
    )
    title_cell.font = Font(bold=True, size=14)
    title_cell.alignment = Alignment(horizontal="center")

    ws.merge_cells(f"A2:{last_col}2")
    period_cell = ws.cell(
        row=2,
        column=1,
        value=_cell_value(f"Fasilitas: {facility_name} | Tahun: {year} | Periode: {period_label}"),
    )
    period_cell.font = Font(bold=True, size=11)
    period_cell.alignment = Alignment(horizontal="center")

    _apply_header_row(ws, 4, headers, col_widths)

    row_num = 5
    for idx, row in enumerate(report_data, 1):
        values = [
            idx,
            row.get("kategori", "Lainnya"),
            row.get("nama_barang", ""),
            row.get("satuan", ""),
            int(row.get("stock_keseluruhan", 0) or 0),
        ]
        for col_idx, val in enumerate(values, 1):
            cell = ws.cell(row=row_num, column=col_idx, value=_cell_value(val))
            cell.border = THIN_BORDER
            if col_idx == 1:
                cell.alignment = Alignment(horizontal="center")
            elif col_idx == 5:
                cell.number_format = NUMBER_FORMAT
                cell.alignment = Alignment(horizontal="right")
        row_num += 1

    if not report_data:
        ws.merge_cells(f"A5:{last_col}5")
        ws.cell(row=5, column=1, value=_cell_value(report_metadata["empty_message"]))
        ws.cell(row=5, column=1).alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[5].height = 65

    source_sheet = wb.create_sheet("Sumber dan Cakupan")
    metadata_rows = [
        ("Fasilitas", facility_name),
        ("Periode", f"{period_label} {year}"),
        ("Posisi stok sampai akhir", report_metadata["period_end_label"]),
        ("Sumber perhitungan", report_metadata["source_description"]),
        ("Pemilihan baseline", report_metadata["baseline_note"]),
        ("Jumlah baris barang", report_metadata["item_count"]),
        ("Baris stok negatif", report_metadata["negative_item_count"]),
        ("Jumlah fasilitas aktif", report_metadata["facility_count"]),
        ("Fasilitas dengan baseline", report_metadata["baseline_count"]),
        ("Fasilitas dilewati tanpa baseline", report_metadata["missing_baseline_count"]),
        (
            "Rincian sumber",
            "Jumlah baris menunjukkan rincian sumber yang disertakan setelah baseline, bukan "
            "jumlah dokumen. Nilai 0 berarti tidak ada baris sumber dalam rentang penyesuaian; "
            "— berarti tidak dihitung tanpa baseline.",
        ),
    ]
    if report_metadata["is_aggregate"]:
        metadata_rows.append((
            "Agregasi",
            "Saldo barang dijumlahkan lintas fasilitas yang memiliki baseline; "
            "saldo positif dan negatif antar fasilitas dapat saling menutup.",
        ))
    if report_metadata.get("empty_message"):
        metadata_rows.append(("Hasil kosong", report_metadata["empty_message"]))
    for row_index, (label, value) in enumerate(metadata_rows, 1):
        source_sheet.cell(row=row_index, column=1, value=_cell_value(label)).font = HEADER_FONT
        source_sheet.merge_cells(start_row=row_index, start_column=2, end_row=row_index, end_column=6)
        source_sheet.cell(row=row_index, column=2, value=_cell_value(value)).alignment = Alignment(
            wrap_text=True, vertical="top",
        )
        source_sheet.row_dimensions[row_index].height = 60 if isinstance(value, str) else 20
    coverage_header_row = len(metadata_rows) + 2
    _apply_header_row(source_sheet, coverage_header_row, [
        "Fasilitas", "Baseline LPLPO", "Status baseline", "Rentang penyesuaian",
        "Baris penerimaan CONFIRMED", "Baris pemakaian rinci",
    ], [40, 28, 24, 55, 28, 28])
    for row_index, coverage in enumerate(report_metadata["coverage"], coverage_header_row + 1):
        has_baseline = bool(coverage["baseline_period"])
        values = [
            coverage["facility_name"], coverage["baseline_period"] or "Dilewati: tanpa baseline",
            coverage["baseline_status"] or "—", coverage["adjustment_period"] or "—",
            coverage["receipt_row_count"] if has_baseline else "—",
            coverage["consumption_row_count"] if has_baseline else "—",
        ]
        for column, value in enumerate(values, 1):
            source_sheet.cell(row=row_index, column=column, value=_cell_value(value)).alignment = Alignment(
                wrap_text=True, vertical="top",
            )
        _apply_border(source_sheet, row_index, 6)
        source_sheet.row_dimensions[row_index].height = 40
    source_sheet.freeze_panes = f"A{coverage_header_row + 1}"

    filename = f"Rincian_Laporan_Persediaan_{facility_name}_{year}_{period_label}.xlsx"
    return _make_response(wb, filename)


def export_puskesmas_rekap_persediaan_excel(rekap_data, totals, year, period_label, facility_name):
    """Export Rekap Laporan Persediaan Puskesmas to Excel.

    Year-to-date summary per category using LPLPO-derived valuation data.

    Args:
        rekap_data: list of dicts with keys:
            kategori, saldo_awal, nilai_terima, nilai_keluar, saldo_akhir
        totals: dict with grand total sums of the valuation fields
        year: int
        period_label: str
        facility_name: str
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Rekap Persediaan"

    headers = [
        "No",
        "Uraian",
        f"Saldo Awal {year}\n(Rp)",
        f"Nilai Terima {year}\n(Rp)",
        f"Nilai Keluar {year}\n(Rp)",
        f"Saldo Akhir {year}\n(Rp)",
    ]
    col_widths = [6, 36, 20, 20, 20, 20]
    col_count = len(headers)
    last_col = get_column_letter(col_count)

    ws.merge_cells(f"A1:{last_col}1")
    title_cell = ws.cell(
        row=1, column=1,
        value=_cell_value("REKAPITULASI LAPORAN PERSEDIAAN OBAT DAN PERBEKALAN KESEHATAN — PUSKESMAS"),
    )
    title_cell.font = Font(bold=True, size=14)
    title_cell.alignment = Alignment(horizontal="center")

    ws.merge_cells(f"A2:{last_col}2")
    period_cell = ws.cell(
        row=2, column=1,
        value=_cell_value(f"Fasilitas: {facility_name} | Tahun: {year} | Periode: {period_label}"),
    )
    period_cell.font = Font(bold=True, size=11)
    period_cell.alignment = Alignment(horizontal="center")

    _apply_header_row(ws, 4, headers, col_widths)
    ws.row_dimensions[4].height = 30

    row_num = 5
    for idx, row in enumerate(rekap_data, 1):
        values = [
            idx,
            row.get("kategori", "Lainnya"),
            Decimal(str(row.get("saldo_awal", 0) or 0)),
            Decimal(str(row.get("nilai_terima", 0) or 0)),
            Decimal(str(row.get("nilai_keluar", 0) or 0)),
            Decimal(str(row.get("saldo_akhir", 0) or 0)),
        ]
        for col_idx, val in enumerate(values, 1):
            cell = ws.cell(row=row_num, column=col_idx, value=_cell_value(val))
            cell.border = THIN_BORDER
            if col_idx == 1:
                cell.alignment = Alignment(horizontal="center")
            elif col_idx >= 3:
                _set_decimal_text(cell, val, decimal_places=12)
        row_num += 1

    # Totals row
    for col_idx in range(1, col_count + 1):
        cell = ws.cell(row=row_num, column=col_idx)
        cell.font = Font(bold=True)
        cell.fill = TOTAL_FILL
        cell.border = THIN_BORDER
    ws.cell(row=row_num, column=2, value=_cell_value("TOTAL")).font = Font(bold=True)
    total_columns = [
        (3, "saldo_awal"),
        (4, "nilai_terima"),
        (5, "nilai_keluar"),
        (6, "saldo_akhir"),
    ]
    for col_idx, key in total_columns:
        c = ws.cell(row=row_num, column=col_idx)
        _set_decimal_text(c, totals.get(key, 0), decimal_places=12)
        c.font = Font(bold=True)

    filename = f"Rekap_Persediaan_{facility_name}_{year}_{period_label}.xlsx"
    return _make_response(wb, filename)

