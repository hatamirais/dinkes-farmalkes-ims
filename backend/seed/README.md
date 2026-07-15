# Seed Data Templates

CSV templates used for bootstrap imports via Django Admin.

Last verified: 2026-05-04
Verification sources: `backend/seed/*.csv`, `backend/apps/items/admin.py`, `backend/apps/stock/admin.py`, `backend/apps/receiving/admin.py`

## Import Order

Import lookup and master dependencies first:

1. `units.csv`
2. `categories.csv`
3. `funding_sources.csv`
4. `programs.csv`
5. `therapeutic_classes.csv`
6. `locations.csv`
7. `suppliers.csv`
8. `facilities.csv`
9. `items.csv`
10. `receiving.csv`

For initial stock, prefer `receiving.csv` (custom receiving import endpoint) so the system creates receiving headers, stock updates, and `Transaction(IN)` entries consistently.

## How to Import

### Standard django-import-export flow

1. Open `/admin/`.
2. Open target model (for example, Units).
3. Click `Import`.
4. Upload CSV and submit dry run.
5. Confirm import.

### Dedicated receiving import

Use `/admin/receiving/receiving/import-csv/` for `receiving.csv`.
Use `/admin/receiving/receiving/export-csv-template/` to download a blank `receiving_template.csv` with the exact columns accepted by the importer.

Import behavior summary:

- Rows are grouped by `document_number` into one `Receiving` header plus multiple `ReceivingItem` rows.
- The first row supplies header-level values such as `supplier_code`, `receiving_date`, and default `sumber_dana_code` or `location_code`.
- Imported receivings are created in status `VERIFIED`, with `Stock` and `Transaction(IN)` posted immediately.
- `sumber_dana_code` and `location_code` can still be overridden per row when a document mixes line-level values.

## CSV Column Specifications

### `units.csv`

Columns:

- `code` (required, unique)
- `name` (required)
- `description` (optional)

### `categories.csv`

Columns:

- `code` (required, unique)
- `name` (required)
- `sort_order` (optional, default `0`)

### `funding_sources.csv`

Columns:

- `code` (required, unique)
- `name` (required)
- `description` (optional)
- `is_active` (optional, default `1`)

### `programs.csv`

Columns:

- `code` (required, unique)
- `name` (required)
- `description` (optional)
- `is_active` (optional, default `1`)

### `therapeutic_classes.csv`

Columns:

- `code` (required, unique)
- `name` (required)
- `description` (optional)
- `is_active` (optional, default `1`)

### `locations.csv`

Columns:

- `code` (required, unique)
- `name` (required)
- `description` (optional)
- `is_active` (optional, default `1`)

### `suppliers.csv`

Columns:

- `code` (required, unique)
- `name` (required)
- `address` (optional)
- `phone` (optional)
- `email` (optional)
- `notes` (optional)
- `is_active` (optional, default `1`)

### `facilities.csv`

Columns:

- `code` (required, unique)
- `name` (required)
- `facility_type` (optional, default `PUSKESMAS`; values: `PUSKESMAS`, `RS`, `CLINIC`, `LABORATORIUM`)
- `address` (optional)
- `phone` (optional)
- `is_active` (optional, default `1`)

### `items.csv`

Columns:

- `kode_barang` (optional, internal item code; auto-generated when missing)
- `barcode` (optional, unique when present; reserved for future scanner workflows)
- `nama_barang` (required)
- `satuan` (required, maps to `Unit.code`)
- `kategori` (required, maps to `Category.code`)
- `is_program_item` (optional, default `0`)
- `is_essential` (optional, default `0`)
- `program` (optional, maps to `Program.code`)
- `therapeutic_classes` (optional, maps to one or more `TherapeuticClass.code`, separated by `|`)
- `minimum_stock` (optional, default `0`)
- `requires_expiry_date` (optional, default `1`; set `0` for non-expiring items)
- `description` (optional)
- `is_active` (optional, default `1`)

Notes:

- `kode_barang` remains the internal item code and is auto-generated when missing.
- Blank `barcode` values are stored as `NULL`; non-blank barcode values must be unique.
- If `is_program_item` is true and `program` is blank, importer auto-uses/creates `DEFAULT`.
- `therapeutic_classes` values must already exist in `therapeutic_classes.csv` or the Therapeutic Class admin lookup.
- `therapeutic_classes` is an import-only relation field on the `items` admin resource; it maps to the many-to-many join table between `Item` and `TherapeuticClass`, not to a physical column on the `items` table.
- Re-import/update matching for `items.csv` uses `nama_barang` as the current import identifier. There is no dedicated mapping-only CSV import for `Terapi Obat` keyed by `kode_barang` yet.

### `receiving.csv`

Expected columns for custom receiving import:

- `document_number` (required)
- `receiving_type` (optional; defaults to `GRANT` in import handler)
- `receiving_date` (required)
- `supplier_code` (optional; applied from the first row of each grouped document)
- `sumber_dana_code` (required on the first row of each `document_number`; later rows may inherit or override it)
- `location_code` (required on the first row of each `document_number`; later rows may inherit or override it)
- `item_code` (required, maps to `Item.kode_barang`)
- `quantity` (required; must be a finite decimal greater than `0`)
- `batch_lot` (optional; auto-generated if blank)
- `expiry_date` (optional only for items with `requires_expiry_date=0`; stored as `NULL` when blank for those items)
- `unit_price` (optional; default `0`)

Import notes:

- Baris pertama per `document_number` menjadi sumber data header `Receiving`.
- `sumber_dana_code` dan `location_code` pada baris item akan override nilai header bila diisi.
- Baris dengan `quantity` kosong, `0`, negatif, `NaN`, atau `Infinity` akan ditolak pada validasi import.
- Import menormalisasi spasi dan Unicode NFC pada header/sel teks, menolak null byte, serta menolak nilai teks yang melampaui panjang kolom model sebelum data disimpan.
- `receiving_date` dan `expiry_date` harus memakai tahun antara `1000` dan `9999`.

Date formats accepted by parser:

- `DD/MM/YYYY`
- `YYYY-MM-DD`
- `DD-MM-YYYY`
- `DD/MM/YY`

Decimal parsing accepts comma separator.

### `stock.csv` (reference only)

The repository still contains `stock.csv` template and stock admin import resources, but for first-time inventory bootstrap, `receiving.csv` is preferred because it posts auditable inbound transactions.

