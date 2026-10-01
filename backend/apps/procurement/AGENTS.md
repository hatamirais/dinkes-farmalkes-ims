# procurement AGENTS.md

App-specific guidance for SPJ / contract procurement workflows.

## Purpose

`procurement` is the internal source of truth for procurement planning and its receiving synchronization. Official external document numbers may originate in another application and are stored only as references.

## Contract Source Of Truth

- `ProcurementContract` is the contractual source of truth.
- `document_number` is the system-issued internal IMS number. `external_document_number` is an optional, user-entered reference from another application and must never drive an IMS sequence.
- Contract approval does not mutate stock.
- Kepala/Admin approval synchronously creates or re-syncs the linked planned procurement receiving execution document.
- Contract create/edit reuses supplier and funding-source quick-create modals on the SPJ form.
- Contract cancellation is a soft-cancel state, not a hard delete. Draft/submitted SPJ can be cancelled with a reason; approved SPJ can be cancelled only while the linked planned receiving is still unused: not `PARTIAL` / `RECEIVED` / `CLOSED`, with no receipt rows and no received quantity. Cancelling an unused approved SPJ also marks its linked receiving plan `CANCELLED`.

## Amendments

- `ProcurementAmendment` stores formal revisions.
- Amendment document numbers use the configured central rule and period counter independently of the parent contract number.
- Kepala/Admin approval of an amendment synchronously creates or re-syncs the linked planned procurement receiving execution document.
- Amendment approval does not mutate stock.

## Numbering

- SPJ and amendment drafts have no official number; operational forms do not accept manual overrides.
- SPJ numbers are issued on submit using `contract_date` and the central `PROCUREMENT_CONTRACT` rule.
- Amendment numbers are issued on submit using `amendment_date`; the default template is `SPJ/{year}/{month}/{seq}` with a monthly shared counter.
- Templates support only the generic `{seq}`, `{year}`, and `{month}` tokens. Counters remain internal and issued values are never reused.
- Django Admin exposes workflow state and audit fields as read-only, conditionally locks `contract_date` / `amendment_date` once the document has a number, and disables parent/bulk deletion. Contract and amendment line inlines may be changed only while their parent remains Draft; all lifecycle transitions, including SPJ soft cancellation, must use the application workflow services.

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
