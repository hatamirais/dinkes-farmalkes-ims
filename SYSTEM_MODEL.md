# SYSTEM_MODEL.md

Canonical reference for current schema, route topology, permission model, and stock mutation behavior.

Last verified: 2026-04-10
Verification sources: `backend/apps/*/models.py`, `backend/config/urls.py`, `backend/apps/*/urls.py`, `backend/apps/core/decorators.py`, `backend/apps/users/access.py`, `backend/config/settings.py`, `backend/apps/receiving/admin.py`, `backend/apps/distribution/services.py`, `backend/apps/stock/views.py`, `backend/apps/lplpo/signals.py`

## 1) Domain Overview

Healthcare IMS is a Django monolith with server-rendered templates. Inventory is tracked at batch/location granularity and all movement is recorded in immutable `Transaction` rows.

Core domains:

- Master data and item catalog (`items`)
- Stock and movement journal (`stock`)
- Inbound receiving (`receiving`)
- Outbound distribution (`distribution`)
- Supplier return (`recall`)
- Expired disposal (`expired`)
- Physical counting (`stock_opname`)
- Puskesmas ad-hoc requests (`puskesmas`)
- LPLPO reporting and requests (`lplpo`)
- Access and module scope control (`users`)

## 2) Route Topology

Root route include map from `backend/config/urls.py`:

- `/` -> dashboard (`apps.core.views.dashboard`)
- `/admin/` -> Django admin
- `/login/`, `/logout/`, `/password/change/`, `/password/change/done/`
- `/settings/` -> system settings (`apps.core.views.SystemSettingsUpdateView`)
- `/users/`, `/items/`, `/stock/`, `/receiving/`, `/distribution/`, `/recall/`, `/expired/`, `/reports/`, `/stock-opname/`, `/puskesmas/`, `/lplpo/`

Module highlights:

- Stock card: `/stock/stock-card/`, `/stock/stock-card/<item_id>/`
- Stock transfer: `/stock/transfers/*`
- Receiving regular: `/receiving/`, `/receiving/create/`, `/receiving/<pk>/`
- Receiving plan: `/receiving/plans/*`
- RS returns: `/receiving/rs-returns/*`, including `/receiving/rs-returns/from-borrow/<distribution_pk>/create/`
- Receiving quick-create APIs: `/receiving/api/quick-create-supplier/`, `/receiving/api/quick-create-funding-source/`, `/receiving/api/quick-create-receiving-type/`
- Borrow RS distribution: `/distribution/borrow-rs/*`
- Expiry alerts: `/expired/alerts/`
- Reports: `/reports/`, `/reports/rekap/`, `/reports/penerimaan-hibah/`, `/reports/pengadaan/`, `/reports/kadaluarsa/`, `/reports/pengeluaran/`
- LPLPO lists: `/lplpo/` (All), `/lplpo/my/` (Puskesmas scoped)
- Puskesmas requests: `/puskesmas/permintaan/`

## 3) Permission and Access Model

Hybrid authorization in `@perm_required`:

1. Django permission (`request.user.has_perm`)
2. Module-scope fallback (`has_module_permission`)

`ModuleAccess.module` values:

- `users`, `items`, `stock`, `receiving`, `distribution`, `recall`, `expired`, `stock_opname`, `reports`, `puskesmas`, `lplpo`, `admin_panel`

`ModuleAccess.scope` values:

- `0 NONE`, `1 VIEW`, `2 OPERATE`, `3 APPROVE`, `4 MANAGE`

Special rule:

- For `users.*` permissions, non-view actions require `MANAGE` scope.

Role default scopes are seeded in `backend/apps/users/access.py` via `ROLE_DEFAULT_SCOPES`.

## 4) Canonical Schema

This section reflects model code in `backend/apps/*/models.py`.

### 4.1 Shared base & Settings

- `TimeStampedModel` (`apps.core.models`)
  - `created_at`, `updated_at`

- `core.SystemSettings` (`system_settings`)
  - Singleton model (forced `id=1`) for global dynamic settings.
  - Fields: `facility_name`, `facility_address`, `facility_phone`, `header_title`, `logo`

### 4.2 Users and authorization

- `users.User` (`db_table=users`)
  - Extends `AbstractUser`
  - Extra fields: `role`, `full_name`, `nip`, `facility` (nullable FK)
  - Role enum: `ADMIN`, `KEPALA`, `ADMIN_UMUM`, `GUDANG`, `AUDITOR`, `PUSKESMAS`

- `users.ModuleAccess` (`db_table=user_module_accesses`)
  - `user` FK -> `users.User`
  - `module` (enum)
  - `scope` (int enum)
  - Unique: `(user, module)`

### 4.3 Master data and item registry

- `items.Unit` (`units`): `code`, `name`, `description`
- `items.Category` (`categories`): `code`, `name`, `sort_order`
- `items.FundingSource` (`funding_sources`): `code`, `name`, `description`, `is_active`
- `items.Program` (`programs`): `code`, `name`, `description`, `is_active`
- `items.Location` (`locations`): `code`, `name`, `description`, `is_active`
- `items.Supplier` (`suppliers`): `code`, `name`, `address`, `phone`, `email`, `notes`, `is_active`
- `items.Facility` (`facilities`): `code`, `name`, `address`, `phone`, `facility_type`, `is_active`
  - `facility_type` choices: `PUSKESMAS`, `RS`, `CLINIC`, `LABORATORIUM`
- `items.Item` (`items`):
  - `kode_barang` (unique, auto-generated `ITM-YYYY-NNNNN` when blank)
  - `nama_barang`
  - `satuan` FK -> `Unit`
  - `kategori` FK -> `Category`
  - `is_program_item`
  - `program` FK -> `Program` (nullable)
  - `minimum_stock`, `description`, `is_active`
  - Index: `idx_item_category_program` on `(kategori, is_program_item)`

### 4.4 Stock and transactions

- `stock.Stock` (`stock`):
  - FKs: `item`, `location`, `sumber_dana`, `receiving_ref` (nullable)
  - Fields: `batch_lot`, `expiry_date`, `quantity`, `reserved`, `unit_price`
  - Unique: `uq_stock_batch` on `(item, location, batch_lot, sumber_dana)`
  - Checks: `quantity >= 0`, `reserved >= 0`
  - Indexes: `idx_stock_fefo`, `idx_stock_expiry`, `idx_stock_item_loc`
  - Properties: `available_quantity`, `total_value`, `is_expired`, `is_near_expiry`

- `stock.Transaction` (`transactions`):
  - Types: `IN`, `OUT`, `ADJUST`, `RETURN`
  - Reference types: `RECEIVING`, `DISTRIBUTION`, `ADJUSTMENT`, `INITIAL_IMPORT`, `RECALL`, `EXPIRED`, `TRANSFER`
  - FKs: `item`, `location`, `sumber_dana` (nullable), `user`
  - Fields: `batch_lot`, `quantity`, `unit_price` (nullable), `reference_type`, `reference_id`, `notes`, `created_at`
  - Indexes: `idx_trans_item_date`, `idx_trans_reference`, `idx_trans_created`
  - Current workflows write `IN` and `OUT`; `RETURN` remains available in the enum but is not emitted by the main document flows verified on 2026-04-10

- `stock.StockTransfer` (`stock_transfers`):
  - Status: `DRAFT`, `COMPLETED`
  - `document_number` auto-generated `TRF-YYYY-NNNNN` when blank
  - FKs: `source_location`, `destination_location`, `created_by`, `completed_by` (nullable)
  - Fields: `transfer_date`, `notes`, `completed_at`
  - Validation: source and destination locations must differ
  - Completion behavior: writes paired `Transaction(OUT)` and `Transaction(IN)` rows with `reference_type=TRANSFER`

- `stock.StockTransferItem` (`stock_transfer_items`):
  - FKs: `transfer`, `stock`, `item`
  - Fields: `quantity`, `notes`
  - Validation: quantity must be `> 0` and selected `item` must match the source stock batch

### 4.5 Receiving

- `receiving.ReceivingTypeOption` (`receiving_type_options`): `code`, `name`, `is_active`
  - Used by quick-create receiving type UI and by `Receiving.receiving_type_label` to resolve non-built-in labels

- `receiving.Receiving` (`receivings`):
  - Type: `PROCUREMENT`, `GRANT`, `RETURN_RS`
  - Status: `DRAFT`, `SUBMITTED`, `APPROVED`, `PARTIAL`, `RECEIVED`, `CLOSED`, `VERIFIED`
  - Fields: `document_number` (auto-generated `RCV-YYYY-NNNNN` when blank), `receiving_date`, `is_planned`, `grant_origin`, `program`, `closed_reason`, `notes`
  - FKs: `supplier` (nullable), `facility` (nullable, required for `RETURN_RS`), `sumber_dana`, `created_by`, `verified_by` (nullable), `approved_by` (nullable), `closed_by` (nullable)
  - Timestamps: `verified_at`, `approved_at`, `closed_at`
  - Index: `idx_recv_status_date`
  - Properties: `is_rs_return`, `receiving_type_label`
  - UI: `RETURN_RS` is intentionally exposed through a dedicated receiving list/form flow, separated from regular receiving entry screens
  - Custom receiving types can still be stored in `receiving_type`; built-in display labels come from `ReceivingType`, while non-built-in labels are resolved from `ReceivingTypeOption`

- `receiving.ReceivingItem` (`receiving_items`):
  - FKs: `receiving`, `order_item` (nullable), `item`, `location` (nullable), `settlement_distribution_item` (nullable), `received_by` (nullable)
  - Fields: `quantity`, `batch_lot`, `expiry_date`, `unit_price`, `received_at`, `created_at`
  - Property: `total_price`
  - `settlement_distribution_item` is used by `RETURN_RS` to settle sisa pengembalian dari dokumen `BORROW_RS` / `SWAP_RS`
  - For `RETURN_RS` launched from a `BORROW_RS` detail page, facility, item, unit price, and funding source are derived from the originating distribution document and enforced server-side

- `receiving.ReceivingDocument` (`receiving_documents`):
  - FK: `receiving`
  - File fields: `file`, `file_name`, `file_type`, `uploaded_at`

- `receiving.ReceivingOrderItem` (`receiving_order_items`):
  - FKs: `receiving`, `item`
  - Fields: `planned_quantity`, `received_quantity`, `unit_price`, `notes`, `is_cancelled`, `cancel_reason`
  - Property: `remaining_quantity`

### 4.6 Distribution

- `distribution.Distribution` (`distributions`):
  - Type: `LPLPO`, `ALLOCATION`, `SPECIAL_REQUEST`, `BORROW_RS`, `SWAP_RS`
  - Status: `DRAFT`, `SUBMITTED`, `VERIFIED`, `PREPARED`, `DISTRIBUTED`, `REJECTED`
  - Workflow includes manual reset action back to `DRAFT` from `SUBMITTED`, `VERIFIED`, `PREPARED`, and `REJECTED` (but not from `DISTRIBUTED`)
  - Provides `kepala_instalasi` and `petugas` assignments logic for print outputs
  - Fields: `document_number` (auto-generated `DIST-YYYYMM-XXXXX` when blank), `request_date`, `program`, `distributed_date`, `notes`, `ocr_text`
  - FKs: `facility`, `created_by`, `verified_by` (nullable), `approved_by` (nullable)
  - Indexes: `idx_dist_status_date`, `idx_dist_facility_date`
  - Property: `is_rs_workflow`

- `distribution.DistributionItem` (`distribution_items`):
  - FKs: `distribution`, `item`, `stock` (nullable)
  - Fields: `quantity_requested`, `quantity_approved` (nullable), `issued_batch_lot`, `issued_expiry_date`, `issued_unit_price`, `notes`, `created_at`
  - FKs also include `issued_sumber_dana` (nullable) to preserve the book-value source used when the RS document was distributed
  - Properties: `settled_quantity`, `outstanding_quantity`, `outstanding_value`
  - Sisa pengembalian RS dihitung dari `quantity_approved - sum(receiving_items.quantity)` untuk baris `settlement_distribution_item` yang terhubung

- `distribution.DistributionStaffAssignment` (`distribution_staff_assignments`):
  - FKs: `distribution`, `user`
  - Purpose: stores staff involved in a distribution document and surfaces them in detail/print output
  - Constraint: unique pair per (`distribution`, `user`)

### 4.7 Recall

- `recall.Recall` (`recalls`):
  - Status: `DRAFT`, `SUBMITTED`, `VERIFIED`, `COMPLETED`
  - Fields: `document_number` (auto-generated `REC-YYYYMM-XXXXX` when blank), `recall_date`, `notes`
  - FKs: `supplier`, `created_by`, `verified_by` (nullable), `completed_by` (nullable)
  - Timestamps: `verified_at`, `completed_at`

- `recall.RecallItem` (`recall_items`):
  - FKs: `recall`, `item`, `stock`
  - Fields: `quantity`, `notes`, `created_at`

### 4.8 Expired

- `expired.Expired` (`expired_docs`):
  - Status: `DRAFT`, `SUBMITTED`, `VERIFIED`, `DISPOSED`
  - Fields: `document_number` (auto-generated `EXP-YYYYMM-XXXXX` when blank), `report_date`, `notes`
  - FKs: `created_by`, `verified_by` (nullable), `disposed_by` (nullable)
  - Timestamps: `verified_at`, `disposed_at`

- `expired.ExpiredItem` (`expired_items`):
  - FKs: `expired`, `item`, `stock`
  - Fields: `quantity`, `notes`, `created_at`

### 4.9 Stock opname

- `stock_opname.StockOpname` (`stock_opnames`):
  - Period type: `MONTHLY`, `QUARTERLY`, `SEMESTER`, `YEARLY`
  - Status: `DRAFT`, `IN_PROGRESS`, `COMPLETED`
  - Fields: `document_number` (auto-generated `SO-YYYYMM-XXXXX` when blank), `period_start`, `period_end`, `notes`, `completed_at`
  - FK: `created_by`
  - M2M: `categories` -> `items.Category`, `assigned_to` -> `users.User`

- `stock_opname.StockOpnameItem` (`stock_opname_items`):
  - FKs: `stock_opname`, `stock`
  - Fields: `system_quantity`, `actual_quantity` (nullable), `notes`
  - Unique: `(stock_opname, stock)`

### 4.10 Reports

- `reports`: Contains views, templates, and services for inventory, expiry, and receiving reporting with Excel export capabilities. No bespoke database models, aggregates data from other apps.

### 4.11 Puskesmas

- `puskesmas.PuskesmasRequest` (`puskesmas_requests`):
  - Status: `DRAFT`, `SUBMITTED`, `APPROVED`, `REJECTED`
  - Fields: `document_number` (auto-generated `REQ-YYYYMM-XXXXX` when blank), `request_date`, `notes`, `rejection_reason`
  - FKs: `facility` (puskesmas only), `program` (nullable), `created_by`, `approved_by` (nullable), `distribution` (nullable OneToOne)
  - Timestamps: `approved_at`
  - Indexes: `idx_pkreq_status_date`, `idx_pkreq_facility_date`

- `puskesmas.PuskesmasRequestItem` (`puskesmas_request_items`):
  - FKs: `request`, `item`
  - Fields: `quantity_requested`, `quantity_approved` (nullable), `notes`

### 4.12 LPLPO

- `lplpo.LPLPO` (`lplpos`):
  - Status: `DRAFT`, `SUBMITTED`, `REVIEWED`, `DISTRIBUTED`, `CLOSED`
  - Fields: `bulan`, `tahun`, `document_number` (auto-generated `LPLPO-YYYYMM-XXXXX` when blank), `notes`
  - FKs: `facility` (puskesmas only), `created_by`, `reviewed_by` (nullable), `distribution` (nullable OneToOne)
  - Timestamps: `submitted_at`, `reviewed_at`
  - Constraints/Indexes: `uq_lplpo_facility_period` unique on `(facility, bulan, tahun)`, `idx_lplpo_facility_period` on `(facility, tahun, bulan)`, `idx_lplpo_status` on `(status)`

- `lplpo.LPLPOItem` (`lplpo_items`):
  - FKs: `lplpo`, `item`
  - Puskesmas fields: `stock_awal`, `penerimaan`, `pemakaian`, `stock_gudang_puskesmas`, `waktu_kosong`, `permintaan_jumlah`, `permintaan_alasan`
  - Computed fields (auto): `persediaan`, `stock_keseluruhan`, `stock_optimum`, `jumlah_kebutuhan`
  - IF fields: `pemberian_jumlah` (nullable), `pemberian_alasan`
  - Audit: `penerimaan_auto_filled`

## 5) Stock Mutation Checkpoints

Operational mutation points (from app behavior and admin import logic):

- Receiving verify/receive path posts `Transaction(IN)` and updates/creates `Stock`.
- `Receiving(receiving_type=RETURN_RS)` still posts a normal `Transaction(IN)`, but operationally it also settles the linked RS distribution item rather than pretending to restore the original batch.
- Receiving CSV admin import (`import-csv/`) posts:
  - `Receiving(status=VERIFIED)`
  - `ReceivingItem`
  - `Stock` update/create
  - `Transaction(IN)`
  - Rows are grouped by `document_number`; the first row supplies header-level values, while row-level `sumber_dana_code` and `location_code` can override header defaults
- LPLPO Finalize creates a Distribution document mapped 1:1.
- Distribution:
  - verification and distribution validations use `Stock.available_quantity` (`quantity - reserved`) when checking the selected batch
  - prepare phase updates document status only (no stock mutation and no reservation write)
  - distribute phase decreases `Stock.quantity` and posts `Transaction(OUT)`; the current workflow does not automatically increment or clear `stock.reserved`
  - `BORROW_RS` and `SWAP_RS` use the same stock-out mechanics as other distributions, while preserving issued batch/value snapshots on each `DistributionItem` for settlement and audit visibility
- Recall verify decreases stock and posts `Transaction(OUT, reference_type=RECALL)`
- Expired verify decreases stock and posts `Transaction(OUT, reference_type=EXPIRED)`
- Stock transfer complete posts paired `OUT` and `IN` transfer transactions and adjusts source/destination stock
- Stock opname completion may post adjustment transactions based on discrepancy handling

## 6) Settings and Security Model

From `backend/config/settings.py`:

- `AUTH_USER_MODEL = "users.User"`
- `APP_VERSION` is loaded from root `VERSION` (semantic version `MAJOR.MINOR.PATCH`)
- `SECRET_KEY` loaded from environment and required (`os.environ[...]`)
- `DEBUG` defaults to `True` unless overridden by environment
- `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` are environment-driven comma-separated lists
- `AUTHENTICATION_BACKENDS` order:
  1. `axes.backends.AxesStandaloneBackend`
  2. `django.contrib.auth.backends.ModelBackend`
- `axes.middleware.AxesMiddleware` included after standard auth/session middleware
- `AXES_FAILURE_LIMIT = 5`, `AXES_COOLOFF_TIME = 0.5`, `AXES_RESET_ON_SUCCESS = True`
- `EMAIL_BACKEND` is environment-configurable and defaults to Django's console backend
- `DATA_UPLOAD_MAX_NUMBER_FIELDS` defaults to `10000` to support wide LPLPO and similar bulk forms
- Session hardening: `SESSION_COOKIE_HTTPONLY`, `SESSION_COOKIE_SAMESITE="Lax"`, browser-close expiry
- CSRF hardening: `CSRF_COOKIE_HTTPONLY`, `CSRF_COOKIE_SAMESITE="Lax"`
- Additional hardening when `DEBUG=False`: secure cookies, HSTS, frame deny, SSL redirect toggle, referrer policy

## 7) CSV Import Contract

### Generic admin import

- Uses django-import-export resources in `backend/apps/items/admin.py` and `backend/apps/stock/admin.py`
- `skip_unchanged = True` is enabled in multiple resources
- Standard flow includes dry-run then confirm import in admin UI

### Dedicated receiving CSV import

Defined in `backend/apps/receiving/admin.py` (`ReceivingAdmin.import_csv_view`):

- Endpoint: `/admin/receiving/receiving/import-csv/`
- Required columns: `document_number`, `receiving_date`, `item_code`, `sumber_dana_code`, `location_code`, `quantity`
- Optional columns: `receiving_type` (defaults to `GRANT`), `supplier_code`, `batch_lot`, `expiry_date`, `unit_price`
- Rows are grouped by `document_number`; first-row supplier and header values seed the parent `Receiving`
- Row-level `sumber_dana_code` and `location_code` may override the first-row values for each line item
- Supported date formats in parser:
  - `DD/MM/YYYY`
  - `YYYY-MM-DD`
  - `DD-MM-YYYY`
  - `DD/MM/YY`
- Decimal parser supports comma decimal separator
- Runs in `@transaction.atomic`

## 8) Documentation Maintenance Policy

If model fields, routes, settings, permission logic, or import behavior change:

1. Update this file first.
2. Update `README.md` and `AGENTS.md` to keep onboarding and operational docs aligned.
3. Update `docs/developer_guide.md` when developer workflow, release, or documentation-process guidance changes.
4. Update `backend/seed/README.md` when CSV import behavior, columns, or ordering changes.
5. Verify references against Context7 primary IDs:
   - `/django/django`
   - `/websites/django-import-export_readthedocs_io_en`
   - `/jazzband/django-axes`
