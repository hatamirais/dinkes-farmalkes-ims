# AGENTS.md - Healthcare IMS

Onboarding guide for coding agents working in this repository.

This project is a Django-based healthcare inventory system used by internal government-health staff. Engineering language is English-first; product-facing labels are mostly Indonesian.

For app-specific rules, see `backend/apps/<app_name>/AGENTS.md` if present.

## Environment Snapshot

| Item | Value |
| --- | --- |
| Python | 3.13+ |
| Django | 6.0.8 |
| Database | PostgreSQL 16 |
| Cache/Broker | Redis when `REDIS_URL` is set; otherwise In-Memory / LocMemCache |
| UI | Django templates + Bootstrap 5; DRF read-only reporting API |
| Static serving | WhiteNoise for collected static assets |
| Auth model | `apps.users.User` |
| Object audit | django-auditlog |
| Settings | `backend/config/settings.py` |
| Root URLs | `backend/config/urls.py` |

## Repository Map

Root files include `README.md`, `AGENTS.md`, `SYSTEM_MODEL.md`, `docker-compose.yml`, `.env.example`, `VERSION`, `backend/`, and `scripts/`. `backend/` contains `manage.py`, `requirements.txt`, `config/`, `apps/`, `templates/`, `static/`, `seed/`, and `tests/`.

## Source Of Truth

Schema: `backend/apps/*/models.py`. Routes: `backend/config/urls.py` + `backend/apps/*/urls.py`. Auth/permission: `backend/apps/core/decorators.py`, `backend/apps/users/access.py`. Security/config: `backend/config/settings.py`. App version: root `VERSION` and `backend/apps/core/versioning.py`. Operational scripts: `scripts/`. CSV import behavior: `backend/apps/*/admin.py` and resource classes. If documentation conflicts with code, code is authoritative until docs are corrected.

## Task Prompt Template

For new coding sessions, a short prompt is enough because this file carries the project rules:

```text
Task: <describe the change>

Follow AGENTS.md, SYSTEM_MODEL.md, and any relevant backend/apps/<app>/AGENTS.md.
Verify behavior with focused tests or a documented manual check.
Update docs when the change affects schema, routes, permissions, settings, workflows, scripts, or CSV/import behavior.
```

## Active Django Apps

| App | Purpose |
| --- | --- |
| `core` | Shared abstractions, dashboard, system settings, centralized error handlers, and maintenance view. |
| `users` | Custom user model and `ModuleAccess` scope model. |
| `items` | Master data and item catalog, including item codes, barcodes, flags, therapeutic classes, expiry requirements, filtering, and XLSX export. |
| `stock` | Stock balances, immutable transactions, stock card, location search, transfers, opening balance import, and Puskesmas stock snapshots. |
| `receiving` | Regular/planned receiving, receiving imports, type options, quick-create lookups, and private receiving attachments. |
| `procurement` | Authoritative SPJ/contract procurement, amendments, approval, and planned procurement receiving synchronization. |
| `distribution` | Outbound workflows, batch/value snapshots, reservations, preparation assignments, LPLPO/manual/special/allocation variants, and outbound reports. |
| `allocation` | Pre-distribution planning that generates reserved facility-level child distributions. |
| `recall` | Supplier return workflow. |
| `expired` | Expired/disposal workflow and alerts. |
| `stock_opname` | Physical stock counting workflow with frozen start and completion quantity checkpoints. |
| `puskesmas` | Facility-scoped requests, receipt confirmations, subunit master data, consumption input, and stock self-checks. |
| `lplpo` | Monthly Puskesmas reporting and stock request workflow. |
| `reports` | Report index, rekap, receiving/procurement/expiry/outbound reports, numbering history, and Puskesmas inventory reports. |
| `api` | Read-only DRF endpoints for internal external-dashboard stock snapshots. |

## Permissions And Errors

There are two permission layers: Django `has_perm` checks through groups/permissions, and module scope fallback (`ModuleAccess`) used by `@perm_required`.

`@perm_required` in `backend/apps/core/decorators.py` allows access if either layer grants permission. Module scopes are `NONE`, `VIEW`, `OPERATE`, `APPROVE`, and `MANAGE`; default scopes per role are in `backend/apps/users/access.py`.

Permission denials should raise `PermissionDenied` so requests flow through the centralized `handler403` page instead of returning raw HTML fragments.

`OPERATOR PUSKESMAS` uses `facility` matching. Views in `puskesmas` and `lplpo` enforce strict facility isolation, and every non-superuser account using those operational surfaces must have a linked `facility` or receive `403`.

Super Admin (`is_superuser` / role `ADMIN`) remains exempt from `puskesmas` and `lplpo` facility scoping. Puskesmas report routes require `reports.view_reports` or REPORTS module-scope `VIEW`; superusers may query all facilities, while non-superusers are forced to their linked `facility`.

`/settings/` is not governed by module-scope fallback. It is an explicit role-gated `core` view that allows only superusers plus users whose role is `ADMIN` or `KEPALA`.

`AUDITOR` keeps read-only module scopes for direct authorized pages; its sidebar is report-focused and only renders the `Laporan` group. Its dashboard hides linked drill-through components that open operational menu pages.

Stock opname completion is split by current discrepancy state: `GUDANG` / operate-scope users may complete when refreshed current stock matches the physical count for all rows, while completion with any remaining discrepancy requires stock-opname approve scope (`KEPALA`/Admin/superuser by default). Completion stores each row's refreshed stock quantity so completed detail and print reports do not drift when later workflows change live `Stock.quantity`.

## Cross-App Data Flow

Stock movement is ledger-first: historical `stock.Transaction` rows are append-only, stock-changing checkpoints happen during workflow actions, and reports should not replace stock movement reporting with auditlog entries.

Inbound: `procurement` approved SPJ/amendment -> linked planned `receiving` document -> receiving execution/import -> `stock.Stock` update + `stock.Transaction(IN)`.

Regular receiving edit/delete is implemented as stock correction, not ledger rewriting. Editing a posted regular receiving appends reversal `Transaction(OUT)` rows, replaces the current receiving items, then appends corrected `Transaction(IN)` rows. Deleting/cancelling appends reversal `Transaction(OUT)` rows and marks the receiving `CANCELLED`. Both are blocked when stock has already been consumed or reserved, and reversal preserves zero-quantity stock rows instead of deleting them because draft workflows may hold protected references to those rows. Corrected reposting is the only path allowed to reuse an unreserved zero-quantity stock row with updated expiry or unit price; normal receiving execution must still reject same-source metadata mismatches. Correction forms must preserve an existing expiry date for a non-expiring item when the browser omits the optional expiry field. Imported receiving rows with row-level funding overrides store their posted funding/source layer on `ReceivingItem` and must be reversed from that actual posted stock/ledger layer, not the header funding source.

Opening balance: Stock Admin opening-balance import -> `stock.OpeningBalanceImport` / `OpeningBalanceImportItem` -> `Stock(source_document_number=OpeningBalanceImport.document_number, receiving_ref=NULL)` update/create -> `Transaction(IN, reference_type=INITIAL_IMPORT)`.

Outbound: `allocation` approval or `lplpo` PIC review or manual/special request -> `distribution.Distribution` / `DistributionItem` -> stock reservation at verification -> stock deduction and reservation clearing at final distribution.

Facility receipt/reporting: delivered distribution -> `puskesmas.PuskesmasReceiptConfirmation` / items -> same-month editable `lplpo` receiving and price sync -> reports derive Puskesmas inventory from LPLPO baseline plus confirmed receipts and detailed consumption.

Consumption: `puskesmas.PuskesmasConsumption` / entries -> same-month editable `lplpo.LPLPOItem.pemakaian` sync -> inventory and request calculations.

Availability checks across distribution, recall, expired, transfer, and several selectors use `Stock.available_quantity` (`quantity - reserved`). Batch selectors should order dated stock by FEFO and place `expiry_date=NULL` rows last as non-expiring stock.

Stock rows and stock transactions carry `source_document_number`. Stock rows are uniquely identified by item, location, batch, funding source, and `source_document_number`; detailed reports and stock cards also group by that source layer and keep location visible where rows are location-specific. Receiving uses the receiving document number as the stock source document, except migrated historical collisions continue on their disambiguated receiving source layer; opening balance uses the opening-balance document number. New receiving and opening-balance source document numbers are serialized through `stock.SourceDocumentNumberClaim` so they cannot collide across workflows. Do not average unit prices across source documents. Same item/location/batch/funding can exist in separate source-document layers, while conflicts within the same source document must preserve exact expiry and unit price.

Receiving and opening-balance imports enforce `Item.requires_expiry_date`: blank `expiry_date` is allowed only for catalog items marked as non-expiring. Manual regular receiving normalizes blank Batch/Lot input to `"-"` before posting stock and transactions. Opening-balance CSV imports accept comma or semicolon delimiters and preserve `unit_price` up to 10 decimal places; decimal-comma values such as `8893,31985` are normalized internally. Legacy no-expiry sentinel backfills normalize copied outbound history fields to `NULL` so historical UI/reporting renders `Tanpa kedaluwarsa` consistently.

## Global Workflow Rules

- Never mutate historical `Transaction` rows; append-only behavior is expected.
- Stock-changing checkpoints happen during workflow actions (`verify`, `prepare`, `distribute`, `complete`, depending on module), not arbitrary model saves.
- Stock transfer completion writes paired `OUT` and `IN` transactions.
- Do not claim REST API/React production paths as implemented; those are planned.
- Keep terminology consistent: use "module scope" for `ModuleAccess` and "Django permissions" for `has_perm` checks.

## Development Guardrails

- Keep changes atomic and verify each behavioral change before expanding scope.
- Prefer Django ORM APIs. Use raw SQL only when the ORM is insufficient, and document the reason.
- Use `select_related` / `prefetch_related` for relationship-heavy reads, `select_for_update()` for race-prone writes, and explicit `transaction.atomic()` around multi-row workflow mutations.
- Forms should use crispy-forms / crispy-bootstrap5 and Bootstrap 5 utilities. Document custom CSS exceptions when they are necessary.
- New logic needs tests scaled to risk and blast radius.
- Use Python logging for operational diagnostics, raise specific exceptions, and do not swallow failures silently.
- Do not edit already-applied migrations unless explicitly requested and safe for the current branch state.

## Input Validation

- Numeric inputs must reject `NaN` and `Infinity`; `Decimal("NaN")` can construct successfully and fail later.
- User-facing or comparable strings should be stripped, NFC-normalized, length-checked, and rejected when they contain null bytes.
- Dates must reject years outside `1000..9999`; datetimes should be timezone-aware.
- Foreign keys and choice fields must be validated against allowed querysets or choices; never trust client-supplied IDs by themselves.
- File uploads must validate server-side MIME and extension, enforce max size, and reject path traversal or absolute paths.

## Migration Discipline

When adding constraints that existing rows might violate:

1. Audit existing rows first and document the count.
2. Add a data-fix migration.
3. Add the constraint migration separately.

## Sensitive POST Throttling And Audit

- `django-axes` remains the login brute-force control. Login lockout is enforced by username and source IP (`AXES_LOCKOUT_PARAMETERS = ["username", "ip_address"]`) with `AXES_CLIENT_IP_CALLABLE` pointing at the project trusted-proxy resolver.
- `AXES_RESET_ON_SUCCESS` is disabled; successful login cleanup is project-owned and must delete only the successful username's failed attempts, not unrelated attempts sharing the same resolved source IP.
- The login route uses Django `LoginView` with `apps.core.forms.CrispyAuthenticationForm`; do not hand-code username/password inputs in `registration/login.html`.
- Authentication and centralized error logs resolve client IPs through `apps.core.client_ip.get_client_ip()`, using `REMOTE_ADDR` by default and accepting `X-Forwarded-For` only when the immediate peer matches `AUTH_AUDIT_TRUSTED_PROXIES`.
- Additional authenticated POST throttling uses `django-ratelimit`; counters use `CACHES["default"]` and `RATELIMIT_USE_CACHE`.
- The read-only reporting API is disabled by default. Enable it with `REPORTING_API_ENABLED=True`, protect it with `REPORTING_API_SHARED_SECRET`, and keep it behind internal network controls. Its snapshot responses cache for `REPORTING_API_CACHE_TTL_SECONDS` seconds, default `21600`.
- `RATELIMIT_FAIL_OPEN=True` is the default so rate-limiting degrades gracefully if there are cache issues.
- Settings-backed knobs include `LOGIN_RATE_LIMIT`, `USER_BULK_ACTION_RATE_LIMIT`, `USER_MUTATION_RATE_LIMIT`, `ITEM_MUTATION_RATE_LIMIT`, `RECEIVING_MUTATION_RATE_LIMIT`, `USER_PASSWORD_RESET_RATE_LIMIT`, `PASSWORD_CHANGE_RATE_LIMIT`, `PUSKESMAS_RECEIPT_CONFIRMATION_MUTATION_RATE_LIMIT`, `PUSKESMAS_CONSUMPTION_MUTATION_RATE_LIMIT`, `PROCUREMENT_MUTATION_RATE_LIMIT`, and `LPLPO_IMPORT_RATE_LIMIT`; legacy `PUSKESMAS_SBBK_MUTATION_RATE_LIMIT` remains accepted as a compatibility fallback.
- Receipt-confirmation throttling is mutation-only: create/edit/delete saves are POST-limited, while the create-form distribution preview uses non-mutating `GET` and must not consume that quota.
- Throttled requests must continue through the centralized error pipeline and render as HTTP `429`.
- `@user_mutation_ratelimit` covers user create, update, toggle-active, and delete.
- `@item_mutation_ratelimit` covers item catalog lookup POST mutations plus receiving and procurement quick-create lookup POST mutations.
- `@receiving_mutation_ratelimit` covers regular receiving correction and cancellation POST mutations.
- `django-auditlog` records database-backed create/update/delete history for selected critical models; its initial webview is Django Admin at `/admin/` through the auditlog `LogEntry` admin, and no custom IMS audit-log sidebar page exists yet.
- Auditlog is signal-driven and does not automatically cover `bulk_create`, `bulk_update`, or `QuerySet.update()` paths. Keep explicit workflow logs or tests for critical bulk operations where row-level audit history is required.
- User bulk activate/deactivate intentionally uses locked per-row `save(update_fields=["is_active"])` calls so account-status changes produce audit entries.

## Development Commands

Setup/run: `docker compose up -d`, `cd backend`, `python manage.py migrate`, `python manage.py runserver`, `python manage.py app_version`.

Windows test helper: `.\scripts\run-django-test.ps1 -Target apps.items` and `.\scripts\run-django-test.ps1 -Target apps.core.tests -KeepDb`.

Playwright multi-role helper from repo root: `Copy-Item .env.playwright.local.example .env.playwright.local`, `npm install`, `npm run playwright:bootstrap`, and `npm run playwright:open`.

Use existing local role accounts for all six app roles in `.env.playwright.local`. The helper stores per-role Chromium profiles under `.playwright-profiles/`; rebuild them with `npm run playwright:refresh-auth` when credentials or sessions change.

## URL Routing Convention

All URL patterns must end with a trailing slash (`/`) to prevent 301 redirects caused by Django's `APPEND_SLASH` middleware. In `urls.py`, every `path()` must end with `/`, including dynamic paths like `path("<int:pk>/", views.detail, name="detail")`.

In tests, use `reverse()` when possible or ensure hardcoded URLs have trailing slashes. In templates, always use `{% url %}` instead of hardcoded app paths. `APPEND_SLASH = True` is explicitly set in `backend/config/settings.py`.

URL consistency tests in `apps.core.tests.test_url_consistency` verify URL patterns and hardcoded test URLs. Run with `.\scripts\run-django-test.ps1 -Target apps.core.tests.test_url_consistency`.

## Documentation And Quality

When code changes affect schema, routes, permissions, settings, or scripts, update impacted docs in the same PR: `README.md`, `AGENTS.md`, `SYSTEM_MODEL.md`, `docs/developer_guide.md` for setup/testing/release/documentation guidance, and `backend/seed/README.md` if CSV schema/semantics changed.

Before opening a PR, verify documented routes exist in URLconfs, model/table names match current models, env vars exist in `.env.example` or settings usage, security behavior mirrors `backend/config/settings.py`, and CSV column docs match actual import resources/forms/admin parser logic.

Use Context7 as primary guidance for third-party best practices. Current reference library IDs: Django `/django/django`, django-import-export `/websites/django-import-export_readthedocs_io_en`, django-axes `/jazzband/django-axes`, and django-auditlog `/jazzband/django-auditlog`.

Keep `AUTH_USER_MODEL` explicitly configured, `SECRET_KEY` environment-driven, `DEBUG=False` production hardening documented, import workflow docs aligned with django-import-export dry-run/confirm semantics, axes backend and middleware docs aligned with configuration, WhiteNoise middleware and `STORAGES["staticfiles"]` docs accurate, and sensitive POST throttling plus centralized `429` behavior synchronized with settings.
