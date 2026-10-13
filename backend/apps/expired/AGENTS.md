# expired AGENTS.md

App-specific guidance for expired-stock and disposal workflows.

## Approval And Stock

- Verification is restricted to superusers or role `ADMIN` / `KEPALA` with expired module scope `APPROVE`. Elevated scope alone does not authorize another role; an active Expired-specific Acting Kepala delegation is the only documented exception.
- Delegated approval is re-resolved and locked in the workflow transaction and recorded atomically in `AuthorityExercise`.
- Availability checks use `Stock.available_quantity`. Stock-changing checkpoints append ledger rows against the exact source-document layer.

## Concurrency, Numbering, And Admin

- Edit POSTs lock and reload the parent before binding forms, then re-check live status inside the same transaction so stale drafts cannot overwrite a number, status, or business date issued concurrently.
- Drafts have no official number. Issuance uses the central numbering service and workflow business date atomically.
- Legacy numbered step-back Draft/Prepared rows retain their number, issue row, and sequence position.
- Django Admin must not hard-delete Expired parents. Lifecycle transitions and deletion/voiding use workflow services.
