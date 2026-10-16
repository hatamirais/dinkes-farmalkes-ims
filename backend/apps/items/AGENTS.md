# items AGENTS.md

App-specific guidance for the item catalog and shared item lookup mutations.

## Purpose

`items` owns item codes, barcodes, flags, therapeutic classes, expiry requirements, filtering, and XLSX export.

## Catalog Invariants

- `Item.requires_expiry_date` controls whether receiving and opening-balance imports may accept a blank expiry date.
- Item identifiers and other comparable strings must be stripped, NFC-normalized, length-checked, and rejected when they contain null bytes.
- Numeric catalog inputs reject `NaN` and `Infinity`.
- Foreign-key and choice values must be validated against the allowed queryset/choices rather than trusting client IDs.

## Mutation Throttling

- `@item_mutation_ratelimit` covers item catalog lookup POST mutations and the receiving/procurement quick-create lookup POST mutations.
- Keep quick-create validation consistent with the canonical item/catalog forms and models.
