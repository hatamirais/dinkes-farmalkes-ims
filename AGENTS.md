# AGENTS.md — Healthcare IMS

> Onboarding guide for AI coding agents working on this Django-based Inventory Management System.

## Project Overview

A web-based healthcare inventory management system for tracking medicines and medical equipment at the Dinas Kesehatan (government health department) level. Built with **Django 6.0.2**, **PostgreSQL 16**, **Bootstrap 5**, and **Redis 7**. It replaces Excel-based workflows with role-based stock tracking, FEFO management, and a full audit trail.

## Quick Reference

| Item               | Value                                  |
| ------------------ | -------------------------------------- |
| Language           | Python 3.13+                           |
| Framework          | Django 6.0.2                           |
| Database           | PostgreSQL 16 (Docker)                 |
| Cache              | Redis 7 (Docker)                       |
| Frontend           | Django Templates + Bootstrap 5         |
| Forms              | crispy-forms + crispy-bootstrap5       |
| Auth               | Custom user model (`apps.users.User`)  |
| Settings           | `backend/config/settings.py`           |
| Root URLconf       | `backend/config/urls.py`               |
| Locale / Timezone  | `id` / `Asia/Jakarta`                  |

## Repository Layout

```text
DJANGO-IMS/
├── AGENTS.md                   # ← You are here
├── README.md                   # User-facing readme
├── docker-compose.yml          # PostgreSQL 16 + Redis 7
├── .env.example                # Required env vars template
├── scripts/
│   └── run-django-test.ps1     # Windows test runner (auto-activates venv)
├── requirements_draft/         # Design documents
│   ├── erd.md                  # Entity Relationship Diagram
│   ├── system_design_renew.md  # Full system design
│   ├── infrastructure_plan.md  # Deployment architecture
│   └── README.md               # Seed data column specs
├── backend/                    # ← Django project root
│   ├── manage.py
│   ├── requirements.txt
│   ├── config/                 # Django settings & URL routing
│   │   ├── settings.py
│   │   ├── urls.py
│   │   ├── wsgi.py
│   │   └── asgi.py
│   ├── apps/                   # All Django apps (see below)
│   ├── templates/              # Shared Django HTML templates
│   │   ├── base.html           # Master layout (Bootstrap 5)
│   │   ├── dashboard.html
│   │   └── <app>/              # Per-app templates
│   ├── static/                 # CSS & JS assets
│   ├── seed/                   # CSV seed data for import
│   └── tests/                  # Top-level test dir
└── .agents/                    # Agent config (rules, skills)
```

## Django Apps

All apps live in `backend/apps/`. Each app follows standard Django structure: `models.py`, `views.py`, `urls.py`, `admin.py`, `forms.py`, `tests.py`.

| App | Path | Purpose |
| --- | --- | --- |
| `core` | `apps/core/` | Base/abstract models, dashboard view, shared utilities |
| `users` | `apps/users/` | Custom `User` model with role field; 5 roles (see below) |
| `items` | `apps/items/` | Item master (medicines, equipment) + lookup tables (Unit, Category, Program, FundingSource, Supplier, Facility) |
| `stock` | `apps/stock/` | `Stock` model (batch/lot tracking, FEFO), `Transaction` audit trail |
| `receiving` | `apps/receiving/` | Incoming stock (procurement & grants), regular + planned receiving workflows |
| `distribution` | `apps/distribution/` | Outgoing stock to Puskesmas/facilities, multi-step workflow |
| `recall` | `apps/recall/` | Supplier returns, Draft → Submitted → Verified → Completed |
| `expired` | `apps/expired/` | Expired item disposal, Draft → Submitted → Verified → Disposed |
| `stock_opname` | `apps/stock_opname/` | Physical inventory counting, discrepancy reports |
| `reports` | `apps/reports/` | Reporting module (in progress) |

## URL Routes

All route prefixes are defined in `backend/config/urls.py`:

| URL Prefix | App / View |
| --- | --- |
| `/` | Dashboard (`apps.core`) |
| `/admin/` | Django Admin |
| `/login/` | Auth login |
| `/logout/` | Auth logout |
| `/password/change/` | Password change |
| `/users/` | `apps.users` (User Management) |
| `/items/` | `apps.items` |
| `/stock/` | `apps.stock` |
| `/receiving/` | `apps.receiving` |
| `/distribution/` | `apps.distribution` |
| `/recall/` | `apps.recall` |
| `/expired/` | `apps.expired` |
| `/reports/` | `apps.reports` |
| `/stock-opname/` | `apps.stock_opname` |

## User Roles

The system uses `@perm_required` decorator for permission-based access control via Django groups (managed in Admin). Five roles:

| Role | Access Scope |
| --- | --- |
| **Admin** | Full system access, User Management (view + create/edit/activate/delete), and Admin Panel |
| **Kepala Instalasi** | Approvals, all reports, dashboard, and User Management (view-only) |
| **Admin Umum** | Receiving, distribution, basic reports |
| **Petugas Gudang** | Stock operations, receiving verification |
| **Auditor** | Financial reports, stock valuation, audit |

### Administrative Access Rules (Latest)

- **Admin Panel** sidebar/menu access is **Admin role only**.
- **User Management** page access is **Admin + Kepala Instalasi**.
- User-management write actions (create, edit, activate/deactivate, delete) are **Admin only**.

### Role-as-Title + Module Role UAC (Latest)

- `User.role` is treated as **job title** for identity/organizational context.
- Effective authorization follows **module role access** (`ModuleAccess`) with scopes:
  - `NONE`, `VIEW`, `OPERATE`, `APPROVE`, `MANAGE`
- Default module scopes are seeded by role title but can be adjusted per user.
- Current baseline:
  - **Admin**: manage all modules + admin panel
  - **Kepala Instalasi**: user management view-only, approve all transaction modules, no admin panel
  - **Admin Umum**: receiving/distribution operate, selected view modules
  - **Gudang**: stock + transaction modules operate, selected view modules
  - **Auditor**: report manage, other modules mostly view

## Key Architectural Patterns

### Document Workflows

Most modules follow a status-based workflow with transitions enforced in views:

- **Receiving (planned):** Draft → Submitted → Approved → Partial/Received → Closed (`Transaction(IN)` during receipt input)
- **Receiving (regular):** create/list/detail available for direct documents
- **Distribution:** create/list/detail available; status enum supports Draft → Submitted → Verified → Prepared → Distributed
- **Recall:** Draft → Submitted → Verified → Completed (`Transaction(OUT)`)
- **Expired:** Draft → Submitted → Verified → Disposed (`Transaction(OUT)`)
- **Stock Transfer:** Draft → Completed (`Transaction(OUT)` from source + `Transaction(IN)` at destination)

### Transaction Audit Trail

All stock movements produce immutable `Transaction` records in `apps.stock`. Never delete or modify existing transactions — always create new ones.

### Auto-generated Document Numbers

Document numbers (e.g., `RCV-YYYY-NNNNN`, `ITM-YYYY-NNNNN`) are auto-generated in models if the user does not provide or leave the form  empty.

### Receiving & Outbound UX (Latest)

- Sidebar groups are organized as:
  - **Penerimaan** → `Buat Penerimaan`, `Rencana Penerimaan`
  - **Pengeluaran** → `Distribusi`, `Recall / Retur`, `Kadaluarsa`
- Create forms for Receiving/Distribution/Recall/Expired use full-width card layout aligned with list pages.
- Top navbar can show contextual back buttons (to sub-main list pages) on non-list routes.

### Search & Formset UX (Latest)

- Default preference for large item selectors is **inline typeahead search** (input + suggestion list), not native dropdown-only selection.
- Typeahead behavior should support keyboard interaction (`ArrowUp/ArrowDown`, `Enter`, `Esc`).
- Distribution `Stok (Batch)` is intentionally **not typeahead**; it is a dependent dropdown filtered by selected `Barang` in the same row.
- Distribution stock option ordering follows FEFO (earliest expiry first) and excludes unavailable batches (`quantity <= reserved`).
- Dynamic line-item tables should support:
  - add row (`Tambah Baris`)
  - remove row per line
  - clear all with confirmation (`Hapus Semua`)
  - minimum one visible row

### Stock Card & Transfer (Latest)

- Stock module provides `Kartu Stok` selector + detail page with running balance and dynamic reference labels (`RECEIVING`, `DISTRIBUTION`, `RECALL`, `EXPIRED`, `TRANSFER`).
- Stock card date filtering accepts `DD/MM/YYYY` and `YYYY-MM-DD` input formats.
- Stock Transfer module routes:
  - `GET /stock/transfers/`
  - `GET|POST /stock/transfers/create/`
  - `GET /stock/transfers/<id>/`
  - `POST /stock/transfers/<id>/complete/`
- Transfer completion updates source/destination stock atomically and writes paired transfer transactions.

### Receiving CSV Import (Admin)

- Receiving Admin includes custom `import-csv/` endpoint for saldo awal ingestion.
- Date parser accepts `DD/MM/YYYY`, `YYYY-MM-DD`, `DD-MM-YYYY`, and `DD/MM/YY`.
- Decimal parser tolerates comma decimal separator and returns row-specific error messages.
- Import creates `Receiving(VERIFIED)` + `ReceivingItem` + `Stock` + `Transaction(IN)` in one flow.

### Item Module Behaviors (Latest)

- Item list supports search (`kode_barang`, `nama_barang`, program code/name), category filter, program-item filter, and pagination (25/page).
- Item module exposes AJAX quick-create endpoints for lookup records:
  - `POST /items/api/quick-create-unit/`
  - `POST /items/api/quick-create-category/`
  - `POST /items/api/quick-create-program/`
- Item import (`ItemResource.before_import_row`) auto-assigns a `DEFAULT` Program when `is_program_item` is true but `program` is empty.

### Template Inheritance

All templates extend `templates/base.html` which provides the Bootstrap 5 layout, navigation, and message display. App-specific templates go in `templates/<app_name>/`.

### CSV Import/Export

Powered by `django-import-export`. Admin classes use `ImportExportModelAdmin` for bulk data operations.

## Environment Setup

### Required Environment Variables (`.env`)

```text
DJANGO_SECRET_KEY=<generate-with-django-utility>
DB_NAME=healthcare_ims
DB_USER=postgres
DB_PASSWORD=<your-password>
DB_HOST=localhost
DB_PORT=5432
ALLOWED_HOSTS=localhost,127.0.0.1
REDIS_URL=redis://localhost:6379/0
SECURE_SSL_REDIRECT=False
```

### Infrastructure (Docker Compose)

```bash
docker compose up -d    # Starts PostgreSQL 16 + Redis 7
```

### Development Server

```bash
cd backend
python manage.py migrate
python manage.py runserver    # → http://localhost:8000
```

## Testing

Use the provided PowerShell helper script from the repo root:

```powershell
.\scripts\run-django-test.ps1 -Target apps.items
.\scripts\run-django-test.ps1 -Target apps.recall
.\scripts\run-django-test.ps1 -Target apps.stock_opname
.\scripts\run-django-test.ps1 -Target tests.test_item_import
```

The script auto-activates the virtualenv, sets cwd to `backend/`, and checks for `crispy_forms` before running.

## Security Notes

- **Brute-force protection:** `django-axes` — locks after 5 failed login attempts (30-min cooldown)
- **Session hardening:** 1-hour sliding expiry, HTTP-only cookies, `SameSite=Lax`
- **CSRF protection:** HTTP-only cookie, `SameSite=Lax`
- **Production mode (`DEBUG=False`):** Enables HSTS, secure cookies, SSL redirect, `X-Frame-Options: DENY`
- **Password policy:** Minimum 10 characters with Django validators

## Coding Conventions

- **App structure:** Follow existing patterns — each app has `models.py`, `views.py`, `urls.py`, `admin.py`, `forms.py`
- **Views:** Function-based views with `@login_required` and `@perm_required` decorators
- **Forms:** Use `crispy_forms` with `bootstrap5` template pack
- **Models:** Use `BigAutoField` as default PK; put shared/abstract models in `apps.core`
- **Templates:** Place in `templates/<app_name>/`; extend `base.html`
- **Locale:** Language code is `id` (Indonesian); timezone is `Asia/Jakarta`
- **Admin:** Register models with `ImportExportModelAdmin` for CSV support

## Documentation

| Document | Purpose |
| --- | --- |
| [`README.md`](README.md) | User-facing project overview |
| [`requirements_draft/system_design_renew.md`](requirements_draft/system_design_renew.md) | Full system design |
| [`requirements_draft/erd.md`](requirements_draft/erd.md) | Entity Relationship Diagram |
| [`requirements_draft/infrastructure_plan.md`](requirements_draft/infrastructure_plan.md) | Deployment architecture |
| [`backend/seed/README.md`](backend/seed/README.md) | Seed data column specs |
| [`security-audit/`](security-audit/) | OWASP Top 10 audit report |
