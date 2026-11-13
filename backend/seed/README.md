# Seed Data Templates

CSV templates used for bootstrap imports via Django Admin.

## User creation CSV (main application)

Users are imported through `/users/` → **Import CSV**, not Django Admin. Download
the blank template at `/users/import/template/`. The existing user export is a
display report and cannot be used directly as an import file.

Exact columns: `username,full_name,nip,email,role,facility_code,is_active,password`.
All columns must be present. Username, role, is_active and password require values;
full_name, nip and email may be blank. Preserve NIP as text, including leading zeros.
UTF-8 (optional BOM), comma or semicolon separator; maximum 1 MiB / 25 data rows.
Use quoted CSV fields for embedded separators. Unknown/duplicate headers are rejected.

Roles: KEPALA, ADMIN_UMUM, GUDANG, AUDITOR, PUSKESMAS. ADMIN is forbidden.
`facility_code` references an existing active Puskesmas (codes are listed on the
upload page): required for PUSKESMAS, optional for ADMIN_UMUM/GUDANG, empty for
other roles. `is_active` must be `true` or `false`. Initial passwords (maximum
1024 characters) must pass the
configured password validators; they are preserved exactly, hidden from previews,
and stored as hashes. The administrator communicates them separately. Users may
change them voluntarily; no first-login change is required.

Import requires superuser, Django `users.add_user`, or USERS module scope MANAGE.
Only role-default scopes/groups are assigned; privilege columns are forbidden.
Existing usernames/nonblank emails and duplicates within the file are rejected
case-insensitively. Blank email may repeat; import never updates existing accounts.
Validation creates no accounts; explicit confirmation creates the whole batch or
none. Previews belong to their uploader, expire after 15 minutes and are single-use.
Confirmation rechecks permissions and facility eligibility. Cancellation or success
deletes staging hashes; expired previews are removed on access or by
`python manage.py cleanup_user_imports` (schedule every 15 minutes).

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



### Puskesmas report authorization (#313)

The read-only `puskesmas_reports` module is independent of central REPORTS.
PUSKESMAS defaults to VIEW; ADMIN, KEPALA, ADMIN_UMUM, GUDANG, and AUDITOR default
to NONE. NONE explicitly denies access; higher scopes provide only read access.
Without staff capabilities, a reader needs an active Puskesmas facility link and
is forced to it, including for Excel exports and forged facility parameters.

To authorize internal staff, set `Laporan Puskesmas` to VIEW in user module access,
then explicitly assign `users.select_puskesmas_report_facility` through Django
Admin user/group permissions. Also assign `users.aggregate_puskesmas_reports`
only when all-facility aggregation is authorized. Aggregation requires both
permissions; these capabilities cannot widen role PUSKESMAS access. AUDITOR
remains read-only and sees the report submenu without operational navigation.
Selection-only staff default to the first active Puskesmas; invalid selections
denied with 403 never widen to all facilities. Superusers retain full scope.

Deployment: run `python manage.py migrate` to register both custom permissions
and the new module choice. No account/group permission backfill is performed.
Existing accounts without a new module row use role defaults immediately;
new/save provisioning seeds that row. Existing explicit module rows are preserved.
Optional `python manage.py sync_module_access` materializes missing rows without
`--overwrite`; do not reset customized scopes. Existing generic Reports grants
are retained but do not authorize these facility reports. Review staff grants
individually; no staff cross-facility grants are automatic.
## Puskesmas initial opening CSV (feature 1)

Use `/puskesmas/saldo-awal/buat/`, not warehouse Stock Admin/receiving import.
Download the template from `/puskesmas/saldo-awal/template/`. Apply migration
`puskesmas.0012_inventory_foundation` and `0013_opening_source_distribution` before serving these routes.

Exact headers, in order:

```csv
line_key,item_code,item_name,unit,quantity,unit_price,batch_lot,expiry_date,sumber_dana_code,provenance_note
```

One file belongs to the selected facility and January 1 year in the form. It
represents all stock held across warehouse, rooms and Pustu before that day's
movements. Do not include receipts dated on/after January 1 again. Item/funding
codes resolve existing active master data; this import does not create master rows.

Select facility/year in the download form. Prefilled rows are candidate acquisition
layers from that facility's completed distributions before January 1, excluding
receipts known to arrive on/after cutover. Item name/unit are reference columns;
issued prices/batches/expiry/funding are copied; known source numbers are retained internally,
never current warehouse prices or quantities for distribution rows. Quantity is always blank. Every
DIST-<id> key stays separate and must not be changed; selecting a row validates
its source, scope, cutoff and snapshot again before posting. Known metadata must
match the source. Unknown snapshot prices remain blank and hold posting.

Fill positive whole quantities only for verified remaining stock. Rows with blank
quantity are skipped; header-only/all-blank-quantity files cannot be submitted.
Keep all ten headers in order. Legacy eleven-column worksheets with
source_document_number and the original nine-column format without item_name/unit
remain accepted; supplied source numbers must still match linked sources.
Add verified stock missing from
history using new line keys outside DIST- and STOCK-; unknown provenance must be explicit.
Additional STOCK-<id> rows offer recorded Instalasi Farmasi Stock identities for
active items/funding, including zero-quantity warehouse rows. Item code/name/unit,
recorded layer price, batch, expiry and funding are prefilled; source document
numbers are recovered internally through line_key, not included in the download.
Quantity and provenance_note are blank. These references do not prove delivery, facility ownership or
historical opening-date price. Operators select only matching verified stock, and
independent review remains mandatory. Metadata must remain unchanged; source changes
before posting require a fresh worksheet. Posted facility prices stay frozen, and
warehouse quantities/transactions are never changed by this import. Identical
warehouse candidates across locations or already present in distribution candidates
are offered once; distinct distribution acquisitions remain separate.
With neither matching history nor warehouse candidates, the downloaded worksheet
contains headers only, ready for manual rows. Formula-leading source text is escaped safely in the download
and restored only against a validated linked source snapshot on import.

Numeric-looking item codes, batches and funding codes are prefixed with an
apostrophe on download to preserve leading zeros and punctuation. Keep identifier
columns as Text when opening CSV in Excel/LibreOffice, including manually added
batches. Source-linked imports accept the protected text and restore the exact
recorded identifier. A spreadsheet-converted batch such as `60125,01` cannot match
the recorded `060125.01`. Validation identifies the field and both values so the
operator can restore the source text. Prices still accept decimal commas.

UTF-8 (optional BOM), comma/semicolon delimiter, maximum 5 MiB and 10,000 data rows.
Use positive whole base-unit quantities and nonnegative original prices (up to
10 decimals). Decimal comma is accepted with correct CSV quoting; omit thousands
separators. Expiry uses ISO YYYY-MM-DD, years 1000..9999. line_key is required and
unique within the file; it is a technical row key, not an invented batch number.
Keep distinct original-price/acquisition rows separate, even for the same batch.

All headers are required. Blank price or required expiry may be staged but blocks
posting. Blank batch/funding/source means unknown and requires provenance_note;
for linked rows with no operator note, the importer records factual missing-source
information and the warehouse-candidate caution internally. Operators may leave
their note blank on linked rows. New manual rows have no source-document link:
provide their provenance_note, mentioning the actual source document if known.
To record a manual source number in its dedicated field, the legacy CSV formats
with source_document_number remain supported. Never infer a source link for a
manually entered row.
Do not create fake codes, source numbers, expiry dates or zero prices. A genuine
zero price is explicit `0`. Empty/zero-stock submissions are not supported. Confirm
the whole-facility/cutover declaration; no zero-stock checkbox is displayed.

Upload validates and stores an actor-bound preview; it changes no inventory.
Submit within 24 hours, then an independent superuser or GUDANG with LPLPO module
scope OPERATE or higher verifies/posts. Submitted rows are frozen. Fix rejected
or held records with a new upload. Posting revalidates live data and is atomic:
an unsupported confirmed receipt since cutover also blocks the whole opening.
Repeated confirmation never duplicates layers/movements.

One initial opening per facility; no cumulative reimport or annual-reset import.
Annual reconciliation posting and correction UI are deferred. Posted records are
immutable. The projected balance omits consumption and is not reliable current
stock; existing LPLPO and reports keep their calculations.
