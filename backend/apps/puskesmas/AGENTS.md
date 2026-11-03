# puskesmas AGENTS.md

App-specific guidance for Puskesmas facility workflows.

## Purpose

`puskesmas` owns ad-hoc requests from Puskesmas, receipt-confirmation input for goods actually received from Instalasi Farmasi, facility-scoped subunit master data (`ruang tindakan` / `Pustu`), monthly detailed consumption input, and a Puskesmas-operator-only read-only stock self-check page.

## Facility Scope

- All operational and report-facing surfaces require a linked `user.facility` for every non-superuser account and enforce same-facility object access.
- `OPERATOR PUSKESMAS` users must never read or write another facility's documents.
- Puskesmas report routes require `reports.view_reports` or REPORTS module-scope `VIEW`.
- Superusers may query all facilities in reports; non-superusers are forced to their linked `facility` and receive `403` when no facility is linked.
- Report HTML displays money with two Indonesian decimal digits; this presentation rule does not round stored prices, report calculations, or Excel exports.
- An active Puskesmas-specific Acting Kepala delegation may satisfy only the request approval/rejection authority check; it does not authorize reset-to-draft. It never bypasses linked-facility or same-facility isolation, which is rechecked between the locked actor and locked request before mutation. Delegated use must be recorded atomically in `AuthorityExercise`.

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

- The request list, detail, and shared create/edit form use the Tailwind desktop base. The form keeps the `items` management fields, row selectors and quantities, and draft save. `puskesmas-form.js` adds/removes request rows using formset indices and DELETE markers, with at least one visible row. The detail retains server-gated submit, approve/reject, reset, and delete actions with Bootstrap JavaScript modals.
- The request-level `program` remains a nullable stored field for existing records and downstream distribution behavior, but the operator create/edit form does not expose it. The list and detail omit request-level Program, and the list no longer filters on `?program=`. Item-level `[P]` markers remain visible on detail rows; `[P]` marks a program item and does not identify a particular Program.
