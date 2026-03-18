# AGENTS.md - Healthcare IMS

Onboarding guide for coding agents working in this repository.

## Purpose

This project is a Django-based healthcare inventory system used by internal government-health staff. The codebase language is English-first for engineering consistency, while product-facing labels are mostly Indonesian.

## Environment Snapshot

| Item | Value |
| --- | --- |
| Python | 3.13+ |
| Django | 6.0.2 |
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
|- requirements_draft/
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

- `core`: shared abstractions and dashboard
- `users`: custom user and `ModuleAccess` scope model
- `items`: master data and item catalog
- `stock`: stock entries, immutable transactions, stock transfer
- `receiving`: regular and planned receiving flows, plus custom CSV import endpoint in admin
- `distribution`: outbound distribution workflow
- `recall`: supplier return workflow
- `expired`: expired/disposal workflow and alerts page
- `stock_opname`: physical counting workflow
- `reports`: currently lightweight placeholder

## Permissions Model

There are two permission layers:

1. Django `has_perm` checks (groups/permissions)
2. Module scope fallback (`ModuleAccess`) used by `@perm_required`

`@perm_required` in `backend/apps/core/decorators.py` allows access if either layer grants permission. Keep this hybrid model in mind before changing authorization logic.

Module scopes:

- `NONE`, `VIEW`, `OPERATE`, `APPROVE`, `MANAGE`

Default scopes per role are defined in `backend/apps/users/access.py`.

## Workflow and Data Mutation Rules

- Never mutate historical `Transaction` rows; append-only behavior is expected.
- Stock-changing checkpoints happen during workflow actions (verify/prepare/distribute/complete depending on module), not arbitrary model saves.
- Stock transfer completion writes paired `OUT` and `IN` transactions.
- Receiving admin CSV import writes `Receiving`, `ReceivingItem`, updates/creates `Stock`, and writes `Transaction(IN)`.

## Documentation Maintenance Contract

When code changes affect schema, routes, permissions, settings, or scripts, update all impacted docs in the same PR:

- `README.md`
- `AGENTS.md`
- `SYSTEM_MODEL.md`
- Relevant files in `requirements_draft/`
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
