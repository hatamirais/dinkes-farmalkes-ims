# reports AGENTS.md

App-specific guidance for report authorization and stock/accounting semantics.

## Authorization

- Puskesmas report routes require `reports.view_reports` or REPORTS module-scope `VIEW`.
- On Puskesmas report routes, superusers may query all facilities. Every non-superuser is forced to the linked `user.facility` and receives `403` when no facility is linked.
- Report permission never grants access to another facility's underlying operational objects.

## Stock Reporting

- Stock movement reports derive from the append-only `stock.Transaction` ledger, not django-auditlog.
- Detailed reports and stock cards preserve `source_document_number` and location where rows are location-specific.
- Do not average unit prices across source-document layers.
- Puskesmas inventory reporting derives from the LPLPO baseline plus confirmed receipts and detailed consumption according to the owning app rules.
- Report HTML shows monetary amounts with two Indonesian decimal digits. Keep underlying Decimal calculations and Excel export precision intact; quantity formatting is separate.
- Keep report links, route names, and documented report variants synchronized with actual URLconfs.
