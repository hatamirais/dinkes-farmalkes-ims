# Sistem Manajemen Inventaris Obat & Alat Kesehatan

## System Design Document

---

## 1. Executive Summary

**Purpose:** Replace Excel-based inventory management with a modern web application for managing medicine and medical equipment distribution at a government healthcare facility (Dinas Kesehatan level).

**Target Users:** 10-20 internal staff (Admin, Head of Facility, General Admin, Warehouse Staff, Accounting Staff)

### Tech Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | React + Vite + TypeScript + Tailwind CSS + shadcn/ui |
| **Backend** | Django 5.1 + Django REST Framework |
| **Database** | PostgreSQL 16 |
| **Auth** | Django built-in + djangorestframework-simplejwt |
| **Storage** | Local filesystem (media files) |
| **Deployment** | Docker + Docker Compose |
| **Infrastructure** | Proxmox VMs (Ubuntu Server) - Dev & Prod |

### Infrastructure Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     PROXMOX HOST                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────┐    ┌─────────────────────────────┐ │
│  │      DEV VM (Ubuntu)    │    │       PROD VM (Ubuntu)      │ │
│  │                         │    │                             │ │
│  │  ┌───────────────────┐  │    │  ┌───────────────────────┐  │ │
│  │  │  Docker Compose   │  │    │  │   Docker Compose      │  │ │
│  │  │  ├─ frontend      │  │    │  │   ├─ frontend         │  │ │
│  │  │  ├─ backend       │  │    │  │   ├─ backend          │  │ │
│  │  │  ├─ postgres      │  │    │  │   ├─ postgres         │  │ │
│  │  │  └─ redis         │  │    │  │   └─ redis            │  │ │
│  │  └───────────────────┘  │    │  └───────────────────────┘  │ │
│  │                         │    │                             │ │
│  │  .env.development       │    │  .env.production            │ │
│  └─────────────────────────┘    └─────────────────────────────┘ │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Dev-to-Prod Deployment Strategy

```mermaid
flowchart LR
    subgraph DEV["Development"]
        D1[Local Dev] --> D2[Git Push]
        D2 --> D3[Dev VM<br/>docker compose up]
    end
    
    subgraph PROD["Production"]
        P1[Git Pull on Prod] --> P2[docker compose<br/>-f docker-compose.prod.yml up]
    end
    
    D3 -->|"Test & Verify"| P1
```

**Seamless Transition Features:**

- **Environment files:** `.env.development` vs `.env.production`
- **Compose profiles:** `docker-compose.yml` (base) + `docker-compose.prod.yml` (overrides)
- **Database migrations:** Django migrations for version-controlled schema changes
- **Same Docker images:** Build once, deploy anywhere
- **CORS configuration:** corsheaders for dev/prod origins

---

## 2. Business Process Overview

```mermaid
flowchart TB
    subgraph RECEIVING["📥 RECEIVING (Penerimaan)"]
        P[Procurement<br/>via eKatalog]
        G[Grants/Hibah<br/>Province/Ministry]
    end
    
    subgraph STORAGE["📦 STORAGE (Penyimpanan)"]
        S[Stock Management<br/>Multi-Location]
        B[Batch & FEFO<br/>Tracking]
        E[Expiry<br/>Monitoring]
    end
    
    subgraph DISTRIBUTION["📤 DISTRIBUTION (Distribusi)"]
        R[Request<br/>LPLPO from Puskesmas]
        A[Allocation<br/>Planned Distribution]
        SR[Special Request<br/>Program Items]
    end
    
    subgraph REPORTING["📊 REPORTING"]
        Q[Quarterly Report]
        SE[Semester Report]
        Y[Yearly Report]
        EX[Data Export]
    end
    
    P --> S
    G --> S
    S --> B --> E
    S --> R & A & SR
    R & A & SR --> REPORTING
```

---

## 3. Core Modules

### 3.1 📥 Receiving Module (Penerimaan)

#### 3.1.1 Procurement (Pengadaan via eKatalog)

| Field | Type | Notes |
|-------|------|-------|
| No. Dokumen Pengadaan | String | From eKatalog |
| Tanggal Penerimaan | Date | |
| Supplier/Vendor | Reference | ForeignKey to Supplier |
| Sumber Dana | Reference | ForeignKey to FundingSource |
| Items | Array | Item, Qty, Batch, ED, Price |
| Dokumen Pendukung | Files | Upload from eKatalog |
| Status | Enum | Draft, Submitted, Verified |

#### 3.1.2 Grants (Hibah)

| Field | Type | Notes |
|-------|------|-------|
| No. Surat Hibah | String | |
| Asal Hibah | Enum | Province, Ministry, Donation |
| Tanggal Penerimaan | Date | |
| Program | Optional | For [P] marked items |
| Sumber Dana | Reference | ForeignKey to FundingSource |
| Items | Array | Item, Qty, Batch, ED, Price |
| Dokumen Pendukung | Files | |
| Status | Enum | Draft, Submitted, Verified |

---

### 3.2 📦 Stock Management (Pengelolaan Stok)

#### Item Master (Master Barang)

| Field | Type | Notes |
|-------|------|-------|
| Kode Barang | String | Auto-generated or manual |
| Nama Barang | String | |
| Satuan | ForeignKey(Unit) | Reference to Unit table |
| Kategori | ForeignKey(Category) | Reference to Category table |
| Is Program Item | Boolean | [P] marker |
| Program Name | Optional | TB, HIV, Kusta, etc. |
| Minimum Stock | Number | For alerts |

#### Unit (Satuan) - Lookup Table

| Field | Type | Notes |
|-------|------|-------|
| Code | String | TAB, BTL, AMP, VIAL, etc. |
| Name | String | Tablet, Botol, Ampul, Vial, etc. |
| Description | Optional | Additional info |

#### Category (Kategori) - Lookup Table

| Field | Type | Notes |
|-------|------|-------|
| Code | String | TABLET, INJEKSI, VAKSIN, etc. |
| Name | String | Display name |
| Is Controlled | Boolean | Flag for NARKOTIKA, etc. |
| Sort Order | Integer | For display ordering |

#### Stock (Persediaan)

| Field | Type | Notes |
|-------|------|-------|
| Item | Reference | ForeignKey to Item |
| Location | Reference | ForeignKey to Location |
| Batch/Lot | String | |
| Expiry Date | Date | For FEFO |
| Quantity | Number | Current stock |
| Reserved | Number | Reserved for pending distributions |
| Unit Price | Decimal | |
| Sumber Dana | Reference | ForeignKey to FundingSource (stays here for per-batch tracking) |
| Receiving Ref | Reference | Link to receiving doc |

---

### 3.3 📤 Distribution Module (Distribusi)

#### 3.3.1 Request (Permintaan via LPLPO)

| Field | Type | Notes |
|-------|------|-------|
| No. LPLPO | String | From Puskesmas |
| Puskesmas | Reference | Requesting facility |
| Tanggal Permintaan | Date | |
| Items Requested | Array | Item, Qty Requested |
| Items Approved | Array | Item, Qty Approved, Batch |
| Status | Enum | Submitted → Verified → Prepared → Distributed |
| Verified By | Reference | User |
| Distributed Date | Date | |

#### 3.3.2 Allocation (Alokasi)

| Field | Type | Notes |
|-------|------|-------|
| No. Alokasi | String | |
| Periode | String | Month/Quarter |
| Type | Enum | Routine, Special |
| Allocations | Array | Facility, Item, Qty, Batch, **ED** |
| Created By | Reference | |
| Approved By | Reference | |
| Status | Enum | Draft → Approved → Distributed |

#### 3.3.3 Special Request (Permintaan Khusus)

| Field | Type | Notes |
|-------|------|-------|
| No. Permintaan | String | |
| Requesting Facility | Reference | Puskesmas, RS, Clinic |
| Program | Optional | Can be any program or none |
| Items Requested | Array | Any items (not limited to [P]) |
| Approval Status | Enum | Pending → Approved → Rejected |
| Approved By | Reference | Manual approval |
| Notes | Text | |
| OCR Text | Text | Extracted from uploaded proof |

> [!NOTE]
> Special Request currently manual process - no public-facing portal needed yet. OCR feature for proof documents.

---

### 3.4 📊 Reporting Module

#### Standard Reports

| Report | Frequency | Description |
|--------|-----------|-------------|
| Laporan Stok | On-demand | Current stock by location/category |
| Kartu Stok | On-demand | Stock card per item |
| Laporan Penerimaan | Monthly | All receiving transactions |
| Laporan Distribusi | Monthly | All distribution transactions |
| Laporan Keuangan | Quarterly/Semester/Yearly | Accounting perspective |
| Near Expiry Report | Weekly | Items expiring soon |
| Stock Opname | As needed | Physical count reconciliation |

#### Export Features

- Export to Excel (XLSX)
- Export to PDF
- Flexible date range selection
- Filter by category, sumber dana, location

> [!IMPORTANT]
> Report formats vary yearly - system must support flexible data export rather than rigid templates

---

## 4. User Roles & Permissions

| Role | Permissions |
|------|-------------|
| **Admin** | Full access, user management, system settings |
| **Kepala Instalasi** | Approve allocations, view all reports, dashboard |
| **Admin Umum** | Manage receiving, create distributions, basic reports |
| **Petugas Gudang** | Stock updates, receiving verification, distribution preparation |
| **Petugas Keuangan** | Financial reports, stock valuation, accounting exports |

---

## 5. Locations (Akan Ditentukan)

> Placeholder for warehouse/storage locations to be provided by client

| Location Code | Location Name | Notes |
|---------------|---------------|-------|
| LOC-001 | TBD | |
| LOC-002 | TBD | |
| ... | ... | |

---

## 6. System Features

### Core Django Packages

```python
# requirements.txt (key packages)
Django==5.1
djangorestframework==3.14
djangorestframework-simplejwt==5.3
django-cors-headers==4.3
django-filter==23.5
django-import-export==3.3  # CSV import/export
django-auditlog==2.3       # Auto transaction logging
psycopg2-binary==2.9
redis==5.0
celery==5.3                # Background tasks
gunicorn==21.2             # Production server
```

### Core Features

- [x] Multi-location stock tracking
- [x] FEFO (First Expiry, First Out) management
- [x] Batch/Lot number tracking
- [x] Funding source (Sumber Dana) tracking
- [x] Program item [P] designation
- [x] Document upload/attachment
- [x] Audit trail (who changed what, when)

### Alerts & Notifications

- [ ] Low stock alerts (below minimum) - Celery periodic task
- [ ] Expiry alerts (first day of expiry month = expired) - Celery periodic task
- [ ] Pending approval notifications - Real-time via Django signals

### Dashboard

**React Frontend Dashboard:**
- Stock overview by category
- Near expiry items summary
- Recent transactions
- Pending requests/approvals

**Django Admin Panel:**
- Quick CRUD for all models
- Batch imports/exports
- User management
- Audit log viewer
- Custom actions (approve, verify, etc.)

---

## 7. Data Migration

Import initial data from [data.csv](file:///d:/projects/Inventory%20Management%20System/data.csv):

- 414 item records
- Fields: namaBarang, satuan, kategori, batch, ed, hargaSatuan, sumberDana, qty, nominal

Migration approach:

1. Create Django management command: `manage.py import_initial_stock`
2. Parse and validate CSV data using django-import-export
3. Create item master records (bulk_create for performance)
4. Create initial stock entries with batch/expiry
5. Link to appropriate sumber dana
6. Generate audit trail using django-auditlog

**Management Command:**
```python
# apps/stock/management/commands/import_initial_stock.py
from django.core.management.base import BaseCommand
from tablib import Dataset
from apps.stock.resources import StockResource

class Command(BaseCommand):
    def handle(self, *args, **options):
        # Import logic here
        pass
```

---

## 8. Project Structure

```
inventory-system/
├── docker-compose.yml          # Base compose (shared services)
├── docker-compose.dev.yml      # Dev overrides (hot reload, debug)
├── docker-compose.prod.yml     # Prod overrides (optimized)
├── .env.example                # Template env file
│
├── frontend/
│   ├── Dockerfile
│   ├── Dockerfile.dev
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── components/         # shadcn/ui components
│       ├── pages/              # Page components
│       ├── hooks/              # Custom hooks
│       ├── lib/                # API client, utils
│       └── types/              # TypeScript types
│
├── backend/
│   ├── Dockerfile
│   ├── Dockerfile.dev
│   ├── requirements.txt
│   ├── manage.py              # Django management
│   ├── config/                # Django project settings
│   │   ├── settings/
│   │   │   ├── base.py
│   │   │   ├── development.py
│   │   │   └── production.py
│   │   ├── urls.py
│   │   └── wsgi.py
│   ├── apps/                  # Django apps
│   │   ├── core/              # Base models, mixins
│   │   ├── items/             # Item master
│   │   ├── stock/             # Stock management
│   │   ├── receiving/         # Penerimaan module
│   │   ├── distribution/      # Distribusi module
│   │   ├── reports/           # Reporting module
│   │   └── users/             # User & permissions
│   └── tests/
│
└── docs/                       # Documentation
```

### Docker Compose Configuration

**Base (`docker-compose.yml`):**

```yaml
services:
  postgres:
    image: postgres:16-alpine
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      - POSTGRES_DB=${DB_NAME}
      - POSTGRES_USER=${DB_USER}
      - POSTGRES_PASSWORD=${DB_PASSWORD}
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    ports:
      - "6379:6379"

  backend:
    build:
      context: ./backend
    depends_on:
      - postgres
      - redis
    environment:
      - DJANGO_SETTINGS_MODULE=config.settings.development
      - DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@postgres:5432/${DB_NAME}
      - REDIS_URL=redis://redis:6379/0
    volumes:
      - media_files:/app/media
    ports:
      - "8000:8000"

  frontend:
    build:
      context: ./frontend
    depends_on:
      - backend
    ports:
      - "5173:5173"

volumes:
  postgres_data:
  redis_data:
  media_files:
```

**Dev Override (`docker-compose.dev.yml`):**

```yaml
services:
  backend:
    build:
      dockerfile: Dockerfile.dev
    volumes:
      - ./backend:/app          # Hot reload
    command: python manage.py runserver 0.0.0.0:8000
    environment:
      - DEBUG=True

  frontend:
    build:
      dockerfile: Dockerfile.dev
    volumes:
      - ./frontend:/app         # Hot reload
      - /app/node_modules       # Prevent overwrite
    command: npm run dev -- --host 0.0.0.0
```

**Prod Override (`docker-compose.prod.yml`):**

```yaml
services:
  backend:
    restart: always
    command: gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 4
    environment:
      - DJANGO_SETTINGS_MODULE=config.settings.production
      - DEBUG=False

  frontend:
    restart: always
    build:
      target: production
    # Nginx serves built static files + proxies API to backend

  nginx:
    image: nginx:alpine
    restart: always
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf
      - frontend_build:/usr/share/nginx/html
    ports:
      - "80:80"
    depends_on:
      - backend
      - frontend

volumes:
  frontend_build:
```

### Deployment Commands

```bash
# Development (on Dev VM)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# Production (on Prod VM)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Run migrations
docker compose exec backend python manage.py migrate

# Create superuser
docker compose exec backend python manage.py createsuperuser

# Collect static files (production)
docker compose exec backend python manage.py collectstatic --noinput

# Import initial CSV data
docker compose exec backend python manage.py import_initial_stock data.csv
```

---

## 9. Resolved Questions

| Question | Resolution |
|----------|------------|
| Supplier/Vendor Management | ✅ Track beyond eKatalog |
| Puskesmas/Facility Master | ✅ 20+ facilities, access via API |
| Expiry Alert Threshold | ✅ First day of expiry month = expired |
| Stock Opname | ✅ Monthly |
| Controlled Substances | ✅ No special tracking (external ministry app) |
| Offline Access | ✅ Not needed (infra network) |
| OCR Feature | ✅ For Special Request proof documents |

---

## 10. Next Steps

1. ✅ Requirements gathering - DONE
2. ✅ Tech stack finalized (Django + DRF + PostgreSQL + Docker)
3. ✅ System design approved
4. ✅ ERD created - see [erd.md](file:///C:/Users/User/.gemini/antigravity/brain/3a2b6b86-b71c-4543-a72e-84234289f10c/erd.md)
5. ⬜ Review & approve ERD
6. ⬜ Define API specifications (DRF ViewSets)
7. ⬜ Project setup & scaffolding
8. ⬜ Django models + migrations
9. ⬜ Django Admin customization
10. ⬜ DRF serializers + viewsets
11. ⬜ React frontend implementation
12. ⬜ CSV import management command
13. ⬜ Celery tasks for alerts
14. ⬜ Testing & deployment
