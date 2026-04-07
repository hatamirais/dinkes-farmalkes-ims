# SYSTEM_MODEL.md

Canonical reference for current schema, route topology, permission model, and stock mutation behavior.

Last verified: 2026-03-31
Verification sources: `backend/apps/*/models.py`, `backend/config/urls.py`, `backend/apps/*/urls.py`, `backend/apps/core/decorators.py`, `backend/apps/users/access.py`, `backend/config/settings.py`, `backend/apps/receiving/admin.py`

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
- `/users/`, `/items/`, `/stock/`, `/receiving/`, `/distribution/`, `/recall/`, `/expired/`, `/reports/`, `/stock-opname/`, `/puskesmas/`, `/lplpo/`, `/puskesmas/`, `/lplpo/`

Module highlights:

- Stock card: `/stock/stock-card/`, `/stock/stock-card/<item_id>/`
- Stock transfer: `/stock/transfers/*`
- Receiving plan: `/receiving/plans/*`
- Expiry alerts: `/expired/alerts/`
- LPLPO lists: `/lplpo/` (All), `/lplpo/my/` (Puskesmas scoped)
- Puskesmas requests: `/puskesmas/`

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

### 4.1 Shared base

- `TimeStampedModel` (`apps.core.models`)
  - `created_at`, `updated_at`

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

- `stock.Transaction` (`transactions`):
  - Types: `IN`, `OUT`, `ADJUST`, `RETURN`
  - Reference types: `RECEIVING`, `DISTRIBUTION`, `ADJUSTMENT`, `INITIAL_IMPORT`, `RECALL`, `EXPIRED`, `TRANSFER`
  - FKs: `item`, `location`, `sumber_dana` (nullable), `user`
  - Fields: `batch_lot`, `quantity`, `unit_price` (nullable), `reference_type`, `reference_id`, `notes`, `created_at`
  - Indexes: `idx_trans_item_date`, `idx_trans_reference`, `idx_trans_created`

- `stock.StockTransfer` (`stock_transfers`):
  - Status: `DRAFT`, `COMPLETED`
  - `document_number` auto-generated `TRF-YYYY-NNNNN` when blank
  - FKs: `source_location`, `destination_location`, `created_by`, `completed_by` (nullable)
  - Fields: `transfer_date`, `notes`, `completed_at`

- `stock.StockTransferItem` (`stock_transfer_items`):
  - FKs: `transfer`, `stock`, `item`
  - Fields: `quantity`, `notes`

### 4.5 Receiving

- `receiving.ReceivingTypeOption` (`receiving_type_options`): `code`, `name`, `is_active`

- `receiving.Receiving` (`receivings`):
  - Type: `PROCUREMENT`, `GRANT`
  - Status: `DRAFT`, `SUBMITTED`, `APPROVED`, `PARTIAL`, `RECEIVED`, `CLOSED`, `VERIFIED`
  - Fields: `document_number` (auto-generated `RCV-YYYY-NNNNN` when blank), `receiving_date`, `is_planned`, `grant_origin`, `program`, `closed_reason`, `notes`
  - FKs: `supplier` (nullable), `sumber_dana`, `created_by`, `verified_by` (nullable), `approved_by` (nullable), `closed_by` (nullable)
  - Index: `idx_recv_status_date`

- `receiving.ReceivingItem` (`receiving_items`):
  - FKs: `receiving`, `order_item` (nullable), `item`, `location` (nullable), `received_by` (nullable)
  - Fields: `quantity`, `batch_lot`, `expiry_date`, `unit_price`, `received_at`, `created_at`

- `receiving.ReceivingDocument` (`receiving_documents`):
  - FK: `receiving`
  - File fields: `file`, `file_name`, `file_type`, `uploaded_at`

- `receiving.ReceivingOrderItem` (`receiving_order_items`):
  - FKs: `receiving`, `item`
  - Fields: `planned_quantity`, `received_quantity`, `unit_price`, `notes`, `is_cancelled`, `cancel_reason`

### 4.6 Distribution

- `distribution.Distribution` (`distributions`):
  - Type: `LPLPO`, `ALLOCATION`, `SPECIAL_REQUEST`
  - Status: `DRAFT`, `SUBMITTED`, `VERIFIED`, `PREPARED`, `DISTRIBUTED`, `REJECTED`
  - Workflow includes manual reset action back to `DRAFT` from `SUBMITTED`, `VERIFIED`, `PREPARED`, and `REJECTED` (but not from `DISTRIBUTED`)
  - Provides `kepala_instalasi` and `petugas` assignments logic for print outputs
  - Fields: `document_number` (auto-generated `DIST-YYYYMM-XXXXX` when blank), `request_date`, `program`, `distributed_date`, `notes`, `ocr_text`
  - FKs: `facility`, `created_by`, `verified_by` (nullable), `approved_by` (nullable)
  - Indexes: `idx_dist_status_date`, `idx_dist_facility_date`

- `distribution.DistributionItem` (`distribution_items`):
  - FKs: `distribution`, `item`, `stock` (nullable)
  - Fields: `quantity_requested`, `quantity_approved` (nullable), `notes`, `created_at`

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
  - Constraints/Indexes: unique `(facility, bulan, tahun)`

- `lplpo.LPLPOItem` (`lplpo_items`):
  - FKs: `lplpo`, `item`
  - Puskesmas fields: `stock_awal`, `penerimaan`, `pemakaian`, `stock_gudang_puskesmas`, `waktu_kosong`, `permintaan_jumlah`, `permintaan_alasan`
  - Computed fields (auto): `persediaan`, `stock_keseluruhan`, `stock_optimum`, `jumlah_kebutuhan`
  - IF fields: `pemberian_jumlah` (nullable), `pemberian_alasan`
  - Audit: `penerimaan_auto_filled`

## 5) Stock Mutation Checkpoints

Operational mutation points (from app behavior and admin import logic):

- Receiving verify/receive path posts `Transaction(IN)` and updates/creates `Stock`.
- Receiving CSV admin import (`import-csv/`) posts:
  - `Receiving(status=VERIFIED)`
  - `ReceivingItem`
  - `Stock` update/create
  - `Transaction(IN)`
- LPLPO Finalize creates a Distribution document mapped 1:1.
- Distribution (current implementation does **not** use `Stock.reserved`):
  - prepare phase updates document status only (no stock mutation and no `stock.reserved` usage)
  - distribute phase allocates from and decreases `Stock.quantity` and posts `Transaction(OUT)`; any references in other docs (e.g. `.github/copilot-instructions.md`) to FEFO allocation via `Stock.reserved` are obsolete
- Recall verify decreases stock and posts `Transaction(OUT, reference_type=RECALL)`
- Expired verify decreases stock and posts `Transaction(OUT, reference_type=EXPIRED)`
- Stock transfer complete posts paired `OUT` and `IN` transfer transactions and adjusts source/destination stock
- Stock opname completion may post adjustment transactions based on discrepancy handling

## 6) Settings and Security Model

From `backend/config/settings.py`:

- `AUTH_USER_MODEL = "users.User"`
- `APP_VERSION` is loaded from root `VERSION` (semantic version `MAJOR.MINOR.PATCH`)
- `SECRET_KEY` loaded from environment and required (`os.environ[...]`)
- `AUTHENTICATION_BACKENDS` order:
  1. `axes.backends.AxesStandaloneBackend`
  2. `django.contrib.auth.backends.ModelBackend`
- `axes.middleware.AxesMiddleware` included after standard auth/session middleware
- `AXES_FAILURE_LIMIT = 5`, `AXES_COOLOFF_TIME = 0.5`, `AXES_RESET_ON_SUCCESS = True`
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
