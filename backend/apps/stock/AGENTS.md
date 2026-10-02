# stock AGENTS.md

App-specific guidance for stock balances and ledger behavior.

## Purpose

`stock` owns stock entries, immutable transactions, stock card, location-based stock search, stock transfer, admin-only opening balance (`Saldo Awal`) CSV import, and a read-only `Stok Puskesmas` snapshot page for Instalasi Farmasi-side planning/audit visibility.

## Stock Quantities

- The stock list and summaries distinguish `stok fisik`, `reserved`, and `stok tersedia`.
- `stok tersedia` is `quantity - reserved`.
- Availability checks across distribution, recall, expired, transfer, and several selectors use `Stock.available_quantity`.
- Batch selectors should order dated stock by FEFO and place `expiry_date=NULL` rows last as non-expiring stock.
- Stock rows are source-document layers. The unique stock tuple is `item + location + batch_lot + sumber_dana + source_document_number`.
- Do not merge same-batch rows from different source documents by averaging prices; accounting values stay tied to the posted source layer.

## Ledger Rules

- `stock.Transaction` is the authoritative append-only stock movement ledger.
- `stock.Transaction.source_document_number` identifies the source stock layer moved by the transaction and must be set by every stock-changing workflow.
- Never mutate historical `Transaction` rows.
- Do not replace stock movement reporting with auditlog entries.
- Stock transfer completion writes paired `OUT` and `IN` transactions.
- Stock Transfer drafts have no official number; completion issues the central `STOCK_TRANSFER` rule atomically using `transfer_date` before writing the paired ledger rows.
- Django Admin keeps Stock Transfer lifecycle/completion fields read-only, locks transfer lines after Draft, and disables global bulk actions; completion must use the workflow so numbering and paired `OUT` / `IN` ledger writes remain atomic.
- Source-layer migrations must keep paired transfer `OUT` and `IN` movements on the same source document layer.
- Source-layer migrations must disambiguate historical receiving/opening-balance document-number collisions.

## Opening Balance Import

- Initial stock bootstrap must use the Stock Admin opening-balance import at `/admin/stock/stock/opening-balance/import-csv/`.
- Do not use `receiving.csv` or direct `stock.csv` import for initial stock bootstrap.
- Generic Stock admin import plus direct Stock add/change/delete mutations are disabled so stock cannot be written without ledger transactions.
- Opening-balance import is restricted to superuser / role `ADMIN`.
- Opening-balance import uses one consistent non-future `effective_date` per `document_number` for report classification.
- Opening-balance CSV imports accept comma or semicolon delimiters.
- It rejects populated `receiving_type` / `supplier_code`.
- It validates decimal precision before preview/confirm.
- It rejects negative unit prices.
- It generates blank batches with document identity.
- It rejects conflicts inside the same source document layer when `expiry_date` or `unit_price` differs.
- It rejects duplicate stock-layer rows inside the same CSV; combine `quantity` into one row or use a different `batch_lot` / `document_number`.
- Reimporting an already posted opening-balance `document_number` is allowed for partial completion: exact existing stock-layer totals are skipped, higher totals for an existing layer post only the quantity delta, and new rows under that document are posted to the existing import header. Reimport rows must provide `batch_lot` explicitly because generated blank-batch names include the CSV row number.
- Confirmed imports create `OpeningBalanceImport` and `OpeningBalanceImportItem`, update stock with `source_document_number=document_number` and `receiving_ref=NULL`, and write `Transaction(IN, reference_type=INITIAL_IMPORT)`. Migrated historical receiving/opening-balance document-number collisions continue on their existing disambiguated `OBI-...` opening-balance source layer during reimport.
- Rekap/yearly reports classify opening-balance rows as `saldo_awal` when effective on/before the report start, or as in-period received stock when effective after the start and within the selected period.
- Later years carry forward from the ledger and do not require re-import.

## Puskesmas Stock Snapshot

- The read-only `Stok Puskesmas` snapshot page is for Instalasi Farmasi-side planning/audit visibility.
- It derives current per-Puskesmas stock from the latest usable LPLPO closing stock plus later confirmed receipt confirmations minus later detailed consumption in the same year.

## Expiry Handling

- Opening-balance imports enforce `Item.requires_expiry_date`.
- Blank `expiry_date` is allowed only for catalog items marked as non-expiring.
- Legacy no-expiry sentinel backfills normalize copied outbound history fields (`DistributionItem.issued_expiry_date` and downstream Puskesmas receipt-confirmation `expiry_date`) to `NULL` so historical UI/reporting renders `Tanpa kedaluwarsa` consistently.
