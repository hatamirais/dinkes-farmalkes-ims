# 🏥 Healthcare Inventory Management System

A web-based inventory management system for managing medicine and medical equipment distribution at government healthcare facilities (Dinas Kesehatan level). Built to replace Excel-based workflows with a modern, structured application.

## ✨ Features

- **Item Master Management** — Full CRUD for medicines & medical equipment with category, unit, and program tracking
- **Multi-Location Stock Tracking** — Track inventory across multiple storage locations with batch/lot numbers
- **FEFO Management** — First Expiry, First Out tracking with expiry date monitoring
- **Receiving Module** — Record incoming stock from procurement (eKatalog) and grants (Hibah)
- **Distribution Module** — Handle LPLPO requests, planned allocations, and special requests to Puskesmas/facilities
- **Funding Source Tracking** — Track budget allocation per batch (DAK, DAU, APBD, etc.)
- **Audit Trail** — Immutable transaction log for all stock movements
- **CSV Import/Export** — Bulk data operations via Django Admin (`django-import-export`)
- **Dashboard** — Overview of stock levels, near-expiry items, and recent transactions

## 🛠️ Tech Stack

| Layer            | Technology                                         |
| ---------------- | -------------------------------------------------- |
| Backend          | Django 6.0.2                                       |
| Frontend         | Django Templates + Bootstrap 5 (crispy-bootstrap5) |
| Database         | PostgreSQL 16                                      |
| Cache/Queue      | Redis 7 (via Docker)                               |
| CSV Import       | django-import-export                               |
| Containerization | Docker Compose                                     |

## 📋 Prerequisites

- Python 3.13+
- Docker & Docker Compose
- Git

## 🚀 Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/<your-username>/DJANGO-IMS.git
cd DJANGO-IMS
```

### 2. Set up environment variables

```bash
cp .env.example .env
# Edit .env with your own values (especially DJANGO_SECRET_KEY)
```

### 3. Start infrastructure services

```bash
docker compose up -d
```

This starts PostgreSQL and Redis containers.

### 4. Set up Python environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate

pip install -r backend/requirements.txt
```

### 5. Run migrations & create superuser

```bash
cd backend
python manage.py migrate
python manage.py createsuperuser
```

### 6. Start the development server

```bash
python manage.py runserver
```

Visit `http://localhost:8000` for the app and `http://localhost:8000/admin/` for the admin panel.

### Running tests safely (Windows)

From repository root, use helper script:

```powershell
.\scripts\run-django-test.ps1 -Target apps.items
```

Notes:

- Script auto-activates `venv` (if available)
- Script always runs tests from `backend/` (prevents wrong cwd errors)
- Script checks `crispy_forms` dependency first and prints install hint if missing

### 7. Import seed data (optional)

CSV seed files are provided in `backend/seed/`. Import them via the Django Admin panel using the **Import** button (powered by `django-import-export`).

Import order: `units` → `categories` → `funding_sources` → `programs` → `locations` → `suppliers` → `facilities` → `items` → `stock`

See [`backend/seed/README.md`](backend/seed/README.md) for column specifications.

## 📁 Project Structure

```text
DJANGO-IMS/
├── docker-compose.yml          # PostgreSQL + Redis
├── .env.example                # Environment template
├── backend/
│   ├── manage.py
│   ├── requirements.txt
│   ├── config/                 # Django settings & URLs
│   ├── apps/
│   │   ├── core/               # Base models, dashboard
│   │   ├── items/              # Item master + lookup tables
│   │   ├── stock/              # Stock + transaction audit trail
│   │   ├── receiving/          # Incoming stock (procurement/grants)
│   │   ├── distribution/       # Outgoing stock to facilities
│   │   ├── reports/            # Reporting (in progress)
│   │   └── users/              # Custom user model with roles
│   ├── seed/                   # CSV seed data
│   ├── templates/              # Django HTML templates
│   └── static/                 # CSS & JS assets
└── requirements_draft/         # Design documents & ERD
```

## 👥 User Roles

| Role                 | Description                              |
| -------------------- | ---------------------------------------- |
| **Admin**            | Full system access + user management     |
| **Kepala Instalasi** | Approvals, all reports, dashboard        |
| **Admin Umum**       | Receiving, distribution, basic reports   |
| **Petugas Gudang**   | Stock operations, receiving verification |
| **Petugas Keuangan** | Financial reports, stock valuation       |

## 📖 Documentation

- [System Design](requirements_draft/system_design_renew.md) — Full system design document
- [ERD](requirements_draft/erd.md) — Entity Relationship Diagram
- [Infrastructure Plan](requirements_draft/infrastructure_plan.md) — Deployment architecture
- [Seed Data Guide](requirements_draft/README.md) — CSV import instructions

## 📝 License

This project is licensed under the [MIT License](LICENSE).
