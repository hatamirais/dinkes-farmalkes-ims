# recall AGENTS.md

App-specific guidance for the supplier-return workflow.

## Workflow And Stock

- Recall availability checks use `Stock.available_quantity`, not physical quantity alone.
- Batch selection follows FEFO and puts `expiry_date=NULL` last.
- Stock mutation occurs only at the documented recall workflow checkpoint and appends ledger rows on the exact source-document layer.

## Concurrency, Numbering, And Admin

- Edit POSTs lock and reload the parent before binding forms, then re-check live status inside the same transaction so stale drafts cannot overwrite a number, status, or business date issued concurrently.
- Drafts have no official number. Issuance uses the central numbering service and the workflow business date atomically.
- Legacy numbered step-back Draft rows retain their consumed number, issue row, and sequence position; only genuinely unnumbered drafts remain outside the issue ledger.
- Django Admin must not hard-delete Recall parents. Lifecycle transitions and deletion/voiding use workflow services so audit and issued-number reservations survive.
