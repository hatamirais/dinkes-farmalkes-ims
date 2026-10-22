# AGENTS.md - Healthcare IMS

Onboarding guide for coding agents working in this repository.

This project is a Django-based healthcare inventory system used by internal government-health staff. Engineering language is English-first; product-facing labels are mostly Indonesian.

Rules in this file apply repository-wide. Before changing an app, also read `backend/apps/<app_name>/AGENTS.md` when present; the app file owns detailed workflow behavior while this file owns shared contracts.

## Environment Snapshot

| Item | Value |
| --- | --- |
| Python | 3.13+ |
| Django | 6.0.8 |
| Database | PostgreSQL 16 |
| Cache/Broker | Redis when `REDIS_URL` is set; otherwise In-Memory / LocMemCache |
| UI | Django templates; Tailwind CSS on desktop dashboards, Item List, four stock read-only screens, the Puskesmas stock report, receiving lists/details, authentication, and centralized errors; Bootstrap 5 on remaining pages; locally vendored Flatpickr 4.6.13 on the delegation form; server-rendered mobile/PWA surface |
| Static serving | WhiteNoise for collected static assets |
| Auth model | `apps.users.User` |
| Object audit | django-auditlog |
| Settings | `backend/config/settings.py` |
| Root URLs | `backend/config/urls.py` |

## Repository And Sources Of Truth

Root files include `README.md`, `SYSTEM_MODEL.md`, `docker-compose.yml`, `.env.example`, `VERSION`, `backend/`, and `scripts/`. The Django project is under `backend/`.

- Schema: `backend/apps/*/models.py`.
- Routes: `backend/config/urls.py` and `backend/apps/*/urls.py`.
- Auth and permission behavior: `backend/apps/core/decorators.py` and `backend/apps/users/access.py`.
- Security and runtime configuration: `backend/config/settings.py`.
- App version: `VERSION` and `backend/apps/core/versioning.py`.
- CSV behavior: the owning app's admin/parser/resource code.
- Operational scripts: `scripts/`.

Code is authoritative when documentation conflicts with implementation; correct the documentation in the same change.

## App Guidance

Detailed rules live beside the owning code:

| Area | Guide |
| --- | --- |
| Shared settings, numbering, errors, throttling | `backend/apps/core/AGENTS.md` |
| Users, module scopes, Acting Kepala, audit | `backend/apps/users/AGENTS.md` |
| Item catalog | `backend/apps/items/AGENTS.md` |
| Stock and opening balance | `backend/apps/stock/AGENTS.md` |
| Receiving | `backend/apps/receiving/AGENTS.md` |
| Procurement | `backend/apps/procurement/AGENTS.md` |
| Distribution | `backend/apps/distribution/AGENTS.md` |
| Allocation | `backend/apps/allocation/AGENTS.md` |
| Recall | `backend/apps/recall/AGENTS.md` |
| Expired/disposal | `backend/apps/expired/AGENTS.md` |
| Stock opname | `backend/apps/stock_opname/AGENTS.md` |
| Puskesmas | `backend/apps/puskesmas/AGENTS.md` |
| LPLPO | `backend/apps/lplpo/AGENTS.md` |
| Reports | `backend/apps/reports/AGENTS.md` |
| Mobile/PWA | `backend/apps/mobile/AGENTS.md` |

## Graphify Usage Policy

Use Graphify selectively to improve codebase understanding while minimizing unnecessary token consumption.

**Use Graphify when:**

- Exploring unfamiliar parts of the codebase.
- Tracing dependencies, imports, references, or call chains.
- Understanding relationships between modules, classes, and functions.
- Planning architectural changes or multi-file refactoring.
- Locating implementations when direct searches are insufficient.

**Avoid Graphify when:**

- Making simple, localized edits.
- The relevant files and functions are already known.
- Fixing straightforward bugs with clear locations.
- Answering questions that can be resolved through direct file inspection.

**Efficiency rules:**

- Prefer targeted Graphify queries over broad exploration.
- Do not repeatedly read `SKILL.md` unless necessary.
- Reuse previously discovered codebase context when still valid.
- Minimize unnecessary tool calls and verbose output.
- Stop exploring once sufficient context is available.
- Never sacrifice correctness just to reduce token usage.

**Default strategy:** Start with targeted file inspection. Use Graphify when understanding code relationships would materially improve accuracy or efficiency.

## Cross-App Contracts

### Permissions And Errors

- There are two permission layers: Django permissions through `has_perm` and module-scope fallback through `ModuleAccess` and `@perm_required`.
- Module scopes are `NONE`, `VIEW`, `OPERATE`, `APPROVE`, and `MANAGE`. Use the terms "Django permissions" and "module scope" consistently.
- Permission denials must raise `PermissionDenied` so the centralized `handler403` renders the response.
- Role-gated checkpoints remain role-gated even when a user has an elevated module scope. Acting Kepala authority is the only documented workflow-specific exception; see the owning app and `users/AGENTS.md`.
- Non-superuser Puskesmas/LPLPO access is facility-isolated. Never infer that report or approval access grants a facility bypass.
- `ADMIN_UMUM` and `GUDANG` may carry an optional active Puskesmas `facility` solely to scope Puskesmas/LPLPO delegation; other facility types are invalid for this link, and this does not make role `PUSKESMAS` eligible for delegation. Workflow targets referenced by `AuthorityExercise` are protected from hard deletion.

### Stock And Ledger

- `stock.Transaction` is the append-only source of truth for stock movement. Never mutate historical transaction rows or replace stock movement reporting with auditlog entries.
- Stock changes occur only at explicit workflow checkpoints, inside transactions with appropriate row locks; never mutate stock from arbitrary model saves.
- Availability is `Stock.available_quantity` (`quantity - reserved`). Dated batch selection is FEFO, with `expiry_date=NULL` last.
- Stock is layered by item, location, batch, funding source, and `source_document_number`. Do not average prices across source-document layers.
- Every stock-changing workflow must preserve the source layer on both `Stock` and `Transaction`. Receiving and opening balance serialize source numbers through `SourceDocumentNumberClaim`.
- Imports and forms enforce `Item.requires_expiry_date`; blank expiry is valid only for non-expiring catalog items.

### Workflow Concurrency, Numbering, And Deletion

- Race-prone workflow actions use `transaction.atomic()` plus `select_for_update()`, then re-check live status after locking.
- Official non-Puskesmas document numbers use the centralized `core` issue ledger. Issued values and their business-date/scope binding are immutable and never reused, including after voiding.
- Number issuance and the workflow checkpoint that consumes it must be atomic. Unnumbered drafts stay outside the issue ledger.
- Historical duplicate or stepped-back numbered documents retain their number and audit meaning; never silently renumber history.
- Parent workflow documents must not be hard-deleted when doing so would erase workflow audit or an issued-number reservation. Use the owning workflow's delete/cancel/void service.

### Main Data Flow

- Inbound: approved procurement contract/amendment -> linked planned receiving -> receiving execution/import -> `Stock` plus `Transaction(IN)`.
- Opening balance: `OpeningBalanceImport` -> source-layered `Stock` plus `Transaction(IN, reference_type=INITIAL_IMPORT)`.
- Outbound: allocation, LPLPO, or standalone request -> `Distribution` -> reservation at verification -> stock deduction and reservation clearing at final distribution.
- Facility reporting: delivered distribution -> confirmed Puskesmas receipt -> editable same-month LPLPO receiving/price sync; detailed consumption -> editable same-month LPLPO usage sync.

## Development Guardrails

- Keep changes atomic and verify each behavioral change before expanding scope.
- Prefer Django ORM APIs. Use raw SQL only when the ORM is insufficient, and document why.
- Use `select_related` / `prefetch_related` for relationship-heavy reads, `select_for_update()` for race-prone writes, and `transaction.atomic()` for multi-row workflow mutations.
- Use crispy-forms / crispy-bootstrap5 and Bootstrap 5 utilities. Document necessary custom CSS exceptions.
- For Tailwind migration work, read root `DESIGN.md` before editing UI. It defines the approved target visual system while the current Bootstrap interface remains live. If the rendered UI's content, controls, actions, or behavior conflict with the documented contract beyond the planned styling change, ask the user before editing that UI.
- Scale tests to risk and blast radius. Use Python logging, raise specific exceptions, and do not swallow failures.
- Do not edit already-applied migrations unless explicitly requested and safe for the current branch state.
- Do not claim React production paths or a general-purpose REST API; the production mobile surface is server-rendered Django.

## Input Validation

- Reject numeric `NaN` and `Infinity`; `Decimal("NaN")` can construct successfully and fail later.
- Strip, NFC-normalize, length-check, and reject null bytes in user-facing or comparable strings.
- Reject years outside `1000..9999`; datetimes must be timezone-aware.
- Validate foreign keys and choices against allowed querysets/choices; never trust client-supplied IDs alone.
- Validate upload MIME and extension server-side, enforce maximum size, and reject traversal or absolute paths.

When adding a constraint that existing rows might violate: audit and record the count, add a data-fix migration, then add the constraint in a separate migration.

## Routing, Testing, And Documentation

- Every URL pattern ends with `/`. Tests should use `reverse()`; templates must use `{% url %}`. Run `apps.core.tests.test_url_consistency` for routing changes.
- Setup/run: `docker compose up -d`, then from `backend/`: `python manage.py migrate`, `python manage.py runserver`, `python manage.py app_version`.
- Windows tests: `.\scripts\run-django-test.ps1 -Target <test.path>`; add `-KeepDb` when appropriate.
- Frontend tooling: use Bun 1.3.14 from `package.json` and Node.js 24 for the Tailwind CLI; run `bun ci` to install the locked dependencies. Tailwind source is `backend/static_src/css/app.css`; commit the generated `backend/static/css/app.tailwind.css` after `bun run css:build`, and verify it with `bun run css:check`. The generated CSS is loaded by `base_tailwind.html` for desktop dashboards, the Item List, the desktop stock list/cards/transaction history and Puskesmas stock report, receiving lists/details, and authentication; centralized errors load it directly. `base.html` remains the Bootstrap compatibility path. Bun and Node are for development and CI verification, not the production Django runtime.
- Playwright: copy `.env.playwright.local.example` to `.env.playwright.local`, use the existing local accounts for the seven configured profiles (six roles plus GUDANG2), run `bun run playwright:bootstrap`, then `bun run playwright:open`. Refresh profiles with `bun run playwright:refresh-auth` after credential/session changes. The Playwright browser helpers still use a local Node runtime because persistent Chromium launch hung under Bun 1.3.14 on Windows during this migration.
- Update affected `README.md`, `AGENTS.md`, `SYSTEM_MODEL.md`, `docs/developer_guide.md`, and `backend/seed/README.md` when behavior, setup, schema, routes, permissions, settings, scripts, or import formats change.
- Before a PR, verify documented routes, model names, environment variables, security behavior, and CSV columns against code.
- Use Context7 as the primary third-party reference. Known IDs: Django `/django/django`, django-import-export `/websites/django-import-export_readthedocs_io_en`, django-axes `/jazzband/django-axes`, and django-auditlog `/jazzband/django-auditlog`.
