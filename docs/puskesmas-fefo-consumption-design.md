# Feature 2: Puskesmas FEFO consumption and inventory reporting

Status: Feature 2 and Puskesmas expiry integration implemented locally; see section 20 for the current contract.
Updated: 2026-11-23. Branch: `design/puskesmas-fefo-consumption`.
Code baseline: `03df29523686d1b55128cdce475cd1103011414c`.

## Scope at a glance

**Feature 2 connects recorded monthly use to the facility inventory journal and
original costs.** Feature 1 already supplies verified opening stock and linked IF
receipts. Feature 2 designs how actual monthly Poli/Pustu use consumes those layers
using FEFO, preserves each allocation's quantity/cost, and feeds consistent
quantity/value results into LPLPO and inventory reporting. Month-end accounting is
agreed, as are editable drafts, explicit finalization, shortage holds and the LPLPO
submission prerequisite. Expiry, correction/dependency and valuation details remain open.

**Feature 3 is separate, deferred follow-up: Puskesmas Stock Opname and
Reconciliation.** It will address physical counting, discrepancy investigation,
reviewed adjustments and the proposed opname prerequisite for LPLPO submission.
See section 15 before starting the next feature. Do not expand feature 2 to build
those counting/reconciliation screens or the mandatory opname gate.

Neither feature has implementation authorization from this design discussion.
Feature 2 completion alone must not remove incomplete-coverage warnings or imply
that physical stock has been verified.

Separate expiry follow-up: [issue #325 — Plan a future Puskesmas expiry workflow](https://github.com/hatamirais/dinkes-farmalkes-ims/issues/325).
This records the possible future app/workflow for design discussion, not approved
implementation scope. It does not resolve feature 2's open monthly FEFO expiry
eligibility policy or remove expired quantity/value automatically.

Separate returns/transfers follow-up: [issue #326 — Plan Puskesmas stock returns to IF and transfers between facilities](https://github.com/hatamirais/dinkes-farmalkes-ims/issues/326).
The user explicitly deferred these physical movements outside Feature 2 on
2026-11-18. This does not mean they never occur or that unsupported movements are
covered by the inventory ledger. Design their source/destination accounting and
operational workflow separately when that work starts.

Feature 2 must explain expiry-related allocation exclusions to the operator:
identify the affected item/layer/batch, expiry date, reporting cutoff, recorded
quantity, eligible/excluded quantities and reason. The user identified this
visibility need during design discussion. The placement and presentation remain
proposed; a consumption review/hold breakdown is the recommended minimum, not a
new full expiry application. Distinguish stock still owned/recorded from stock
eligible for automatic consumption allocation. Do not silently remove quantity or
value. Future expiry monitoring/notifications and disposition workflows remain
tracked separately in #325. This visibility requirement does not approve the
proposed month-end exclusion rule: treatment of expiry within the month remains
open, including whether/how evidenced pre-expiry use can be allocated.

Operational clarification from the user: Puskesmas operators normally set items
aside when less than a month remains before expiry. This is reported practice,
not a verified universal policy or an approved automatic cutoff. Calendar-month
versus fixed-day interpretation, exact boundary and withdrawal authority remain
undefined. Do not silently translate it into a hard-coded 30-day rule.

Implication for design discussion: expiry alone cannot identify stock actually
withdrawn from use. Automatic FEFO must not silently treat physically set-aside
quantity as usable. Consider recording layer/batch, withdrawn quantity, effective
withdrawal date, actor and reason through the future expiry workflow (#325),
preserving owned quantity/value until an explicit disposition. Withdrawal during
a month also does not prove whether earlier monthly consumption used that batch.
Any minimum withdrawal-recording integration needed by feature 2 must be explicitly
agreed or deferred with the corresponding allocation/readiness limitation. This
clarification does not authorize a new withdrawal workflow in feature 2 or approve
the earlier proposed blanket month-end expiry exclusion rule.

Subsequent user clarification supersedes the proposed neutral set-aside model:
the operator explicitly marks a selected batch/quantity as expired and excludes
it from stock; reports retain it as an expired-stock movement. This is an
operator-triggered action, not an automatic action when an alert threshold is
reached, and it has no separate approval route. The reported physical practice
may involve near-expiry items; whether the product label should distinguish
near-expiry withdrawal from already-expired stock remains to discuss.

Agreed preparation direction for the future Puskesmas expiry module: a deliberate
operator posting action, broadly analogous to IF's expiry stock-removal checkpoint
but without a separate reviewer. Preserve the removed quantity, original-layer
cost, actor, effective/recorded dates, reason and source links as explicit expiry
outflow history; do not erase the stock history or classify it as medical use.
Reports must reconcile opening + receipts - consumption - expiry outflow + other
signed movements = closing, for both quantity and value. No extra approval route
does not waive own-facility authorization, validation, atomic posting, duplicate
protection or audit/logging. Actual disposal/return is not implied by this action.

This replaces the earlier recommendation that operator 'set aside' should only
reduce allocatable quantity while leaving reported stock unchanged. The physical
custody of removed goods, count/report boundaries, correction rules and whether
the posting belongs before/after monthly consumption still require agreement.
Date-aware FEFO must respect posted expiry outflows without removing quantities
twice. No module implementation or Feature 2 scope expansion is authorized here;
these clarified requirements remain part of the #325 preparation.

Agreed monthly ordering (user agreement, 2026-11-17): record all known expiry
outflows for the reported month before finalizing that month's consumption. FEFO
allocates consumption from the stock remaining after those outflows, while still
respecting source/date eligibility and prior consumption. A later expiry correction
must recheck the finalized consumption and affected LPLPO through the applicable
correction/reopening rules; it must not silently change their balances. This is
month-end accounting ordering, not evidence of actual daily batch use.

The required expiry posting capability is a cross-feature dependency: agreeing its
ordering does not implement #325, authorize a substitute manual adjustment, or
establish complete movement coverage before that capability exists. Treatment of
stock past its expiry date without a recorded operator outflow remains unresolved;
neither automatic removal nor blanket month-end allocation exclusion is approved.

## 1. Decision record and boundaries

PR [#324](https://github.com/hatamirais/dinkes-farmalkes-ims/pull/324)
is merged. GitHub metadata reports merge commit `03df295...` and merge time
2026-11-17 02:08:18 UTC (09:08:18 Asia/Jakarta); local main was at that commit
with a clean working tree before creating this branch. No remote update beyond
that merge is claimed. PR test results are historical reports, not checks rerun
for this investigation.

Agreed in this discussion:

- Investigate/design first; do not implement until the design is agreed.
- **Inventory presentation:** provide a separate Persediaan Puskesmas submenu,
  resembling an item list but showing facility holdings rather than editing the
  shared item catalog (user agreement, 2026-11-18). Show one item summary with
  quantity/value and drill-down into original-price layers, remaining quantities,
  batches, expiry dates and known sources. Display the reporting cutoff and
  accounting completeness; monthly closing is not today's live availability.
  HTML, print and Excel must use consistent accounting calculations. Puskesmas
  operators see only their own facility; IF staff read access follows the existing
  dedicated Puskesmas report selection/aggregation permissions, granting no new
  mutations. Expiry and stock opname remain separate operational menus. Exact
  route/layout details remain implementation design, not runtime changes.
- **Rollout dependency:** build and test Feature 2 first, but enable operational
  consumption finalization and inventory-backed LPLPO submission only after the
  Puskesmas expiry module (#325) is integrated and verified (user agreement,
  2026-11-18). Draft preparation and testing may proceed beforehand. Keep the
  implementations separate; do not silently expand Feature 2 to implement expiry
  posting. Record the activation/coverage boundary explicitly, and do not bypass
  the dependency with synthetic expiry movements or claim reliable live stock.
  Existing legacy-mode behavior is not silently converted by this rollout choice.
- **Losses and damaged stock are Feature 3 work** (user agreement, 2026-11-18).
  Their investigation and evidenced adjustments belong to Puskesmas stock-opname/
  reconciliation, not Feature 2. Keep them separate from medical consumption and
  expiry outflows. Deferral does not prove absence of these movements: if such a
  discrepancy occurs before a supported resolution exists, affected coverage
  remains incomplete/unresolved; do not invent a balancing movement.
- **Physical returns to IF and transfers to another facility are outside current
  scope**, tracked separately in #326 (user direction, 2026-11-18). Do not add
  these workflows to Feature 2 or disguise their quantities as consumption/expiry.
- **Current inflow scope:** the user confirms that all Puskesmas stock currently
  comes through Instalasi Farmasi (2026-11-18). Feature 2 uses verified opening
  stock and supported linked IF receipt confirmations; direct purchases/donations
  are excluded from current implementation scope and may be designed separately
  if later needed. This is user-provided operational scope, not a database audit
  or evidence that every IF receipt is recorded. Unsupported sources must not be
  fabricated as IF receipts or assumed covered if practice changes. This decision
  does not establish coverage of returns, losses or other outgoing movements.
- **January opening adoption:** when January LPLPO already contains manual opening
  values, show the difference from independently verified, posted opening inventory
  and require explicit operator confirmation to adopt it. Update opening quantities
  and dependent calculations atomically, retaining previous values and adoption
  actor/time/source in audit history and logs. Preserve request quantities, reasons
  and other non-inventory operator inputs. Once adopted, opening stock is derived
  from verified inventory and cannot be manually overridden in the LPLPO form or
  offline import. Submitted/processed LPLPO must first follow authorized
  return/reopening; never silently overwrite it. Later finalized-period restrictions
  remain applicable. This is Feature 2 document integration, not a physical count
  or the future mandatory stock-opname gate (user agreement, 2026-11-18).
- **Consumption correction authority:** only an authorized Puskesmas operator
  within their own active facility or Super Admin may correct consumption, always
  preserving audit history and logs (user decision, 2026-11-18). No original-
  preparer-only restriction was requested; authorization follows facility and
  action access. Existing submitted-LPLPO return/reopening and later-finalized-
  month restrictions still apply. This does not grant operators authority to
  reopen submitted LPLPO themselves. Do not grant GUDANG, KEPALA or other staff
  consumption correction authority through opening/report permissions.
  Terminology clarification: Super Admin is the project's ADMIN administrator,
  distinct from ADMIN_UMUM. `UserManager._create_user` and `User.save` force Django
  superusers to ADMIN and prevent ordinary creation/promotion to ADMIN without
  superuser status. The model preserves existing legacy ADMIN/non-superuser rows,
  and `is_super_admin()` deliberately includes them. Do not describe ADMIN_UMUM
  as Super Admin or invent a new ordinary-ADMIN role tier. Preserve the existing
  helper's compatibility semantics when designing this consumption checkpoint;
  the separate opening-verification authority remains unchanged.
- **Remove the LPLPO harga_satuan column for now**, rather than displaying an
  average that may confuse operators (user decision, 2026-11-17). Original layer
  prices/costs remain in inventory accounting and monetary reports. This is a
  presentation/input decision, not authorization to delete historical price data
  or implement the change before the design is agreed.
- **Initial correction restriction:** an earlier month's consumption cannot be
  corrected once any later month's consumption for the same facility is finalized.
  Such corrections require an authorized reopening process covering affected
  periods; implementing that process is deferred. With no later finalized month,
  corrections may proceed subject to allocation, period and authorization checks
  and the agreed return/reopening prerequisite for submitted LPLPO. Never silently
  recalculate finalized history (user agreement, 2026-11-17).
- **Known expiry outflows for a month precede that month's consumption
  finalization.** Later expiry corrections must recheck consumption and LPLPO,
  using authorized return/reopening when already submitted (2026-11-17). Full
  expiry posting remains the separate #325 follow-up; see the dependency above.
- **Monthly Pemakaian Rinci records how much each Poli/Pustu actually uses in
  that month** (user clarification, 2026-11-17). It is not an internal-transfer
  document. Do not subtract warehouse-to-room/Pustu issues again.
- **Verified month-end accounting is sufficient**, accepting the limitations of
  monthly totals rather than collecting actual daily use dates (user agreement,
  2026-11-17). This does not approve a posting action, shortage policy, expiry
  exception, or a claim of today's live availability.
- **Keep Puskesmas Stock Opname and Reconciliation as feature 3**, to revisit after
  feature 2. Record the handoff now without implementing or broadening feature 2
  (user direction, 2026-11-17). The proposed mandatory opname gate remains a
  feature-3 design decision.
- **Monthly consumption is saved as a draft and explicitly finalized on or after
  the last day of the reported month; it remains correctable and LPLPO follows updates,
  with audit trail and logs** (user direction, 2026-11-17). Retain immutable posted
  revisions and journal evidence underneath that editable workflow. This is design
  agreement, not implementation authorization.
- **Submitted/processed LPLPO requires authorized return/reopening before
  consumption corrections can synchronize it** (user agreement, 2026-11-17).
  No silent changes to submitted history. Existing stage/distribution restrictions
  still apply; authority and treatment of later dependent periods remain open.
- **Late consumption finalization is allowed**, including in a later calendar
  month/year, while the accounting effective date stays the reported month's final
  day and recorded_at is the actual posting timestamp (user agreement, 2026-11-17).
  Example: January finalized on February 2 retains January 31 as its accounting
  date. This does not waive coverage, period/dependency, allocation or access checks,
  nor change the current LPLPO active-year creation rule.
- **Shortages do not prevent draft saving but block consumption finalization until
  every quantity can be fully allocated** (user agreement, 2026-11-17). Failed
  correction leaves the previous finalized revision and LPLPO unchanged. Feature 3
  is the planned home for guided discrepancy investigation/resolution, including
  receipt and consumption recording errors. No physical-count or adjustment UI
  is added to feature 2.
- **LPLPO drafts may be prepared/saved, but submission requires successfully
  finalized consumption for the same facility/month** (user agreement, 2026-11-17).
  Missing, draft or shortage-held consumption blocks submission with a clear reason.
  This gate belongs to feature 2 and is distinct from feature 3's proposed physical
  stock-opname gate. Submission must use the accepted current finalized revision;
  it must not deduct stock again or use an older revision to bypass an active hold.

Existing feature-1 agreements remain: whole-facility opening; separate original
price layers; explicit unknown provenance; no posting without original price or
required expiry; independent opening verification; immutable posted receipts;
continuous annual carry with explicit differences and complete prior coverage.

Still OPEN: detailed timing/chronology and update boundaries; expiry policy for monthly
totals; posting/reversal and downstream dependencies; layered valuation versus the
LPLPO format; movement coverage/readiness; authorized LPLPO return/reopening details.
All entities and behavior below labelled proposed are recommendations, not current
schema, approved requirements, or permission grants. The feature-1 handoff is input
to this discussion, not feature-2 authorization.

After reviewing date-granularity tradeoffs, the user accepted month-end accounting.
Current inflows are confirmed by the user as IF-only; purchases/donations are deferred.
Physical returns/transfers are deferred to #326; loss/damage investigation and
supported adjustments are deferred to Feature 3. Draft/finalization shortage
holds and the finalized-consumption prerequisite for LPLPO submission are agreed.
The user decided to remove the LPLPO harga_satuan column for now to avoid confusion;
do not replace it with an average. An inventory submenu for original layer
prices and facility quantities/values is agreed. Exact monetary presentation/report contracts and historical
compatibility still need to be finalized; implementation is not authorized.
Feature 1 records earlier user-provided development-only/no-real-data context;
this investigation did not audit a database or reconfirm deployment status.

## 2. Verified current state

References are relative to the repository root, at the baseline above; symbols
remain useful if line numbers move. Targeted inspection was sufficient; Graphify
was unnecessary. Read root guidance, SYSTEM_MODEL and puskesmas/lplpo/users/core/
reports/distribution guides, plus the opening design and import-performance notes.

| Finding | Primary code evidence |
| --- | --- |
| One consumption header per facility/month/year; entries are nonnegative integer item/subunit quantities. There is no posting status, business day, allocation, valuation or revision field. | `backend/apps/puskesmas/models.py:436` (`PuskesmasConsumption`), `:513` (`PuskesmasConsumptionEntry`) |
| Input is labelled use at a Poli/Pustu. Only positive cells produce rows, so missing rows cannot prove explicitly verified zero use or complete coverage. User has now confirmed the business meaning as actual monthly use. | `backend/apps/puskesmas/forms.py:746` (`PuskesmasConsumptionMatrixForm`), `:830`, `:910` (`build_entries`) |
| Save immediately synchronizes detailed quantities to editable LPLPO; edit deletes/recreates entries; delete cascades entries. None posts inventory. | `backend/apps/puskesmas/views.py:860` (`consumption_create`), `:1021` (`consumption_edit`), `:1125` (`consumption_delete`); `services.py:66`, `:80` |
| Consumption mutability checks only same-month LPLPO DRAFT/REJECTED_PUSKESMAS or no LPLPO. Create locks LPLPO before Facility; edit/delete do not use the shared facility wrapper. Thus the receipt/LPLPO serialization contract does not yet cover consumption. This is code evidence, not a reproduced race. | `backend/apps/puskesmas/services.py:49`; `views.py:903`, `:1052`, `:1135`; `inventory_locking.py:12` |
| Receipt/LPLPO create/edit/import/submit use actor/module then facility serialization before view work. Consumption must join this order rather than retaining LPLPO-before-facility. | `backend/apps/puskesmas/inventory_locking.py:12` (`serialize_facility_document`); receipt decorators in `views.py`; `backend/apps/lplpo/views.py:503`, `:776`, `:985`, `:1112` |
| Opening reviewer is an active superuser or GUDANG with LPLPO OPERATE+, different from preparer. Active KEPALA with LPLPO VIEW+ has only opening oversight. | `backend/apps/puskesmas/inventory.py:68`, `:81`, `:504` |
| Account readiness is hard-coded FOUNDATION_INCOMPLETE. There is no persisted closed-through or monthly coverage record. | `backend/apps/puskesmas/inventory_models.py:39` |
| Initial opening creates distinct layers, positive projections/journal, then posts eligible existing confirmed receipts atomically. An existing account blocks annual posting. | `backend/apps/puskesmas/inventory.py:488`, `:504` |
| Linked receipt posting uses issued distribution snapshots and actual received_date, rejects future dates/missing source/price/required expiry, and is unique per receipt. Earlier-than-opening receipts are excluded from posting. | `backend/apps/puskesmas/inventory.py:561` (`post_receipt`) |
| Posting supports exactly one opening or receipt source. Layer supports exactly one opening-line or receipt-line origin. Movement is unique per posting/layer. Projection inherits a guard that prohibits ordinary updates, so a consumption service cannot simply call balance.save(). | `backend/apps/puskesmas/inventory_models.py:10`, `:24`, `:135`, `:151`, `:171`, `:180` |
| Posted inventory and receipt mutations have application/ORM guards and read-only Admin surfaces. These are not database triggers or a guarantee against direct SQL. | `backend/apps/puskesmas/inventory_models.py`; `inventory_locking.py`; `admin.py:22` |
| January opening stays manual in LPLPO. Later months carry the previous usable LPLPO closing, including negative quantities, without requiring CLOSED. | `backend/apps/lplpo/models.py:60`, `:81`, `:505`; create flow in `views.py:504`; lplpo guide |
| LPLPO receipt prices are monthly quantity-weighted averages, with prior-month fallback. One harga_satuan values opening, receipts, use, and closing. The same value cannot generally equal four distinct layered valuations. | `backend/apps/lplpo/models.py:226`, `:359` onward (`nilai_*`), `:407`, `:447` |
| Detailed-use totals are server-authoritative for editable LPLPO pemakaian; there is no posted-versus-draft distinction. LPLPO submission currently changes document workflow, not inventory. | `backend/apps/puskesmas/services.py:66`, `:80`; `backend/apps/lplpo/views.py:78`, `:1113` |
| Rincian takes latest usable same-year LPLPO up to end month (including Draft, excluding rejected), then later confirmed receipts minus later detailed use. Missing baselines exclude facilities. The quarter/semester is an ending-stock cutoff. | `backend/apps/puskesmas/views.py:2292` (`puskesmas_report_persediaan`); `exports.py:272` |
| Rekap selects LPLPO rows within selected month bounds; opening uses start-month stock_awal*price, flows use each month's price, closing uses latest selected row per facility/item. The docstring says year-to-date but code filters start_month..end_month. Missing periods need explicit coverage; arithmetic identity is not guaranteed across changing monthly prices. | `backend/apps/puskesmas/views.py:2605` (`puskesmas_report_rekap_persediaan`), `:2660` onward; `exports.py:410` |
| Riwayat Pemakaian uses only DISTRIBUTED/CLOSED LPLPO, not all detailed-use documents. Self-check is a latest non-rejected LPLPO snapshot without post-baseline adjustments. | `backend/apps/puskesmas/views.py:2191` (`puskesmas_report_pemakaian`), `stock_current`; puskesmas guide |
| HTML/print share report templates/data, and Excel consumes view-calculated report rows; rincian already exports a coverage sheet. This is the pattern to preserve. | `backend/templates/puskesmas/report_persediaan.html`, `report_rekap_persediaan.html`; `backend/apps/puskesmas/exports.py:272`, `:410` |
| Report access uses puskesmas_reports and explicit staff selection/aggregation Django permissions. It grants no operational cross-facility writes. | `backend/apps/users/access.py:505` onward (`puskesmas_report_access`); `backend/apps/puskesmas/views.py` (`_resolve_report_facility`) |
| Ordinary consumption creator gate permits PUSKESMAS or is_super_admin, with same-facility checks for others. is_super_admin also covers legacy role ADMIN; opening authority is deliberately different. | `backend/apps/puskesmas/views.py:218`, `:224`; `backend/apps/users/access.py` (`is_super_admin`) |
| Warehouse expired/recall/opname details refer to stock.Stock. They do not supply missing facility-layer movements. LPLPO has removed pembelian_puskesmas. | `backend/apps/expired/models.py:59`, `recall/models.py:64`, `stock_opname/models.py:103`; `backend/apps/lplpo/models.py:226` |

Documentation discrepancies found: reports/AGENTS still describes generic Reports
authorization, superseded by users access code/root/puskesmas guides. Some older
SYSTEM_MODEL receipt-role wording also omits legacy ADMIN authority, while its
foundation section records it. These are not proposed permission changes. Only
this design record is edited in this phase; canonical behavior docs must be aligned
when affected implementation/documentation work is authorized.

## 3. Posting date: month-end accounting agreed; detailed policy OPEN

| Choice | Advantages | Costs and limitations |
| --- | --- | --- |
| Monthly totals, one month-end accounting allocation | Fits the confirmed monthly workflow; retains existing matrix; least entry burden; exact quantities and assigned original-layer accounting costs can reconcile at month end. | No actual use dates or batches. A late-month receipt may fund earlier actual use. An item used before expiry but expiring mid-month appears ineligible at month end. Cannot prove daily availability, physical FEFO compliance, or live stock today. |
| Dated consumption totals per item/subunit, monthly rollup | Can exclude receipts arriving after use and stock expired on that use date; allows meaningful daily as-of balances when every movement is timely recorded. | More entry/import work; requires source dates; monthly totals alone cannot be converted into dated history. Still an accounting FEFO assignment, not proof staff physically chose the assigned batch. |

Example: 20 units available on the 1st, 80 received on the 25th, monthly use 60.
Month-end allocation succeeds. It cannot tell whether 60 were used on the 10th
(unsupported by recorded stock) or the 28th. Do not distribute 60 across days by
assumption. Likewise, stock expiring on the 15th could legitimately have been used
on the 10th; an undated total cannot establish this.

Agreed direction: retain monthly entry with explicitly labelled month-end
accounting allocation and its limitations. Actual-use-date eligibility and
daily/current availability cannot be promised from these totals. Dated input is
retained above as an alternative if requirements change. Explicit consumption
finalization is the agreed checkpoint; late finalization is allowed and submitted
LPLPO requires authorized return/reopening before synchronized corrections.
Detailed chronology/dependencies and the expiry evidence path remain open.

Agreed direction, with unresolved details explicitly marked:

1. Save editable draft quantities without stock deduction. An explicit finalize
   action on or after the month's final day is the user's chosen workflow; there
   is no single-day-only finalization window. Validation of complete receipts/prior
   coverage and later-period dependency restrictions remains proposed.
2. Effective date is calendar month end; opening precedes January 1 activity;
   receipts on a date precede that date's month-end accounting use. Recorded_at
   remains the actual posting timestamp. Finalization cannot precede the month's
   final day. Same-day receipts/use after finalization need revision/reconciliation
   before claiming the entire day is covered; finalizing during that day does not
   prove all remaining activity is recorded.
3. Receipt dates inside the month qualify; later months do not. Earlier month use
   must be posted first, including an explicit zero-use completion.
4. LPLPO consumes finalized monthly use. Subsequent accepted consumption updates
   synchronize its consumption and derived quantities/values in the same atomic
   operation as the revised posting. Whether draft consumption is also shown as
   provisional LPLPO input remains open. Saving LPLPO, rendering reports, and retries
   never deduct again. Agreed: LPLPO draft preparation/saving is allowed, but
   submission requires successfully finalized consumption for that facility/month.
   Missing/draft/shortage-held consumption blocks submission with a clear reason.
   Submitted-document correction requires authorized return/reopening first.

The earlier alternative of posting only as part of LPLPO submission is not the
selected direction: consumption has its own explicit finalization checkpoint.

Finalized consumption remains editable as a business workflow, per the user's
direction. Proposed mechanics: preserve the previous revision/allocations, append
exact reversal and replacement postings, and refresh the eligible LPLPO atomically.
Record before/after quantities, allocation/cost changes, actor, effective/recorded
times, reason, revision links and synchronization outcome in durable history and
structured logs. A failed allocation/replacement must leave the prior posted
consumption and LPLPO unchanged. Show a failed attempt as an error/log rather than
as a successfully synchronized revision. Current DRAFT/REJECTED_PUSKESMAS LPLPO
mutability is a verified code boundary. Agreed: submitted/processed LPLPO must first
be returned/reopened through an authorized workflow before consumption corrections
can synchronize it. Return/reopening does not itself reverse consumption or grant
permission to rewrite historical postings. Later dependent periods and authority
details still require agreement.

The month-end expiry problem needs a decision with the date choice: recommend
excluding expiry <= effective date for ordinary automatic allocation. If this
holds a real pre-expiry use, require dated evidence and an approved dated path,
or choose dated consumption from the start. Do not silently permit expired stock,
assume the use happened earlier, or let shortage resolution override expiry.

## 4. FEFO and shortages (proposed, business policy OPEN)

Allocate same-facility/item posted eligible balances only. Opening stock is
available at the declared January cutoff, not an invented acquisition date.
Receipt posting effective_date must be <= consumption effective_date. Exclude
unverified/incomplete, future, voided/reversed origins, quarantined/recalled stock
where such a state exists, and nonpositive available quantity. Unknown optional
provenance accepted by opening verification stays explicitly unknown and does not
become invented provenance or an automatic reason to discard that verified stock.

Order: expiry ascending NULLS LAST, origin posting effective_date, origin posting
PK, layer PK. Blank expiry is eligible only under verified catalog policy permitting
it. Missing mandatory expiry holds posting; future catalog-policy changes need
explicit review rather than silent history rewriting. On expiry date, recommend
ineligible (matches warehouse `Stock.is_expired` comparison, but use the chosen
business date rather than today's clock). Expired units remain owned quantity/value
until an explicit disposal/return/adjustment; disclose unusable quantity separately
from allocatable quantity. Expiry itself must not silently delete value.

For subunit costs, allocate an item's total FEFO first, then attribute contiguous
slices to immutable entry snapshots sorted by subunit PK. Display sort_order/name
changes must not change costs. This is deterministic accounting attribution, not
evidence that a particular Pustu physically used a particular batch. If that claim
is required, capture actual batch/use evidence and reconsider facility-wide FEFO.

Agreed shortage handling: allow draft save, show reconciliation requirements,
and hold the entire period unposted when any item cannot be fully allocated. Show
requested, eligible, short, expired, future and unposted-source quantities and the
coverage cutoff. No partial posted document, negative synthetic layer, zero-cost
plug, borrowed other-facility stock, or guessed purchase. Valid resolutions include
correcting input, recording a supported omitted receipt, or reviewed source-backed
adjustment. Retry rechecks everything; it never automatically posts merely because
a later receipt arrived.

Draft saving, the finalization hold, and requiring successful consumption
finalization before LPLPO submission are agreed. The earlier alternative of
submitting an incomplete/unvalued LPLPO while consumption is held is not selected.

Discussion example (illustrative): records support 70 eligible units, while the
operator reports actual use of 90. Preserve the reported 90 as evidence; the gap
of 20 may reflect an omitted source, wrong opening/input, expiry eligibility, or
another unrecorded movement. Do not silently lower use to 70. Separate three choices:

- Saving the reported facts: agreed to allow a draft with the discrepancy.
- Posting a costed inventory event: agreed to hold the whole event until all
  quantities can be allocated to supported layers; show no invented cost for 20.
- Submitting LPLPO: agreed to hold submission until consumption for that month is
  successfully finalized. Draft LPLPO preparation/saving remains allowed. Current
  submitted LPLPO locks same-month source mutations; authorized return/reopening
  remains required for corrections.

Accepted tradeoff: an unresolved allocation shortage can delay LPLPO submission
and its stock request. Draft preparation stays available. The application must
explain the blocking item/quantity and reason; it must not fabricate stock or costs
to release the gate. Any operational emergency exception would need a separate
explicit decision rather than an undocumented bypass.

## 5. Allocation, journal, idempotency and concurrency

Proposed additive concepts; final field/class names remain implementation details:

| Concept | Contract |
| --- | --- |
| Consumption revision and immutable entry snapshots | Facility/period, revision, effective date, digest, actor/time, source header; snapshot item, subunit identity, quantity. Protect originals; editing current entries cannot erase posted evidence. |
| Consumption posting | Extend existing posting source constraint for exactly one consumption revision as an additional source, with unique source identity. Add event kind and protected reversal/replacement links without invalidating old opening/receipt rows. |
| Allocation | Protected posting/revision-entry/layer, positive whole quantity, original unit_price snapshot and exact extended cost. Unique posting/entry/layer. Sum per entry equals posted input quantity. |
| Movement | Aggregate all subunit allocations for the same layer into one signed movement per posting/layer to retain existing uniqueness. Negative use; reversal appends the exact positive original quantity and price. |
| Period coverage/closing snapshot | Facility/period, version, completeness and exception reasons, source counts/digests, opening/flow/closing quantity and value per item, close/reopen actor/time. Explicit zero-use confirmation distinct from absent data. |
| Projection | Mutable only through a narrow inventory service under locks, rebuilt from journal; immutable origin economics and historical movements remain guarded. Current ImmutableRecord inheritance must be deliberately changed for Balance, not bypassed broadly in views. |

All required database effects occur in one atomic transaction: lock and recheck
active actor/module permissions, facility, source/status/revision, prior period and
closure, candidate balances, then create revision/posting/allocations/movements,
update projections and coverage, and refresh/snapshot the applicable LPLPO.
Never put required stock/LPLPO effects in on_commit; reserve it for optional
notifications. Retry same source/revision/digest returns the existing result;
changed payload for an existing event is rejected. Database uniqueness backs
idempotency; UI button disabling is supplementary only.

Use the existing Facility mutex to serialize all facility writes, including
consumption create/edit/delete/finalize/reverse, receipt catch-up/live confirmation,
LPLPO transitions/imports, closure/reopen and later adjustments. It exists even if
no account or LPLPO exists. Target order is actor/module -> facility -> workflow/
period rows -> source/catalog/balance rows in consistent PK order. Retain compatible
receipt/source ordering; inspect every affected path, including rejection/delete,
before claiming a global lock-order guarantee. Existing consumption LPLPO-first
locking must change. Do not acquire actor locks for a second user while holding
facility locks. Recheck role/facility/digest/live status after locks.

Lock candidate balances by stable PK; perform FEFO ordering in memory from the
locked, reloaded rows. No skip_locked: it could skip the earliest-expiring stock
and report a false shortage. Facility locking also serializes new eligible receipt
layers against allocation; locking only existing balance rows cannot protect an
absent/new layer. Other facilities should continue independently. PostgreSQL
concurrency tests must verify final ledgers and totals, not just HTTP success.

Cross-row facility/item/price/source consistency and allocation sums need explicit
service validation and reconciliation tests; ordinary CheckConstraint cannot be
assumed to enforce related-row accounting. Add DB checks/unique constraints for
local positivity, event identity and valid source shape. Audit existing rows before
new restrictive constraints; separate any data fix from constraint migrations.
Do not edit migrations 0012–0015 or synthesize historical allocations.

## 6. Edits, reversals, backdating and period closure (OPEN)

Recommended first policy:

- Draft: editable; delete/cancel allowed only before any posting, retaining the
  audit required by the final workflow. Draft values never count as posted stock.
- Finalized consumption is correctable by user agreement; individual posted input
  snapshots, allocations, movements and original costs are not overwritten.
  A reviewed correction appends an exact reversal and a new revision/replacement
  atomically; failed replacement leaves the original active. Reversal-only requires
  an explicit cancelled/coverage-gap outcome. Never rerun FEFO to determine reversal
  quantities/costs. A unique reversal link prevents reversing twice.
- Agreed initial restriction: until a reopening workflow exists, permit correction only in an editable,
  unclosed period with no later finalized dependent period. Conservatively block
  earlier-period corrections even when a later allocation happens to use a different
  layer: chronological FEFO and closing snapshots can still change.
- Backdated receipt, opening correction or adjustment before finalized coverage must
  also be blocked pending reviewed reopening; immutable receipts alone are not enough
  because a newly entered earlier receipt can change the earlier FEFO result.
- Same-period existing receipts need not be reversed for a consumption correction;
  replacement rechecks all eligible layers and coverage under lock. Changes affecting
  a submitted LPLPO require its authorized return/reopen path first.
- LPLPO rejection alone does not undo consumption; distribution fulfillment is an IF
  warehouse event, not facility consumption closure. Introduce explicit inventory
  period closure, distinct from LPLPO CLOSED, with no unresolved sources/shortages.

Alternative: reopen a chronological suffix, reverse dependent consumption postings
in reverse order, retain every old version, replay forward and produce replacement
LPLPO/report snapshots for review. This enables backdated corrections but is a
larger controlled workflow; never silently recalculate submitted history. Recommend
deferring it while retaining the dependency links needed to build it. Existing
feature-1 receipt correction UI remains deferred; this feature must either include
the chosen safe correction slice or keep real rollout gated on it.

## 7. LPLPO price column removal agreed; valuation details OPEN

Proposed source of truth: inventory journal/allocations plus versioned period
snapshots; LPLPO consumes these for enrolled periods. Detailed use remains the input
source, but posted revisions provide finalized quantity/cost. Draft previews must
be labelled provisional and must not look like inventory valuation.

Illustrative arithmetic, not production data: opening 10 units at Rp100 = Rp1,000;
receipt 10 at Rp200 = Rp2,000; FEFO use 12 = Rp1,400; closing 8 at Rp200 = Rp1,600.
No single harga_satuan values all four correctly. A Rp150 average gives Rp1,800
use and Rp1,200 closing, losing the layer result.

Recommended: one LPLPO quantity row per item remains useful; add a linked immutable
inventory period/item snapshot with exact opening/receipt/use/other-adjustment/
closing values and drill-down by original layer/price. Existing harga_satuan can
remain for legacy documents and any explicitly required reference-price field,
clearly identified; it must not drive enrolled-period nilai_* or asset totals.
Update all HTML/detail/print/XLSX/export and offline import paths together. Exact
amount field precision must be derived from quantity/price maxima and summed volume
using the shared high-precision Decimal helpers, not guessed as the price precision.

Agreed user direction: remove the LPLPO harga_satuan column for now, without an
average replacement. Inspecting facility holdings/prices in a separate inventory
submenu is also agreed. This is compatible
with layered valuation in principle. The price view would need to expose distinct
original-price layers (quantity, price, value, batch/expiry and known source), since
one item can have several prices. Removing the input alone would not replace the
existing nilai_* calculations or reports; those must use the agreed inventory
snapshot contract before the field stops driving enrolled-period valuation. Keep
historical stored prices and document output intact. The submenu is agreed;
column removal is a design decision, with no UI implementation yet authorized.

Alternatives: split LPLPO into original-price/layer subrows (more faithful within
the document, larger schema/UI/offline-form change); retain the official single-price
form plus a separate authoritative valuation annex (smaller form change but must
explain that the form's price multiplication is not inventory valuation). Confirm
whether an externally mandated form requires that single price. This investigation
has not established a legal/reporting format requirement.

January integration, only after explicit facility/year enrollment:

- Initial January stock_awal quantity/value comes from verified opening before
  January 1 movements. January receipts and use are separate period movements.
- Later monthly opening equals prior covered inventory closing including signed
  supported adjustments, not an editable legacy LPLPO balance. January in later
  years carries prior closing and explicit annual differences; never re-add the
  complete verified snapshot.
- Agreed for existing DRAFT/REJECTED_PUSKESMAS: show a difference preview and require an
  explicit operator adoption/reconciliation; retain old values/reason/source
  versions. Once enrolled, prohibit manual/offline override of inventory-derived
  fields while preserving demand/physical-count/reviewer fields as applicable.
- Agreed: submitted/processed periods stay unchanged. Block conversion until authorized
  return/reopening, or retain the year as legacy and cut over at a later supported
  January. Do not change displayed historical monetary results on deployment.
- Cover items present in inventory/consumption even if omitted or inactive in
  today's catalog/form; no silent dropping of balances. LPLPO creation-year and
  continuity rules remain unless a separate approved change is necessary.

`stock_gudang_puskesmas` is described as a warehouse physical count. It cannot be
treated as a whole-facility physical verification without a scope change. Preserve
that distinction on self-check and reconciliation screens.

## 8. Shared report contract and boundaries

Propose one read service for enrolled, covered intervals consumed by HTML, print
and Excel. Query parameters and export routes apply the same facility access.
The snapshot/source mode, opening boundary, closing cutoff, recorded-through
version, included/excluded facilities and completeness reasons travel with rows.

For covered interval [start, end], quantities and values both satisfy:

`closing = opening + receipts - consumption + signed other movements`

Opening is the balance immediately before start-date activity. For initial January,
include the verified opening once as the start boundary; it is not January receipt
income. Activity is start..end inclusive. Monthly reporting uses calendar months.
Quarter/semester rincian retains an end-of-period stock cutoff; proposed rekap uses
the selected interval's opening and flows through that end. If year-to-date rekap
is desired instead, explicitly choose January as start and label it accordingly.
Do not use 'latest available LPLPO within range' as proof of closing at the end.

Use sum(quantity_delta * immutable original price); per-layer closing value is
remaining quantity * that layer's price. Show purchases/donations/returns/losses/
adjustments separately if supported, so totals reconcile without disguising losses
as clinical use. Carry explicit signed corrections/reversals and their source links.
Category grouping must use a consistent classification version within a snapshot
so totals are not silently moved by later catalog edits.

Keep reporting bases explicit. Legacy periods keep existing calculations and labels;
new inventory reports use the inventory foundation alone. Do not add verified opening
to an LPLPO baseline or combine legacy and inventory valuations into an unexplained
aggregate. All-facility reliable totals include only facilities covered through the
requested cutoff; excluded facilities and reasons are visible, never zero-filled.
Expose per-facility shortages before aggregation, since one facility's surplus can
hide another's deficit. Never infer zero from an absent consumption document.

Money display may use two Indonesian decimals, with no intermediate rounding.
Excel must preserve exact Decimal evidence (text/exact-price detail where spreadsheet
numeric precision would lose digits) alongside usable formatted totals; verify this
across actual output. Rendering/exporting never posts stock. Riwayat Pemakaian's
current finalized-LPLPO-only source and the LPLPO-only self-check need explicit source
labels/transition decisions, not an unnoticed switch to all draft input.

## 9. Other movements and readiness: explanation for discussion

These are possible real events, **not confirmed facility practices**:

| Event | Example and inventory effect | Present facility-ledger support / required action |
| --- | --- | --- |
| IF delivery | 100 units physically received from an issued distribution: +100 at issued original layer prices. | Implemented linked confirmed receipts after verified opening; audit completeness and dates. |
| Local purchase or donation | Facility buys or receives donated stock outside IF distribution: positive quantity and verified acquisition value. | No facility-layer posting source found. Do not enter it as an invented IF receipt or assume donation cost zero. Add a reviewed source workflow if it occurs. |
| Patient/subunit return | Unused goods return from patient to facility (+ only if they previously left the facility boundary); room-to-warehouse return is internal and neutral. | External usable returns need provenance, original layer/cost and condition; no facility service found. |
| Return to IF / transfer to another facility | 10 leave this facility: -10 at their layer costs; destination acknowledgement is a separate linked event. | No facility-layer return/transfer source found. A warehouse Recall is not evidence this already posts facility stock. |
| Loss, damage, expiry/disposal | 5 destroyed/lost: -5 with reason, authority and original costs, separate from actual medical use. | Warehouse expired/recall paths target Stock. Facility unusable classification and disposal postings need coverage if applicable. |
| Physical-count adjustment | Count discovers +3 or -3 after investigation: explicit reviewed difference, never overwrite ledger. | No general facility adjustment posting found. Positive differences need verified original value/expiry or remain held; do not manufacture unknown-price stock. |
| Internal warehouse/Poli/Pustu transfer | 20 move between parts of the same facility: whole-facility net zero. | No whole-facility deduction. Subunit location tracking, if needed, is a separate future scope. |

Example: opening 100, IF receipts 50, medical use 80 gives 70 only if no other
movements occurred. A separate purchase of 20 and disposal of 5 makes actual closing
85. A perfect FEFO algorithm still reports the wrong balance if these events are
missing. Ask staff which events happen; unsupported events cannot be assumed absent.

Proposed readiness is dated coverage, not a permanent boolean:

- UNINITIALIZED: no verified opening/account.
- FOUNDATION_INCOMPLETE: opening/receipts exist but required movement or period
  coverage is missing; preserve current warning.
- RECONCILIATION_REQUIRED: unresolved shortage, unsupported source, discrepancy,
  stale/reopened period, or evidence hold; no reliable closing for the affected cutoff.
- VERIFIED_THROUGH(date): opening plus all applicable inflows/outflows, explicit
  zero-use months, reconciled layer projection/journal, source completeness and
  approved closing through that date. Report only through covered dates.

Monthly use means a reliable finalized month-end accounting balance at best.
It does not establish today's live available stock during the following month.
Even dated entry supports 'current' only when all required events are timely and
complete through the displayed date. Staff assertions about unused movement types
need an explicit applicability/coverage record; if such an event later occurs,
invalidate affected readiness until recorded/reconciled. Preserve known unknown
historical provenance without claiming exact delivery lineage.

Annual January posting remains a later focused increment: this feature can build
period coverage and closing primitives, but does not by itself authorize annual
reconciliation. Prerequisites: complete prior-year movement coverage/closing,
retained layer identities, independently verified target counts/prices/expiry,
all omitted/zero layers explicitly addressed, original-price signed differences,
January 1 event order, and a reviewed correction path. Existing one-initial-account
guard stays until that increment is authorized.

## 10. Permissions, cutover and operations

Preserve role gates and facility isolation, distinguishing Django permissions from
module scope. Consumption correction is agreed for authorized own-facility
Puskesmas operators and Super Admin, with audit trail and logs. An extra independent
reviewer for ordinary consumption correction is not part of that decision. LPLPO
return/reopening authority remains distinct. Do not extend opening-only GUDANG cross-facility
authority, Kepala read-only oversight, Acting Kepala, or report staff selection to
consumption mutation. Account/source/entry/layer IDs and exports must be scoped on
the server and rechecked under locks. Retain legacy ADMIN receipt authority separately.

Cutover is explicit per facility and supported period, preferably January with a
verified opening and no submitted conflicting periods. First perform a read-only
inventory of existing consumption, LPLPO statuses, receipt sources/dates and gaps,
with measured counts. No audit counts are known here. Keep pre-cutover consumption
unallocated and legacy valuations intact. Do not turn historic LPLPO totals or the
current monthly average into original-price layers. Controlled catch-up is allowed
only from real sources with complete evidence, operator review, deterministic
chronological posting and a reconciliation preview; unsupported history remains
uncovered. Development data reset is a separate authorized operation.

Operational feedback should show draft/provisional, ready to post, held with
item-specific reasons, posted revision/cost breakdown, and last covered cutoff.
Explain the next corrective action without exposing other facilities' stock.
Retain actor, source/digest, effective/recorded dates, reason, prior/replacement
links, closure/reopen and explicit-zero attestations. Application logs/auditlog
supplement the journal; neither substitutes for costed movement records. Keep
CSRF POST, rate limits, stale-revision checks and named trailing-slash routes.

Performance: batch-load candidates and sources per facility/period; no query per
matrix cell. Bound input/candidate work and measure lock time, query count,
allocation/journal persistence, report aggregation and rendering separately.
The opening-import performance note shows batched parsing improved locally but
preview persistence remained costly; it does not establish consumption throughput.
Do not bypass immutable guards via bulk writes for speed. Any service-only bulk
path needs explicit validation and audit evidence because bulk operations bypass
ordinary saves/signals. Benchmark actual workload before choosing a background job
or setting latency promises; no staging/production throughput is established.

## 11. Framework evidence

Requirements pin Django 6.0.8; no installed/runtime version was measured here.
Context7 `/django/django` was queried for locking and validation; it returned
main-branch material. Version-sensitive decisions were checked against official
Django 6.0 documentation:

- [Transactions](https://docs.djangoproject.com/en/6.0/topics/db/transactions/):
  atomic contains required database effects; on_commit is after successful commit.
- [select_for_update](https://docs.djangoproject.com/en/6.0/ref/models/querysets/#select-for-update):
  evaluate locks within atomic, avoid nullable joined lock targets, specify lock
  targets deliberately. Use PostgreSQL TransactionTestCase/separate connections
  for real lock tests; SQLite cannot validate this contract.
- [Model validation](https://docs.djangoproject.com/en/6.0/ref/models/instances/#validating-objects):
  save does not automatically call full_clean; services explicitly validate input.
- [Constraints](https://docs.djangoproject.com/en/6.0/ref/models/constraints/):
  database uniqueness/checks complement validation; cross-row accounting still
  requires service invariants and reconciliation.

No framework upgrade, new runtime configuration, raw SQL requirement, or deployed
PostgreSQL version is proposed or inferred.

## 12. Phased implementation and validation plan (after agreement/authorization)

1. Resolve semantics/date/expiry/shortage/valuation/readiness and minimum correction
   scope. Record each user decision here; approve UI/source transitions explicitly.
2. Read-only data/capability audit with counts; confirm environment/runtime versions
   and actual source records. Choose enrollment cohorts and cutover. New constraints
   follow audit -> separate data fix if needed -> constraint migration.
3. Add revision/allocation/posting extensions and narrow mutable projection service;
   align locks across all affected receipt/consumption/LPLPO checkpoints. Keep
   reporting/readiness incomplete. No synthetic backfill or applied-migration edits.
4. Implement draft/finalize/hold, exact reversal/replacement within agreed dependency
   restrictions, and explicit zero/completion coverage. Preserve source immutability.
5. Add period snapshots and opt-in January/later LPLPO integration, then shared
   HTML/print/Excel reports with explicit legacy mode and coverage. Roll out only
   supported movements and keep readiness limited where coverage is incomplete.
6. Pilot with independently reconciled evidence and role checks; enable dated
   verified balances only through agreed coverage. Defer annual differences and
   suffix reopening unless separately agreed. Rollback disables new enrollment/
   posting surfaces while retaining all journal/history and labelled legacy reports;
   never drop populated tables or delete allocations to roll back.

Focused validation requirements (future tests; no test doubles requested):

- FEFO distinct price/origin layers, deterministic ties/subunit attribution, future
  receipts, opening cutoff, nullable permitted expiry, expiry-day/month-boundary
  cases, inactive catalog history, verified zero price, exact Decimal totals.
- Shortage all-or-nothing rollback, preserved draft, explicit zero-use versus missing
  period, repeated finalize/different digest, one movement per layer with multiple
  subunit allocations, source protection and draft-delete behavior.
- Exact reversal at original cost, replacement failure rollback, repeat reversal,
  dependent-period/backdated source blocks, LPLPO return/reject does not double-post.
- Rebuild each layer balance from signed movements; allocation quantity/cost sums
  equal posting and period snapshots; opening + receipts - use + others = closing
  for quantity and value. Use real ORM records/services, not fabricated history.
- PostgreSQL concurrency: consumption vs receipt/catch-up, duplicate finalize,
  edit/delete vs finalize, receipt backdate vs close, finalize vs LPLPO submit,
  reversal vs later period, access revocation, and independent facilities. Use
  separate connections and inspect journal, projections, coverage and LPLPO together.
- Own-facility operations; forged foreign facility/source/layer/subunit IDs denied;
  report selector/aggregate capability boundaries; GUDANG opening authority and
  Kepala oversight do not widen consumption; legacy ADMIN receipt regression.
- January verified opening counted once, later carry, unchanged submitted legacy
  snapshots, explicit adoption of drafts, offline import override rejection,
  missing/inactive item inclusion, changing prices, missing periods, range boundary
  coverage, all-facility exclusions and negative-per-facility visibility.
- Compare the same service results in HTML, print and Excel: quantities, exact layer
  costs, formatted totals, source version/cutoffs, coverage and excluded reasons.
  Verify both legacy and enrolled modes and that GET/export has no inventory effects.
- Manual multi-role checks using developer-guide profiles: operator monthly input,
  hold/reconcile/finalize, stale duplicate tabs, authorized correction, forbidden
  dependency/backdate, LPLPO submit/return, print/XLSX and read-only staff oversight.
- Measure small/large candidate/query/lock/render workloads and journal replay.
  No consumption performance threshold is claimed before measurement.

Existing regression commands, to run only during implementation as appropriate:

```powershell
.\scripts\run-django-test.ps1 -Target apps.puskesmas.test_inventory -KeepDb
.\scripts\run-django-test.ps1 -Target apps.puskesmas.tests.PuskesmasConsumptionFormTests -KeepDb
.\scripts\run-django-test.ps1 -Target apps.puskesmas.tests.PuskesmasConsumptionViewTests -KeepDb
.\scripts\run-django-test.ps1 -Target apps.puskesmas.tests.PuskesmasReportViewTests -KeepDb
.\scripts\run-django-test.ps1 -Target apps.lplpo.tests.LPLPOWorkflowTests -KeepDb
.\scripts\run-django-test.ps1 -Target apps.core.tests.test_url_consistency -KeepDb
```

New focused test labels must be documented when they exist. Apply migrations before
serving; check migration drift and URLs for implementation changes. Update actual
SYSTEM_MODEL/app guides/application reference with implemented contracts, and
developer/seed guidance only if operations/imports change. No CSS build is needed
for this design-only document.

## 13. Minimum next decisions

1. Month-end accounting and explicit consumption finalization on or after the
   month's last day are accepted; late finalization retains the month-end effective
   date. Clarify same-day activity and the expiry evidence path; daily use dates
   are not required by the agreed direction.
2. Draft saving, shortage holds on consumption finalization, and requiring finalized
   monthly consumption for LPLPO submission are agreed. Draft LPLPO preparation is
   allowed; no incomplete/unvalued submission bypass is selected.
3. Finalized consumption must remain correctable and synchronize LPLPO, with audit
   trail/logs. Authorized return/reopening before updating submitted/processed
   LPLPO is agreed. Blocking earlier consumption corrections when a later month
   for the same facility is finalized is also agreed; multi-period reopening is
   deferred. Corrections are limited to authorized own-facility Puskesmas operators
   and Super Admin, with audit trail/logs. Finalize LPLPO return/reopening authority
   and exact reversal/replacement mechanics.
4. Removing the LPLPO harga_satuan column without an average replacement is agreed.
   Finalize exact layered-value report/snapshot presentation and legacy compatibility;
   do not remove historical stored prices or silently rewrite historical documents.
5. Current inflows are agreed as IF-only; direct purchases/donations are deferred.
   Physical returns/transfers are deferred to #326. Loss/damage investigation and
   supported adjustments belong to Feature 3. Finalize coverage/readiness limits
   for these deferred movements. Operational finalization and inventory-backed
   LPLPO submission must wait for verified expiry-module integration, as agreed. Monthly
   verified-through balances are recommended until complete dated recording can
   support current availability.

Validation record for this phase: code/document inspection and Context7/official
Django reference checks only. No Django tests, migrations, database audits, live
browser checks, deployment, performance measurements or feature implementation
were performed. Documentation checks: all 13 fully qualified backend file paths
in this document exist; no trailing-whitespace lines found. Git no-index whitespace
check emitted no whitespace errors (it reported the repository LF-to-CRLF warning;
exit 1 indicates the new-file difference). External Django references were opened;
GitHub PR metadata was fetched. These checks do not validate runtime behavior.

## 14. Instalasi Farmasi stock-opname comparison (2026-11-17)

User requested inspection of IF stock opname as a possible model for Puskesmas
discrepancies. This is a design comparison, not approval to implement or change
stock-opname runtime behavior. Read stock_opname and stock app guidance, models,
views, routes, app registration and relevant test definitions. Targeted repository
search found no separate opname stock-posting service or signal handler.

Verified behavior:

- `backend/apps/stock_opname/views.py:253` (`opname_start`) starts a counting
  document, issues its number, and snapshots existing positive Stock rows within
  the selected categories. Scope is fixed at start; this does not mean stock
  movements are frozen throughout the counting session. Zero-stock/unrecorded
  layers are not automatically included by that selector.
- `models.py:103` (`StockOpnameItem`) retains starting system_quantity, nullable
  actual_quantity, completion_stock_quantity and notes per warehouse Stock row.
  Its stock FK preserves the existing location/batch/funding/source-price layer
  relationship; it is not a whole-facility Puskesmas model.
- `views.py:347` (`opname_input`) saves physical counts/notes, allowing incomplete
  input to remain in progress. `views.py:516` (`opname_complete`) refuses an empty
  or partially uncounted session, locks the document/items with related Stock,
  and compares physical counts against current Stock.quantity at completion.
- `_user_can_complete_opname` at `views.py:57` allows normal operational authority
  for matching counts; remaining differences require approval authority, including
  the documented delegated path. Completion freezes comparison quantities and
  records completed_by/completed_at and any AuthorityExercise. Detailed authority
  comes from the existing stock-opname scope/resolver, not a new Puskesmas grant.
- **Completion does not change Stock.quantity or create Transaction rows.** The
  completion function updates the count rows/header and authority audit only;
  no posting handler was found in targeted repository inspection. The guide's
  statement that completion appends adjustment entries was inconsistent with
  code and is corrected in this documentation-only change. This is static evidence;
  no runtime test was executed in this follow-up.
- `views.py:36` uses frozen completion quantities for completed detail/print, so
  later warehouse movement does not change that historical comparison. Existing
  tests at `tests.py:961` and `:1012` assert this presentation contract; reading
  those tests is not a claim that they were rerun or prove adjustment posting.

Design implication: reuse the **count -> discrepancy -> authorized review -> frozen
evidence** workflow pattern. A Puskesmas adjustment checkpoint would be additional
functionality, writing explicit signed facility movements at verified original
layer costs, not a call to the current warehouse opname completion endpoint.
Keep independent facility scoping, permissions and the shared facility mutex.
Because Puskesmas use is monthly, count and accounting balances must share an
explicit cutoff; copying a comparison to today's warehouse balance would not
establish a prior month-end reconciliation. Record/resolve intervening movements.

Two related but different discrepancies:

| Situation | What counting/review can establish | What it cannot establish alone |
| --- | --- | --- |
| Posted movement balance is 70, physical month-end count is 65 | A verified residual difference of -5, potentially resolved by source correction or an authorized layer-specific -5 adjustment. | Whether the cause was unrecorded use, loss, wrong receipt or count error without investigation. |
| Eligible stock is 70 but reported use is 90, so FEFO cannot post | Evidence that use and supported stock disagree; counting remaining goods helps investigation. | The missing acquisition's date, original price, expiry or consumed batch. A physical closing count cannot create the missing costed 20 units. |

Deferred feature-3 proposal, still OPEN: offer a Puskesmas reconciliation document linked
to the monthly consumption/closing period. Save reported use and counts without
silently changing either; show ledger expected quantity, counted quantity, residual
difference and source-coverage/allocation holds. An authorized reviewer resolves
supported missing sources first, then may post evidenced residual adjustments
through a dedicated immutable posting service. Never double-count a source fix and
an adjustment for the same difference. Unknown positive-layer prices/required
expiry remain held; an aggregate count must not be spread across prices by guess.
If consumption is held, label closing as provisional rather than implying a posted
ledger closing exists. Only remove the hold once allocations, adjustments and the
period quantity/value identity reconcile atomically.

This provides an explicit route to investigate and resolve discrepancies instead
of only displaying a blocking error. It does not yet decide
who reviews Puskesmas adjustments, or whether this
workflow is monthly mandatory or exception-only. Annual January reconciliation
may share these primitives but remains a separately gated checkpoint. No feature-2
implementation or warehouse runtime changes were made in this follow-up.

## 15. Deferred feature 3: Puskesmas Stock Opname and Reconciliation

Status: recorded follow-up, to design after feature 2; implementation not authorized.
This section supersedes any reading of section 14 that would add physical counting
or a full discrepancy-resolution workflow to feature 2. Use a separate design and
implementation branch when feature 3 starts; do not maintain a separate Puskesmas
product fork or change application architecture merely because this work is separate.

Business context to confirm: the user recalls that operators normally perform
stock opname before filling the LPLPO Excel form. This is a working assumption,
not a verified operational procedure or a settled monthly counting requirement.

Proposed feature-3 responsibilities:

Agreed scope addition (2026-11-18): investigate losses and damaged stock and post
supported, evidenced adjustments through this reconciliation workflow. Do not
implement these adjustments in Feature 2 or classify them as medical use/expiry
merely to make balances reconcile. Detailed review authority and accounting
checkpoints remain part of Feature 3 design.

- Whole-facility physical counting across warehouse, Poli and Pustu, with a clear
  common cutoff and handling of movements during the counting session.
- Comparison with feature-2 accounting balances, retaining reported use, counted
  quantity, expected balance and unexplained differences as distinct evidence.
- Discrepancy investigation and authorized, evidenced layer-specific adjustments;
  no guessed prices, synthetic receipts or automatic conversion of loss into use.
- Frozen count/review history, permissions/facility isolation and correction rules.
- A decision on requiring completed/reconciled opname before LPLPO submission,
  while potentially allowing draft preparation during reconciliation.
- Coordination with future annual January differences without re-adding opening
  stock or implementing annual posting merely because monthly counting exists.

Feature 2 should provide the foundation this work consumes: costed allocations,
immutable posting/source/reversal links, accounting balances for explicit cutoffs,
and clear shortage/coverage explanations. It does not implement physical-count
forms, count-review queues, general physical-difference adjustment posting, or an
opname-based LPLPO submission gate. Consumption reversal/replacement remains a
feature-2 design concern because posted consumption needs its own correction rules.

Feature 2 holds consumption finalization on shortages while allowing draft saving;
LPLPO submission requires finalized consumption, while its drafts remain allowed. Deferring
feature 3 does not establish reliable-balance readiness. Unsupported movements or unresolved gaps
keep the affected balance incomplete. Do not add a manual quantity override as a
temporary substitute for feature 3. A period's costed accounting result and its
physical verification are different claims and must be labelled accordingly.

Agreed responsibility split: feature 2 detects allocation shortages and explains
the hold; feature 3 is the planned home for guided investigation, evidence, review
and resolution. Seek a supported explanation for each discrepancy, but do not
assume one is already known or force a balancing adjustment merely to close a case.
An unresolved case remains visibly open. Correct a proven receipt/consumption error
through its owning workflow with audit history; use a distinct reviewed adjustment
only where supported and authorized. In particular, receipt short-delivery may
mean the recorded inflow is overstated; it is not a reason to add stock to clear
a consumption shortage. Feature 3 must respect feature-1 posted-receipt immutability
and feature-2 correction/reopening rules. Feature 2 does not silently supply the
deferred general correction/adjustment interfaces.

Handoff checklist after feature 2:

1. Review the final implemented feature-2 posting, coverage, LPLPO and correction
   contracts; carry forward remaining limitations rather than assuming this draft
   was implemented in full.
2. Confirm actual counting practices with an operator: timing, whole-facility scope,
   granularity by batch/price layer, evidence, and whether counting is monthly or
   only required for exceptions.
3. Reuse the IF workflow pattern identified in section 14, remembering its current
   completion does not post stock adjustments; do not reuse warehouse ownership
   or permission assumptions for facility stock.
4. Agree reviewer authority, discrepancy resolution, count cutoff, closure/reopening,
   unknown-cost handling and LPLPO gate behavior before implementation.
5. Create the dedicated feature-3 design/branch and define focused reconciliation,
   valuation, facility-isolation and concurrency validation. No date is committed.

## 16. IF expiry workflow comparison and Puskesmas preparation

Local inspection requested by the user after issue #325 was created. Earlier
detailed GitHub updates were rejected by automatic approval review. After the user
clarified operator-triggered expiry outflows and explicitly requested the issue
update, #325 was successfully updated with that direction, no separate approval,
no automatic threshold deduction, audit/reporting needs and remaining questions.
This section retains the deeper local investigation evidence; no module
implementation is authorized.

Verified current IF behavior at the investigation baseline:

| Step | Code evidence and stock effect |
| --- | --- |
| Monitoring | `backend/apps/expired/views.py:181` (`expired_alerts`) selects dated warehouse stock with available quantity and expiry within 90 days, including past dates. Rows distinguish past-date expired, 0..30-day near-critical and later near-expiry. Search/location/level filters and pending/actionable quantities support operator review. The monitoring page itself does not deduct stock. |
| Preparation | `backend/apps/expired/models.py:7`, `:59` define DRAFT/SUBMITTED/VERIFIED/DISPOSED documents with specific warehouse Stock rows and quantities. `forms.py:46` offers positive available dated batches ordered by expiry; it does not restrict selection to already-expired stock. The 90/30-day alert bands are not a mandatory withdrawal rule. |
| Pending document | `views.py:475` (`expired_submit`) issues the document number and changes status. `forms.py:101` subtracts quantities in other SUBMITTED expiry documents when validating quantities; alerts also show pending amounts. Submission does not itself deduct quantity or create a separate held-stock balance. Do not assume this pending calculation reserves stock against every other workflow. |
| Verification | `backend/apps/expired/services.py:23` (`execute_expired_verification`) locks/rechecks document and stock, checks availability, deducts Stock.quantity and appends OUT/EXPIRED Transaction rows with original price, funding, batch, location and source-document number. It then records verifier/time and VERIFIED. This is the stock-changing checkpoint. |
| Authority | `views.py:511` (`expired_verify`) requires the expired approval scope plus the ADMIN/KEPALA/superuser role gate or applicable delegated authority, re-resolved under transaction. This is IF authority, not a proposed automatic Puskesmas grant. |
| Disposal completion | `views.py:560` (`expired_dispose`) records DISPOSED, actor and timestamp after VERIFIED; it does not deduct stock a second time. Do not describe this action as the first stock removal. |
| History/output | Detail/print shows document rows and verifier/disposal identity. `services.py:141` (`_build_destroy_rows`) builds disposal audit rows from DISPOSED documents and values them using linked Stock.unit_price. It does not use the posted OUT price snapshot for that calculation; a Puskesmas adaptation should preserve original movement costs explicitly. This is not a facility withdrawal history. |

Puskesmas adaptation proposed for discussion:

Historical proposal below: the user's later clarification recorded under Scope
at a glance supersedes steps 2–3's neutral-held-stock recommendation. The selected
direction is explicit operator-posted expiry outflow with no separate approval,
not an automatic threshold action. Retain this comparison as investigation history.

1. Reuse the idea of a near-expiry/expired list, but query the facility's inventory
   layers with its permissions and coverage. Do not reuse warehouse Stock ownership.
   Confirm the alert and withdrawal thresholds; the IF 90/30-day bands do not prove
   what 'less than a month' means for Puskesmas.
2. Add an explicit withdrawal-from-use record for actual set-aside quantities:
   layer/batch, quantity, effective withdrawal date, actor and reason. This state
   is not implemented by IF's monitoring list or its submitted document alone.
3. Keep withdrawal neutral to owned quantity/value while making the affected
   remaining quantity unavailable to FEFO. Later approved removal/return/disposal
   needs an explicit accounting checkpoint, once only, with original costs. Agree
   that checkpoint rather than copying IF verification's immediate quantity
   deduction into a simple Puskesmas set-aside action.
4. Record release/correction and approved disposition separately, with evidence,
   permissions and audit history. Coordinate with physical counting so set-aside
   stock is included as held stock and is not removed again as a count difference.
5. Define monthly FEFO interaction before rollout: a withdrawal date and quantity
   can identify stock unavailable afterward, but do not prove the batch used by
   earlier undated monthly consumption. Keep that eligibility question open.

Illustration, not operational data: starting 100, actual use 60, set aside 40 gives
60 consumption, 40 still held, zero further usable quantity in that batch. A later
approved removal posts -40 at the retained original price. Merely displaying an
alert, setting aside, and recording disposal completion must not each post -40.

No separate withdrawal schema, threshold, Puskesmas reviewer role, or disposition
checkpoint was agreed during the comparison above. Subsequently, the user chose
operator-posted expiry exclusion with no approval route, as recorded at the top
of this document; schema, dates, correction and report/count boundaries remain
open. Full expiry workflow stays in #325; any minimum
Feature 2 dependency requires explicit scope agreement. This comparison used code
and existing test-definition inspection only; no tests, database actions, browser
checks or runtime changes were performed.

## 17. Consolidated planning summary (2026-11-18)

This section and the agreed decisions in section 1 take precedence over older
discussion proposals marked OPEN elsewhere. Historical proposals are retained as
discussion evidence; they must not be mistaken for additional approved scope.
The user subsequently authorized implementation. See section 18 for the staged
runtime contract; the expiry activation dependency remains mandatory.

### Agreed Feature 2 behavior

- Use the verified January opening and supported IF receipt layers as the stock
  foundation. No current direct purchase/donation workflow.
- Monthly Poli/Pustu quantities mean actual use, not internal transfers. Retain
  monthly entry and month-end accounting rather than require daily input.
- Save editable drafts; explicitly finalize on or after the month's final day.
  Accounting effective date is month end, actual posting time remains auditable.
- Deduct consumption using deterministic FEFO allocations while retaining original
  layer quantities, prices, cost and source lineage; no averaged inventory prices.
- Preserve drafts on shortage; block the whole consumption finalization until all
  use is supported. Never invent stock/cost or silently reduce reported use.
- Prepare/save LPLPO drafts, but submit only with finalized same-month consumption.
  Subsequent accepted corrections synchronize editable LPLPO atomically, with audit
  history/logs and no repeated stock deduction.
- Allow corrections by authorized own-facility Puskesmas operators and Super Admin
  (ADMIN, distinct from ADMIN_UMUM), preserving existing helper compatibility.
  Submitted LPLPO first requires authorized return/reopening under existing stage
  restrictions. Block earlier consumption correction once a later month is finalized;
  a multi-period reopening workflow is deferred. Preserve all old posted evidence.
- Adopt verified January opening into existing editable LPLPO through a difference
  preview and explicit confirmation. Preserve prior values/audit and unrelated
  operator inputs. Lock adopted opening against manual/offline override. Submitted
  documents are not silently changed. Carry inventory closing into later months.
- Remove the LPLPO harga_satuan column without an average replacement; retain
  historical prices and exact original-layer accounting/report values.
- Add Persediaan Puskesmas: item quantity/value summaries, layer detail, cutoff and
  completeness labels; consistent HTML/print/Excel; existing facility/report access.
- Record known expiry outflows before monthly consumption finalization. Keep expiry
  outflows separate from medical use. The expiry module is separate #325 work;
  operator marks batch/quantity expired without separate approval or automatic
  threshold deduction. Its corrections must recheck affected consumption/LPLPO.
- Build/test Feature 2 before expiry, but activate operational finalization and
  inventory-backed LPLPO submission only after expiry integration is verified.

### Deferred work

- Feature 3: physical stock opname, discrepancy investigation and supported
  loss/damage/count adjustments; proposed mandatory opname-before-LPLPO gate.
- #325: full Puskesmas expiry module, threshold/monitoring and expiry posting.
- #326: physical returns to IF and transfers between facilities.
- Direct purchases/donations, annual January difference posting, and multi-period
  reopening remain outside this implementation scope. Never imply these movements
  are covered merely because their supporting feature is deferred.

### Remaining gaps, not a claim that every design detail is settled

1. **Unrecorded expiry:** the owner agreed explicit expiry outflows precede use,
   but has not selected how FEFO treats a layer past its expiry date when no expiry
   outflow has been recorded. Do not infer an automatic write-off, allow expired
   allocation by default, or treat the earlier blanket month-end exclusion proposal
   as approved. Settle this with the expiry integration before operational activation.
   Monthly allocation remains an accounting assignment, not proof of physical batch
   use or use-date eligibility.
2. **Technical design consolidation:** specify revision/reversal and locking services,
   same-day receipts/late backdated receipt restrictions, explicit zero-use coverage,
   source-of-truth versions, submission freshness and projection reconciliation.
   Proposed exact reversal/replacement preserves original costs; it does not grant
   a new reviewer role. Keep existing LPLPO authority/stage restrictions; any missing
   reopening path is a limitation to expose, not permission to add an implicit bypass.
3. **Readiness and historical validation:** audit actual supplied data before
   enrollment; retain legacy documents and reports. Implement consistent interval
   boundaries and precision; no claim of reliable current availability or physical
   verification from monthly accounting alone. Unsupported losses/returns/etc.
   leave affected coverage incomplete until evidenced resolution exists.

### Authorized implementation sequence

1. Consolidate this design against code and finalize the remaining technical
   contracts, preserving the explicit expiry activation dependency.
2. Add allocation/revision/posting and narrow balance-update services, constraints
   and shared locks; verify idempotency, exact original costs and transactional safety.
3. Add draft/finalize/hold/correction with retained history/logs, zero-use completion
   and agreed period/permission restrictions.
4. Integrate January adoption, later carry, LPLPO synchronization/submission gate,
   price-column removal and legacy/offline compatibility.
5. Add the inventory submenu and shared quantity/value reports, with cutoff/coverage.
6. Validate focused PostgreSQL concurrency, permissions, accounting identities,
   regression targets and multi-role HTML/print/Excel checks. Keep operational
   activation gated until #325 and its integration are verified separately.

## 18. Staged implementation record (2026-11-18)

Implemented migration 0016 with immutable consumption revisions, protected
original-price allocations, exact reversal/replacement postings, durable draft/
correction audit and immutable LPLPO adoption snapshots. The service serializes
actor/module, facility, document and balances, checks digest/source freshness,
requires consecutive finalized months (including explicit zero use), reconciles
journal/projection and rejects shortage atomically. Backdated receipts cannot
change a finalized allocation period; earlier correction is blocked by later
finalized use or submitted LPLPO.

January adoption now provides a difference preview for existing editable LPLPO;
new January documents use posted opening automatically. Later months inherit the
binding. Bound quantity/value calculations use the same exact journal reader as
the new Persediaan Puskesmas submenu. Forms and offline imports protect source
quantities, unrelated operator inputs survive, and the single price column is
hidden while historical fields/schema remain compatible. Legacy documents retain
their original behavior. The inventory report provides item summaries, expandable
layers, interval/coverage warnings, category totals, pagination, full print and
exact-value XLSX. The initial conditional redirects were replaced by the shared
reporting rework in section 19.

**Operational gate remains closed.** Public finalization and bound LPLPO submission
call the hard-closed expiry readiness service. There is no deployment setting to
bypass this dependency. The private posting engine is exercised with real ORM
fixtures and PostgreSQL transaction/concurrency tests; this does not activate it
for users. Candidate expired-by-cutoff layers hold the engine pending the final
expiry policy, rather than silently write off stock or allocate expired quantities.
Issue #325 must implement explicit operator expiry outflows, correction dependencies
and verified integration before activation. Stock opname/Feature 3 and other
unsupported movements remain deferred, so completeness warnings remain.

Validation entry points: `apps.puskesmas.test_consumption_inventory`, existing
inventory/consumption/report suites, LPLPO workflow/offline suites, URL consistency,
Django migration checks and browser verification. See the developer guide for
reproduction commands. No production enrollment, deployment or historical data
certification is implied by local validation.

Local validation on 2026-11-18 passed 22 new consumption-inventory tests, 41
existing inventory tests, 11 consumption-view tests, 52 report tests, 108 LPLPO
workflow tests, 16 offline-XLSX tests and 5 URL-consistency tests (255 distinct
tests). Django system checks, migration drift checks, CSS build/check and diff
whitespace checks passed. Migration 0016 was applied locally. Playwright on
127.0.0.1:8000 verified PUSKESMAS and ADMIN at 1440×960 and 390×844: filters,
layer expansion, pagination, XLSX download and full print output, without console
errors or document overflow. Browser UI did not mutate real adoption/stock data;
those mutations were exercised in the isolated ORM tests. Expiry activation,
production data completeness and other browser engines were not validated.

## 19. Shared inventory/reporting rework (approved 2026-11-23)

The user approved one accounting source with distinct page purposes: Persediaan
explores stock/layers, Rincian is the formal item-quantity report and Rekap is the
category/value report. Each URL retains its layout; adoption-based redirects are
removed. `stock_reports.stock_report_snapshot` selects one source per facility/
interval: verified opening journal when coverage reaches the interval start,
otherwise labelled historical LPLPO quantity and per-document price semantics.
No LPLPO or adoption is required for journal reports. Mixed scopes label sources,
never double-count a facility and exclude facilities missing both sources.
Historical values retain their reconciliation limitations; no original-price
layers are invented. Reports never adopt or mutate documents.

Preset/custom month filters share links preserving facility and interval. Opening
reference, source, cutoff and missing finalizations appear in HTML/print/Excel.
Zero posted consumption differs explicitly from finalized zero use. The mandatory
expiry activation gate, Feature 3 scope and historical LPLPO records are unchanged.

Rework validation passed locally: 52 existing report tests and 32 focused
consumption/inventory tests (including 10 reporting rework cases). Four affected
legacy quantity/valuation/export cases were repeated after final refinements.
Django system/migration-drift checks, CSS build/check and diff whitespace checks
passed. Playwright on 127.0.0.1:8001 verified PUSKESMAS and ADMIN across all three
routes at 1440×960 and 390×844: source/opening/coverage display, distinct page
identity, interval-preserving links/filter changes, Excel downloads and source
visibility under print media. No console errors or document overflow were seen;
mobile initial-load screenshots were also checked. No real stock/adoption writes
were performed. Browser plugin was unavailable; regular Playwright was used.
Other browser engines and physical-printer output remain unverified.


## 20. Puskesmas expiry implementation (2026-11-23)

The user authorized implementation of #325 and explicitly chose automatic atomic
same-month consumption reallocation after expiry corrections. This section
supersedes the earlier closed activation gate; historical stages above are retained
as decision evidence. Actual operator withdrawal is dated separately from month-end
use, never automatically triggered by ED or a warning threshold. The 30-day default
is an adjustable list filter, not an agreed mandatory disposal/withdrawal threshold.

The implementation retains immutable expiry documents, original-cost line/revision
snapshots, idempotent request keys, reasoned reversal/replacement/VOID and on-commit
logs. Stored withdrawal dates are fixed. Same-month replay restores consumption,
changes expiry and reallocates use in one transaction; affected submitted LPLPO,
later finalized periods, shortage or unresolved expired stock abort all changes.
Editable bound carries synchronize. No review route, warehouse mutation or physical
disposal/return claim exists. Read/write authority remains facility-isolated.

Unrecorded expired-by-cutoff quantities hold finalization (including zero use)
until explicit withdrawal in that period; later-dated expiry is insufficient.
This conservative policy never silently writes off or allocates expired stock.
Public consumption finalization/bound submission now use this integration without
an environment bypass. Reports and bound LPLPO distinguish expiry from medical
use at original costs; offline information cannot override the journal. Physical
stock completeness remains incomplete, and Feature 3/returns/annual reconciliation
stay deferred. Details and reproduction targets are in the owning app guides.

Local verification: 283 distinct tests passed (18 expiry, 32 consumption/inventory,
41 opening/receipt foundation, 11 consumption views, 52 reports, 108 LPLPO workflow,
16 offline-XLSX and 5 URL consistency). This includes same-month reversal/replay,
transactional rollback, explicit-zero versus unresolved expiry, future-dated expiry
coverage, cross-facility denials and expiry/consumption concurrency. Django system
and migration-drift checks, CSS build/check and whitespace checks passed. Migrations
were applied locally; LPLPO 0019 updates the closing-field formula help text.

Playwright verified PUSKESMAS/ADMIN list/create surfaces on 127.0.0.1:8001 at
1440×960 and 390×844: page identity, warning/page-size filters, facility selection,
dynamic layer rows, initially unchecked confirmation and no document overflow or
console errors. Screenshots were inspected. No real expiry/consumption posting
was performed for browser QA; those mutations used the isolated PostgreSQL tests.
The Browser plugin was unavailable. Other browser engines and physical printing
remain unverified; this validation does not certify historical stock data.

## 21. Shared IF expiry presentation (2026-11-23)

The user authorized reuse after comparing IF expiry monitoring and stock posting.
Shared code now owns dated-batch statuses/level filters, the status badge partial,
and the item-to-batch choice widget/JavaScript filter. IF retains its warehouse
query, 90-day horizon, reservation/submitted-document availability and approvals;
Puskesmas retains its 30-day adjustable horizon and facility journal writer.
The widget's former Recall import remains a compatibility alias.

Puskesmas monitoring supports scoped categories, search and allowlisted sorting.
Withdrawal rows choose a searchable item before its source batch/layer, including
dynamically added rows and initialized corrections. Server validation rejects
item/layer mismatch and unauthorized layers. Batch labels retain original price,
funding and source. Critical display/filter includes ED day through 30 days ahead;
this presentation does not change the monthly accounting hold or post stock.

Local verification for this reuse: 110 distinct tests passed (22 Puskesmas expiry,
1 shared display-boundary, 58 IF expiry and 29 Recall). System/migration-drift,
CSS build/check and diff whitespace checks passed. Playwright on 127.0.0.1:8001
verified PUSKESMAS and ADMIN at 1440×960 and 390×844: filter state, initial/dynamic
item-to-batch selection, unchecked confirmation and no document overflow/console
errors. ADMIN also exercised IF's critical filter. Screenshots were inspected.
Browser plugin was unavailable; regular Playwright was used. No real stock writes
were performed; posting/rollback tests used the isolated PostgreSQL test database.
Other browser engines and actual disposal/physical stock remain unverified.
