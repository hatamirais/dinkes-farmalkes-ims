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

```
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

| App              | Path                        | Purpose                                                  |
| ---------------- | --------------------------- | -------------------------------------------------------- |
| `core`           | `apps/core/`                | Base/abstract models, dashboard view, shared utilities   |
| `users`          | `apps/users/`               | Custom `User` model with role field; 5 roles (see below) |
| `items`          | `apps/items/`               | Item master (medicines, equipment) + lookup tables (Unit, Category, Program, FundingSource, Supplier, Facility) |
| `stock`          | `apps/stock/`               | `Stock` model (batch/lot tracking, FEFO), `Transaction` audit trail |
| `receiving`      | `apps/receiving/`           | Incoming stock (procurement & grants), Draft → Submitted → Verified workflow |
| `distribution`   | `apps/distribution/`        | Outgoing stock to Puskesmas/facilities, multi-step workflow |
| `recall`         | `apps/recall/`              | Supplier returns, Draft → Submitted → Verified → Completed |
| `expired`        | `apps/expired/`             | Expired item disposal, Draft → Submitted → Verified → Disposed |
| `stock_opname`   | `apps/stock_opname/`        | Physical inventory counting, discrepancy reports         |
| `reports`        | `apps/reports/`             | Reporting module (in progress)                           |

## URL Routes

All route prefixes are defined in `backend/config/urls.py`:

| URL Prefix         | App / View             |
| ------------------- | ---------------------- |
| `/`                 | Dashboard (`apps.core`) |
| `/admin/`           | Django Admin            |
| `/login/`           | Auth login              |
| `/logout/`          | Auth logout             |
| `/password/change/` | Password change         |
| `/items/`           | `apps.items`            |
| `/stock/`           | `apps.stock`            |
| `/receiving/`       | `apps.receiving`        |
| `/distribution/`    | `apps.distribution`     |
| `/recall/`          | `apps.recall`           |
| `/expired/`         | `apps.expired`          |
| `/reports/`         | `apps.reports`          |
| `/stock-opname/`    | `apps.stock_opname`     |

## User Roles

The system uses a custom `@role_required` decorator for RBAC. Five roles:

| Role                 | Access Scope                             |
| -------------------- | ---------------------------------------- |
| **Admin**            | Full system access + user management     |
| **Kepala Instalasi** | Approvals, all reports, dashboard        |
| **Admin Umum**       | Receiving, distribution, basic reports   |
| **Petugas Gudang**   | Stock operations, receiving verification |
| **Petugas Keuangan** | Financial reports, stock valuation       |

## Key Architectural Patterns

### Document Workflows

Most modules follow a status-based workflow with transitions enforced in views:

- **Receiving:** Draft → Submitted → Verified (creates `Stock` + `Transaction(IN)`)
- **Distribution:** Draft → Submitted → Verified → Prepared → Distributed (`Transaction(OUT)`)
- **Recall:** Draft → Submitted → Verified → Completed (`Transaction(OUT)`)
- **Expired:** Draft → Submitted → Verified → Disposed (`Transaction(OUT)`)

### Transaction Audit Trail

All stock movements produce immutable `Transaction` records in `apps.stock`. Never delete or modify existing transactions — always create new ones.

### Auto-generated Document Numbers

Document numbers (e.g., `RCV-YYYY-NNNNN`, `ITM-YYYY-NNNNN`) are auto-generated in models. Do not allow users to set these manually.

### Template Inheritance

All templates extend `templates/base.html` which provides the Bootstrap 5 layout, navigation, and message display. App-specific templates go in `templates/<app_name>/`.

### CSV Import/Export

Powered by `django-import-export`. Admin classes use `ImportExportModelAdmin` for bulk data operations.

## Environment Setup

### Required Environment Variables (`.env`)

```
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
- **Views:** Function-based views with `@login_required` and `@role_required` decorators
- **Forms:** Use `crispy_forms` with `bootstrap5` template pack
- **Models:** Use `BigAutoField` as default PK; put shared/abstract models in `apps.core`
- **Templates:** Place in `templates/<app_name>/`; extend `base.html`
- **Locale:** Language code is `id` (Indonesian); timezone is `Asia/Jakarta`
- **Admin:** Register models with `ImportExportModelAdmin` for CSV support

## Documentation

| Document                                                  | Purpose                      |
| --------------------------------------------------------- | ---------------------------- |
| [`README.md`](README.md)                                  | User-facing project overview |
| [`requirements_draft/system_design_renew.md`](requirements_draft/system_design_renew.md) | Full system design           |
| [`requirements_draft/erd.md`](requirements_draft/erd.md)  | Entity Relationship Diagram  |
| [`requirements_draft/infrastructure_plan.md`](requirements_draft/infrastructure_plan.md) | Deployment architecture      |
| [`backend/seed/README.md`](backend/seed/README.md)        | Seed data column specs       |
| [`security-audit/`](security-audit/)                      | OWASP Top 10 audit report    |
