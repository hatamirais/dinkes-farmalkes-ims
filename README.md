# Healthcare Inventory Management System

Web-based inventory management for medicines and medical equipment at the Dinas Kesehatan level. The system replaces spreadsheet workflows with structured document flows, role-aware access control, and an immutable stock movement audit trail.

## Tech Stack

| Layer | Technology |
| --- | --- |
| Language | Python 3.13+ |
| Framework | Django 6.0.2 |
| Database | PostgreSQL 16 |
| Cache/Broker | Redis 7 |
| UI | Django Templates + Bootstrap 5 |
| Forms | django-crispy-forms + crispy-bootstrap5 |
| Data Import | django-import-export |
| Security | django-axes |

## Key Capabilities

- Item master and lookup management (`Unit`, `Category`, `Program`, `FundingSource`, `Location`, `Supplier`, `Facility`)
- Batch-level stock with FEFO support and funding-source traceability
- End-to-end workflows for receiving, distribution, recall, expired disposal, stock transfer, and stock opname
- Immutable `Transaction` log for all stock movement (`IN`, `OUT`, `ADJUST`, `RETURN`)
- User access control via Django permissions and per-user `ModuleAccess` scopes
- CSV import support via Django Admin, including dedicated Receiving CSV import endpoint

## Current Modules

### Implemented and active

- `items`: item/lookup CRUD + list filtering + AJAX quick-create lookup endpoints
- `stock`: stock list, transaction list, stock card, and stock transfer flow
- `receiving`: regular receiving and planned receiving workflow
- `distribution`: request/verification/preparation/distribution workflow
- `recall`: draft to complete supplier return flow
- `expired`: draft to disposed expired-item flow + expiry alerts page
- `stock_opname`: physical count workflow and discrepancy report printing
- `users`: user management and module-scope assignment

### Placeholder

- `reports`: index route is available, model layer is still placeholder (`backend/apps/reports/models.py`)

## Workflow Snapshot

- Receiving (planned): `DRAFT -> SUBMITTED -> APPROVED -> PARTIAL/RECEIVED -> CLOSED`
- Receiving (regular/imported): commonly persisted as `VERIFIED` after posting
- Distribution: `DRAFT -> SUBMITTED -> VERIFIED -> PREPARED -> DISTRIBUTED` (or `REJECTED`)
- Recall: `DRAFT -> SUBMITTED -> VERIFIED -> COMPLETED`
- Expired: `DRAFT -> SUBMITTED -> VERIFIED -> DISPOSED`
- Stock transfer: `DRAFT -> COMPLETED`
- Stock opname: `DRAFT -> IN_PROGRESS -> COMPLETED`

## Data Model (At a Glance)

- Core inventory tables: `items`, `stock`, `transactions`
- Document headers: `receivings`, `distributions`, `recalls`, `expired_docs`, `stock_transfers`, `stock_opnames`
- Document lines: `receiving_items`, `receiving_order_items`, `distribution_items`, `recall_items`, `expired_items`, `stock_transfer_items`, `stock_opname_items`
- Authorization tables: `users`, `user_module_accesses`

For canonical schema details, see `SYSTEM_MODEL.md`.

## Repository Layout

```text
Healthcare-Inventory-Management-System/
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

## Getting Started

### 1) Clone

```bash
git clone git@github.com:ahliweb/Healthcare-Inventory-Management-System.git
cd Healthcare-Inventory-Management-System
```

### 2) Configure environment

```bash
cp .env.example .env
```

Set at least:

- `DJANGO_SECRET_KEY`
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
- `ALLOWED_HOSTS`

### 3) Start infrastructure

```bash
docker compose up -d
```

### 4) Install Python dependencies

```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
pip install -r backend/requirements.txt
```

On Windows PowerShell:

```powershell
venv\Scripts\activate
pip install -r backend/requirements.txt
```

### 5) Run migrations and create admin user

```bash
cd backend
python manage.py migrate
python manage.py createsuperuser
```

### 6) Run development server

```bash
python manage.py runserver
```

App URL: `http://localhost:8000`
Admin URL: `http://localhost:8000/admin/`

## Testing

- Recommended on Windows: `scripts/run-django-test.ps1`
- Example:

```powershell
.\scripts\run-django-test.ps1 -Target apps.items
```

The script changes into `backend/`, optionally activates `venv`, and checks `crispy_forms` before running tests.

## Versioning

This repository now uses semantic versioning with `MAJOR.MINOR.PATCH` in the root `VERSION` file.

- Show current version: `python manage.py app_version`
- Bump patch version: `python manage.py app_version --patch`
- Bump minor version: `python manage.py app_version --minor`
- Bump major version: `python manage.py app_version --major`
- Set explicit version: `python manage.py app_version --set 2.0.0`

The active app version is loaded from `VERSION` at startup and shown in the authenticated UI header.

### Automatic release on version bump

When `VERSION` changes on `main`, GitHub Actions runs `.github/workflows/release-on-version-change.yml` to:

- verify `python manage.py app_version` matches the `VERSION` file,
- run `python manage.py test apps.core`,
- create git tag `v<version>` (if it does not already exist),
- create a GitHub Release for that tag.

## Seed and Import

- Seed templates live in `backend/seed/`
- Import sequence: `units -> categories -> funding_sources -> programs -> locations -> suppliers -> facilities -> items -> receiving`
- For initial stock, prefer `receiving.csv` via the custom Receiving Admin import (`/admin/receiving/receiving/import-csv/`) so stock and `Transaction(IN)` records are created together.

Details: `backend/seed/README.md` and `requirements_draft/README.md`.

## Security Notes

- Brute-force lockout with `django-axes` (`AXES_FAILURE_LIMIT=5`, `AXES_COOLOFF_TIME=0.5`)
- `axes.backends.AxesStandaloneBackend` is configured before Django `ModelBackend`
- Session and CSRF cookies use `HttpOnly` and `SameSite=Lax`
- Production hardening is enabled when `DEBUG=False` (HSTS, secure cookies, frame deny, referrer policy)

## Documentation Index

- `AGENTS.md`: coding-agent orientation and conventions
- `CHANGELOG.md`: release notes and version history
- `SYSTEM_MODEL.md`: canonical schema and workflow model map
- `backend/seed/README.md`: CSV seed column specification
- `requirements_draft/system_design_renew.md`: functional and architecture design narrative
- `requirements_draft/erd.md`: ERD reference
- `requirements_draft/infrastructure_plan.md`: infrastructure and deployment plan
- `requirements_draft/README.md`: import workflow and migration notes

## Documentation Governance Plan

Use this cycle to keep all docs aligned with code and best practices.

1. Inventory all documentation files in repository root, `requirements_draft/`, and `backend/seed/`.
2. Map each statement in docs to source-of-truth files:
   - models -> `backend/apps/*/models.py`
   - routes -> `backend/config/urls.py` and `backend/apps/*/urls.py`
   - security/settings -> `backend/config/settings.py`
   - scripts -> `scripts/`
3. Validate third-party guidance against Context7 primary references:
   - `/django/django`
   - `/websites/django-import-export_readthedocs_io_en`
   - `/jazzband/django-axes`
4. Flag drift by severity:
   - Critical: wrong schema, workflow, auth, or security behavior
   - Major: outdated commands/routes/env vars
   - Minor: wording/format/terminology inconsistency
5. Update canonical docs first (`SYSTEM_MODEL.md`, `README.md`, `AGENTS.md`), then dependent drafts.
6. Add or update "Last verified" metadata and include verification source paths.
7. Run doc QA checklist before merge:
   - no route mismatch
   - no model/table mismatch
   - all commands executable as written
   - all environment keys exist
8. Enforce ongoing maintenance by requiring doc updates in PRs that change models, routes, settings, or scripts.

## License

MIT. See `LICENSE`.
