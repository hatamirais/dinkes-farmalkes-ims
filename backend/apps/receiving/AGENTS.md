# receiving AGENTS.md

App-specific guidance for receiving workflows.

## Purpose

`receiving` owns regular and planned receiving flows, custom CSV import endpoint and matching CSV template download in admin, quick-create lookup endpoints, custom `ReceivingTypeOption` support, and authenticated download links for `ReceivingDocument` attachments stored under `PRIVATE_MEDIA_ROOT`.

## Stock Mutation

- Receiving admin CSV import writes `Receiving`, `ReceivingItem`, updates or creates `Stock`, and writes `Transaction(IN)`.
- CSV rows are grouped by required `import_group`; it is import metadata, not the official document number. The official Receiving number is issued after group validation in the same transaction as stock and ledger posting.
- Receiving stock rows use the receiving `document_number` as `Stock.source_document_number`, except migrated historical document-number collisions continue on their disambiguated existing stock source layer.
- Receiving transactions use the same receiving source document value as the stock row they post to.
- Receiving `document_number` values must not collide with opening-balance import document numbers; generated receiving numbers skip opening-balance-owned `RCV-YYYY-NNNNN` values.
- Receiving `document_number` is system-issued and immutable. Its `SourceDocumentNumberClaim` is retained after cancellation/deletion so issued values cannot be reused.
- Unnumbered Receiving drafts do not create source-number claims; the claim is created only when the populated official number is saved. Historical non-planned Receiving issuance metadata is reconstructed from `verified_by` / `verified_at` because regular and CSV workflows set those fields immediately before issuance. Contract-linked planned Receiving history uses `approved_by` / `approved_at`; legacy manual plans without an exact checkpoint remain unknown.
- Same item/location/batch/funding can appear in different receiving documents as separate stock layers; do not average their `unit_price` values.
- Within one receiving source-document layer, expiry date and unit price must remain exact. A same-layer mismatch is rejected instead of merged.
- Stock mutation belongs to receiving execution/import workflow actions, not arbitrary model saves.
- Manual regular receiving normalizes blank Batch/Lot input to `"-"` before creating `ReceivingItem`, `Stock`, and `Transaction` rows.
- Receiving and opening-balance imports enforce `Item.requires_expiry_date`: blank `expiry_date` is allowed only for catalog items marked as non-expiring.
- Regular receiving correction is ledger-safe: edit/cancel actions append reversal `Transaction(OUT)` rows instead of mutating historical `Transaction(IN)` rows. Edit then reposts corrected `Transaction(IN)` rows; cancel marks the document `CANCELLED`. Both actions must lock affected stock rows, fail if the received stock has already been consumed or reserved, and preserve zero-quantity stock rows instead of deleting them because draft workflows may reference those rows. Correction reposting may reuse an unreserved zero-quantity receiving stock row with corrected expiry or unit price; normal receiving and planned receiving execution must still reject same-source metadata mismatches. Correction forms preserve an existing expiry date for a non-expiring item when the browser omits the optional expiry field. CSV-imported rows with per-row `sumber_dana_code` overrides store their posted funding/source layer on `ReceivingItem` and must be reversed from that actual posted stock/ledger layer.
- Regular receiving edit/cancel is limited to superusers/Admin plus roles `GUDANG` and `KEPALA` with receiving operate access, and POST mutations use `RECEIVING_MUTATION_RATE_LIMIT`.

## Receiving Types

- Receiving type dropdowns and labels resolve from active `ReceivingTypeOption` rows.
- System rows include `PROCUREMENT` / `Pengadaan` and `GRANT` / `Hibah`; quick-create rows are non-system custom types.
- `requires_supplier=True` on a receiving type row requires the form/model to capture a supplier.
- Regular receiving edit keeps an inactive historical type selectable and valid when the existing document already uses that exact type; inactive types remain invalid for new selections, and retained inactive types still enforce their stored `requires_supplier` flag.

## Procurement-Linked Planned Receiving

- SPJ-linked procurement receiving plans are no longer manually approved.
- Approved SPJ contracts auto-create or re-sync exactly one linked planned `Receiving(contract!=NULL)` document.
- SPJ-linked planned receiving leftovers must be corrected through procurement amendments rather than the receiving-side `Tutup Sisa` close-items action.
- New no-contract planned receiving creation is disabled; `/receiving/plans/create/` redirects to the SPJ create flow.
- Legacy manual `Receiving(is_planned=True, contract IS NULL)` rows remain readable and executable through receiving routes for compatibility.

## Attachments

- `ReceivingDocument` attachments are stored under `PRIVATE_MEDIA_ROOT`.
- Download links must remain authenticated.

## Admin Import Gotchas

- Keep the custom CSV import endpoint and matching CSV template download in admin aligned with the actual parser/resource behavior.
- CSV column docs must match the receiving admin parser/resource classes.
- The receiving CSV header is `import_group`, not `document_number`; opening-balance CSV continues to use `document_number` because it owns a separate source-document identity.
- Quick-create lookup POST mutations are covered by `@item_mutation_ratelimit`, not the user-management throttle bucket.
