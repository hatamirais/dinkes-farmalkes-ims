# stock_opname AGENTS.md

App-specific guidance for physical stock counting.

## Counting And Completion

- Starting an opname freezes its counting scope and issues its number using `period_end`.
- Completion refreshes current stock under the workflow transaction and stores that refreshed quantity on every row so completed detail/print output does not drift after later stock movements.
- `GUDANG` or operate-scope users may complete only when every refreshed current-stock quantity matches the physical count.
- Any remaining discrepancy requires stock-opname approve scope (`KEPALA`, Admin, or superuser by default).
- Completion adjustments are explicit stock workflow actions and append ledger entries; historical transactions remain immutable.

## Concurrency, Dates, And Admin

- Edit POSTs lock and reload the parent before binding forms, then re-check the live status in the same transaction so stale Draft edits cannot race with start/issuance.
- Once numbered, `period_end` remains bound to the issue and cannot change.
- Django Admin keeps the whole header editable only in Draft and keeps `period_end` read-only for every numbered record.
- Django Admin must not hard-delete Stock Opname parents; workflow deletion/voiding preserves audit and number reservations.
