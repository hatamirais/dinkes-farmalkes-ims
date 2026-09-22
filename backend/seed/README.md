# Seed Data Templates

CSV templates used for bootstrap imports via Django Admin.

Last verified: 2026-07-28
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
10. Opening balance CSV (`opening_balance_template.csv`) for initial stock only
11. `receiving.csv` for operational receiving history/imports

For initial stock, use the admin-only opening balance import in Stock Admin. It creates `OpeningBalanceImport`, `OpeningBalanceImportItem`, stock updates, and `Transaction(IN, reference_type=INITIAL_IMPORT)` entries so opening balances stay separate from operational receiving.

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

- Rows are grouped by `import_group` into one `Receiving` header plus multiple `ReceivingItem` rows. The official Receiving number is issued by the central numbering service after the group validates.
- The first row supplies header-level values such as `supplier_code`, `receiving_date`, and default `sumber_dana_code` or `location_code`.
- Imported receivings are created in status `VERIFIED`, with `Stock` and `Transaction(IN)` posted immediately.
- `sumber_dana_code` and `location_code` can still be overridden per row when a document mixes line-level values.

### Dedicated opening balance import

Use `/admin/stock/stock/opening-balance/import-csv/` for first-time stock bootstrap.
Use `/admin/stock/stock/opening-balance/export-csv-template/` to download a blank `opening_balance_template.csv`.

This route is restricted to superuser / role `ADMIN` accounts and is not part of normal operational receiving. Uploading a CSV first runs validation and shows a preview table; the database is changed only after the admin presses `Konfirmasi Import`. Confirmed imports create stock source-document layers using `Stock.source_document_number = document_number` and post `Transaction(IN)` rows with `source_document_number=document_number` and `reference_type=INITIAL_IMPORT`; migrated historical receiving/opening-balance document-number collisions are the compatibility exception and continue on their existing `OBI-...` opening-balance source layer. Rekap/yearly reports classify those rows by opening balance `effective_date`: `saldo_awal` when effective on/before the report start, or in-period received stock when effective after the report start and within the selected period. Opening balance `document_number` values must remain unique across receiving documents and non-opening-balance `SourceDocumentNumberClaim` rows so different workflows never share the same stock source layer. Reusing a posted opening-balance `document_number` is allowed for partial completion: exact existing stock-layer totals are skipped, higher totals for an existing layer post only the quantity delta, while new rows under that document are posted to the existing import header. Reimport rows must provide `batch_lot` explicitly because generated blank-batch names include the CSV row number. Duplicate stock-layer rows in the same CSV are rejected; combine `quantity` into one row or use a different `batch_lot` / `document_number`.

Opening balance imports must not use `receiving_type` or `supplier_code`. If those columns are present with values, the importer rejects the file so receiving templates are not silently treated as saldo awal.

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

- `import_group` (required; grouping identity only, not the official document number)
- `receiving_type` (optional; defaults to `GRANT` in import handler; must match an active `ReceivingTypeOption.code`)
- `receiving_date` (required)
- `supplier_code` (optional; applied from the first row of each grouped document)
- `sumber_dana_code` (required on the first row of each `import_group`; later rows may inherit or override it)
- `location_code` (required on the first row of each `import_group`; later rows may inherit or override it)
- `item_code` (required, maps to `Item.kode_barang`)
- `quantity` (required; must be a finite decimal greater than `0`)
- `batch_lot` (optional; auto-generated if blank)
- `expiry_date` (optional only for items with `requires_expiry_date=0`; stored as `NULL` when blank for those items)
- `unit_price` (optional; default `0`)

Import notes:

- Baris pertama per `import_group` menjadi sumber data header `Receiving`.
- `import_group` tidak dibandingkan dengan nomor Saldo Awal dan tidak disalin ke `Receiving.document_number`. Setelah grup lolos validasi, sistem menerbitkan nomor resmi dan melewati kandidat yang sudah diklaim Saldo Awal/Receiving agar source layer tetap unik.
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

### `opening_balance_template.csv`

Expected columns for admin-only opening balance import:

- `document_number` (required, unique across workflows; may match an existing opening-balance import for partial reimport)
- `effective_date` (required; date the opening balance becomes effective for reports; every row in the same `document_number` must use the same date; cannot be later than the posting date because stock is posted immediately)
- `sumber_dana_code` (required)
- `location_code` (required)
- `item_code` (required, maps to `Item.kode_barang`)
- `quantity` (required; must be a finite decimal greater than `0`, with at most 12 digits and 2 decimal places)
- `batch_lot` (optional on first import; auto-generated with document identity if blank; required when reimporting a posted opening-balance document)
- `expiry_date` (optional only for items with `requires_expiry_date=0`; stored as `NULL` when blank for those items)
- `unit_price` (optional; default `0`; cannot be negative, with at most 23 digits and 10 decimal places)

Compatibility note: `receiving_date` is accepted as an alias for `effective_date` when converting older draft files, but use `effective_date` for new files.

Opening balance import notes:

- Rows are grouped by `document_number`.
- Comma and semicolon delimiters are accepted. For comma-delimited files, quote decimal-comma values such as `"2500,50"` so the parser does not treat them as extra columns.
- Every data row must match the header column count.
- `document_number` must not already exist as a receiving document, except for posted legacy opening-balance documents that were migrated onto an `OBI-...` source layer after historical receiving/opening-balance collisions. Receiving import enforces the reverse rule as well. A posted opening-balance `document_number` may be reused to import missing rows for that same source document.
- The stock layer key is `item_code + location_code + batch_lot + sumber_dana_code + source_document_number`; this is normally `document_number`, or the migrated `OBI-...` layer for legacy collisions.
- Existing rows for the same posted opening-balance document and exact stock-layer total are skipped during reimport; if the row quantity is higher than the already-posted total, only the delta is posted, and lower totals are rejected.
- Blank `batch_lot` is rejected during reimport of a posted opening-balance document so row-number-based generated batch names cannot change when rows are inserted, removed, or reordered.
- Rows for the same stock layer must be unique within one CSV; duplicate rows are rejected instead of accumulated so partial reimports cannot silently skip omitted quantities. Rows for the same stock layer must use the same `expiry_date` and exact `unit_price`; mismatches are rejected instead of merged. The same batch from a different `document_number` is kept as a separate layer and prices are not averaged. Decimal-comma unit prices such as `8893,31985` are accepted by the dedicated opening-balance importer and normalized internally.
- Import creates one `OpeningBalanceImport` header plus `OpeningBalanceImportItem` rows.
- Stock rows are updated/created with `source_document_number=document_number` and `receiving_ref=NULL`, except migrated receiving/opening-balance collisions remain on the existing `OBI-...` opening-balance source layer.
- Transactions use the same opening-balance source layer, `reference_type=INITIAL_IMPORT`, and `reference_id` pointing to the `OpeningBalanceImport`.
- Date formats and decimal parsing follow the receiving CSV parser rules.

### `stock.csv` (reference only)

The repository may still contain `stock.csv` fixtures for reference, but generic Stock admin import and direct Stock add/change/delete mutations are disabled. For first-time inventory bootstrap, use the dedicated opening balance import so the report ledger has explicit `INITIAL_IMPORT` semantics.

