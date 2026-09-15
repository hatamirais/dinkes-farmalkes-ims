# distribution AGENTS.md

App-specific guidance for outbound distribution workflows.

## Purpose

`distribution` owns outbound distribution workflow, step-back/reset actions before distribution, issued batch/value snapshots on `DistributionItem`, row-level `reserved_quantity` bookkeeping for outbound commitments, object-level preparer assignment for regular/special-request preparation, special-request numbering, generated LPLPO distributions, allocation-generated child distributions, and distribution-owned report variants.

## Core Workflow

- Regular and special-request distributions use `DRAFT/REJECTED -> PREPARED -> SUBMITTED -> VERIFIED -> DISTRIBUTED`.
- Verification/rejection at `SUBMITTED` is restricted to superusers or role `ADMIN` / `KEPALA` with distribution module scope `APPROVE`; elevated scope alone does not authorize another role.
- Assigned `DistributionStaffAssignment` users control draft/rejected preparation, submission, and final fulfillment.
- When no preparers are assigned, approve-scope users remain the fallback managers.
- Final distribution for standalone documents follows the same assignee/fallback authorization rule as preparation.
- Reset-to-draft, step-back, delete, final fulfillment, and generated-LPLPO return-to-Puskesmas follow the same object-level assignee/fallback rule as edit, prepare, and submit.

## Reservation And Stock Deduction

- Verification reserves the selected batch quantities on `Stock`.
- Verification and rejection lock and re-check the distribution status so repeated or stale approval actions cannot apply twice.
- Reset, step-back, delete, and reversal release reservations for standalone distributions.
- Final distribution consumes both `quantity` and `reserved` together in one transaction-safe workflow step.
- Verification reserves the selected stock batch per `DistributionItem`.
- Step-back from `VERIFIED` and generated-LPLPO reversal release reservations for standalone distributions.
- Final distribution clears the reservation while deducting physical stock.

## LPLPO Distributions

- `Distribution(distribution_type=LPLPO)` is normally system-generated from PIC review submission in `lplpo_review`.
- A separate `manual_lplpo_create` route exists as a permanent operational fallback for mid-year rollout/catch-up work when Puskesmas LPLPO documents have not been backfilled.
- Do not expose `LPLPO` as a manual distribution type in the generic distribution create/edit flow.
- LPLPO-generated draft distributions lock item identity plus requested/approved quantities during edit; the edit step is only for batch selection, notes, and staffing.
- LPLPO-generated draft distributions preserve `quantity_requested=permintaan_jumlah` and `quantity_approved=pemberian_jumlah`.
- Manually created LPLPO distributions do not have an `lplpo_source` document and remain editable like normal draft distributions while still using the LPLPO numbering/report bucket.
- Generated LPLPO distributions provide a dedicated reversal action that cancels the generated distribution and returns the parent LPLPO to `REJECTED_PUSKESMAS` with a required reason while the document is still pending distribution.
- That reversal action follows the same distribution assignee/fallback authorization rule and requires LPLPO module scope `OPERATE`.

## Allocation Distributions

- `Distribution(distribution_type=ALLOCATION)` is system-generated from allocation approval.
- Allocation-generated child distributions remain parent-managed by the Allocation module and do not use generic distribution reset/step-back actions.
- Allocation-generated child distributions start in `VERIFIED` with selected stock already reserved.
- Quantities are locked and cannot be edited.
- Stock deduction is deferred to per-distribution delivery confirmation.
- Allocation-generated child distributions must be reverted from the parent Allocation workflow instead of generic distribution endpoints.

## Routes And Numbering

- User-facing manual create paths are `special_request_create` for permintaan khusus and `manual_lplpo_create` for manual LPLPO rollout/catch-up distributions.
- Keep the generic `distribution_create` route reserved for internal or compatibility flows tied to broader distribution orchestration.
- Special-request numbering UI preloads the next suggested number while requiring confirmation before manual override.
- Distribution numbering templates for `LPLPO` and `SPECIAL_REQUEST` are user-configurable through `SystemSettings`.
- Supported numbering placeholders are `{seq}` and `{year}`.
- Sequence counters remain scoped per distribution type and matched against the active template.

## Reports

- The combined outbound report remains on `/reports/pengeluaran/`.
- Distribution owns dedicated route-based report variants at `/distribution/report/`, `/distribution/report/special-requests/`, `/distribution/report/allocation/`, and `/distribution/report/lplpo/`.
