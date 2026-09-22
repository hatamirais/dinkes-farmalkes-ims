# procurement AGENTS.md

App-specific guidance for SPJ / contract procurement workflows.

## Purpose

`procurement` is the authoritative SPJ / contract procurement module.

## Contract Source Of Truth

- `ProcurementContract` is the contractual source of truth.
- Contract approval does not mutate stock.
- Kepala/Admin approval synchronously creates or re-syncs the linked planned procurement receiving execution document.
- Contract create/edit reuses supplier and funding-source quick-create modals on the SPJ form.
- Contract cancellation is a soft-cancel state, not a hard delete. Draft/submitted SPJ can be cancelled with a reason; approved SPJ can be cancelled only while the linked planned receiving is still unused: not `PARTIAL` / `RECEIVED` / `CLOSED`, with no receipt rows and no received quantity. Cancelling an unused approved SPJ also marks its linked receiving plan `CANCELLED`.

## Amendments

- `ProcurementAmendment` stores formal revisions.
- Amendment document numbers are scoped to the parent SPJ as `{SPJ}-A{seq}`, for example `SPJ-2026-00001-A1`.
- Kepala/Admin approval of an amendment synchronously creates or re-syncs the linked planned procurement receiving execution document.
- Amendment approval does not mutate stock.

## Numbering

- SPJ and amendment drafts have no official number; operational forms do not accept manual overrides.
- SPJ numbers are issued on submit using `contract_date` and the central `PROCUREMENT_CONTRACT` rule.
- Amendment numbers are issued on submit using `amendment_date`; their counter is scoped by parent contract id and the default template is `{parent}-A{seq}`.
- Rule validation reserves enough output space for the amendment suffix inside the 100-character document field. Counters remain internal and issued values are never reused.

## Role Rules

- `GUDANG` may operate, create, and submit procurement documents.
- `GUDANG` cannot approve SPJ or amendments, even when granted elevated procurement module scope.

## Receiving Link

- Approved SPJ contracts and amendments are responsible for keeping the linked planned procurement receiving document synchronized.
- The planned Receiving number is issued when contract approval creates/synchronizes the plan, using the Receiving business date.
- Procurement-linked receiving leftovers must be corrected through procurement amendments, not receiving-side close-items actions.
- New planned procurement receiving documents must originate from approved SPJ/amendment synchronization; the receiving-side manual plan create route redirects to SPJ creation and is compatibility-only.
- Quick-create lookup POST mutations are covered by `@item_mutation_ratelimit`, not the user-management throttle bucket.
- Procurement mutations are POST-limited by `PROCUREMENT_MUTATION_RATE_LIMIT`.
