# lplpo AGENTS.md

App-specific guidance for monthly LPLPO reports and stock requests.

## Purpose

`lplpo` owns monthly reporting and stock requests from Puskesmas.

## Facility Scope And Cross-Facility Access

- Puskesmas-owned stages (`DRAFT`, `REJECTED_PUSKESMAS`, edit, submit, delete, XLSX import/export, and prefill helpers) require a linked `user.facility` for every non-superuser and remain same-facility only.
- Instalasi Farmasi stages are cross-facility only in stage-gated ways.
- `GUDANG` may verify/reject `SUBMITTED` documents and review `PIC_VERIFIED` / `REJECTED_PIC` documents across facilities.
- A facility-linked `GUDANG` user with an active LPLPO delegation additionally sees own-facility legacy `REVIEWED` rows in the normal queue. Delegation must never expose another facility's `REVIEWED` rows; expired or revoked delegation removes this addition.
- `KEPALA` uses cross-facility LPLPO access only for the legacy `REVIEWED/finalize` compatibility path plus read-only historical visibility on `APPROVED` / `CLOSED`.
- Users with role exactly `ADMIN` (not `ADMIN_UMUM`) may reject active no-distribution LPLPO documents back to Puskesmas from later pre-distribution stages such as `PIC_VERIFIED`.

## Workflow

- Active workflow is `DRAFT -> SUBMITTED -> PIC_VERIFIED -> APPROVED -> CLOSED`.
- PIC review records the review audit fields and immediately creates the linked draft `Distribution`; there is no active Kepala approval checkpoint in the normal path.
- Legacy rows may still exist in `REVIEWED` or `REJECTED_PIC`; compatibility finalize/reject actions remain only for those older documents.
- Approved LPLPO documents that already spawned a draft distribution can be explicitly returned to `REJECTED_PUSKESMAS` only by cancelling that generated distribution before any stock distribution completes.
- `Distribution(distribution_type=LPLPO)` is normally system-generated from PIC review submission in `lplpo_review`.
- The legacy `lplpo_finalize` route remains only to finish older `REVIEWED` rows and should not be treated as the primary workflow path.
- An active LPLPO-specific Acting Kepala delegation applies only to the legacy `REVIEWED` finalize/reject compatibility checkpoint. It does not create a new approval stage, bypass facility/stage visibility, or alter the normal PIC-driven path; same-facility access is rechecked between the locked actor and locked LPLPO before mutation, and delegated use must be recorded atomically in `AuthorityExercise`.
- Legacy reject and finalize transactions acquire locks in one order: the applicable delegation first, then the LPLPO row.

## Creation And Carry-Forward

- LPLPO creation for each Puskesmas facility is locked to the active server-calendar year.
- Creation must be contiguous from January; users cannot skip months.
- The next create action must always target the earliest missing month in that same year.
- The first active-year January LPLPO is the yearly bootstrap baseline.
- Create/edit pages must explain that January `stock_awal` is entered manually from opening stock records.
- February onward carries forward from the previous month's `stock_keseluruhan`, including negative balances when the prior period closed below zero.
- LPLPO creation auto-fills `stock_awal` from the immediately previous month's LPLPO for the same facility when one exists and is not `REJECTED_PUSKESMAS` or `REJECTED_PIC`; carry-over no longer waits for the prior document to reach `CLOSED`.

## Receiving And Price Autofill

- January `stock_awal` stays manual.
- January `penerimaan` may be auto-suggested from same-facility/month confirmed `PuskesmasReceiptConfirmationItem` totals and remains editable by the operator.
- February onward, `penerimaan` autofill is sourced from same-facility/month confirmed receipt-confirmation rows.
- January `harga_satuan` follows the same rule as `penerimaan`: when confirmed January receipt rows exist, the form may auto-suggest a same-month weighted-average confirmed receipt price per item as the yearly asset-valuation baseline, while still allowing operator edits.
- February onward uses same-facility/month confirmed receipt `unit_price` values and falls back to the previous month's LPLPO unit price when no new confirmed receipt exists for the period.

## Item Calculations And Editing

- LPLPO no longer tracks `pembelian_puskesmas`.
- Computed `persediaan` is `stock_awal + penerimaan`, so negative ending stock acts as the safeguard for underreported balances.
- LPLPO edit no longer accepts manual `pemakaian` overrides; operators must update the matching `puskesmas` detailed-consumption document instead.
- `pemakaian` is server-authoritative from detailed consumption.

## Offline XLSX Round Trip

- Draft and rejected LPLPO documents support offline XLSX round trip: export the current workbook from detail/edit, fill editable columns offline, then import into the same `DRAFT` / `REJECTED_PUSKESMAS` document.
- Offline XLSX import is available only after a monthly LPLPO document has been created through the standard site flow.
- Import updates only the existing document's editable Puskesmas fields: `stock_awal`, `penerimaan`, `harga_satuan`, `stock_gudang_puskesmas`, `waktu_kosong`, `permintaan_jumlah`, and `permintaan_alasan`.
- Import preserves `pemakaian` as server-authoritative from detailed consumption and recomputes all derived fields server-side.
- Import is POST-limited by `LPLPO_IMPORT_RATE_LIMIT`.
