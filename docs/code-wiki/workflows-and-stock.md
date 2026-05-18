# Workflows and Stock Mutation

This page focuses on the business-critical rule: document workflows mutate stock only at specific checkpoints.

## Core Principle

Do not treat model save events as the main inventory mutation mechanism. Stock changes happen during explicit workflow actions and must keep `stock.Transaction` append-only.

## Inventory Spine

- `backend/apps/stock/models.py`
  - `Stock`: current on-hand quantity per item, batch, location, and funding source
  - `Transaction`: immutable movement log

## Receiving

- Files:
  - `backend/apps/receiving/views.py`
  - `backend/apps/receiving/admin.py`
- Behavior:
  - Verified or received receiving flows create or update `Stock`
  - They also write `Transaction(IN)`
  - Admin CSV import is not a side path; it is a live inventory creation path

## Distribution

- Files:
  - `backend/apps/distribution/views.py`
  - `backend/apps/distribution/services.py`
- Workflow:
  - `DRAFT -> SUBMITTED -> VERIFIED -> PREPARED -> DISTRIBUTED`
- Mutation rule:
  - `prepare` changes workflow state only
  - `distribute` deducts `Stock.quantity` and writes `Transaction(OUT)`
- Availability checks use `Stock.available_quantity`
- Current workflow does not automatically maintain `Stock.reserved`

## Allocation

- Files:
  - `backend/apps/allocation/views.py`
  - `backend/apps/allocation/services.py`
- Workflow:
  - `DRAFT -> SUBMITTED -> APPROVED -> PARTIALLY_FULFILLED -> FULFILLED`
- Mutation rule:
  - Approval creates one child `Distribution` per facility
  - Approval does not deduct stock
  - Stock is deducted only when each child distribution is delivered

## Recall

- Files:
  - `backend/apps/recall/views.py`
- Mutation rule:
  - Verify step decreases stock
  - Writes `Transaction(OUT)` with `reference_type=RECALL`

## Expired

- Files:
  - `backend/apps/expired/views.py`
- Mutation rule:
  - Verify step decreases stock
  - Writes `Transaction(OUT)` with `reference_type=EXPIRED`

## Stock Transfer

- Files:
  - `backend/apps/stock/views.py`
  - `backend/apps/stock/models.py`
- Mutation rule:
  - Completion writes paired `OUT` and `IN` transactions
  - Source and destination stock records are updated together

## Stock Opname

- Files:
  - `backend/apps/stock_opname/views.py`
- Mutation rule:
  - Start snapshots current `Stock.quantity` into `StockOpnameItem.system_quantity`
  - Completion marks the session as finished and timestamps it
  - Completion does not currently mutate `Stock` or write `Transaction` rows; discrepancy handling remains a reporting/follow-up step

## Document Numbering

- Generic numbering helpers:
  - `backend/apps/core/numbering.py`
- Distribution-specific numbering:
  - `backend/apps/distribution/numbering.py`
- Dynamic templates come from `core.SystemSettings`
- `LPLPO` and `SPECIAL_REQUEST` distribution numbers use template-based generation

## Safe Change Checklist

Before changing any workflow:

1. Verify the current status graph in `views.py` and `services.py`.
2. Check whether the action writes `Stock`, `Transaction`, both, or neither.
3. Preserve append-only `Transaction` behavior.
4. Update documentation if the checkpoint or status graph changes.
