# AGENTS.md - Healthcare IMS

Onboarding guide for coding agents working in this repository.

## Purpose

This project is a Django-based healthcare inventory system used by internal government-health staff. The codebase language is English-first for engineering consistency, while product-facing labels are mostly Indonesian.

## Environment Snapshot

| Item | Value |
| --- | --- |
| Python | 3.13+ |
| Django | 6.0.4 |
| Database | PostgreSQL 16 |
| Cache/Broker | Redis 7 |
| UI | Django templates + Bootstrap 5 |
| Auth model | `apps.users.User` |
| Settings | `backend/config/settings.py` |
| Root URLs | `backend/config/urls.py` |

## Repository Map

```text
.
|- README.md
|- AGENTS.md
|- SYSTEM_MODEL.md
|- docker-compose.yml
|- .env.example
|- backend/
|  |- manage.py
|  |- requirements.txt
|  |- config/
|  |- apps/
|  |- templates/
|  |- static/
|  |- seed/
|  `- tests/
`- scripts/
```

## Source of Truth Rules

- Schema truth: `backend/apps/*/models.py`
- Route truth: `backend/config/urls.py` + `backend/apps/*/urls.py`
- Auth/permission truth: `backend/apps/core/decorators.py`, `backend/apps/users/access.py`
- Security/config truth: `backend/config/settings.py`
- App version truth: root `VERSION` and `backend/apps/core/versioning.py`
- Operational script truth: `scripts/`
- CSV import behavior truth: `backend/apps/*/admin.py` and resource classes

If documentation conflicts with code, code is authoritative until docs are corrected.

## Active Django Apps

- `core`: shared abstractions, dashboard, dynamic system settings (login platform label, logo/headers, and configurable distribution numbering templates), placeholder administration history pages for receiving and distribution archives, plus centralized `400/403/404/500` handlers and a `/maintenance/` `503` view
- `users`: custom user and `ModuleAccess` scope model
- `items`: master data and item catalog; items may be flagged as program item `[P]` (`is_program_item`) or essential `[E]` (`is_essential`)
- `stock`: stock entries, immutable transactions, stock card, location-based stock search, and stock transfer
- `receiving`: regular and planned receiving flows, custom CSV import endpoint in admin, quick-create lookup endpoints, and custom `ReceivingTypeOption` support
- `distribution`: outbound distribution workflow, step-back/reset actions before distribution, issued batch/value snapshots on `DistributionItem`, and special-request numbering UI that preloads the next suggested number while requiring confirmation before manual override. The user-facing manual create path is `special_request_create`; keep the generic `distribution_create` route reserved for internal or compatibility flows tied to broader distribution orchestration.
- `allocation`: pre-distribution planning and orchestration. Draft→Submitted→Approved lifecycle auto-generates one `Distribution` per facility on approval. Approved allocations may be stepped back to Submitted by approvers, which deletes the auto-generated child distributions so approval can be re-run cleanly. Allocation no longer stores a header-level funding source; item batch selection can span all available stock sources. Stock deduction deferred to delivery confirmation per distribution. Module is active and gated by `ModuleAccess` scopes like all other modules.
- `recall`: supplier return workflow
- `expired`: expired/disposal workflow and alerts page
- `stock_opname`: physical counting workflow
- `puskesmas`: ad-hoc requests from Puskesmas
- `lplpo`: monthly reporting and stock requests from Puskesmas
- `reports`: report index with rekap, hibah receiving, procurement, expiry, outbound reporting views, and document numbering history for LPLPO/Special Request distributions

## Permissions Model

There are two permission layers:

1. Django `has_perm` checks (groups/permissions)
2. Module scope fallback (`ModuleAccess`) used by `@perm_required`

`@perm_required` in `backend/apps/core/decorators.py` allows access if either layer grants permission. Keep this hybrid model in mind before changing authorization logic.

Permission denials should raise `PermissionDenied` so requests flow through the centralized `handler403` page instead of returning raw HTML fragments.

Module scopes:

- `NONE`, `VIEW`, `OPERATE`, `APPROVE`, `MANAGE`

Default scopes per role are defined in `backend/apps/users/access.py`.

### Specialized Roles (e.g. OPERATOR PUSKESMAS)

- `OPERATOR PUSKESMAS` role uses `facility` matching. Views in `puskesmas` and `lplpo` enforce strict facility isolation so that operators from one facility cannot read/write another facility's documents.

## Workflow and Data Mutation Rules

- Never mutate historical `Transaction` rows; append-only behavior is expected.
- Stock-changing checkpoints happen during workflow actions (verify/prepare/distribute/complete depending on module), not arbitrary model saves.
- Stock transfer completion writes paired `OUT` and `IN` transactions.
- Receiving admin CSV import writes `Receiving`, `ReceivingItem`, updates/creates `Stock`, and writes `Transaction(IN)`.
- Receiving supports built-in and custom type codes; UI labels for non-built-in types are resolved from `ReceivingTypeOption`.
- `Distribution(distribution_type=LPLPO)` is system-generated from `lplpo_finalize`; do not expose it as a manual distribution type in the generic distribution create/edit flow.
- Distribution numbering templates for `LPLPO` and `SPECIAL_REQUEST` are user-configurable through `SystemSettings`; supported placeholders are `{seq}` and `{year}` and sequence counters remain scoped per distribution type and matched against the active template.
- `Distribution(distribution_type=ALLOCATION)` is system-generated from `allocation` approval; one per facility, starts in `VERIFIED` status, quantities are locked and cannot be edited.
- Allocation approval atomically creates `Distribution` + `DistributionItem` records for each facility. Stepping an allocation back from `APPROVED` to `SUBMITTED` deletes those child distributions so they can be regenerated on the next approval. Stock deduction is deferred to per-distribution delivery confirmation.
- Allocation auto-transitions to `PARTIALLY_FULFILLED` when any child distribution is delivered, and `FULFILLED` when all are delivered.
- Availability checks across distribution, recall, expired, transfer, and several selectors use `Stock.available_quantity` (`quantity - reserved`), but current workflows do not automatically increment or decrement `reserved` during distribution processing.

## Documentation Maintenance Contract

When code changes affect schema, routes, permissions, settings, or scripts, update all impacted docs in the same PR:

- `README.md`
- `AGENTS.md`
- `SYSTEM_MODEL.md`
- `docs/developer_guide.md` when setup, testing, release, or documentation process guidance changes
- `backend/seed/README.md` (if CSV schema/semantics changed)

## Context7 Reference Policy

Use Context7 as primary guidance for third-party best practices. Current reference library IDs:

- Django: `/django/django`
- django-import-export: `/websites/django-import-export_readthedocs_io_en`
- django-axes: `/jazzband/django-axes`

Apply these principles:

- Keep `AUTH_USER_MODEL` explicitly configured before relying on auth migrations.
- Keep `SECRET_KEY` environment-driven.
- Keep `DEBUG=False` production hardening documented and synchronized with settings.
- Keep import workflow docs aligned with dry-run/confirm semantics from django-import-export.
- Keep axes backend ordering and middleware placement documented exactly as configured.

## Development Commands

```bash
docker compose up -d
cd backend
python manage.py migrate
python manage.py runserver
python manage.py app_version
```

Windows test helper:

```powershell
.\scripts\run-django-test.ps1 -Target apps.items
.\scripts\run-django-test.ps1 -Target apps.core.tests -KeepDb
```

## Quality Checklist for Agent PRs

Before opening a PR, verify:

- Routes documented in markdown exist in URLconfs.
- All model/table names in docs match current models.
- Env vars in docs exist in `.env.example` or settings usage.
- Security behavior in docs mirrors `backend/config/settings.py`.
- CSV column docs match actual import resources/forms/admin parser logic.

## Notes

- Do not claim REST API/React production paths as implemented; those are planned.
- Keep terminology consistent: use "module scope" for `ModuleAccess` and "Django permissions" for `has_perm` checks.
