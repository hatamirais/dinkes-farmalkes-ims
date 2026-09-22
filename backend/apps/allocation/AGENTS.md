# allocation AGENTS.md

App-specific guidance for pre-distribution allocation planning.

## Purpose

`allocation` owns pre-distribution planning and orchestration.

## Workflow

- The lifecycle is `DRAFT -> SUBMITTED -> APPROVED`.
- Approval auto-generates one `Distribution` per facility.
- Approval immediately reserves the approved batch quantities for each generated child distribution.
- Approved allocations may be stepped back to `SUBMITTED` by approvers.
- Stepping an allocation back releases generated child distribution reservations.
- Stepping back also deletes the auto-generated child distributions so approval can be re-run cleanly.

## Generated Distributions

- `Distribution(distribution_type=SPECIAL_REQUEST, allocation_id=<parent>)` is system-generated from allocation approval.
- Children use the same `DISTRIBUTION_SPECIAL_REQUEST` numbering rule and continuing sequence as standalone Permintaan Khusus; `allocation_id` is the only origin discriminator.
- Children are included in both the general Permintaan Khusus report and the allocation-origin report.
- Generated child distributions start in `VERIFIED` status with selected stock already reserved.
- Generated child distribution quantities are locked and cannot be edited.
- Allocation-generated child distributions remain parent-managed by the Allocation module.
- Revert generated child distributions from the parent Allocation workflow, not generic distribution reset/step-back endpoints.
- Stepping back voids every issued child number before deleting the child rows; sequence values are not reused.

## Numbering

- Allocation drafts have no official number. The `ALLOCATION` rule is issued atomically on submit using `allocation_date`.
- Templates/reset/padding are configured centrally on `/settings/numbering/`; users cannot enter official numbers or edit counters.

## Stock Behavior

- Stock deduction is deferred to per-distribution delivery confirmation.
- Allocation approval reserves stock only; it does not consume physical stock.
- Item batch selection can span all available stock sources.
- Allocation no longer stores a header-level funding source.

## Fulfillment

- Allocation auto-transitions to `PARTIALLY_FULFILLED` when any child distribution is delivered.
- Allocation auto-transitions to `FULFILLED` when all child distributions are delivered.

## Permissions

- Allocation is active and gated by `ModuleAccess` scopes like all other modules.
