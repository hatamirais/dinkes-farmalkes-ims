# reports AGENTS.md

App-specific guidance for report authorization and stock/accounting semantics.

## Authorization

- Puskesmas report routes require dedicated `puskesmas_reports` module scope VIEW or higher; generic Reports permissions do not grant access. See `puskesmas/AGENTS.md` for facility isolation and explicit eligible-staff selection/aggregation permissions. Superusers retain full scope.
- Report permission never grants access to another facility's underlying operational objects.

## Stock Reporting

- Stock movement reports derive from the append-only `stock.Transaction` ledger, not django-auditlog.
- Detailed reports and stock cards preserve `source_document_number` and location where rows are location-specific.
- Do not average unit prices across source-document layers. Source-price Excel cells preserve up to 15 decimal places as text, and source-price amounts multiplied by stock quantities preserve up to 17.
- Puskesmas inventory/report views share the owning app's `stock_reports` snapshot: original-layer journal within verified opening coverage, labelled historical LPLPO/receipt/consumption fallback outside coverage, and excluded facilities without either source. Sources are selected per facility and never counted twice.
- Report HTML shows monetary amounts with two Indonesian decimal digits. Keep underlying Decimal calculations and Excel export precision intact; quantity formatting is separate.
- Keep report links, route names, and documented report variants synchronized with actual URLconfs.
