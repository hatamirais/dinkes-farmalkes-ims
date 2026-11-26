# Feature 3 · Puskesmas Stock Opname and Reconciliation

First-release design decisions recorded through 2026-11-25. Monthly Stock
Opname is a prerequisite to creating LPLPO for a facility and month covered
by the rollout. The
[Feature 2 handoff](puskesmas-fefo-consumption-design.md#15-deferred-feature-3-puskesmas-stock-opname-and-reconciliation)
defines the scope. The baseline is [PR #327](https://github.com/hatamirais/dinkes-farmalkes-ims/pull/327),
verified as the two-parent merge commit `a7d13186` on fetched `main`.

## Verified behavior at the Feature 2 baseline

| Area | Current behavior | Code |
| --- | --- | --- |
| Instalasi Farmasi Stock Opname | Start freezes the positive warehouse stock rows in scope and issues a number bound to `period_end`. Completion requires at least one counted row and no uncounted snapshot rows. Matching counts can be completed with operational authority. A current difference requires approval authority, with eligible Acting Kepala delegation recorded. Completion freezes the refreshed quantities, actor and time. It writes neither a warehouse stock change nor a ledger transaction. | [Start](../backend/apps/stock_opname/views.py#L253), [completion](../backend/apps/stock_opname/views.py#L516), [app guide](../backend/apps/stock_opname/AGENTS.md) |
| Puskesmas inventory | A verified opening establishes facility journal coverage. Opening and supported confirmed receipts create protected layers with original price, batch, expiry, funding and source document. Movement totals track a facility and layer. Poli/Pustu identify where consumption was reported, while inventory layers and balance projections have no subunit location. Posted receipts are immutable and there is no general posted-receipt correction flow. | [Inventory models](../backend/apps/puskesmas/inventory_models.py), [receipt posting](../backend/apps/puskesmas/inventory.py#L561), [receipt write guards](../backend/apps/puskesmas/inventory_locking.py#L65) |
| Consumption | Drafts have no journal outflow. Finalization posts month-end FEFO at exact layer prices, with undated layers last. Prior covered months require finalized revisions, including explicit zero use. Shortage, coverage or projection problems, or remaining expired-by-cutoff stock hold finalization. Corrections append reversal and replacement, subject to the current LPLPO and later-finalization guards. | [Consumption posting and period checks](../backend/apps/puskesmas/consumption_inventory.py) |
| Expiry | An operator records an explicit dated withdrawal. Corrections and VOID retain the original evidence and may atomically replay same-month FEFO consumption. Submitted affected LPLPOs and later finalized months can block the change. Later-dated withdrawals cannot resolve earlier expiry coverage, and net later withdrawals can block historical FEFO allocation. | [Expiry posting](../backend/apps/puskesmas/expiry.py), [consumption posting](../backend/apps/puskesmas/consumption_inventory.py) |
| Reporting | Persediaan, Rincian and Rekap choose journal or labelled legacy LPLPO fallback per facility and interval. Missing baseline excludes the facility from that source rather than implying zero. Journal coverage and missing finalizations remain visible. The separate stock self-check compares two fields from a legacy-style LPLPO view, with no independent count evidence. The calculated digital balance does not certify physical stock. | [Report source selection](../backend/apps/puskesmas/stock_reports.py#L264), [stock self-check](../backend/apps/puskesmas/views.py#L564), [system model](../SYSTEM_MODEL.md) |
| LPLPO | The operator's create action already serializes on the facility and validates the earliest missing month of the active server year. Submission takes the actor, facility and document locks. Bound submission requires a current matching finalized consumption revision and syncs journal-backed fields. The unbound path has no such inventory prerequisite. Creation and submission currently have no Stock Opname check. The model describes `stock_gudang_puskesmas` as the warehouse physical count. It remains an operator field, including through permitted XLSX import, with no link to a frozen count. | [Create](../backend/apps/lplpo/views.py#L510), [submit](../backend/apps/lplpo/views.py#L1138), [physical-stock field](../backend/apps/lplpo/models.py#L275), [inventory prerequisite](../backend/apps/puskesmas/inventory_reporting.py#L164), [LPLPO app guide](../backend/apps/lplpo/AGENTS.md) |

The operator's reported practice is to count before filling in the LPLPO workbook.
Its frequency, cutoff, location coverage and authority have yet to be confirmed.

## Agreed Feature 3 sequence

1. Start Stock Opname for the facility and reporting month and retain a stock
   snapshot for that month, following IF's snapshot and count pattern.
2. Verify the month's receiving and medical consumption across the warehouse,
   Poli and Pustu. Use the owning workflows to record and finalize movements as
   required. Count physical stock across those locations and confirm alignment
   with the digital balance at the same cutoff.
3. Only after the operator completes this checkpoint may they create that
   facility's LPLPO for the month, including its first draft. The count must
   be closed and reconciled. An unresolved discrepancy blocks creation even
   after count closure. Approval to close a count does not waive this gate.

The accounting cutoff is facility-local end-of-day on the last day of the
reporting month, aligned with Feature 2. An operator may enter a recorded count
later. A location may also physically count before or after the cutoff when
documented intervening movements let the operator reconcile it to month-end.
For example, 90 units counted on March 2 plus 10 units documented as used after
February closed represents 100 units at February month-end. If the movement
record is incomplete or its timing is uncertain, keep the comparison provisional
and LPLPO creation blocked.

An authorized operator at the same facility can close a complete count when the
cutoff evidence is current and the physical and digital balances agree, with no
unresolved discrepancies. This follows IF's operational completion pattern.
A designated Instalasi Farmasi `GUDANG` reviewer with explicit Feature 3
authority for the facility may close a complete count with open discrepancies.
The reviewer must be someone other than the preparer. Closure freezes the count
evidence, keeps the cases open, and leaves LPLPO creation blocked. Adjustment
approval is a separate action. An approver must have LPLPO module scope
`OPERATE` or higher, explicit Feature 3 adjustment-approval authority for the
facility, and be someone other than the adjustment preparer. Any role that
meets all three checks is eligible, including a designated `GUDANG` reviewer.

The first release permits new reconciliation adjustments only for documented
loss or damage that reduces stock on an identified existing layer at its
original price. A surplus stays open for investigation or correction through
its owning workflow. Creating a layer or adding stock to resolve a surplus
requires a separate decision. An exact reversal of an erroneous posted
adjustment is a linked correction, distinct from recognizing a surplus.

Post loss or damage reductions at the facility's month-end reconciliation
cutoff, after that month's finalized consumption. Keep the incident date
separately as evidence when known. Posting the reduction uses the remaining
quantity on the identified layer and preserves the finalized FEFO allocation.

If a subsequent correction recalculates same-month FEFO, apply the original
approved loss or damage reduction after the recalculated consumption. The
correction can proceed only if the reduction still fits its original layer
at the same quantity and cost. Preserve the approved adjustment and its
journal entry. If the layer can no longer support the approved reduction,
roll back the entire attempted correction and route the conflict for review.

The first release includes a narrowly scoped, audited correction path owned by
Puskesmas receiving for verified errors on posted receipts. The original receipt
and journal entries remain immutable. The correction preserves the evidence and
links a separate journal correction to the original receipt and affected source
layers, using the original costs. This allows receiving to correct proven
overstatements such as short deliveries. The approver must have LPLPO module
scope `OPERATE` or higher, explicit posted-receipt correction approval
authority for the facility, and be someone other than the correction preparer.
This authority is specific to receipt corrections. The first release allows
only reductions for documented quantity overstatements on existing posted
receipt lines, at their original prices and on their original layers. For
example, if 100 units were posted and only 90 arrived, record a linked reduction
of 10. Understated quantities and errors in batch, price, source or receipt date
stay open until their correction rules are agreed.

If that month's consumption is already finalized, the receiving correction
automatically recalculates its FEFO allocation in the same transaction,
following the existing expiry correction pattern. Append the linked receiving
correction and the consumption reversal and replacement together. Preserve
reported usage quantities and original layer prices, then synchronize affected
editable inventory-bound LPLPO and carries. If the correction or recalculation
fails, roll back all of it and keep the discrepancy open. An affected submitted
LPLPO or later finalized consumption blocks the operation under the existing
period guards. Cross-period replay remains outside this decision.

Reopening a closed count requires LPLPO module scope `OPERATE` or higher and
explicit Feature 3 reopening authority for the facility. The approver must
be someone other than the requester. Reopening retains the prior count and
comparison as historical evidence and records the reason, requester and
approver.

The reopening request includes a reason, a reference identifying the affected
count line, location or source document, and a short description of what
needs to change. The reviewer sees that evidence alongside the original count
and comparison before deciding.

An affected submitted LPLPO must return through its existing authorized
workflow before the count can reopen. If no authorized return is available,
the reopening remains blocked. An affected editable LPLPO stays editable.
Keep the prior count link in the audit history and block submit or resubmit
until a current reconciled revision is linked. Recheck period dependencies
under lock before reopening.

For an LPLPO linked to Stock Opname, populate the existing
`stock_gudang_puskesmas` field per item from the warehouse portion of the
current reconciled count at the reporting cutoff. Treat this value as
read-only in the form and exported workbook, and reject changes through
form submission or XLSX import. Refresh it from the new reconciled revision
when an editable LPLPO is relinked. The whole-facility count and its Poli
and Pustu breakdown remain in Stock Opname.

Activate the LPLPO creation requirement facility by facility. A facility needs
a verified opening, sufficient journal coverage to reconcile its first gated
reporting month, and a supported transition to inventory-bound LPLPO. Every
gated LPLPO must use the inventory journal for its digital quantities so they
come from the same journal used for the reconciled count. Facilities awaiting
coverage or a supported binding transition continue using the existing LPLPO
workflow. After activation, missing or stale journal evidence in a gated month
keeps the comparison provisional and LPLPO creation blocked. Record the first
gated month explicitly so later checks can apply the same boundary.
The requirement follows the facility and reporting month. It applies both
when a Puskesmas operator creates an LPLPO and when authorized staff create
one on the facility's behalf. Existing creation permissions still apply.

The first release uses the existing January binding or adoption and later
carry-forward path. A facility without a supported binding path stays on
the existing workflow until it is eligible. The active-year LPLPO creation
sequence still starts at the earliest missing month, beginning in January.
For example, if July is the first gated month and the facility is entering
its LPLPO for the first time, January through June follow the existing
workflow and July requires a reconciled count. Missing historical records
must remain identified as missing. This release defers a new midyear binding
path for an unbound sequence.

Existing drafts for reporting months before the facility's first gated month
keep the existing workflow. Drafts already created for the first gated month
or later stay editable, and require a linked current reconciled count before
submission. An existing draft does not qualify as count evidence.

When physical units from multiple journal layers are indistinguishable, a
matching observed total can reconcile at the item, batch and expiry level.
Record the attribution limit and retain each source layer's original price
and value in the journal. Preserve any source attribution the operator can
prove. A difference that needs a layer-level posting stays open until evidence
identifies the layer and quantity to correct.

The same-facility operator gathers evidence for blocked cases. Route cases
needing independent review to the facility's designated `GUDANG` reviewer.
Show the blocking reason and the next eligible action, including who can take
it, on Stock Opname and LPLPO creation. Cases requiring a receipt correction,
stock adjustment or reopening must use the authority for that action.

Freeze the monthly roster at the start of the count. The warehouse and every
active Poli and Pustu must confirm that counting is complete or explicitly
confirm zero stock. Include inactive locations that still hold stock. An
unconfirmed location is incomplete and prevents count closure.

The first release supports monthly counts. Record quantities by location in
the item's inventory unit and capture batch and expiry where applicable.
When staff count in a different unit, retain the observed quantity and unit
and the documented conversion from verified packaging or catalog data. Use
the converted inventory quantity for reconciliation. An unverified conversion
leaves the affected count provisional. Additional non-monthly counts are
deferred.

Provide a frozen printable record for each closed count revision. Show the
facility, reporting month and cutoff, location coverage, physical and digital
quantities, discrepancies and their status at closure, and the recorded
closing actor and approval evidence where applicable. Authorized users can
view and print older revisions after a correction or reopening. Each print
uses its revision's stored comparison and closure record.

This is an agreed requirement for Feature 3. The reported operator practice
remains contextual evidence about current operations.

## Proposed workflow

### Count the whole facility at a common cutoff

- Reuse IF's pattern of an editable draft, frozen counting scope, explicit count
  entry, a completion check for missing entries, and stable detail/print output.
  Evaluate reuse of presentation components after the Puskesmas evidence and
  permission rules are agreed. IF warehouse models, live quantity comparison,
  numbering, deletion and approval rules are specific to that workflow.
- Record warehouse, all in-scope Poli and Pustu, and any exceptional storage
  identified by the facility, including damaged or expired stock still physically
  held. Freeze the location roster and its scope at start, including any inactive
  location still holding stock. Require each location to attest completion.
  Distinguish an explicit zero, a missing count and unexpected stock. Capture
  item, unit, quantity, batch/expiry and condition as observed, with source-layer
  identifiers where evidenced. Keep warehouse, Poli and Pustu observations
  distinct, then roll up for facility comparison. The current journal cannot
  supply expected quantities by subunit.
  Keep physically held stock visible by condition and custody, including
  quantities already withdrawn in the journal. Define which observations
  correspond to the journal's accounting scope and cite withdrawal evidence
  before excluding any of them from the comparable total.
- Record the facility-local cutoff date, the boundary it represents, count
  timestamps, entry timestamps and the evidence used to align observations to
  month-end. Include finalized use and effective-dated withdrawals through that
  cutoff in the journal comparison. For different count times across locations,
  use a documented movement pause or reconcile each intervening movement from
  evidence, including in-transit handoffs to avoid counting twice. Keep the
  comparison provisional when movement timing or a same-day boundary cannot be
  established from the available date-level journal and physical records.
- Derive expected balances from dated journal movements and persist the opening
  reference, covered-through date, posting and revision references or an
  equivalent stable snapshot identifier, per-layer quantity/value, and coverage
  exceptions. Preserve the baseline first reviewed and any later comparison
  revisions. Show reported draft use separately from posted use. A missing
  opening, missing finalization, unsupported receipt, or failed projection check
  leaves a visible coverage issue. A legacy LPLPO comparison may provide context
  but cannot supply original-price layers.
  Allow count capture and investigation while consumption finalization is held.
  The provisional comparison can help investigate the hold without claiming a
  finalized expected balance or authorizing a stock entry.

### Investigate and route each discrepancy

| Evidence | Proposed disposition |
| --- | --- |
| Counting or unit conversion error | Recount or correct the observation with a reason, prior reading and evidence. No inventory posting is needed. |
| Receiving error or short delivery | Route to Puskesmas receiving. Editable receiving follows its existing safeguards. For a posted receipt, use the planned audited receiving correction for an evidenced quantity overstatement on an existing line when the period permits it. Keep the case open when the error or period is unsupported or evidence is incomplete. |
| Omitted, duplicated or incorrect medical use | Fix the draft or invoke the existing authorized consumption correction when allowed, preserving month-end FEFO, exact costs and history. Record any period guard that blocks correction. |
| Expired stock | Track physical presence and withdrawal separately and use the expiry workflow for an evidenced withdrawal. Include the withdrawal date in the cutoff comparison. An item withdrawn from usable stock may still be physically held pending disposal. |
| Proven loss or damage | Seek independent authorization for a reduction on an identified existing layer when the quantity, original cost and accounting disposition are established. Document custody or quarantine separately from the approved accounting effect. |
| Surplus, ambiguous source layer, missing quantity or price, or unexplained difference | Retain an open case with the missing evidence and any known quantity. A quantity-only difference may be shown while value remains unknown. Use a verified originating workflow where available. The first release cannot post a surplus adjustment or create a layer from count evidence. |

Compare identified layers at their original prices using exact decimal arithmetic.
For indistinguishable layers with a shared item, batch and expiry, show the
evidenced quantity comparison and disclose any attribution limit. Preserve layer
prices and leave the value of an unattributed difference unknown. A verified zero
price is a known price. Keep evidence gaps open instead of creating a synthetic
receipt or balancing entry. Keep independently evidenced location and layer
differences visible even when they cancel in a facility total.

### Separate count closure, reconciliation and posting

1. An authorized counter submits a complete location roster and freezes an
   observation revision. A same-facility operator with closing authority can
   close a complete, current and reconciled count. An independent, designated
   `GUDANG` reviewer can close a complete count with open cases for a facility
   they are authorized to cover. Record the reviewer, time and count revision.
2. Cases retain the original comparison, investigation, evidence, decision maker
   and owning workflow links. Recompute against a new frozen journal comparison
   when a verified source revision changes the expected cutoff balance. Use
   sufficient coverage and evidence that all differences were resolved to mark
   reconciliation complete. Keep unresolved cases visible after count closure.
3. At an explicit checkpoint, an independently authorized adjustment would
   append a typed facility journal posting linked to approved case evidence,
   with per-layer deltas and exact cost. Validate the cutoff balance and live
   projection, preserve history and prevent negative quantity. Count closure
   and adjustment approval carry no implicit inventory write. Adjustment
   posting/reversal and dependent recalculation would be atomic. Confirm which
   dependencies can be supported before enabling posting. Loss or damage
   postings follow finalized monthly consumption in the accounting order.
   Cross-period replay remains a separate decision.
4. Correct frozen observations through a linked, reasoned revision or recount.
   Reopening requires recorded authority and preserves prior comparisons,
   cases and decisions. Correct a posted adjustment through a linked reversal
   and, when justified, replacement. If submitted LPLPO or later-period
   dependencies would be affected, hold the change and use the existing
   authorized return path where available. A returned document still requires
   a fresh dependency check. Unavailable correction routes leave cases open.

### Permissions, concurrency and report integration

- Propose active same-facility operators for preparation and counting. The
  agreed cross-facility closure authority is specific to designated
  `GUDANG` reviewers and the facilities they are authorized to cover.
  Check Django permissions and module scope separately from facility/object
  authority. Existing report grants, opening verification access and Acting
  Kepala delegations grant no Feature 3 authority by themselves. Evaluate
  adjustment approval against the actor's current LPLPO module scope,
  facility-specific approval authority and relationship to the adjustment
  preparer. Apply the same criteria to posted-receipt correction approval,
  checking the authority for that action and the correction preparer. For
  reopening, check the distinct reopening authority and independence from
  the requester. Keep these action-specific policies portable to a future
  attribute-based access control (ABAC) migration.
- Use the facility mutex that serializes receipt, consumption, expiry and LPLPO
  checkpoints. Lock the fresh actor and applicable access data, facility, then
  documents and layers in a documented order. Recheck current status, scope,
  digest, cutoff-relevant source revisions and dependent periods under lock.
  Human count sessions use frozen inputs and stale-data checks across requests.
  Retries must be idempotent, and failed checks or replay must roll back the
  entire mutation. A concurrent in-cutoff source change must invalidate stale
  approval or wait for the competing checkpoint, with a fresh check on retry.
- Check the same facility, reporting month, cutoff and qualifying count
  revision on the server inside the existing LPLPO creation transaction,
  before creating the header or item rows. Create gated LPLPO with its
  inventory binding and count link in that transaction. At submit/resubmit,
  require both an inventory binding and a current reconciled count revision
  under the same facility lock. The count should be completable before any
  LPLPO exists for that month. Apply the gate from the facility's first gated
  month to every LPLPO creation path, including authorized staff creation on
  behalf of the facility.
- Budget explicit journal and report integration for approved adjustments.
  Today's posting constraint recognizes opening, receipt, consumption, expiry
  and reversal. Today's period report falls through to consumption when an
  in-period movement is neither opening, receipt nor expiry. A new adjustment
  and its reversal therefore need explicit attribution in reports and any
  affected bound LPLPO closing/carry calculations. Test ordering against
  month-end FEFO, including later-dated adjustments on earlier eligible layers,
  before permitting historical adjustment or replay. Keep medical use, expiry
  and reconciliation effects separately visible. [Posting constraint](../backend/apps/puskesmas/inventory_models.py#L135),
  [period calculations](../backend/apps/puskesmas/inventory_reporting.py#L17).
- Keep returns, transfers and annual reconciliation outside this design unless
  explicitly added. Retain relevant observations as investigation evidence
  without introducing those movement or January opening workflows.

## Implementation and rollout

The implementation uses the Puskesmas journal and LPLPO's existing authorized
routes. See the [rollout instructions](developer_guide.md#puskesmas-stock-opname-rollout)
for readiness, grants and activation. Confirm the form fields against a recent
operator worksheet and the applicable SOP before facility rollout if available.
Actual operator practice remains unverified.

For a facility already subject to Stock Opname, December remains creatable
after the year rolls over when January through November exist. This lets
operators complete the physical comparison after December's cutoff. Gated
January can carry the previous December's inventory binding when the
facility already has a verified opening covering the new month.

## Validation path

| Check | Reproduction target |
| --- | --- |
| Count and cutoff | Enter a February month-end count in March, then compare with a separate March observation reconstructed to February month-end using documented intervening movements. Count warehouse, Poli and Pustu at different times. Verify the normalized totals, explicit zero versus uncounted, unexpected items, an unresolved movement, later posting exclusion and unchanged historical comparison after a correction. |
| Location coverage | Verify the frozen roster includes the warehouse, active Poli and Pustu, and an inactive location that still holds stock. Verify an explicit zero-stock confirmation satisfies location coverage, while an unconfirmed location blocks closure. |
| Counting units | Enter a documented box-to-inventory-unit conversion and verify the normalized quantity, original observation and evidence are retained. An unverified conversion leaves the comparison provisional. |
| Valuation and investigation | Count otherwise identical layers with different sources and prices. Verify approved loss/damage reductions use the identified existing layer and exact cost. Confirm surplus and unknown-layer cases stay open without a posting or a new layer. Correct a documented short delivery on a posted receipt and verify original rows and movements remain intact, the linked correction uses the original price and source, and report totals classify it under receiving. Reject quantity increases and changes to batch, price, source or receipt date through this correction path. Exercise corrected use, expiry and an exact linked adjustment reversal. |
| Indistinguishable layers | With two receipt layers for the same item, batch and expiry at different prices, verify a matching physical total reconciles with the attribution limit recorded and each journal valuation intact. Repeat with a shortage and verify it stays open with unknown value and no layer posting until the affected layer and quantity are evidenced. |
| Blocked cases | Trigger a missing-evidence case and a case requiring independent review. Verify Stock Opname and LPLPO creation show the blocking reason and next eligible action. Verify the facility operator can gather evidence, review is restricted to the designated reviewer for the facility, and posting or reopening still requires authority for that specific action. |
| Loss or damage ordering | Record a known incident date before month-end and apply an approved reduction to a layer with finalized consumption. Verify the posting uses the month-end cutoff, leaves the finalized FEFO allocation intact, and reduces the remaining layer at exact cost. An insufficient remaining balance leaves the case open and writes no movement. |
| Recalculation with a posted adjustment | Rerun same-month FEFO after an eligible correction. Verify it succeeds when the approved reduction still fits the same layer and retains its journal entry, quantity and cost. Repeat with insufficient stock on that layer and verify the whole correction rolls back and the conflict is routed for review. |
| Permissions and history | Verify a same-facility operator can close a complete, current matching count. Verify only an independent, designated `GUDANG` reviewer covering the facility can close a complete count with open cases, and that closure leaves cases open. Exercise adjustment approval, posted-receipt correction approval and reopening with and without LPLPO `OPERATE` scope and the facility-specific authority for each action. Reject self-approval, including a reopen requester approving their own request. Exercise revoked access, stale evidence, retries, reversal and protected history. |
| Reopening evidence | Require a reason, affected record or location reference and description of the requested change. Verify the reviewer can inspect these with the prior count and comparison and that approval retains the earlier revision and records the decision. |
| Printable history | Print a closed revision with open discrepancies, then reopen, reconcile and close a new revision. Verify the earlier print still shows its original quantities, discrepancy status and closure evidence. Verify an authorized user can print both revisions and an unauthorized facility user cannot access either. |
| Concurrency and dependency guards | Correct a posted receipt after same-month consumption finalization. Verify FEFO reallocates with unchanged reported use and original costs, retains linked reversals and replacements, and refreshes editable bound LPLPO and carries. Verify shortage, an affected submitted LPLPO or later finalized consumption leaves the journal, projections and case unchanged by the attempted correction. In PostgreSQL transaction tests, race closure, adjustment, or reopening with receipt/expiry/consumption mutation and LPLPO submit. Verify single posting and live dependency rechecks. |
| LPLPO and outputs | Verify count completion can occur before an LPLPO exists. A current reconciled count allows operator creation subject to existing checks. Missing, stale, wrong-month and foreign counts, or a closed count with an unresolved case, must block creation without writing a header or lines. Verify an affected submitted LPLPO blocks reopening until authorized return. Verify affected editable LPLPOs can be edited but cannot submit or resubmit until a current reconciled revision is linked. Preserve the old link in history and verify Feature 2 prerequisites and editable carry synchronization. |
| LPLPO warehouse stock | Reconcile an item held in the warehouse, a Poli and a Pustu. Verify LPLPO shows only the warehouse quantity for the field and Stock Opname retains the full count. Verify form and XLSX edits cannot change the derived quantity, unrelated inputs remain editable, and relinking an editable LPLPO refreshes the value while preserving the prior link. |
| Facility rollout | Compare two facilities with different journal coverage and first gated months. Verify creation follows the existing workflow while a facility awaits coverage, and requires a current reconciled count from its first gated month. Exercise creation as both the facility operator and authorized staff acting on the facility's behalf. Verify a later coverage gap blocks creation for a gated month and cannot be bypassed by falling back to legacy LPLPO. Verify existing drafts before the gate follow the existing submission workflow. Existing drafts for gated months stay editable and cannot submit without a current reconciled count. |
| Inventory binding | Compare a facility with a verified opening but an unbound LPLPO sequence and one using January binding and later carry-forward. Verify the first stays on the existing workflow until eligible for activation. For July activation, verify the January–June sequence follows the existing workflow and July is created with its inventory binding and reconciled count link together. Verify the digital figures use the journal and no unbound gated LPLPO can be created or submitted. |

Existing regression suites to run when implementing include
`apps.stock_opname.tests`, `apps.puskesmas.test_inventory`,
`apps.puskesmas.test_consumption_inventory`, `apps.puskesmas.test_expiry`,
`apps.lplpo.tests` and `apps.lplpo.test_offline_xlsx`. On Windows run each with
`.\scripts\run-django-test.ps1 -Target <test.path>`. If routes change, also run
`apps.core.tests.test_url_consistency`. This draft records source inspection.
