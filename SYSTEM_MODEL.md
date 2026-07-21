# SYSTEM_MODEL.md

Canonical reference for current schema, route topology, permission model, and stock mutation behavior.

Last verified: 2026-07-14
Verification sources: `backend/apps/*/models.py`, `backend/config/urls.py`, `backend/apps/*/urls.py`, `backend/apps/core/decorators.py`, `backend/apps/users/access.py`, `backend/config/settings.py`, `backend/apps/receiving/admin.py`, `backend/apps/distribution/services.py`, `backend/apps/allocation/services.py`, `backend/apps/stock/views.py`, `backend/apps/lplpo/models.py`, `backend/apps/core/rate_limits.py`, `backend/apps/users/views.py`, `backend/apps/core/tests/test_auditlog_integration.py`

## 1) Domain Overview

Healthcare IMS is a Django monolith with server-rendered templates. Inventory is tracked at batch/location granularity and all movement is recorded in immutable `Transaction` rows.

Core domains:

- Master data and item catalog (`items`)
- Stock and movement journal (`stock`)
- Procurement contracts and amendments (`procurement`)
- Inbound receiving (`receiving`)
- Outbound distribution (`distribution`)
- Pre-distribution allocation orchestration (`allocation`)
- Supplier return (`recall`)
- Expired disposal (`expired`)
- Physical counting (`stock_opname`)
- Puskesmas ad-hoc requests (`puskesmas`)
- LPLPO reporting and requests (`lplpo`)
- Access and module scope control (`users`)

## 2) Route Topology

Root route include map from `backend/config/urls.py`:

- `/` -> dashboard (`apps.core.views.dashboard`)
- `/admin/` -> Django admin, including the `django-auditlog` `LogEntry` webview for authorized staff/admin users
- `/login/`, `/logout/`, `/password/change/`, `/password/change/done/`
  - `/password/change/` uses a rate-limited subclass of Django's `PasswordChangeView`
- `/settings/` -> system settings (`apps.core.views.SystemSettingsUpdateView`), restricted to superusers plus roles `ADMIN` and `KEPALA`
- `/maintenance/` -> maintenance preview / service unavailable page (`apps.core.views.maintenance_mode`, HTTP 503)
- `/users/`, `/items/`, `/stock/`, `/receiving/`, `/procurement/`, `/distribution/`, `/allocation/`, `/recall/`, `/expired/`, `/reports/`, `/stock-opname/`, `/puskesmas/`, `/lplpo/`

Global error handlers in `backend/config/urls.py`:

- `handler400` -> `apps.core.views.bad_request`
- `handler403` -> `apps.core.views.permission_denied_handler`
- `handler404` -> `apps.core.views.page_not_found_handler`
- `handler500` -> `apps.core.views.server_error_handler`

Module highlights:

- Stock card: `/stock/stock-card/`, `/stock/stock-card/<item_id>/`
- Puskesmas stock snapshot: `/stock/puskesmas-stock/`
- Stock transfer: `/stock/transfers/*`
- Receiving regular: `/receiving/`, `/receiving/create/`, `/receiving/<pk>/`, `/receiving/<pk>/documents/<document_pk>/download/`
- Receiving plan: `/receiving/plans/*`
  - Procurement-linked plans (`Receiving.contract != NULL`) are created and synchronized from approved SPJ contracts/amendments. Their leftover close action routes to procurement amendment creation, and the receiving-side close-items endpoint redirects direct access back to that amendment flow. Legacy manual planned receivings without `contract` remain readable and executable through the receiving close-items flow.
- Procurement: `/procurement/`, `/procurement/create/`, `/procurement/api/quick-create-supplier/`, `/procurement/api/quick-create-funding-source/`, `/procurement/<pk>/`, `/procurement/<pk>/edit/`, `/procurement/<pk>/submit/`, `/procurement/<pk>/approve/`, `/procurement/<pk>/close/`, `/procurement/<pk>/amend/`, `/procurement/amendments/<pk>/`, `/procurement/amendments/<pk>/edit/`, `/procurement/amendments/<pk>/submit/`, `/procurement/amendments/<pk>/approve/`
- Receiving quick-create APIs: `/receiving/api/quick-create-supplier/`, `/receiving/api/quick-create-funding-source/`, `/receiving/api/quick-create-receiving-type/`
- Items: `/items/`, `/items/export/`, `/items/create/`, `/items/<pk>/edit/`, `/items/<pk>/delete/`, plus quick-create lookup APIs under `/items/api/`
- Distribution history: `/distribution/`, `/distribution/report/`, `/distribution/report/special-requests/`, `/distribution/report/allocation/`, `/distribution/report/lplpo/`, `/distribution/create/`, `/distribution/lplpo/create/`, `/distribution/<pk>/`, `/distribution/<pk>/edit/`, `/distribution/<pk>/delete/`, `/distribution/<pk>/step-back/`, `/distribution/<pk>/reset-to-draft/`, `/distribution/<pk>/submit/`, `/distribution/<pk>/verify/`, `/distribution/<pk>/prepare/`, `/distribution/<pk>/distribute/`, `/distribution/<pk>/reject/`, `/distribution/<pk>/return-lplpo-to-puskesmas/`
- Special requests: `/distribution/special-requests/`, `/distribution/special-requests/create/`
- Expiry alerts: `/expired/alerts/`
- Reports: `/reports/`, `/reports/riwayat-penomoran/`, `/reports/rekap/`, `/reports/penerimaan-hibah/`, `/reports/pengadaan/`, `/reports/kadaluarsa/`, `/reports/pengeluaran/`
- LPLPO: `/lplpo/` (All), `/lplpo/my/` (Puskesmas scoped), `/lplpo/create/`, `/lplpo/print-report/`, `/lplpo/api/prefill-penerimaan/`, `/lplpo/<pk>/`, `/lplpo/<pk>/edit/`, `/lplpo/<pk>/export-xlsx/`, `/lplpo/<pk>/import-xlsx/`, `/lplpo/<pk>/submit/`, `/lplpo/<pk>/verify/`, `/lplpo/<pk>/reject/`, `/lplpo/<pk>/review/`, `/lplpo/<pk>/finalize/`, `/lplpo/<pk>/delete/`, `/lplpo/<pk>/print/`
  - `review/` is the active stock-planning checkpoint: PIC review saves `pemberian_*`, stamps review audit fields, and atomically creates the linked draft LPLPO distribution.
  - `finalize/` remains only as a compatibility endpoint for older rows still stuck in `REVIEWED` from the previous workflow.
  - Super Admin sees all statuses on `/lplpo/` and can perform create/edit/submit/delete across facilities.
  - Puskesmas-owned routes and states stay facility-scoped for all non-superusers: `DRAFT`, `REJECTED_PUSKESMAS`, edit, submit, delete, XLSX export/import, and the prefill helper all require a linked `user.facility` and stay same-facility only.
  - Instalasi Farmasi LPLPO access is stage-gated across facilities: `GUDANG` may access queue/detail/print on `SUBMITTED`, `PIC_VERIFIED`, `REJECTED_PIC`, `APPROVED`, and `CLOSED` documents, verify/reject `SUBMITTED` documents, and review `PIC_VERIFIED` / `REJECTED_PIC` documents; `KEPALA` only gets cross-facility LPLPO access on legacy `REVIEWED/finalize` and read-only historical `APPROVED` / `CLOSED` states. Users whose role is exactly `ADMIN` (not `ADMIN_UMUM`) may directly reject active LPLPO documents without a linked distribution back to `REJECTED_PUSKESMAS`, including `PIC_VERIFIED`.
  - Non-Puskesmas non-superuser staff continue to use `/lplpo/` as the submitted queue only.
  - `api/prefill-penerimaan/` sources monthly totals and weighted-average unit prices from same-facility/month `puskesmas.PuskesmasReceiptConfirmationItem` rows, including January bootstrap as an editable suggestion baseline when confirmed receipt data exists.
  - `/export-xlsx/` and `/import-xlsx/` are draft-only offline-entry helpers for Puskesmas operators and super admins. They work only on existing `DRAFT` / `REJECTED_PUSKESMAS` documents after the standard monthly create flow has already generated the item rows.
- Puskesmas stock self-check: `/puskesmas/stok/`
  - Only users with role `PUSKESMAS` may access this page, and every request is scoped to `request.user.facility`; unlinked Puskesmas users receive `403`.
  - Uses the latest non-rejected LPLPO for the linked facility/year and compares `LPLPOItem.stock_keseluruhan` against `LPLPOItem.stock_gudang_puskesmas` as a read-only digital-vs-physical check. It does not apply post-LPLPO receipt/consumption adjustments and does not mutate stock.
- Puskesmas requests: `/puskesmas/permintaan/`, `/puskesmas/permintaan/buat/`, `/puskesmas/permintaan/<pk>/`, `/puskesmas/permintaan/<pk>/edit/`, `/puskesmas/permintaan/<pk>/delete/`, `/puskesmas/permintaan/<pk>/submit/`, `/puskesmas/permintaan/<pk>/approve/`, `/puskesmas/permintaan/<pk>/reject/`, `/puskesmas/permintaan/<pk>/reset-draft/`
  - Superusers may work across facilities, while every non-superuser request is forced to the linked `user.facility` and receives `403` when no facility is linked or the object belongs to another facility.
  - Report routes `/puskesmas/laporan/penerimaan/`, `/puskesmas/laporan/pemakaian/`, `/puskesmas/laporan/persediaan/`, and `/puskesmas/laporan/rekap-persediaan/` are all-facility only for superusers; every non-superuser request is forced to the request user's linked facility.
- Puskesmas subunits: `/puskesmas/subunit/`, `/puskesmas/subunit/buat/`, `/puskesmas/subunit/<pk>/edit/`, `/puskesmas/subunit/<pk>/delete/`
  - Stores dynamic room/helper-site columns per facility for the detailed consumption matrix.
  - Only `PUSKESMAS` role users and superusers may mutate subunit rows.
- Puskesmas detailed consumption: `/puskesmas/pemakaian/`, `/puskesmas/pemakaian/buat/`, `/puskesmas/pemakaian/<pk>/`, `/puskesmas/pemakaian/<pk>/edit/`, `/puskesmas/pemakaian/<pk>/delete/`
  - Only `PUSKESMAS` role users and superusers may create, edit, or delete detailed consumption.
  - Detailed-consumption mutations are blocked when the same facility-month LPLPO already exists in any status beyond `DRAFT` or `REJECTED_PUSKESMAS`.
  - Create/edit/delete is rate-limited by `PUSKESMAS_CONSUMPTION_MUTATION_RATE_LIMIT` and each mutation atomically re-syncs same-month editable LPLPO `pemakaian` totals. Opening or re-saving an editable LPLPO also refreshes those totals when the matching detailed-consumption document already exists.
- Puskesmas receipt confirmation: `/puskesmas/penerimaan/`, `/puskesmas/penerimaan/buat/`, `/puskesmas/penerimaan/<pk>/`, `/puskesmas/penerimaan/<pk>/edit/`, `/puskesmas/penerimaan/<pk>/delete/`
  - Only `PUSKESMAS` role users and superusers may create, edit, or delete receipt confirmations.
  - Linked operational create/edit uses a fixed checklist per `distribution.DistributionItem`; checked rows become stored receipt items and unchecked rows require a header note while staying out of LPLPO aggregation.
  - Receipt-confirmation mutations are blocked when the same facility-month LPLPO already exists in any status beyond `DRAFT` or `REJECTED_PUSKESMAS`.
  - Create/edit/delete is rate-limited by `PUSKESMAS_RECEIPT_CONFIRMATION_MUTATION_RATE_LIMIT` and each mutation atomically re-syncs same-month editable LPLPO lines. Opening or re-saving an editable LPLPO also refreshes same-month `penerimaan` and weighted `harga_satuan` when confirmed receipt-confirmation rows already exist.
- Allocation: `/allocation/`, `/allocation/create/`, `/allocation/<pk>/`, `/allocation/<pk>/edit/`, `/allocation/<pk>/delete/`, `/allocation/<pk>/reset-to-draft/`, `/allocation/<pk>/submit/`, `/allocation/<pk>/approve/`, `/allocation/<pk>/step-back/`, `/allocation/<pk>/reject/`, `/allocation/<pk>/distributions/<dist_pk>/prepare/`, `/allocation/<pk>/distributions/<dist_pk>/deliver/`
- Users sensitive POST actions: `/users/bulk-action/`, `/users/<pk>/toggle-active/`, `/users/<pk>/delete/`, `/users/<pk>/reset-password/`

## 3) Permission and Access Model

Hybrid authorization in `@perm_required`:

1. Django permission (`request.user.has_perm`)
2. Module-scope fallback (`has_module_permission`)

Permission denials are expected to raise `PermissionDenied` so the centralized 403 handler can render the standard fallback-aware error page and emit structured logs.

`ModuleAccess.module` values:

- `users`, `items`, `stock`, `receiving`, `procurement`, `distribution`, `allocation`, `recall`, `expired`, `stock_opname`, `reports`, `puskesmas`, `lplpo`, `admin_panel`

`ModuleAccess.scope` values:

- `0 NONE`, `1 VIEW`, `2 OPERATE`, `3 APPROVE`, `4 MANAGE`

Special rule:

- For `users.*` permissions, non-view actions require `MANAGE` scope.
- `puskesmas` facility isolation applies to every non-superuser account, with Super Admin users (`is_superuser`) as the only fully cross-facility users. `lplpo` is split: Puskesmas-owned stages remain same-facility for non-superusers, while Instalasi Farmasi roles receive limited cross-facility access based on route/action and `LPLPO.status`.
- Puskesmas report routes require `reports.view_reports` (or REPORTS module-scope VIEW fallback), and their facility isolation is stricter than the general module access model: superusers may query all facilities, while every non-superuser must have a linked `facility` and is scoped to it.
- Puskesmas receipt-confirmation create/edit/delete routes add a role gate on top of module access: only `User.Role.PUSKESMAS` and superusers can manage receipt-confirmation mutations.
- Puskesmas subunit and detailed-consumption create/edit/delete routes add the same role gate: only `User.Role.PUSKESMAS` and superusers can manage those mutations.
- `/settings/` is an explicit role-gated exception outside the hybrid `@perm_required` path: only superusers plus `User.Role.ADMIN` and `User.Role.KEPALA` may open or update system settings.
- Procurement SPJ and amendment approval actions combine module scope with an explicit role gate: superusers/Admin and `KEPALA` may approve when they have the required procurement approval scope, while `GUDANG` remains limited to operate/create/submit behavior and cannot approve even if its procurement module scope is elevated.
- `AUDITOR` retains read-only module scopes for direct authorized pages, but the global sidebar renders only the `Laporan` group for this role and the dashboard suppresses linked drill-through cards/sections that open operational menus.

Role default scopes are seeded in `backend/apps/users/access.py` via `ROLE_DEFAULT_SCOPES`.

## 4) Canonical Schema

This section reflects model code in `backend/apps/*/models.py`.

### 4.1 Shared base & Settings

- `TimeStampedModel` (`apps.core.models`)
  - `created_at`, `updated_at`

- `core.SystemSettings` (`system_settings`)
  - Singleton model (forced `id=1`) for global dynamic settings.
  - Fields: `platform_label`, `facility_name`, `facility_address`, `facility_phone`, `header_title`, `lplpo_distribution_number_template`, `special_request_distribution_number_template`, `logo`

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
- `items.TherapeuticClass` (`therapeutic_classes`): `code`, `name`, `description`, `is_active`
- `items.Location` (`locations`): `code`, `name`, `description`, `is_active`
- `items.Supplier` (`suppliers`): `code`, `name`, `address`, `phone`, `email`, `notes`, `is_active`
- `items.Facility` (`facilities`): `code`, `name`, `address`, `phone`, `facility_type`, `is_active`
  - `facility_type` choices: `PUSKESMAS`, `RS`, `CLINIC`, `LABORATORIUM`
- `items.Item` (`items`):
  - `kode_barang` (unique, auto-generated `ITM-YYYY-NNNNN` when blank)
  - `barcode` (optional, unique when present, reserved for future scanner workflows)
  - `nama_barang`
  - `satuan` FK -> `Unit`
  - `kategori` FK -> `Category`
  - `is_program_item` — designated program item `[P]`
  - `is_essential` — designated essential item `[E]`
  - `program` FK -> `Program` (nullable)
  - M2M: `therapeutic_classes` -> `TherapeuticClass` (optional, multi-value reporting groups)
  - `requires_expiry_date` — item-level control for whether receiving/stock batches must capture an expiry date
  - `minimum_stock`, `description`, `is_active`
  - Index: `idx_item_category_program` on `(kategori, is_program_item)`

### 4.4 Stock and transactions

- `stock.Stock` (`stock`):
  - FKs: `item`, `location`, `sumber_dana`, `receiving_ref` (nullable)
  - Fields: `batch_lot`, `expiry_date` (nullable for non-expiring stock), `quantity`, `reserved`, `unit_price`
  - Semantics: `quantity` is physical stock, `reserved` is outbound stock already booked by active distribution documents, and `available_quantity = quantity - reserved` is the allocatable balance shown on LPLPO review, allocation, special-request, and stock summary surfaces
  - Unique: `uq_stock_batch` on `(item, location, batch_lot, sumber_dana)`
  - Checks: `quantity >= 0`, `reserved >= 0`
  - Indexes: `idx_stock_fefo`, `idx_stock_expiry`, `idx_stock_item_loc`
  - Properties: `available_quantity`, `total_value`, `is_expired`, `is_near_expiry`

- `stock.Transaction` (`transactions`):
  - Types: `IN`, `OUT`, `ADJUST`, `RETURN`
  - Reference types: `RECEIVING`, `DISTRIBUTION`, `ADJUSTMENT`, `INITIAL_IMPORT`, `RECALL`, `EXPIRED`, `TRANSFER`, `ALLOCATION`
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

### 4.5 Procurement

- `procurement.ProcurementContract` (`procurement_contracts`):
  - Status: `DRAFT`, `SUBMITTED`, `APPROVED`, `CLOSED`
  - Fields: `document_number` (auto-generated `SPJ-YYYY-NNNNN` when blank; manual input is limited to 95 characters to reserve `{SPJ}-A{seq}` amendment suffix space inside the 100-character storage field), `contract_date`, `notes`
  - FKs: `supplier`, `sumber_dana`, `created_by`, `submitted_by` (nullable), `approved_by` (nullable), `closed_by` (nullable)
  - Timestamps: `submitted_at`, `approved_at`, `closed_at`
  - Index: `idx_proc_contract_status_date`
  - Contract create/edit templates expose authenticated quick-create modals for `Supplier` and `FundingSource` through procurement-scoped POST endpoints that reuse receiving lookup validation
  - Approval is restricted to Admin/Superuser or `KEPALA` with procurement approval scope and atomically creates or updates exactly one linked planned `receiving.Receiving(contract=this, is_planned=True)` document

- `procurement.ProcurementContractLine` (`procurement_contract_lines`):
  - FKs: `contract`, `item`
  - Fields: `original_quantity`, `original_unit_price`, `notes`
  - Unique: `(contract, item)`

- `procurement.ProcurementAmendment` (`procurement_amendments`):
  - Status: `DRAFT`, `SUBMITTED`, `APPROVED`
  - Fields: `document_number` (auto-generated from the parent SPJ as `{contract.document_number}-A{seq}` when blank, for example `SPJ-2026-00001-A1`), `amendment_date`, `notes`
  - FKs: `contract`, `created_by`, `submitted_by` (nullable), `approved_by` (nullable)
  - Timestamps: `submitted_at`, `approved_at`
  - Index: `idx_proc_amend_status_date`
  - Approval is restricted to Admin/Superuser or `KEPALA` with procurement approval scope, re-syncs the linked planned procurement receiving against the newly effective contract state, and rejects revised quantities below already received quantities

- `procurement.ProcurementAmendmentLine` (`procurement_amendment_lines`):
  - FKs: `amendment`, `contract_line`
  - Fields: `revised_quantity`, `revised_unit_price`, `notes`
  - Unique: `(amendment, contract_line)`

### 4.6 Receiving

- `receiving.ReceivingTypeOption` (`receiving_type_options`): `code`, `name`, `is_active`
  - Used by quick-create receiving type UI and by `Receiving.receiving_type_label` to resolve non-built-in labels

- `receiving.Receiving` (`receivings`):
  - Type: `PROCUREMENT`, `GRANT`
  - Status: `DRAFT`, `SUBMITTED`, `APPROVED`, `PARTIAL`, `RECEIVED`, `CLOSED`, `VERIFIED`
  - Fields: `document_number` (auto-generated `RCV-YYYY-NNNNN` when blank), `receiving_date`, `is_planned`, `grant_origin`, `program`, `closed_reason`, `notes`
  - FKs: `contract` (nullable FK to `procurement.ProcurementContract`), `supplier` (nullable), `facility` (nullable), `sumber_dana`, `created_by`, `verified_by` (nullable), `approved_by` (nullable), `closed_by` (nullable)
  - Timestamps: `verified_at`, `approved_at`, `closed_at`
  - Index: `idx_recv_status_date`
  - Properties: `receiving_type_label`
  - Custom receiving types can still be stored in `receiving_type`; built-in display labels come from `ReceivingType`, while non-built-in labels are resolved from `ReceivingTypeOption`

- `receiving.ReceivingItem` (`receiving_items`):
  - FKs: `receiving`, `order_item` (nullable), `item`, `location` (nullable), `settlement_distribution_item` (nullable), `received_by` (nullable)
  - Fields: `quantity`, `batch_lot`, `expiry_date` (nullable only when `item.requires_expiry_date=False`), `unit_price`, `received_at`, `created_at`
  - Property: `total_price`

- `receiving.ReceivingDocument` (`receiving_documents`):
  - FK: `receiving`
  - File fields: `file`, `file_name`, `file_type`, `uploaded_at`
  - `file` uses private filesystem storage rooted at `PRIVATE_MEDIA_ROOT`; user access is mediated by the authenticated receiving download route rather than `MEDIA_URL`

- `receiving.ReceivingOrderItem` (`receiving_order_items`):
  - FKs: `receiving`, `item`, `contract_line` (nullable FK to `procurement.ProcurementContractLine`)
  - Fields: `planned_quantity`, `received_quantity`, `unit_price`, `notes`, `is_cancelled`, `cancel_reason`
  - Property: `remaining_quantity`

### 4.6 Distribution

- `distribution.Distribution` (`distributions`):
  - Type: `LPLPO`, `ALLOCATION`, `SPECIAL_REQUEST`
  - Status: `DRAFT`, `SUBMITTED`, `VERIFIED`, `GENERATED`, `PREPARED`, `DISTRIBUTED`, `REJECTED`
  - Current allocation workflow auto-generates child distributions directly in `VERIFIED`; `GENERATED` remains in the enum for compatibility with older rows and migrations, but is not emitted by the active services
  - Current regular/special-request workflow is `DRAFT/REJECTED -> PREPARED -> SUBMITTED -> VERIFIED -> DISTRIBUTED`
  - Generated LPLPO draft distributions keep the reviewed LPLPO quantities immutable on the distribution edit screen; that edit step is limited to batch selection, notes, staff, and other header metadata
  - Manual LPLPO distributions can also be created from `/distribution/lplpo/create/` as an operational fallback when monthly LPLPO documents are not yet available. These records still use `distribution_type=LPLPO` and the same numbering/reporting bucket, but they do not have an `lplpo_source` document and therefore remain editable like normal draft distributions.
  - Workflow includes manual reset action back to `DRAFT` from `SUBMITTED`, `VERIFIED`, `PREPARED`, and `REJECTED` (but not from `DISTRIBUTED` or compatibility-only `GENERATED`)
  - Provides `kepala_instalasi` and `petugas` assignments logic for print outputs
  - Fields: `document_number` (auto-generated `DIST-YYYYMM-XXXXX` when blank for non-rule types; `LPLPO` and `SPECIAL_REQUEST` use the templates stored in `SystemSettings`), `request_date`, `program`, `distributed_date`, `notes`, `ocr_text`
  - Special-request create/edit form preloads the currently suggested document number, keeps automatic generation when the suggestion is left unchanged, and requires explicit UI confirmation before manual edits are enabled.
  - FKs: `facility`, `created_by`, `verified_by` (nullable), `approved_by` (nullable), `allocation` (nullable, links to parent `allocation.Allocation` for auto-generated distributions)
  - Indexes: `idx_dist_status_date`, `idx_dist_facility_date`

- `distribution.DistributionItem` (`distribution_items`):
  - FKs: `distribution`, `item`, `stock` (nullable)
  - Fields: `quantity_requested`, `quantity_approved` (nullable), `reserved_quantity`, `issued_batch_lot`, `issued_expiry_date`, `issued_unit_price`, `notes`, `created_at`
  - `reserved_quantity` stores how much stock is currently booked for that row so reservation release/reapply remains deterministic across edits, standalone reset/step-back, allocation step-back, delete, and final fulfillment
  - FKs also include `issued_sumber_dana` (nullable) to preserve the book-value source used when stock is distributed

- `distribution.DistributionStaffAssignment` (`distribution_staff_assignments`):
  - FKs: `distribution`, `user`
  - Purpose: stores staff involved in a distribution document, surfaces them in detail/print output, and acts as the object-level authorization source for draft/rejected preparation, submission, and final fulfillment
  - Constraint: unique pair per (`distribution`, `user`)

### 4.7 Allocation

- `allocation.Allocation` (`allocations`):
  - Status: `DRAFT`, `SUBMITTED`, `APPROVED`, `PARTIALLY_FULFILLED`, `FULFILLED`, `REJECTED`
  - Fields: `document_number` (auto-generated `ALK-YYYY-NNNN` when blank), `title`, `allocation_date`, `referensi`, `notes`, `rejection_reason`
  - FKs: `created_by`, `submitted_by` (nullable), `approved_by` (nullable)
  - Timestamps: `submitted_at`, `approved_at`
  - Index: `idx_alloc_status_date` on `(status, allocation_date)`
  - Approval triggers atomic auto-generation of one `Distribution` per facility (type=ALLOCATION, status=VERIFIED)
  - `title` is an optional document header field intended for display and future print/report output
  - Funding source is derived from each selected stock batch rather than stored on the allocation header
  - Stock deduction occurs at each child Distribution's delivery confirmation, not on the Allocation itself
  - Allocation auto-transitions to `PARTIALLY_FULFILLED` / `FULFILLED` based on child Distribution delivery progress

- `allocation.AllocationItem` (`allocation_items`):
  - FKs: `allocation`, `item`, `stock` (nullable)
  - Fields: `total_qty_available` (snapshot at draft time), `notes`
  - Property: `total_qty_allocated` (computed sum of child facility allocations)

- `allocation.AllocationItemFacility` (`allocation_item_facilities`):
  - FKs: `allocation_item`, `facility`
  - Fields: `qty_allocated`
  - Unique: `(allocation_item, facility)`
  - Quantities are locked after approval

- `allocation.AllocationFacility` (`allocation_facilities`):
  - FKs: `allocation`, `facility`
  - Purpose: header-level facility selection for the matrix UI
  - Unique: `(allocation, facility)`

- `allocation.AllocationStaffAssignment` (`allocation_staff_assignments`):
  - FKs: `allocation`, `user`
  - Unique: `(allocation, user)`

### 4.8 Recall

- `recall.Recall` (`recalls`):
  - Status: `DRAFT`, `SUBMITTED`, `VERIFIED`, `COMPLETED`
  - Fields: `document_number` (auto-generated `REC-YYYYMM-XXXXX` when blank), `recall_date`, `notes`
  - FKs: `supplier`, `created_by`, `verified_by` (nullable), `completed_by` (nullable)
  - Timestamps: `verified_at`, `completed_at`

- `recall.RecallItem` (`recall_items`):
  - FKs: `recall`, `item`, `stock`
  - Fields: `quantity`, `notes`, `created_at`

### 4.9 Expired

- `expired.Expired` (`expired_docs`):
  - Status: `DRAFT`, `SUBMITTED`, `VERIFIED`, `DISPOSED`
  - Fields: `document_number` (auto-generated `EXP-YYYYMM-XXXXX` when blank), `report_date`, `notes`
  - FKs: `created_by`, `verified_by` (nullable), `disposed_by` (nullable)
  - Timestamps: `verified_at`, `disposed_at`

- `expired.ExpiredItem` (`expired_items`):
  - FKs: `expired`, `item`, `stock`
  - Fields: `quantity`, `notes`, `created_at`

### 4.10 Stock opname

- `stock_opname.StockOpname` (`stock_opnames`):
  - Period type: `MONTHLY`, `QUARTERLY`, `SEMESTER`, `YEARLY`
  - Status: `DRAFT`, `IN_PROGRESS`, `COMPLETED`
  - Fields: `document_number` (auto-generated `SO-YYYYMM-XXXXX` when blank), `period_start`, `period_end`, `notes`, `completed_at`
  - FK: `created_by`, `completed_by` (nullable)
  - M2M: `categories` -> `items.Category`, `assigned_to` -> `users.User`

- `stock_opname.StockOpnameItem` (`stock_opname_items`):
  - FKs: `stock_opname`, `stock`
  - Fields: `system_quantity`, `actual_quantity` (nullable), `notes`, `created_at`, `updated_at`
  - Unique: `(stock_opname, stock)`

### 4.11 Reports

- `reports`: Contains views, templates, and services for inventory, expiry, receiving, outbound, and document-numbering-history reporting with Excel export capabilities. The procurement receiving report now includes `Receiving.contract.document_number` so realized receipts can be traced back to SPJ contracts. The combined outbound recap remains available on `/reports/pengeluaran/`, while the distribution module exposes route-based filtered variants for `SPECIAL_REQUEST`, `ALLOCATION`, and `LPLPO` under `/distribution/report/*`. No bespoke database models, aggregates data from other apps.
- `stock` also exposes an Instalasi Farmasi-facing read-only `/stock/puskesmas-stock/` page that computes current Puskesmas stock from the latest usable yearly LPLPO baseline plus later same-year `CONFIRMED` receipt confirmations minus later same-year detailed consumption. The page is intentionally non-CRUD and hidden from `PUSKESMAS` role users.
  The Puskesmas-side `Rincian Persediaan` report uses the same source model within the selected period: latest usable LPLPO up to the period end month, plus later same-year `CONFIRMED` receipt confirmations up to the period end month, minus later same-year detailed consumption up to the period end month. Facilities without a usable LPLPO baseline are skipped rather than using distribution-only fallback stock.
  The Puskesmas-side rekap persediaan view now also aggregates valuation data from `lplpo.LPLPOItem.harga_satuan` into category-level summary rows.
  The Puskesmas-side rincian/rekap persediaan filters use yearly, quarterly (`Triwulan I-IV`), and semester (`Semester I-II`) period selectors.

### 4.12 Puskesmas

- `puskesmas.PuskesmasReceiptConfirmation` (`puskesmas_sbbks`):
  - Fields: `document_number` (auto-generated `RCVCONF-YYYYMM-XXXXX` when blank), `received_date`, `status` (`DRAFT` / `CONFIRMED`), `notes`
  - FKs: `facility` (puskesmas only), `distribution` (nullable OneToOne to `distribution.Distribution`), `created_by`
  - Indexes: `idx_sbbk_facility_date` on `(facility, received_date)`
  - Purpose: receiver-side confirmation header for goods actually received from Instalasi Farmasi; source of truth for Puskesmas receipt history and monthly LPLPO `penerimaan`
  - Behavior: linked operational receipts can be saved as `DRAFT` when goods are incomplete; only `CONFIRMED` rows are treated as finalized receipt data for LPLPO
  - Compatibility: legacy migrated rows may remain `distribution=NULL` and are still editable through a dedicated compatibility path

- `puskesmas.PuskesmasReceiptConfirmationItem` (`puskesmas_sbbk_items`):
  - FKs: `sbbk`, `item`, `distribution_item` (nullable FK to `distribution.DistributionItem`)
  - Fields: `quantity`, `unit_price`, `batch_lot`, `expiry_date`, `notes`, `created_at`
  - Behavior: linked operational rows are now copied directly from checked `distribution_item` source rows, one stored row per confirmed source line; duplicate/manual split rows remain possible only on legacy compatibility edits
  - Compatibility: legacy migrated rows may remain `distribution_item=NULL`; new operational rows are expected to carry source linkage
  - Derived usage: same-facility/month aggregates from `sbbk.status='CONFIRMED'` feed LPLPO `penerimaan` totals and weighted-average `harga_satuan` autofill

- `puskesmas.PuskesmasSubunit` (`puskesmas_subunits`):
  - Purpose: facility-specific reporting bucket for treatment rooms and helper sites
  - Fields: `name`, `subunit_type`, `sort_order`, `is_active`
  - FKs: `facility` (puskesmas only)
  - Constraint: unique `(facility, name)`

- `puskesmas.PuskesmasConsumption` (`puskesmas_consumptions`):
  - Purpose: monthly detailed consumption header per Puskesmas
  - Fields: `bulan`, `tahun`, `notes`
  - FKs: `facility` (puskesmas only), `created_by`, `updated_by` (nullable)
  - Constraint: unique `(facility, bulan, tahun)`
  - Index: `idx_pkcons_fac_period` on `(facility, tahun, bulan)`

- `puskesmas.PuskesmasConsumptionEntry` (`puskesmas_consumption_entries`):
  - Purpose: normalized item-by-subunit quantity rows for one monthly detailed-consumption document
  - FKs: `consumption`, `item`, `subunit`
  - Fields: `quantity`
  - Constraint: unique `(consumption, item, subunit)`
  - Summed per item, same facility/month, into `lplpo.LPLPOItem.pemakaian`

- `puskesmas.PuskesmasRequest` (`puskesmas_requests`):
  - Status: `DRAFT`, `SUBMITTED`, `APPROVED`, `REJECTED`
  - Fields: `document_number` (auto-generated `REQ-YYYYMM-XXXXX` when blank), `request_date`, `notes`, `rejection_reason`
  - FKs: `facility` (puskesmas only), `program` (nullable), `created_by`, `approved_by` (nullable), `distribution` (nullable OneToOne)
  - Timestamps: `approved_at`
  - Indexes: `idx_pkreq_status_date`, `idx_pkreq_facility_date`

- `puskesmas.PuskesmasRequestItem` (`puskesmas_request_items`):
  - FKs: `request`, `item`
  - Fields: `quantity_requested`, `quantity_approved` (nullable), `notes`

Puskesmas stock self-check:

- Route `/puskesmas/stok/` is a read-only view, not a database model.
- It selects the latest same-year LPLPO for the logged-in Puskesmas user's linked facility, excluding `REJECTED_PUSKESMAS` and `REJECTED_PIC`.
- It renders each selected `LPLPOItem` with digital stock (`stock_keseluruhan`), recorded physical stock (`stock_gudang_puskesmas`), and the difference for manual reconciliation.

### 4.13 LPLPO

- `lplpo.LPLPO` (`lplpos`):
  - Status: `DRAFT`, `SUBMITTED`, `PIC_VERIFIED`, `REJECTED_PUSKESMAS`, `REVIEWED`, `REJECTED_PIC`, `APPROVED`, `DISTRIBUTED`, `CLOSED`
  - Fields: `bulan`, `tahun`, `document_number` (auto-generated `LPLPO-YYYYMM-XXXXX` when blank), `rejection_reason`, `notes`
  - FKs: `facility` (puskesmas only), `created_by`, `verified_by` (nullable), `reviewed_by` (nullable), `approved_by` (nullable), `distribution` (nullable OneToOne)
  - Timestamps: `submitted_at`, `verified_at`, `reviewed_at`, `approved_at`
  - Constraints/Indexes: `uq_lplpo_facility_period` unique on `(facility, bulan, tahun)`, `idx_lplpo_facility_period` on `(facility, tahun, bulan)`, `idx_lplpo_status` on `(status)`
  - Workflow is `DRAFT -> SUBMITTED -> PIC_VERIFIED -> APPROVED -> CLOSED` for active documents; `REVIEWED` remains as a legacy compatibility status for older rows.
  - The active rejection loop is `SUBMITTED -> REJECTED_PUSKESMAS`. The legacy `REVIEWED -> REJECTED_PIC` loop remains only for older documents. The `ADMIN` role has an override to reject active no-distribution LPLPO documents from later pre-distribution statuses back to `REJECTED_PUSKESMAS`; `ADMIN_UMUM` does not receive this override.
  - While the generated distribution is still pending fulfillment, an approved LPLPO may also be returned to `REJECTED_PUSKESMAS` by cancelling its generated distribution with a required rejection reason

- `lplpo.LPLPOItem` (`lplpo_items`):
  - FKs: `lplpo`, `item`
  - Puskesmas fields: `stock_awal`, `penerimaan`, `harga_satuan`, `pemakaian`, `stock_gudang_puskesmas`, `waktu_kosong`, `permintaan_jumlah`, `permintaan_alasan`
  - Computed fields (auto): `persediaan` (`stock_awal + penerimaan`), `stock_keseluruhan`, `stock_optimum`, `jumlah_kebutuhan`
  - IF fields: `pemberian_jumlah` (nullable), `pemberian_alasan`
  - Audit: `penerimaan_auto_filled`
  - Create flow is locked to the active server-calendar year and must be contiguous from January; each facility can only create the earliest missing month for that year
  - The first January document in the active server year is the annual bootstrap baseline; the create/edit UI explains that `stock_awal` is entered manually from facility opening records
  - That same January bootstrap still keeps `stock_awal` manual, but may auto-suggest `penerimaan`, set `penerimaan_auto_filled=True`, and fill `harga_satuan` from the same-month confirmed receipt weighted average while remaining editable by the operator
  - February onward auto-fills `stock_awal` from the previous month's LPLPO for the same facility when that prior document exists and is not `REJECTED_PUSKESMAS` or `REJECTED_PIC`; negative closing balances are carried forward as-is so operators can see and correct underreported stock
- February onward derives `penerimaan` from same-facility/month `puskesmas.PuskesmasReceiptConfirmationItem.quantity` totals
- February onward derives `harga_satuan` from the weighted-average same-facility/month `puskesmas.PuskesmasReceiptConfirmationItem.unit_price` values and falls back to the previous month's LPLPO unit price when there is no new receipt
- `pemakaian` is now derived from same-facility/month `puskesmas.PuskesmasConsumptionEntry.quantity` totals and is read-only on the LPLPO edit screen
- Draft/rejected rows can also be updated through the XLSX offline-entry round trip; import updates only `stock_awal`, `penerimaan`, `harga_satuan`, `stock_gudang_puskesmas`, `waktu_kosong`, `permintaan_jumlah`, and `permintaan_alasan`, then recomputes derived fields server-side while preserving `pemakaian` and reviewer fields

## 5) Stock Mutation Checkpoints

Operational mutation points (from app behavior and admin import logic):

- Procurement contract/amendment approval is restricted to Admin/Superuser or `KEPALA` with procurement approval scope and never mutates stock; it only creates or re-syncs the linked planned receiving execution document.
- Procurement-linked receiving leftovers are closed audit-first through procurement amendments; direct receiving-side close-items cancellation is reserved for non-contract planned receivings.
- Receiving verify/receive path posts `Transaction(IN)` and updates/creates `Stock`.
- Receiving CSV admin import (`import-csv/`) posts:
  - `Receiving(status=VERIFIED)`
  - `ReceivingItem`
  - `Stock` update/create
  - `Transaction(IN)`
  - Rows are grouped by `document_number`; the first row supplies header-level values, while row-level `sumber_dana_code` and `location_code` can override header defaults
- Receiving CSV admin template download (`export-csv-template/`) returns a blank `receiving_template.csv` with the exact columns accepted by the dedicated importer and does not mutate data.
- LPLPO approval/finalize creates a Distribution document mapped 1:1, marks the LPLPO `APPROVED`, and closes the LPLPO once the linked Distribution reaches `DISTRIBUTED`.
- For generated LPLPO draft distributions, the preparation edit UI displays both requested and approved quantities for reference but locks those values and rejects added/deleted rows; users only assign batches and preparation metadata there.
- Generated LPLPO distributions cannot use the generic delete action. While still pending distribution, assigned distribution preparers or fallback distribution approvers with LPLPO module scope `OPERATE` may use `/distribution/<pk>/return-lplpo-to-puskesmas/` with a required reason to cancel the generated distribution and return the parent LPLPO to `REJECTED_PUSKESMAS`.
- Distribution:
  - verification and distribution validations use `Stock.available_quantity` (`quantity - reserved`) when checking the selected batch
  - prepare phase updates document status only (no stock mutation and no reservation write)
  - draft/rejected preparation, submission, and final standalone distribution are restricted to assigned `DistributionStaffAssignment` users, with approve-scope users as a fallback only when no staff assignments exist
  - reset-to-draft, step-back, and delete use that same object-level assignee/fallback authorization rule before their status guards run
  - verify phase now locks the selected stock rows and increments `Stock.reserved` while copying the same amount into `DistributionItem.reserved_quantity`
  - reset-to-draft, step-back from `VERIFIED`, generated-LPLPO reversal, and delete release `reserved` using `DistributionItem.reserved_quantity` for standalone distributions, while allocation-generated child distributions release reservations only through parent allocation step-back
  - generated-LPLPO reversal uses the same object-level assignee/fallback authorization as preparation actions and requires LPLPO module scope `OPERATE`
  - distribute phase decreases `Stock.quantity`, clears the matching reserved balance, snapshots the issued batch/value fields, and posts `Transaction(OUT)`
- Recall verify decreases stock and posts `Transaction(OUT, reference_type=RECALL)`
- Expired verify is restricted to Kepala/Admin approvers, decreases stock, and posts `Transaction(OUT, reference_type=EXPIRED)`. After verification, Gudang/Kepala/Admin users with expired operate scope may mark the document `DISPOSED` to finalize the physical disposal audit stamp without another stock mutation.
- Stock transfer complete posts paired `OUT` and `IN` transfer transactions and adjusts source/destination stock
- Stock opname completion requires at least one counted row and no remaining uncounted snapshot rows, records `status=COMPLETED`, `completed_by`, and `completed_at`, and does not mutate `Stock` or write `Transaction` rows
- Allocation:
  - Approval phase auto-generates `Distribution(type=ALLOCATION, status=VERIFIED)` per facility and reserves the selected stock for each child distribution row
  - Stepping an approved allocation back releases those child reservations before deleting the generated distributions
  - Per-distribution delivery confirmation decreases `Stock.quantity`, clears the child's reserved balance, and posts `Transaction(OUT, reference_type=ALLOCATION, reference_id=allocation.pk)`
  - Parent Allocation auto-transitions to `PARTIALLY_FULFILLED` / `FULFILLED` based on child distribution delivery progress

## 6) Settings and Security Model

From `backend/config/settings.py`:

- `AUTH_USER_MODEL = "users.User"`
- `APP_VERSION` is loaded from root `VERSION` (semantic version `MAJOR.MINOR.PATCH`)
- `SECRET_KEY` loaded from environment and required (`os.environ[...]`)
- `django-auditlog` is installed for database-backed create/update/delete history on selected critical models; the initial audit-log webview is available through Django Admin `/admin/`
- `DEBUG` defaults to `False` unless overridden by environment
- `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` are environment-driven comma-separated lists
- `FEATURE_ALLOCATION_UI_ENABLED` is still loaded into settings for compatibility/tests, but current runtime routing and navigation rely on permissions/module scope instead of branching on this flag
- `AUTHENTICATION_BACKENDS` order:
  1. `axes.backends.AxesStandaloneBackend`
  2. `django.contrib.auth.backends.ModelBackend`
- `PRIVATE_MEDIA_ROOT` is environment-configurable and defaults to `backend/private_media`; receiving attachments are stored here instead of the public `MEDIA_ROOT` tree
- `auditlog.middleware.AuditlogMiddleware` is loaded after Django `AuthenticationMiddleware` so auditlog can attach the logged-in actor to `LogEntry` rows
- `axes.middleware.AxesMiddleware` included after standard auth/session middleware
- `AUDITLOG_INCLUDE_TRACKING_MODELS` registers critical user/access, master-data, operational-header, and `Stock` models. No custom IMS audit-log page is implemented yet.
- Auditlog does not replace `stock.Transaction`, and signal-driven audit entries do not automatically cover `bulk_create`, `bulk_update`, or `QuerySet.update()` changes. User bulk activate/deactivate avoids `QuerySet.update()` and saves locked rows individually so account-status changes are captured.
- `AXES_FAILURE_LIMIT = 5`, `AXES_COOLOFF_TIME = 0.5`, `AXES_RESET_ON_SUCCESS = True`
- Sensitive POST throttling uses `django-ratelimit` with settings-backed defaults:
  - `USER_BULK_ACTION_RATE_LIMIT = 10/m`
  - `USER_MUTATION_RATE_LIMIT = 20/m`
  - `ITEM_MUTATION_RATE_LIMIT = 20/m` (shared by item lookup quick-create POSTs plus receiving and procurement lookup quick-create POSTs)
  - `USER_PASSWORD_RESET_RATE_LIMIT = 5/m`
  - `PASSWORD_CHANGE_RATE_LIMIT = 5/m`
  - `PUSKESMAS_RECEIPT_CONFIRMATION_MUTATION_RATE_LIMIT = 20/m` (legacy `PUSKESMAS_SBBK_MUTATION_RATE_LIMIT` remains accepted as fallback)
  - `PUSKESMAS_CONSUMPTION_MUTATION_RATE_LIMIT = 20/m`
  - `PROCUREMENT_MUTATION_RATE_LIMIT = 20/m`
  - `LPLPO_IMPORT_RATE_LIMIT = 5/h`
- Rate-limited requests are rendered through the centralized error pipeline as HTTP `429`
- `EMAIL_BACKEND` is environment-configurable and defaults to Django's console backend
- `DJANGO_LOG_LEVEL` controls the Django logger level and defaults to `WARNING`
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
- Template endpoint: `/admin/receiving/receiving/export-csv-template/`, returning `receiving_template.csv` with the importer headers only
- Required columns: `document_number`, `receiving_date`, `item_code`, `sumber_dana_code`, `location_code`, `quantity` (`quantity` must be a finite decimal greater than `0`)
- Optional columns: `receiving_type` (defaults to `GRANT`), `supplier_code`, `batch_lot`, `expiry_date`, `unit_price`
- Rows are grouped by `document_number`; first-row supplier and header values seed the parent `Receiving`
- Row-level `sumber_dana_code` and `location_code` may override the first-row values for each line item
- Blank `expiry_date` values in the dedicated receiving import are accepted only for items with `requires_expiry_date=False`; older sentinel `2099-12-31` values are normalized by follow-up data migrations rather than being generated for new imports
- The follow-up item backfill migration marks legacy catalog items with null-expiry stock/receiving history as `requires_expiry_date=False`, and stock admin import follows the same conditional blank-expiry rule
- Historical copied sentinel dates in `DistributionItem.issued_expiry_date` and `PuskesmasReceiptConfirmationItem.expiry_date` are normalized to `NULL` by follow-up data migrations so downstream history and reports do not keep rendering `31/12/2099`
- Parser-level validation normalizes CSV headers and text cells with stripped NFC text, rejects null bytes anywhere in the parsed CSV, enforces model-backed maximum lengths before saving, and rejects receiving/expiry dates whose years are outside `1000` through `9999`
- Supported date formats in parser:
  - `DD/MM/YYYY`
  - `YYYY-MM-DD`
  - `DD-MM-YYYY`
  - `DD/MM/YY`
- Decimal parser supports comma decimal separator and rejects blank, `0`, negative, `NaN`, and `Infinity` quantities
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
   - `/jazzband/django-auditlog`

