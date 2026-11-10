# AGENTS.md - Healthcare IMS

Django healthcare inventory system for internal government-health staff. Engineering language is English-first; product-facing labels are mostly Indonesian.

## Scope And Required Reading

- This file applies repository-wide. Before changing an app, read `backend/apps/<app_name>/AGENTS.md`; it owns detailed workflow behavior. For cross-app work, read every affected app's guide.
- Start with targeted file inspection. Use Graphify only when unfamiliar code relationships, dependencies, call chains, architecture, or refactoring require it, or direct searches are insufficient. Prefer targeted queries, reuse context, and stop once sufficient evidence is available; skip it for simple localized work.
- Code is authoritative when documentation conflicts; correct affected documentation in the same change. Do not invent production details or claim unverified test results.

## Sources Of Truth

| Concern | Source |
| --- | --- |
| Schema | `backend/apps/*/models.py` |
| Routes | `backend/config/urls.py`, `backend/apps/*/urls.py` |
| Django permissions and module scopes | `backend/apps/core/decorators.py`, `backend/apps/users/access.py` |
| Runtime and security settings | `backend/config/settings.py` |
| Dependency versions | `backend/requirements.txt`, `package.json`, lockfiles |
| App version | `VERSION`, `backend/apps/core/versioning.py` |
| CSV behavior | Owning app's admin/parser/resource code; `backend/seed/README.md` |
| Operational commands | `scripts/`; `docs/developer_guide.md` |

The Django project is under `backend/`; auth model is `apps.users.User`. PostgreSQL is the database; Redis is optional with LocMemCache fallback. UI is server-rendered Django, including mobile/PWA; do not claim React production paths or a general-purpose REST API.

## App Guidance

Guides live at `backend/apps/<app>/AGENTS.md`:

| Area | App guides |
| --- | --- |
| Shared settings, numbering, errors, throttling | `core` |
| Accounts, module scopes, Acting Kepala, audit | `users` |
| Catalog, stock, opening balance | `items`, `stock` |
| Inbound | `procurement`, `receiving` |
| Outbound | `allocation`, `distribution`, `recall`, `expired` |
| Physical counting | `stock_opname` |
| Facility operations and reporting | `puskesmas`, `lplpo`, `reports` |
| Mobile/PWA | `mobile` |

## Shared Safety Contracts

### Permissions And Audit

- Django permissions (`has_perm`) and module-scope fallback (`ModuleAccess`, `@perm_required`) are separate layers. Scopes: `NONE`, `VIEW`, `OPERATE`, `APPROVE`, `MANAGE`. Use the terms "Django permissions" and "module scope" consistently.
- Denials raise `PermissionDenied` for centralized `handler403` rendering.
- Role-gated checkpoints stay role-gated despite elevated module scope. Acting Kepala is the documented workflow-specific exception; consult `users` and the owning app guides.
- Non-superuser Puskesmas/LPLPO operations are facility-isolated. Puskesmas reports require `puskesmas_reports`; only explicit eligible-staff selection/aggregation capabilities widen report scope. Generic report/approval access grants no facility bypass.
- Delegate eligibility and optional active Puskesmas links for `ADMIN_UMUM`/`GUDANG` follow `users/AGENTS.md`; role `PUSKESMAS` is never eligible. Targets referenced by `AuthorityExercise` must not be hard-deleted.

### Stock And Workflow Integrity

- `stock.Transaction` is the append-only stock ledger. Never mutate historical transactions or substitute auditlog for movement reporting.
- Change stock only at explicit workflow checkpoints, inside `transaction.atomic()` with appropriate row locks, never arbitrary model saves.
- Availability is `Stock.available_quantity` (`quantity - reserved`). Dated batches use FEFO; `expiry_date=NULL` sorts last. Blank expiry is valid only when `Item.requires_expiry_date` permits it.
- Preserve item, location, batch, funding source, and `source_document_number` layers on both `Stock` and `Transaction`. Never average prices across source-document layers. Receiving/opening balance serialize source numbers through `SourceDocumentNumberClaim`.
- Puskesmas `Stok Akhir Digital` is a calculated report balance. Preserve baseline/adjustment coverage across HTML, print, and Excel; missing baselines exclude facilities rather than representing zero stock. See `puskesmas/AGENTS.md`.
- Race-prone actions lock with `select_for_update()` inside `transaction.atomic()`, then re-check live status.
- Official non-Puskesmas numbers use the centralized `core` issue ledger. Issue the number atomically with its consuming checkpoint. Issued values and business-date/scope binding are immutable and never reused, including after VOID; unnumbered drafts stay outside the ledger.
- Historical duplicate or stepped-back numbered documents retain their number and audit meaning. Never silently renumber history.
- Use the owning workflow's delete/cancel/void service. Never hard-delete a parent if that erases workflow audit or an issued-number reservation.
- Cross-app flow and mutation checkpoints are documented in `SYSTEM_MODEL.md`. Allocation matrix validation and child staff/signature rules belong to `allocation/AGENTS.md`; receiving/consumption-to-LPLPO synchronization belongs to the `puskesmas` and `lplpo` guides.

## Implementation Guardrails

- Keep changes atomic; verify each behavior before expanding scope. Scale tests to risk and blast radius.
- Prefer Django ORM APIs; document why raw SQL is necessary. Use `select_related`/`prefetch_related` for relationship-heavy reads and transactions/row locks for multi-row writes.
- Use Python logging and specific exceptions; do not swallow failures.
- Do not edit already-applied migrations unless explicitly requested and safe for the current branch.
- Reject numeric NaN/Infinity, null bytes, out-of-range years (outside `1000..9999`), and naive datetimes. Strip, NFC-normalize, and length-check user-facing/comparable strings.
- Validate foreign keys and choices against allowed querysets/choices. Validate upload MIME, extension, size, and paths; reject traversal and absolute paths.
- Before adding a constraint existing rows may violate: audit and record the count, add a data-fix migration, then add the constraint in a separate migration.
- All URL patterns end with `/`. Tests use `reverse()`; templates use `{% url %}`. Run `apps.core.tests.test_url_consistency` for routing changes.

## UI And Verification

- Read root `DESIGN.md` for Tailwind migration work. If rendered content, controls, actions, or behavior conflict with the documented contract beyond the planned styling change, ask the user before editing that UI.
- Use bound Django fields with `tailwind_field`/`tailwind_widget` and project-owned Tailwind components. Preserve JavaScript hooks and the desktop Bootstrap behavior bridge; do not reintroduce Bootstrap CSS or Crispy packages.
- Desktop uses `base_tailwind.html` (`base.html` is a compatibility alias); mobile uses independent `mobile/base.html` and `mobile.js` without Bootstrap JavaScript. Keep native Django Admin styling isolated. Print rules live in `backend/static_src/css/print.css`.
- Setup: follow `docs/developer_guide.md#persiapan-lokal`; run migrations before serving. User CSV previews require `cleanup_user_imports` every 15 minutes; see `users/AGENTS.md`.
- Windows Django tests: `.\scripts\run-django-test.ps1 -Target <test.path>`; add `-KeepDb` when appropriate.
- CSS: use Bun 1.3.14 and Node.js 24; `bun ci`, `bun run css:build`, then `bun run css:check`. Commit generated `backend/static/css/app.tailwind.css`; entry point is `backend/static_src/css/app.css`. Bun/Node are development and CI tools, not Django production runtime dependencies.
- Playwright: follow `docs/developer_guide.md#playwright-lokal-untuk-verifikasi-multi-role`. Use existing local accounts from `.env.playwright.local.example`; bootstrap/open profiles and refresh auth after credential/session changes.
- Presentation details and verification history: `docs/css-refactoring/DESIGN_SYSTEM.md`, `MIGRATION_LEDGER.md`, and `MIGRATION_CLOSEOUT.md` in that directory. Do not copy surface inventories or migration history into root guidance.

## Documentation Maintenance

- Keep root README focused on orientation and links, and root AGENTS under 150 lines with shared instructions. Put app-specific rules in the owning app guide.
- Update only affected documentation: `SYSTEM_MODEL.md` for schema/routes/permissions/workflow contracts; `docs/application_reference.md` for functional descriptions; `docs/developer_guide.md` for setup/tooling/operations; `backend/seed/README.md` for import formats. Update root entry points when their summaries or links change.
- Before a PR, verify documented routes, models, environment keys, security behavior, and CSV columns against code. A structural docs move does not establish that every existing behavior claim was reverified.
- Use Context7 as the primary third-party reference: Django `/django/django`, import-export `/websites/django-import-export_readthedocs_io_en`, Axes `/jazzband/django-axes`, auditlog `/jazzband/django-auditlog`.
