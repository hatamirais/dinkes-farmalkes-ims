# Feature 1: Puskesmas opening inventory and movement foundation

Status: first increment implemented after explicit user authorization; validation
record below. Annual reconciliation, corrections and feature 2 remain deferred.
Updated 2026-11-11.
Investigation baseline: `2280ea6ed916650487d88b850c3ac31db648c013`.
Branch: `design/puskesmas-opening-inventory`.

This document retains the investigation baseline and design discussion alongside
the agreed requirements. Section 12 records the implemented first increment;
future correction/annual/consumption contracts elsewhere remain deferred. No
production deployment or real-data onboarding is claimed.

## 1. Agreed requirements and scope

Kepala oversight uses the existing LPLPO VIEW threshold (including higher scopes)
for active KEPALA accounts. It exposes submitted, rejected and posted openings
across active Puskesmas, without private drafts/cancelled previews. The bell
includes informational submitted-opening notices linked to the read-only list;
these are status-based counts, without acknowledgement tracking. It grants no preparation/review/posting authority, report access
or other facility operations. Backend action checks enforce the read-only boundary;
no new ModuleAccess scope or approval stage is needed.

Confirmed by the user in this discussion:

- Prepare and verify opening stock every January at the start of the year.
- Carry remaining layers forward; annual verification posts explicit differences
  rather than adding the entire opening file to the carried balance.
- A facility operator prepares; a superuser or an Instalasi Farmasi operator with
  LPLPO module scope OPERATE or higher verifies and posts. Unverified opening
  records do not become Puskesmas inventory. The Instalasi Farmasi authority is
  specific to this opening-stock review/posting checkpoint across active facilities;
  it does not grant general cross-facility operational mutation access.
- Opening quantities cover all stock held by the facility, including warehouse,
  treatment rooms, and Pustu.
- Verified quantity and original price may be recorded despite missing historical
  batch, funding, or source-document provenance. Missing provenance stays explicit.
- Unknown original price or missing expiry for an expiry-required item holds the
  affected opening records pending evidence; they cannot enter posted inventory.
- Later annual reconciliation posting requires complete prior-year consumption
  and closing coverage. Feature 1 may stage verification while that gate is unmet.
- The user confirms the application is still in development with no real
  operational data. This is user-provided deployment context, not a database audit.
- Receipt drafts remain editable; confirmation posts immutable inventory effects.
  Corrections require superuser-reviewed reversal/replacement before dependent
  movements or period closure. Corrections after consumption remain blocked until
  feature 2 defines the policy. Ordinary receipt confirmation remains an operator
  action, distinct from authorized opening-stock verification and superuser-reviewed
  corrections.

The requested direction also requires distinct valuation layers, immutable receipt
prices, facility isolation, an append-only movement journal, and a feature-2 FEFO
handoff. Feature 1 does not implement consumption allocation, shortage blocking,
monthly consumption posting dates, or allocated-consumption reversal policy.
January LPLPO entry and current reports remain unchanged.

### Agreed first implementation scope

Use dedicated Puskesmas layers, balances and append-only movements; implement the
first January opening import/verification, immutable idempotent receipt posting,
and incomplete-balance safeguards together. Opening verifiers are superusers or
role GUDANG with LPLPO module scope OPERATE or higher; preparer and verifier differ.

Defer the reversal/replacement interface to a focused increment before real
operational use. Initially reject edits/deletion of posted economic records.
Defer annual reconciliation posting until feature 2 provides complete closing
coverage; retain its contract, without building a dormant posting workflow now.
Use separate initial-opening and future annual-reconciliation CSV templates;
the initial template has no internal layer IDs. The correction and annual entities
and algorithms below describe future contracts, not first-increment deliverables.

Remaining implementation details (field/class names, bounded staging and exact
validation mechanics) can be resolved within these agreed contracts. No further
business-design approval is needed for routine implementation choices.

## 2. Investigation baseline: verified before implementation

References use paths relative to the repository root and stable symbols; line
anchors identify the investigated revision. Existing test definitions were read
as examples of intended behavior; no Django tests or database audits were run.

| Finding | Primary code evidence |
| --- | --- |
| Warehouse stock is location-owned, with mandatory funding and no facility FK. Its unique tuple is item/location/batch/funding/source-document number; expiry and price are checked for conflicts by the importer rather than included in that tuple. | `backend/apps/stock/models.py:23` (`Stock`); `backend/apps/stock/admin.py:1569` |
| Locations have no facility relationship. Facilities are distribution destinations. Treating a facility as a warehouse location would require a new ownership contract. | `backend/apps/items/models.py:140`, `:175` |
| Warehouse movements have location, item, batch, source number, price, funding, actor and creation timestamp, but no facility or explicit business-effective date/expiry snapshot. Append-only is an application contract; the model itself has no general update/delete prohibition. | `backend/apps/stock/models.py:165` (`Transaction`); stock `AGENTS.md` |
| Opening import is a custom Stock Admin flow, restricted to superuser or role ADMIN; generic Stock import and direct add/change/delete are disabled. | `backend/apps/stock/admin.py:226`, `:254`, `:274` |
| Upload -> validation -> session-token preview -> confirmation; confirmation reparses/revalidates and atomically creates import detail, stock and INITIAL_IMPORT transactions. It locks existing headers and claims new document numbers through a unique registry. | `backend/apps/stock/admin.py:274`, `:369`, `:503`, `:518` |
| Warehouse reimport is cumulative-target semantics: skip equal totals, reject smaller totals, post only positive differences, allow new rows. Blank generated batches are unsuitable for reimport. This is not annual physical reconciliation. | `backend/apps/stock/admin.py:369`, `:1497`; `backend/apps/stock/tests.py:471`, `:558`, `:641` |
| Warehouse CSV headers are document_number,effective_date,sumber_dana_code,location_code,item_code,quantity,batch_lot,expiry_date,unit_price. Upload limit is 5 MiB; UTF-8 BOM, comma/semicolon delimiters and decimal-comma prices are supported. Expiry is conditional on catalog policy. | `backend/apps/stock/admin.py:39`, `:62`, `:540`, `:1137` |
| Shared CSV checks cover extension, MIME, filename/path, size and a bounded UTF-8 sample; the owning parser must validate the full content. The opening parser and source-price fields preserve up to 15 decimals with max_digits=28 and high-precision arithmetic. | `backend/apps/core/upload_validation.py:21`, `:63`; `backend/apps/core/decimal_validation.py:6` |
| Receipt headers have facility, received_date, DRAFT/CONFIRMED, nullable one-to-one distribution link. Detail retains separate quantity/price/batch/expiry and nullable distribution-row links; it has no funding/source-number snapshot. | `backend/apps/puskesmas/models.py:45`, `:203` |
| Final operational receipts require a complete distribution checklist. Saving checked rows copies issued distribution snapshots, but currently substitutes zero for missing issued price. Linked edits delete and recreate all detail rows. Legacy unlinked rows have a manual compatibility path. | `backend/apps/puskesmas/views.py:465`, `:487`, `:1211`, `:1356`; `backend/apps/puskesmas/forms.py` (`PuskesmasReceiptConfirmationChecklistFormSet`) |
| Warehouse final distribution snapshots batch/expiry/price/funding on DistributionItem, deducts warehouse stock, and writes warehouse OUT with source-document number. DistributionItem also retains a protected Stock link; it has no issued_source_document_number field. | `backend/apps/distribution/models.py:159`; `backend/apps/distribution/services.py:303` |
| Receipt create/edit/delete checks monthly LPLPO mutability and synchronizes editable LPLPO in atomic blocks. The receipt edit/delete paths shown do not lock/reload the receipt; the initial month-mutability query does not lock LPLPO. CONFIRMED receipts can still be edited, reverted to Draft or deleted while the period is editable. | `backend/apps/puskesmas/services.py:21`; `backend/apps/puskesmas/views.py:1211`, `:1356`, `:1566` |
| Monthly incoming quantity and price helpers read only same-facility/month CONFIRMED receipt rows. Price is sum(quantity*unit_price)/sum(quantity), quantized to 10 decimals; opening quantity/value is absent from the calculation. | `backend/apps/lplpo/models.py:384`, `:407`; existing weighted-price test at `backend/apps/lplpo/tests.py:497` |
| One harga_satuan on LPLPOItem values opening, receipts, consumption and closing quantities. This cannot express distinct layer costs. January opening remains manual; later carry-forward and price fallback are separate existing behavior. | `backend/apps/lplpo/models.py:226`, `:336`, `:359`, `:447`; `backend/apps/lplpo/AGENTS.md` |
| Detailed consumption is monthly facility/item/subunit whole-number quantity, with no layer allocations or costs. It synchronizes editable LPLPO quantities. | `backend/apps/puskesmas/models.py:405`, `:482`; `backend/apps/puskesmas/services.py:66`, `:80` |
| Rincian uses a latest usable same-year LPLPO baseline plus later confirmed receipts minus later consumption. Draft baselines are usable; missing baselines are excluded. Rekap values LPLPO quantities using harga_satuan. | `backend/apps/puskesmas/views.py:2284`, `:2597` |
| Operational receipt mutations have a PUSKESMAS/superuser role gate and same-facility checks in addition to Django permissions/module scope. Report staff-selection capabilities grant read access only. | `backend/apps/puskesmas/views.py:180`, `:188`; `backend/apps/core/decorators.py:30`; `backend/apps/users/access.py:505` |
| Central warehouse recap starts from all Transaction rows; inserting facility movements there could contaminate warehouse totals without broader changes. | `backend/apps/reports/views.py:466` |

Read root AGENTS, SYSTEM_MODEL, and app guides for stock, items, puskesmas,
lplpo, distribution, users, core and reports. Targeted inspection was sufficient;
Graphify was unnecessary. The reports app guide contains an older generic-report
authorization statement; current Puskesmas route code and users access helper use
the dedicated puskesmas_reports contract. This design follows code/root guidance.

No production row counts, PostgreSQL server version, historical completeness,
or actual opening-data quality were established. Requirements pin Django 6.0.8;
this is a file fact, not a claim about an installed or deployed runtime.

## 3. Recommended architecture and alternatives

Use dedicated inventory models/services owned by `puskesmas`, referencing existing
Facility, Item, FundingSource and receipt/distribution rows. Keep warehouse Stock
and Transaction unchanged. This avoids a facility-as-location fiction, prevents
warehouse report contamination, and supports unknown provenance without weakening
warehouse funding/source contracts.

Reuse shared upload/Decimal validation, catalog expiry rules, facility access
helpers, permission infrastructure, preview/explicit-confirm principles and ORM
transaction patterns. Do not invoke private StockAdmin posting methods or reuse
its source-number registry: that registry identifies warehouse receiving/opening
documents, whereas a Puskesmas layer needs its own origin and facility identity.
Extract a small pure helper only if needed and covered by existing importer checks;
do not refactor the warehouse importer as a prerequisite.

Alternatives:

- Extend Stock/Transaction with facility ownership: possible only with a broad
  audit of selectors, transfers, approval, warehouse reports and constraints. Too
  much blast radius for this feature; no safe mapping exists today.
- Add another monthly price or reuse LPLPO as the ledger: loses original costs,
  expiry/provenance and correction lineage. Reject.
- Independent yearly books: avoids continuous carry but weakens layer continuity.
  User selected continuous layers plus annual reconciliation instead.

### Proposed entities (names provisional)

| Entity | Purpose and invariants |
| --- | --- |
| PuskesmasInventoryAccount | One per facility; initial coverage date, operational/readiness state, closed-through date, version. Serializes posting and supports missing-row creation via a lock on existing Facility plus a unique facility key. |
| PuskesmasOpeningVerification | Facility/year, January 1 effective date, INITIAL or ANNUAL_RECONCILIATION, DRAFT/SUBMITTED/POSTED/REJECTED/REVERSED, preparer/verifier/poster timestamps, reason, revision, file digest and totals. Only one effective posted verification per facility/year; reversed versions retained. |
| PuskesmasOpeningVerificationLine | Stable external line_key, item, verified target quantity, price and provenance fields, evidence reference, verification result; optional protected existing layer link for annual reconciliation. Submitted versions frozen; changes require a new reviewed revision. |
| PuskesmasInventoryLayer | Immutable origin identity, facility/item, batch and its knowledge status, expiry and status, original unit_price, nullable funding and source provenance, protected opening/receipt origin, effective acquisition date. Each origin line creates a separate layer even if all visible attributes match another origin. |
| PuskesmasInventoryBalance | One-to-one layer projection of posted quantity. Changed only by posting services in the same transaction as movements; rebuildable from journal. In feature 1 this is an incomplete projection, not allocatable current stock. |
| PuskesmasInventoryPosting | Unique business-event/idempotency identity, facility, effective date, recorded-at, actor and immutable input digest; protected source document and optional reversal_of. Receipt posting/exclusion coverage must be queryable. |
| PuskesmasInventoryMovement | Append-only posting + layer + signed quantity_delta + immutable price snapshot; movement kind OPENING/RECEIPT/ANNUAL_ADJUSTMENT/REVERSAL, effective date and recorded timestamp. Protected sources and reversal lineage. Future consumption kind is reserved in the contract, not activated. |
| PuskesmasInventoryCorrection | Immutable reviewed correction source with protected original posting, reason, replacement row snapshots, preparer/reviewer and revision identity. Keeps original receipt facts intact and distinguishes replacement posting from a retry of the original event. |

Prefer layer ownership as the single source of facility/item identity; any redundant
posting/movement scope fields require service consistency validation. Use typed,
protected source FKs with checks for allowed combinations rather than unprotected
polymorphic IDs. No reservation/allocation model is needed for feature 1.

Database constraints: unique account/facility, stable source-event identity,
unique line_key within a submitted document revision, one balance per layer,
one original receipt posting per receipt, unique replacement posting per correction
revision, one reversal per posting, nonzero
movement delta, positive initial quantities, nonnegative price and projected layer
balance, and conditional uniqueness for an effective annual verification.
Implement cross-row consistency in the locked service, not by claiming a Django
CheckConstraint can compare related rows. Deny updates/deletes of posted journal,
layer attributes and source details in services, forms and Admin; guard model and
queryset mutation paths. These application controls do not make raw database SQL
immutable. If database-enforced append-only protection is required, explicitly
design a PostgreSQL trigger migration and its operational privileges.

## 4. Layer identity, value and incomplete history

Economic attributes are facility, item, batch, expiry, original price, funding,
warehouse source provenance where known, and Puskesmas acquisition origin.
Use a surrogate layer identity plus unique protected origin-line identity. Avoid
a nullable composite business key that accidentally merges unrelated unknowns.
Same batch at two prices or from two origins remains two layers. Do not merge
layers merely to simplify display; aggregate quantities/values at read time.

Keep these distinct: verification document ID, Puskesmas receipt number,
distribution/SBBK number, and original warehouse receiving/opening source number.
The first two identify facility events; they do not replace warehouse provenance.
Internal UUIDs/line keys are technical identifiers, never invented batch numbers.

Historical representation:

- Missing batch/source number/funding: null/blank plus explicit UNKNOWN status,
  evidence note and verification actor. No fictitious FundingSource or LEGACY
  business document is created. Keep unknown origins distinct.
- Price: a verified nonnegative original cost is required for valued posting;
  zero is permitted only when explicitly verified as zero. Unknown cost remains
  unposted staging, not a zero-cost inventory layer. Do not derive price from
  monthly LPLPO averages or current warehouse prices.
- Expiry: recommend null only for catalog-permitted non-expiring items, with an
  explicit NOT_APPLICABLE status. Unknown expiry for an expiry-required item is
  unresolved evidence and blocks posting/readiness for that opening document.
  Do not substitute 2099 or label unknown expiry as non-expiring. Holding these
  records pending evidence is agreed.
- Verification confirms the available facts; it does not reconstruct missing
  acquisition dates, past receipts or batches. Initial layers have an opening
  effective date and unknown original acquisition date if unsupported.

Recommend whole base-unit quantities for this foundation, consistent with current
receipt validation, LPLPO and consumption. Use compatible Decimal storage and
explicit whole-unit validation; fractional stock would require a separately
agreed change to downstream quantity contracts. Preserve 10 price decimals;
compute quantities times layer prices with project high-precision helpers. Round
presentation to two money decimals only; do not round layers to displayed money.

## 5. January semantics and double-count prevention

Initial coverage starts at January 1 of the selected year. Opening represents
stock physically held immediately before that day's movements, across all rooms
and Pustu. Goods in transit are excluded. January 1 receipts post after opening.
Posting now for a past January records today's recorded-at and the true January
effective date; it never fabricates a past verification/posting timestamp.

Pre-cutover receipt documents are historical evidence, not additional stock IN.
Post-cutover CONFIRMED receipts are eligible once, by received_date, regardless
of when entered. A distribution's warehouse OUT alone never posts facility IN.
A pre-cutover delivery confirmed late needs a verified actual received date;
placing it after cutover while including it in opening would count it twice.
Freeze/reconcile that classification at verification and record exclusions and
reasons. Source-line links and file digests assist duplicate detection but cannot
prove that manually entered opening stock does not already include a later receipt.
The preparer/verifier must attest to this boundary from evidence.

Annual January verification is a target snapshot, not a second INITIAL IN:

1. Establish complete prior-year closing movement coverage and a closed-through
   boundary. Carry layer quantities and prices without emitting another IN.
2. Match verification targets to stable carried layer IDs; verify additions
   separately. Never infer allocation between two prices from an item total.
3. Preview each layer's expected December closing, verified January target,
   quantity difference and value difference at its original cost.
4. Post only signed differences as ANNUAL_ADJUSTMENT effective January 1, before
   January receipts/consumption. Unchanged layers produce no stock movement.
5. Original prices stay immutable. A claimed price correction needs a documented
   reversal/replacement of the affected origin, not an edit to a carried layer.

Require a complete facility snapshot: omitted carried layers are validation
errors, not implicit zero. Explicit zero targets may retire carried balances.
For the first opening, empty/header-only/all-blank-quantity files and zero-stock
submissions are rejected. A complete opening can be staged
over multiple uploads, but posts once as a reviewed immutable revision.

**Feature boundary:** feature 1 cannot establish a reliable December closing when
consumption is unposted. It can stage the next annual verification, but must refuse
its posting until feature 2 supplies complete closing coverage/reconciliation.
Do not calculate annual differences from opening + receipts alone. If posting
annual reconciliations before feature 2 is required, a separate verified layered
closing/correction workflow must be agreed first; it is not implicitly included.

Initial historical catch-up also requires all eligible receipts since January to
be classified and posted once. Missing or unsupported linked snapshots remain
visible exceptions. Existing annual/monthly documents are never renumbered,
deleted or converted into synthetic inventory history.

## 6. Import, verification, permissions and posting

Proposed main-application workflow:
`DRAFT -> preview/validate -> SUBMITTED -> authorized verification + atomic POSTED`.
The verifier is a superuser or an Instalasi Farmasi operator with LPLPO module
scope OPERATE or higher.
Reject returns a reason and permits a new editable revision. No stock changes at
upload, preview or submission. The post action itself is the verification checkpoint
and records the immutable reviewed digest and verifier; avoid a verified-but-edited
intermediate payload. Preparation and verification must be separate actors.

Initial header form: one active facility, year, effective January 1, verification
reference and notes. Facility is server-bound for operators. Initial CSV columns:

```csv
line_key,item_code,item_name,unit,quantity,unit_price,batch_lot,expiry_date,sumber_dana_code,source_document_number,provenance_note
```

All headers are required for a stable template; optional values may be blank.
The separate future annual template must identify carried layers; it is deferred.
Unknown optional provenance requires a note and explicit preview flags.
No location_code: this is the agreed whole-facility boundary, not warehouse stock.
Opening verification references belong in the header, not source_document_number.
Future annual layer IDs must resolve against the facility and item server-side.

Recommend UTF-8 with optional BOM, comma/semicolon delimiters, ISO dates, decimal
dot or comma with correct CSV quoting and no ambiguous thousands separators.
Proposed limit: 5 MiB and 10,000 data rows per upload, benchmark before finalizing;
these are proposed bounds, not production settings. Reject unknown/duplicate
headers, uneven rows, header-only uploads, duplicate line keys, malformed full-file
UTF-8/null bytes, invalid dates/years, future openings, non-finite/overflow/negative
numbers, disallowed fractional quantities, and invalid/inactive catalog choices.
Reuse filename/MIME/size validation; do not trust MIME as proof of content.
NFC-normalize/strip/length-check strings. Escape CSV/Excel formula text on export.

Preview shows facility/year/boundary, row errors, missing-provenance flags,
per-layer quantities and exact prices/values, reconciliation deltas, candidate
receipt overlap/exclusions and facility totals. No partial posting of valid rows.
Use private actor-bound staging, expiry (recommend 24 hours for review drafts),
single-use confirmation tokens and immutable submitted revisions. The verifier
has an explicit authorized review path; do not transfer the preparer's session
token as approval. Recheck actor, scope, active facility/catalog, payload version
and live layer balances at posting. A changed payload/balance invalidates review.
Persist submitted evidence; transient preview expiry does not erase posted audit.

Permissions proposal:

- PUSKESMAS operator: existing operational role gate plus new add/change/view
  verification Django permissions or PUSKESMAS module-scope fallback; all bounded
  to the linked active facility. No cross-facility file IDs or POST parameters.
- Opening review/post: superusers or Instalasi Farmasi operators with LPLPO module
  scope OPERATE or higher may review submitted openings for active facilities and
  post them. Require Instalasi Farmasi operator eligibility as well as that scope;
  a Puskesmas operator's LPLPO OPERATE scope or a report grant is not sufficient.
  Preparation and verification remain separate actors. Recheck eligibility and
  scope under lock. No automatic delegation exception.
- Opening verification is an explicit cross-facility checkpoint authorized by this
  design, not a widening of Puskesmas preparation/edit access. The agreed
  Instalasi Farmasi role is GUDANG, matching current LPLPO cross-facility
  verification (`backend/apps/lplpo/access.py`). Do not silently grant
  every role with LPLPO OPERATE the new authority.
- Reverse/correction actions retain the agreed superuser gate. Opening post uses
  the explicit role-and-LPLPO-scope rule above, not generic approve/report scope or
  permissive Django-permission fallback alone.
- Inventory/report read: reuse dedicated puskesmas_reports policy and explicit
  staff-selection/aggregation capabilities; never grant write scope from them.
- Denials raise PermissionDenied. Writes use CSRF-protected POST and bounded
  mutation throttling. Admin inventory models are read-only.

Posting must atomically persist header checkpoint, layers, movements, balance
projection, idempotency key, review snapshot and workflow audit. A retry returns
the same posting when the source digest matches; changed data requires a correction.
No cumulative-target positive-only reimport from StockAdmin: it would silently
change an already verified opening. Reuploads may replace an unsubmitted draft;
submitted/posted data require a new revision/correction.

Correction proposal: before any dependent activity, a superuser with a reason can
append exact opposite movements and mark the original verification reversed, then
verify a replacement in the same controlled correction operation. Preserve source
versions and number/key reservations. Reject reversal if later dependent movements
or a closed period exist. Receipt corrections follow the same rule below. Feature
2 defines corrections once allocations/consumption exist. Never decrement a used
layer into negative stock or erase its history to make a correction succeed.

## 7. Receipt integration contract

For an initialized facility, post at the atomic DRAFT -> CONFIRMED checkpoint,
after validating every source row. Draft checked rows do not contribute stock.
Snapshot original issued_unit_price, issued_batch_lot, issued_expiry_date and
issued_sumber_dana from locked DistributionItem rows, with protected receipt and
distribution-row lineage. Copy known warehouse source number into immutable
facility provenance. The current protected stock link can supply it when verified;
do not substitute a current warehouse price or silently assume unproven history.
Consider adding an issued source-number snapshot at warehouse distribution time
for future distributions; no historical backfill without evidence.

Missing issued price must not use the current `or Decimal('0')` fallback for ledger
posting. Explicit zero is valid; missing is an exception requiring resolution.
For legacy unlinked receipts, preserve existing documents but do not automatically
turn them into priced layers: verify their row facts and inclusion/exclusion first.
Legacy linked rows that differ from distribution snapshots also need reconciliation;
do not overwrite historical receipts to force agreement.

One receipt posting per stable receipt event, one acquisition layer per source
line, unique event key and digest. One-to-one distribution linkage helps but does
not alone prevent duplicate posting/recreated source rows. Once posted, receipt
item IDs and economic fields are immutable; replace the delete/recreate edit
path for posted documents. Block date/facility/status/economic edits and deletion,
including reverting to Draft. UI, service and Admin/CLI entry points must agree.
Allow draft/pre-cutover compatibility edits only within their existing boundaries;
moving a historical receipt across cutover requires reviewed reclassification.

Recommend controlled whole-receipt reversal/replacement only if no dependent
movement or closed period exists, using original layer costs and explicit reason.
Do not add a physical-return workflow here or silently change LPLPO aggregates.
If corrected receipts affect editable LPLPO, synchronize from the effective receipt
version atomically; submitted periods remain blocked. This is a proposed workflow
change requiring design approval, not current behavior.

More specifically, retain the original receipt and its one-to-one distribution
link. A correction supplies an immutable replacement snapshot and supersedes the
original posting; it does not create a second operational receipt for the same
distribution. Monthly receipt aggregation would use the original rows unless a
posted correction exists, then its effective replacement rows exactly once. This
requires a deliberate change to the receipt-source helper, with existing monthly
weighted-price formula unchanged. Raw historical source rows and prior audit remain
visible. Original event retries still return the original result; correction
revisions have separate keys. The exact correction UI/schema needs design approval.

### Concurrency and idempotency

Use explicit transaction.atomic(), not signals or on_commit() for inventory writes.
Recommended lock order across affected services: actor/module access, Facility
and account, source parent, source detail rows ordered by PK, existing layers/
balances ordered by PK, affected LPLPO rows ordered by facility/year/month/PK.
All participating receipt mutations, opening/annual posting, catch-up, and relevant
LPLPO create/submit/mutation checkpoints must share the facility lock before
reading mutability/coverage. Audit actual lock order during implementation and
change interacting paths together; locking only receipt posting does not close
the existing LPLPO submission race or protect a missing LPLPO row.

Lock the existing Facility row when account/posting rows do not exist; an empty
select_for_update query cannot serialize creation. Unique database event/source
constraints are the final duplicate defense. Reload source status and authorization
after acquiring locks, check completeness and snapshot values, then post all rows
and synchronize editable LPLPO in that same transaction. Preserve existing
warehouse deductions: receipt posting does not issue another warehouse OUT.
Catch-up and live confirmation use the same posting service and event key.

## 8. Coexistence, rollout and feature-2 handoff

Deploy additive schema only, with no automatic synthetic opening or historic
consumption allocations. Facility states should distinguish UNINITIALIZED,
FOUNDATION_INCOMPLETE and READY (READY unavailable from feature 1 alone).
Receipt confirmations for uninitialized facilities retain existing behavior;
after opening, a controlled catch-up classifies every eligible confirmed receipt.
Live confirmations and catch-up serialize on the same facility account.

Feature 1 may expose verified opening and receipt journal for authorized audit,
with clear coverage dates and exceptions. Any projected balance must say that
consumption has not been posted and cannot be used as current stock, availability,
shortage validation, or reliable asset closing value. Existing self-check, stock
snapshot, LPLPO, rincian and rekap keep their current sources and labels. Do not
sum the new opening into an existing LPLPO-based report, or mix two foundations
in aggregate totals. No readiness is implied by merely importing a file.

Future movement accounting contract:

- For a fully covered interval, closing quantity/value = opening quantity/value
  + receipt deltas - consumption deltas + signed correction/reversal deltas.
  Value is sum(layer quantity * original layer price), never closing quantity
  times a newly averaged monthly price. Show corrections separately.
- Facility-wide scope includes rooms/Pustu: internal transfers are neutral.
  Feature 2 must confirm that monthly subunit input means actual consumption,
  rather than goods merely issued from the facility warehouse.
- Eligible FEFO layers: same facility/item, positive posted allocatable balance,
  verified expiry/provenance eligibility and effective availability by consumption
  business date. Exclude reversed/incomplete/unverified stock and future receipts.
- Deterministic order: expiry ascending NULLS LAST, acquisition effective date,
  origin posting ID, layer ID. Equal dates therefore remain stable; unknown
  original dates on initial stock use the declared opening effective date.
  Blank expiry means verified catalog-permitted non-expiring only. Recommend
  excluding expiry <= consumption date, consistent with warehouse is_expired;
  feature 2 must approve that operational expiry rule.
- Allocations must retain layer ID, quantity and price, plus consumption
  document/entry/revision linkage. Lock candidates in a consistent order and
  recheck balances inside the transaction. Reversal must reference original
  allocations and costs rather than rerunning FEFO against today's stock.
- Automatic shortage blocking, monthly consumption effective dates, subunit
  allocation order, shortage resolution, and allocation/reversal behavior remain
  feature-2 decisions. Do not infer them from this foundation's balance checks.
- Before READY/report switchover, prove complete opening, receipt and consumption
  coverage through a declared date, reconcile differences, and explicitly agree
  the report and January LPLPO transition. Preserve historical reports and disclose
  pre-cutover limitations. Never turn aggregate LPLPO totals into invented layers.

Rollback: disable new posting/readiness surfaces without deleting journal rows;
legacy reports continue. Do not drop populated tables as a rollback strategy.

## 9. Framework evidence

Context7 `/django/django` was consulted for transaction/locking and model validation.
Its results included main-branch material, so version-dependent recommendations
were checked against current official Django 6.0 documentation matching requirements:

- [Transactions](https://docs.djangoproject.com/en/6.0/topics/db/transactions/):
  keep all required database effects inside atomic; on_commit callbacks run after
  commit and cannot roll back a failed inventory posting.
- [select_for_update](https://docs.djangoproject.com/en/6.0/ref/models/querysets/#select-for-update):
  evaluate locks within a transaction; verify concurrency with TransactionTestCase
  on PostgreSQL. SQLite is not evidence for row-lock behavior.
- [Constraints](https://docs.djangoproject.com/en/6.0/ref/models/constraints/):
  use database uniqueness/checks alongside validation. nulls_distinct=False has a
  PostgreSQL 15+ restriction; this design avoids depending on a nullable composite
  layer identity and does not assume the deployed PostgreSQL version.
- [Model validation](https://docs.djangoproject.com/en/6.0/ref/models/instances/#validating-objects):
  save does not call full_clean automatically; posting services must validate
  imported/source data explicitly.

## 10. Remaining design decisions

The business questions raised in this discussion are resolved. The user accepted
immutable posted receipts and superuser-reviewed reversal/replacement before
dependent movements or closure after reviewing the explanation. This deliberately
changes today's direct editable-period receipt mutations for posted documents.
The user subsequently accepted the architecture and reduced first implementation
scope recorded in section 1, then explicitly authorized implementation.

Agreed after the first draft: hold records without verified original price or
required expiry pending evidence, and gate annual posting on complete prior-year
coverage. The application has no real operational data yet, so production-history
migration and historical catch-up are contingency contracts, not required launch
work. Do not build speculative legacy backfill tooling for development fixtures.

Receipt immutability means draft data stays editable, but confirmation creates
inventory effects that cannot be silently rewritten. For example, receiving 100
units and later consuming 20 leaves 80. Changing the receipt to 90 must also
account for the original +100 and its dependent consumption; overwriting the row
alone breaks the journal. Before dependencies, a reviewed correction can append
-100 and +90, preserving both the original fact and its correction. After dependent
consumption or closure, feature 2 must define the correction policy. This is a
future workflow invariant, not an obligation to preserve disposable test data.
Development database resets remain a separate, explicitly authorized operation;
no reset or deletion is authorized by the user's clarification alone.

Implement the agreed architecture with whole-unit quantities and explicit
validation. Resolve routine CSV/staging bounds, naming and mutation guards during
implementation with evidence and focused tests. No production configuration or
deployment dates are specified. Future correction UI and annual reconciliation
posting remain deferred as described in section 1.

## 11. Phased implementation and validation plan (after authorization)

1. **Implementation preparation.** Confirm runtime/database versions and review the
   affected code against the agreed scope. Before real onboarding,
   inventory the supplied January source data and record counts for missing
   price/expiry/funding/batch/source,
   missing distribution snapshots, receipt discrepancies, duplicate origins and
   receipt-date overlaps per facility. Read-only audit first; do not claim zero
   exceptions without measurements. Confirm PostgreSQL/runtime versions.
2. **Additive foundation.** Add models, constraints and posting services with
   explicit facility locks, audit identity and reconciliation queries. No automatic
   historical data migration. If an existing table needs a constraint, audit counts,
   then separate data-fix and constraint migrations; never edit applied migrations.
3. **Opening workflow.** Build operator draft/import/preview/submission and
   authorized superuser/Instalasi Farmasi review/post/reject; version review evidence.
   Implement only the first January opening posting. Annual reconciliation posting
   is deferred until feature 2 establishes complete closing coverage.
4. **Receipt integration.** Refactor linked saves to preserve posted source rows,
   add snapshot validation/idempotent posting and coverage classifications, enforce
   mutation guards, and align LPLPO lock order. Controlled catch-up uses the same
   service. Keep all warehouse and legacy reporting calculations intact.
5. **Pilot in incomplete mode.** Verify one real facility's evidence, opening totals
   and receipt lineage; audit discrepancies and permissions. Export clearly scoped
   journal evidence. Feature 2 separately implements consumption and readiness.

Focused automated checks to implement/run:

- CSV full validation, decimal precision, whole units, unknown provenance, expiry
  policy, path/MIME/size/row bounds, duplicate keys, stale/expired previews and review
  digest changes. Upload/submission has no inventory effects.
- Operator own-facility prepare, forged facility/layer IDs denied, inactive facility
  rejected, superuser review, eligible Instalasi Farmasi operator with LPLPO OPERATE
  or higher can review/post, insufficient scope denied, and different
  preparer/verifier. Puskesmas operators and report grants cannot acquire posting
  authority from LPLPO scope alone. Read/export isolation matches report policy.
- Initial quantity/value exactness, distinct same-batch prices/origins, verified
  zero versus unknown price, explicit zero facility, all-or-nothing rollback,
  repeat confirmation, revised payload rejection, protected posted history.
- Annual unchanged carry emits no IN; positive/negative layer deltas use original
  prices; omitted layers rejected; explicit zero handled; missing prior closing
  blocks posting; Jan 1 events follow opening. Never add full target to carry.
- Receipt Draft versus Confirmed, missing snapshot, later source-price changes,
  stable posted rows, edit/delete/revert guards, catch-up versus live confirmation,
  pre-cutover late entry, no second warehouse deduction, LPLPO sync rollback.
- PostgreSQL TransactionTestCase using separate connections for duplicate initial
  posting, concurrent receipt confirmation, annual verification versus receipt,
  stale correction, and LPLPO submission versus receipt. Check final journal,
  balances, coverage and LPLPO together, not only HTTP responses.
- Reconciliation: balance per layer equals sum(movement.quantity_delta); value
  equals sum(delta*immutable price). Ledger replay yields the same projection.
- Regression checks for January LPLPO, weighted receipt prices, report coverage,
  HTML/print/XLSX values, warehouse opening reimport and report authorization.

Existing test targets for the later regression pass (not run in this design work):

```powershell
.\scripts\run-django-test.ps1 -Target apps.stock.tests.OpeningBalanceImportAdminTests
.\scripts\run-django-test.ps1 -Target apps.puskesmas.tests.PuskesmasSBBKViewTests
.\scripts\run-django-test.ps1 -Target apps.lplpo.tests.LPLPOWorkflowTests
.\scripts\run-django-test.ps1 -Target apps.puskesmas.tests.PuskesmasReportViewTests
.\scripts\run-django-test.ps1 -Target apps.core.tests.test_url_consistency
```

New focused tests need their actual labels recorded when implemented. Use KeepDb
only with appropriate database state. Follow developer-guide local setup/migrations
and multi-role Playwright profiles for manual checks: operator uploads/submits,
superuser and eligible Instalasi Farmasi operator review/post, stale duplicate
browser tab, unauthorized other-facility operational access,
receipt confirmation/retry/edit rejection, and unchanged LPLPO/report exports.
Record commands, environment, observed values and failures; no fabricated pass.

Documentation at implementation: SYSTEM_MODEL for actual schema/checkpoints/
permissions/routes; puskesmas and any changed stock/distribution/lplpo/users app
guides; application_reference for workflow; seed/README for final CSV; developer
guide only for new operations/cleanup/catch-up tooling. Proposed routes stay under
`/puskesmas/` with trailing slashes, named reverse/template links and URL consistency
tests. Update this decision record with accepted/rejected choices and feature-2
handoff. This design document does not establish runtime behavior.

## 12. Implemented first increment and verification (2026-11-11)

Implemented seven models in `inventory_models.py` (re-exported by `models.py`):
account, opening verification/header and line, posting, immutable origin layer,
balance projection and movement. Migration `0012_inventory_foundation` creates
only new tables/constraints; it does not fabricate history. No correction model,
annual posting service, consumption allocation or READY state is implemented.

`/puskesmas/saldo-awal/`, `template/`, `buat/`, and `<pk>/` implement list, download,
actor-bound preview, submission, independent review/reject/post. Initial CSV has
no internal layer IDs. Drafts have a 24-hour submission expiry and remain retained;
submitted documents and their rows are frozen. Original-price/expiry holds block
the whole posting. Empty/zero-stock submissions are no longer supported.
Posting supports retries and catches up existing fully linked confirmed receipts
since January 1 atomically; unsupported sources abort rather than invent layers.

Receipt integration posts issued snapshots once after account initialization,
protects posted row identities and prevents edit/delete/revert. Receipt and relevant
LPLPO mutations share actor/module/facility locks; permissions are rechecked after
locking. Independent model/QuerySet guards cover ordinary ORM mutations and Admin
inventory access is superuser-only/read-only. Raw database SQL bypasses those
application guards. Reports and January LPLPO formulas remain unchanged.

Verification commands are in section 11 and the developer guide. Completed
regression targets: receipt view tests (26), LPLPO workflow (108), Puskesmas report
views (52), warehouse opening import (46), URL consistency (5), auditlog integration
(5), and Puskesmas report access policy (5). Inventory tests separately cover
precision, holds/rollback, zero stock, independent authority, scoped previews,
rejection, immutable sources, cutover exclusion, live confirmations and three
PostgreSQL concurrent-posting/submission scenarios. Record the final inventory
test count: 14 passed on the final run, including the live-confirmation/replay
check and three PostgreSQL concurrency tests. Across the listed targets, 261
distinct tests passed; this is not a claim that the full repository suite ran.
Verified runtime: Django 6.0.8, PostgreSQL server version 160011 (16.11), Node
24.12.0 and Bun 1.3.14. No production database/version audit was performed.

`manage.py check`, `makemigrations --check --dry-run`, local `migrate`, `bun ci`,
`bun run css:build`, `bun run css:check`, and `git diff --check` were run. CSS builds
match the generated artifact without a stylesheet diff. Test fixtures use real ORM
rows/services, not mocked stock/posting behavior.

Browser smoke used existing local PUSKESMAS and GUDANG Playwright profiles because
the Browser plugin is unavailable. Both list pages returned 200, the operator
form rendered bound validation errors without saving, and desktop/mobile
screenshots were inspected. Mobile form has no page overflow; no captured console
or page errors. Screenshots/scripts/logs are temporary local artifacts outside the
repository. Full posting is verified by Django client/service tests, not claimed
as a browser-executed posting. Real January evidence and real operational rollout
are not verified; correction UI remains a prerequisite before that rollout.

## 13. Agreed worksheet enhancement (2026-11-11)

The template now has facility/year selection and eleven columns, adding item_name
and unit as master-data reference labels. Each pre-cutover DISTRIBUTED row addressed
to that facility is a candidate, excluding receipts confirmed on/after cutover.
Issued batch/expiry/original price/funding and known warehouse source provenance
are copied. Quantities always remain blank and no remaining balance is inferred.
Same-batch rows with different acquisition origins/prices stay separate.

DIST-<id> keys bind selected rows to a protected nullable source_distribution_item
on opening lines (migration 0013); source economic fields, scope and cutoff are
validated during import/preparation and again at posting. Unlinked historical
lines keep their existing digests. Original nine-column manual files remain
accepted. Manual additions use keys outside DIST-. Spreadsheet formula-leading
text is escaped on export and decoded only against the linked original snapshot.

Blank quantities skip rows; at least one positive whole quantity is required.
This supersedes the original empty-facility/zero-stock attestation design. The
checkbox is removed, CSV upload is required and service checks also reject the
legacy zero-stock shortcut. The historical model flag is retained without
rewriting posted data or applied migrations. The coverage confirmation remains;
this change removes only the zero-stock checkbox requested by the user.

No eligible history produces a header-only worksheet for manual completion, not
an inferred zero balance. Candidate prefill is not proof of stock still held:
operators verify quantities against opening evidence before the existing preview,
submission and independent verification. Annual reconciliation and feature 2
remain deferred.

Validation for this enhancement: all 19 `apps.puskesmas.test_inventory` tests and
5 URL-consistency tests passed on PostgreSQL. Coverage includes worksheet
round-trip, blank quantities, source/facility/year tampering, stale source prices,
missing price snapshots and formula-safe CSV text without substituting current
warehouse prices. Migration 0013 was applied locally; Django system/migration-drift
and generated CSS checks passed. Browser checks with the existing Puskesmas profile
verified scoped download, eleven guide columns, absent zero checkbox, rejected
header-only upload and no mobile page overflow/page errors. Test logs and browser
artifacts remain outside the repository; no real opening stock was posted by QA.

## 14. Agreed broader Instalasi Farmasi candidates (2026-11-13)

This supersedes section 13's history-only template scope. Keep the facility's
eligible historical distribution rows first, then offer recorded warehouse Stock
identities for active items and funding, including zero-quantity rows. All eight
identity fields are prefilled where recorded; quantity remains blank. Skip warehouse
identities already represented by a distribution candidate or another warehouse
location using item, exact price, batch, expiry, funding and source document.
Distinct distribution acquisitions remain separate. Manual historical additions
remain supported with keys outside both DIST- and STOCK-.

STOCK-<id> is an automatic reference that operators must not change. A nullable
protected source_stock FK (migration 0014) records an identity reference only, not
a delivery claim or warehouse transfer. Its economic fields are validated during
import, preparation and posting, with source row locks at write checkpoints. A
changed source requires a fresh worksheet; posted inventory retains its own frozen
snapshot. Null new FKs are omitted from digests to preserve existing documents.

Warehouse price metadata is a candidate for historical verification, not proof of
the Puskesmas's original acquisition cost. Candidates are not restricted by warehouse
quantity, current availability, expiry, location activity or an inferred historical
receipt date. The verifier must establish that selected stock actually belonged to
the facility before January 1 at the stated original price. Later receipts must not
be included twice. There is no automatic ownership inference or source backfill.
Warehouse records from other facility distributions are not exposed; only shared
warehouse identities and the selected facility's eligible distributions are offered.

Blank quantities are skipped, positive whole quantities enter preview, empty
submissions are rejected, and independent verification remains mandatory. Neither
warehouse Stock nor Transaction is changed by opening posting. Existing feature-2,
annual-posting and correction boundaries remain unchanged.

Validation: 23 inventory tests passed on PostgreSQL, including four new checks for
no-history prefill, all eight fields, manual additions, zero-quantity warehouse
sources, identity deduplication, tampering/stale source rollback, formula-safe text,
unchanged warehouse quantities/journal and frozen posted facility prices.
Manual check: download for a Puskesmas with no distribution history, confirm warehouse
identities have blank quantities, select matching stock and add a manual historical
row, then review the preview before submission. Verify a second user sees both
origins and their provenance. Posting must leave the warehouse stock card unchanged.

## 15. Simpler operator worksheet (2026-11-13)

The downloaded CSV now omits source_document_number (CSV cannot hide columns) and
leaves provenance_note blank. This supersedes the visible document column and
prefilled note in sections 13/14; the downloadable format has ten columns. Source
document identity remains stored internally: DIST-/STOCK- keys resolve known source
numbers during parsing, then preparation/posting revalidate the full snapshot under
source locks. Source documents remain visible during review. No database fields,
posted records or digests are changed by this format update.

For linked rows, blank operator notes are allowed; the importer records factual
missing-source information and the warehouse-candidate caution internally. This
does not verify ownership or invent missing history. Manual additions have no
automatic document reference and must include a provenance note; known source
documents may be described there. Legacy nine/eleven-column CSVs can still provide
the dedicated source_document_number field. Supplied linked document numbers must
match the source, preserving tamper detection for those formats.

Validation: all 24 inventory tests passed on PostgreSQL. Coverage includes blank
downloaded notes, absent document column, internal source recovery for both kinds
of references, legacy document-column validation, required manual provenance,
formula-safe source recovery and unchanged posting behavior. Manual check: download
a fresh template, confirm ten columns and empty notes, enter a positive quantity,
then confirm the preview recovers the source document and factual provenance.

An attached operator CSV reproduced a spreadsheet-converted batch on row 393,
changing recorded `060125.01` to `60125,01`. Restoring that field in memory allowed
333 selected rows to parse against local source records. The manually added row 13
had blank quantity and was skipped under the agreed rule. To submit it, the
operator must supply quantity, a unique manual line_key and a provenance note.

Numeric-looking item/batch/funding codes now receive an apostrophe text prefix in
downloads. Import restores protected text by matching the linked source. Exact
batch comparisons and decimal-comma price support are covered together by a
regression test. Source mismatches report the specific field and both values.
All 26 inventory tests passed on PostgreSQL, including an end-to-end manual-layer
addition through independent posting. A real LibreOffice headless CSV-to-ODS-to-CSV
check using Indonesian import language and special-number detection preserved
the protected batch `060125.01`. The resulting CSV passed the application parser
with quantity 340 and the recorded exact price. Temporary verification files remain
outside the repository. Excel round-trip behavior has not been verified.

The updated operator file at `.dev/note/new-seeding/SALDO-AWAL-LPLPO-PUSKESMAS.csv`
also reproduced four source-price conversions, removing decimal separators from
992.249, 3741.111, 1705.404 and 4370.649. Known prices are now exported as protected
text with an apostrophe, and price parsing accepts that prefix before validating
finite values, precision and exact source prices. This includes manual price input.
The local CSV was corrected at those four source prices and the converted batch
using verified database values. Its added manual row received key MANUAL-13.
The corrected file passes parser validation with 334 rows, including its supplied
manual quantity 60, unit price 404.56, batch WQPITU and operator provenance note.

All 27 inventory tests passed. A LibreOffice CSV-to-ODS-to-CSV check with Indonesian
import language preserved all five affected source rows and their exact original
prices/batches. The resulting file passed the application parser. This validation
did not post the operator file to facility inventory.

## 16. Automatic manual-row references (2026-11-16)

Operators may leave line_key blank for manually added stock. Parsing generates a
MANUAL- reference using UUID4 for each selected blank-key row. The generated key is
saved in the preview and retained through submission/posting. Blank-quantity rows
are skipped as before. Existing supplied manual keys remain supported, with
duplicate detection and the reserved DIST-/STOCK- source-validation rules.
Manual rows still need quantity and provenance evidence. This supersedes earlier
instructions requiring operators to invent manual line keys. Existing previews
and posted documents retain their references. The upload guide and CSV contract
describe the automatic behavior.

Validation passed on PostgreSQL with 28 inventory tests. A focused upload-form
check verified that generated references are saved in the draft preview alongside
an explicit legacy manual key. Revalidating the operator CSV in memory with its
WQPITU row key cleared accepted all 334 rows and generated a manual reference for
quantity 60. The source file and facility inventory were not changed by that check.

## 17. Draft preview cancellation (2026-11-16)

The active preparer can cancel their own DRAFT preview, including an expired
preview, with Batalkan Pratinjau on the existing detail route. A confirmation
precedes CSRF POST action=cancel with the current digest. The service locks the
actor/module, facility and document in the existing order, rechecks authority,
digest and live status, then records CANCELLED, cancelled_by and cancelled_at.
The header and uploaded lines remain available as history. A repeat request is
idempotent and success returns to the list. Submitted/rejected/posted documents
cannot use this draft action. Posted correction/reversal work remains deferred.

Migration 0015 adds the status choice and nullable protected cancellation actor
and timestamp. It was applied locally. All 32 inventory tests passed, including
creator/facility enforcement, stale digest, expired draft cancellation, retained
rows, idempotency, submitted/posted blocking and a PostgreSQL cancellation versus
submission race. Browser checks with the existing operator preview verified the
button, confirmation dismissal, desktop/mobile layout and navigation. The live
preview remained DRAFT during browser verification.

## 18. Upload confirmation removed (2026-11-16)

At the user's request, the upload form no longer includes boundary_attested.
Whole-facility and January 1 cutoff guidance is displayed as plain text beside
the upload form. A valid CSV can proceed directly to preview. This supersedes
earlier references to a required operator coverage confirmation. The independent
reviewer's posting confirmation continues to apply at its existing checkpoint.
No stored inventory fields or calculations depend on the removed form field.

All 32 inventory tests passed, including upload-to-preview tests omitting the
field. Browser verification confirmed zero checkboxes in the import section,
visible cutoff guidance, preserved file-picker spacing and no mobile overflow.
