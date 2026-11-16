# puskesmas AGENTS.md

App-specific guidance for Puskesmas facility workflows.

## Purpose

`puskesmas` owns ad-hoc requests from Puskesmas, receipt-confirmation input for goods actually received from Instalasi Farmasi, facility-scoped subunit master data (`ruang tindakan` / `Pustu`), monthly detailed consumption input, and a Puskesmas-operator-only read-only stock self-check page.

## Facility Scope

- Operational preparation/edit surfaces require a linked `user.facility` for every non-superuser account and enforce same-facility object access. The opening-stock verification checkpoint below is an explicit exception for authorized Instalasi Farmasi staff.
- `OPERATOR PUSKESMAS` users must never read or write another facility's documents.
- Reports use the dedicated `puskesmas_reports` module at VIEW or higher, never generic `reports.view_reports`. PUSKESMAS defaults to VIEW; an explicit NONE denies access. Other roles default to NONE.
- Facility-bound readers require an active Puskesmas link and ignore query-driven scope widening. Eligible internal roles ADMIN, KEPALA, ADMIN_UMUM, GUDANG, and AUDITOR may select active facilities only with the explicit `users.select_puskesmas_report_facility` Django permission. All-facility mode additionally requires `users.aggregate_puskesmas_reports`. PUSKESMAS cannot use either staff permission. Superusers retain both capabilities.
- Selection-only staff land on the first active facility when no selection is provided, never on an aggregate. Invalid explicit selections raise PermissionDenied. HTML, print, Excel, facility selectors, and sidebar share this policy. These read-only capabilities grant no workflow authority.
- Report HTML displays money with two Indonesian decimal digits; this presentation rule does not round stored prices, report calculations, or Excel exports.
- An active Puskesmas-specific Acting Kepala delegation may satisfy only the request approval/rejection authority check; it does not authorize reset-to-draft. It never bypasses linked-facility or same-facility isolation, which is rechecked between the locked actor and locked request before mutation. Delegated use must be recorded atomically in `AuthorityExercise`.

## Initial opening inventory foundation

- `/puskesmas/saldo-awal/` owns first January opening preparation, CSV validation/preview, submission and independent review/posting. See `inventory.py`, `inventory_models.py`, and `inventory_views.py`; new models are re-exported from `models.py`.
- The preparation page has independent native collapsible sections for template download/CSV column guidance and the bound import form. The import section starts open and remains open when validation errors render. The download has its own facility/year selector and ten-column guide matching the worksheet parser. source_document_number is recovered internally for linked rows and omitted from new downloads; provenance_note is blank in downloads. Legacy nine/eleven-column files remain accepted with source validation.
- Opening list/detail display years without thousands grouping. The detail labels its quantity-times-price total in Rupiah with two decimal display places, using Subtotal when prices are missing and explaining the excluded rows. Stored/calculated precision and original unit-price display remain exact. The warning explains incomplete consumption recording in operator terms and directs readers to LPLPO/reports. Detail tables scroll within the page and action controls use the shared form-action spacing.
- Operators prepare only their linked active facility. Draft previews are actor-bound and expire for submission after 24 hours; retained documents are not automatically deleted. Rejected/held data is corrected by a new upload, never by editing submitted rows.
- Whole-facility and January 1 cutoff guidance is plain text on the upload form; the former boundary_attested checkbox is removed. Preview creation accepts valid uploads without an attestation field. Independent reviewer confirmation at posting remains required.
- The active preparer can cancel their own DRAFT preview, including an expired preview, via the detail page's confirmed CSRF POST action=cancel. Cancel takes actor/module, facility and document locks, rechecks authority/status/digest, then retains the header/lines as CANCELLED with cancelled_by/cancelled_at. Repeat cancellation is idempotent. Submitted/rejected/posted records cannot use this draft action. Cancellation records no inventory movements and redirects to the opening list.
- Superusers or role `GUDANG` with LPLPO module scope `OPERATE` or higher may review/post across active facilities. Preparer cannot verify their own opening. Recheck actor/module/facility under lock; report permissions and Acting Kepala do not grant posting authority.
- Opening covers all stock held across warehouse, rooms and Pustu before January 1 movements. One initial account per facility. Annual reconciliation posting and reversal/correction UI are deferred; posted records cannot be edited/deleted. No fabricated batches, funding, source documents, prices or expiry dates.
- Missing batch/funding/source is explicit blank/NULL plus required provenance note. For linked rows with no operator note, import records factual missing-source information internally; warehouse candidates also get their identity-only caution. Manual rows must supply their own note when provenance is incomplete. Missing original price or required expiry holds the entire posting. Verified zero price is valid. Empty/header-only/all-quantity-blank files and new zero-stock submissions are rejected; the old zero_stock model flag is retained only for historical audit/digest compatibility.
- Template rows first use this facility's DISTRIBUTED source rows strictly before January 1 of the selected year, excluding confirmations known to arrive on/after cutover. DIST-<id> rows use issued snapshots and keep a protected source-distribution-item link. Additional STOCK-<id> candidates use recorded warehouse Stock metadata for active items/funding, even when warehouse quantity is zero; a nullable protected source_stock link records identity only, never delivery or facility ownership. Matching warehouse economic identities are omitted across locations and against distribution candidates. Quantity is always blank; names/units are reference columns.
- The importer skips structurally valid rows with blank quantity, requires at least one positive whole quantity, and still accepts the original nine-column manual format. DIST- rows are checked against facility/year and source economic fields during preview/preparation/posting; STOCK- metadata is also revalidated under source row locks. Review must verify actual ownership, historical price and opening-date coverage; warehouse candidates are not historical proof. Posting does not mutate warehouse stock or its ledger. Manual rows use distinct keys outside both reserved prefixes. Formula-safe CSV export round-trips linked source text without changing original stored facts.
- CSV parsing batches selected source/item/funding lookups into request-local maps through csv_reference_maps. It retains active catalog and facility/date source filters, spreadsheet-safe code restoration, exact snapshot checks and row-numbered errors. Preparation/posting still query and lock live sources. Performance baseline, tracking and validation are in docs/puskesmas-opening-import-performance.md; query-count regression checks belong to test_inventory.py.
- Worksheet exports prefix numeric-looking item/batch/funding identifiers and known prices with an apostrophe to preserve leading zeros, punctuation and exact decimal prices in spreadsheets. Import restores identifier prefixes only against the linked source; price parsing accepts one optional leading apostrophe before finite/precision checks. Decimal commas are supported for prices. Batch text is compared exactly, and mismatch errors identify the field and submitted/source values. Manual additions require a positive quantity and a note for incomplete provenance. Blank manual line_key values receive unique MANUAL- UUID references during parsing, retained through preview/posting. Existing explicit manual keys remain accepted if unique.
- Posting creates distinct original-price layers, balance projections and append-only movements atomically. Existing confirmed linked receipts on/after coverage start are posted by the same receipt service; unsupported historical sources abort the entire opening for review. Earlier receipts are included in the verified opening rather than posted again.
- Confirmed linked receipts post once only after initialization; use issued distribution snapshots, never current warehouse prices. Missing issued price is an error, not zero. Inventory sources use protected FKs. Posted receipts and their rows are immutable through instance/queryset operations; no delete/recreate of posted rows. Pre-cutover dates cannot be moved across the opening boundary.
- Receipt mutations and LPLPO create/edit/import/submit share actor/module then facility locks before binding forms/checking periods. Row locks and unique constraints protect concurrent opening/receipt posting. Warehouse stock is not deducted again.
- Accounts always report `FOUNDATION_INCOMPLETE`: consumption does not post yet. Never use the new projection for current availability, shortage validation, LPLPO opening, or existing rincian/rekap. Journal and layer/balance mutations are application-guarded; direct database SQL is outside those guards.
- Initial CSV contract: `backend/seed/README.md`; decision record and feature-2 boundary: `docs/puskesmas-opening-inventory-design.md`. Focused tests: `apps.puskesmas.test_inventory`.

## Rincian Persediaan Report

- `/puskesmas/laporan/persediaan/` labels its calculated balance `Stok Akhir Digital`, distinct from warehouse availability.
- The latest usable same-year LPLPO up to the selected end month is the baseline; Draft is usable and rejected statuses are excluded. Add only later same-year `CONFIRMED` receipt rows and subtract later detailed consumption through that end month. Quarter/semester selection describes an ending-stock cutoff, not only movements within the quarter/semester.
- HTML and print expose per-facility baseline period/status, adjustment window, included receipt/consumption detail-row counts, and active-facility coverage. A missing baseline means the facility is skipped, not that stock is zero. Zero included source rows differs from a missing baseline.
- All-facility mode sums item balances across covered facilities. Its negative-item count refers to aggregated rows, which can mask individual facility shortages. Item numbering remains continuous across categories.
- Excel keeps the item table on `Rincian Persediaan` (headers on row 4, items from row 5) and adds `Sumber dan Cakupan` with the same provenance and coverage. Valid empty exports explain missing baselines, no active facilities, or no resulting items. Invalid filters render HTML validation errors. Reports never mutate stock.

## Stock Self-Check

- The stock self-check page is LPLPO-only.
- It uses the latest non-rejected LPLPO for the logged-in facility.
- It compares `stock_keseluruhan` (digital stock) with `stock_gudang_puskesmas` (physical stock recorded on that LPLPO).
- It does not apply post-LPLPO receipt or consumption adjustments.
- It does not mutate stock.
- Its desktop page at `/puskesmas/stok/` uses the Tailwind base and renders the existing bound year/search/mismatch filter fields directly; facility scope, values, and pagination remain view-owned.

## Poli/Pustu Subunits

- `/puskesmas/subunit/` and its create/edit forms use the Tailwind desktop base. The list keeps its facility-scoped search/type filters, table, and existing server-side 25-row page slice.
- The form keeps the operator's hidden facility field and read-only facility display; superusers retain the active-Puskesmas facility selector. The `name`, `subunit_type`, and `is_active` fields remain bound Django controls with their existing validation.
- Delete remains POST-only and refuses subunits referenced by consumption entries. The views retain their explicit creator role gate and cross-facility checks.

## Receipt Confirmations

- The receipt-confirmation list, detail, and shared create/edit form use the Tailwind desktop base. The form keeps its distribution preview GET, fixed linked checklist, legacy unlinked row formset, and draft/final POST action values. Bootstrap JavaScript still owns the delete modal; `puskesmas-form.js` owns the preview and checklist state.

- Puskesmas `Riwayat Penerimaan` is sourced from `PuskesmasReceiptConfirmation` and `PuskesmasReceiptConfirmationItem`.
- Linked receipt-confirmation create/edit uses a fixed checklist sourced from `DistributionItem` rows.
- Operators can save an incomplete document as `DRAFT` when goods are still missing.
- Operators may only finalize with `CONFIRMED` once every source row is checked as physically received.
- Only `CONFIRMED` receipt confirmations contribute to LPLPO `penerimaan` and weighted `harga_satuan`.
- Legacy migrated receipt-confirmation rows may have null `distribution` / `distribution_item` links and must remain editable through the compatibility edit path with manual row editing.
- New operational receipts still require distribution linkage.
- Create/edit/delete saves are POST-limited by `PUSKESMAS_RECEIPT_CONFIRMATION_MUTATION_RATE_LIMIT`; the create-form distribution preview is non-mutating `GET` and must not consume that quota.

## LPLPO Sync From Receipts

- Saving, editing, or deleting a receipt confirmation atomically re-syncs only same-month editable LPLPO rows in `DRAFT` or `REJECTED_PUSKESMAS`.
- Opening or re-saving an editable LPLPO refreshes same-month `penerimaan` and weighted `harga_satuan` from existing confirmed receipt-confirmation data so older drafts do not keep stale receiving values.
- Once a facility-month LPLPO is `SUBMITTED` or beyond, receipt-confirmation mutation for that period is blocked.

## Detailed Consumption

- The detailed-consumption list, detail, and shared create/edit form use the Tailwind desktop base. The form keeps facility/month fields, dynamic subunit matrix cells, server-bound errors, and the superuser `load_matrix` POST action. The matrix retains horizontal scrolling and two sticky identifier columns. The create/edit matrix groups all item rows under visible Kategori separators; this changes presentation only and keeps each item's quantity field and save behavior.
- The create/edit matrix shows `Stok LPLPO Terakhir` immediately after Satuan, sourced from `stock_keseluruhan` on the latest non-rejected LPLPO for the selected facility across years. The heading displays that LPLPO's period and status. A missing item or missing LPLPO displays `—`, while an actual zero or negative balance is shown as stored. This is a digital snapshot, not live physical stock or a validation limit for the quantity fields.
- The matrix Total cell displays the sum of that item's visible subunit quantities, including saved values on edit, and updates while the operator types. Blank cells count as zero; invalid values show `—` until corrected. The display does not submit a separate field or replace server validation and LPLPO synchronization.

- Detailed consumption is sourced from `PuskesmasConsumption` and `PuskesmasConsumptionEntry`.
- Consumption is stored separately per facility/month and per facility-defined subunit.
- The sum of `PuskesmasConsumptionEntry.quantity` per item is the editable-period source of truth for `LPLPOItem.pemakaian`.
- Saving, editing, or deleting detailed consumption atomically re-syncs only same-month editable LPLPO rows in `DRAFT` or `REJECTED_PUSKESMAS`.
- Opening or re-saving an editable LPLPO refreshes same-month `pemakaian` values when a detailed-consumption document already exists.
- Once a facility-month LPLPO is `SUBMITTED` or beyond, detailed consumption mutation for that period is blocked.
- Mutation saves are POST-limited by `PUSKESMAS_CONSUMPTION_MUTATION_RATE_LIMIT`.

## Request Screens

- The request list, detail, and shared create/edit form use the Tailwind desktop base. The form keeps the `items` management fields, row selectors and quantities, and draft save. `puskesmas-form.js` adds/removes request rows using formset indices and DELETE markers, with at least one visible row. Removed rows disable editable inputs so native browser validation cannot block saving; their existing formset IDs and checked DELETE controls stay enabled for Django. The detail retains server-gated submit, approve/reject, reset, and delete actions with Bootstrap JavaScript modals.
- The request-level `program` remains a nullable stored field for existing records and downstream distribution behavior, but the operator create/edit form does not expose it. The list and detail omit request-level Program, and the list no longer filters on `?program=`. Item-level `[P]` markers remain visible on detail rows; `[P]` marks a program item and does not identify a particular Program.
