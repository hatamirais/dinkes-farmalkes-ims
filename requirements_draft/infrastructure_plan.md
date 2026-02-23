# Infrastructure Plan

## Overview

The infrastructure is designed for high reliability, ease of deployment, and seamless scalability on **Proxmox VMs (Ubuntu Server)**. We use **Docker Compose** to orchestrate all services, ensuring consistency between Development and Production environments.

## Architecture Diagram

```mermaid
graph TD
    Client[Client Browser/Mobile] -->|HTTPS| Nginx[Nginx Reverse Proxy]
    
    subgraph Docker Network
        Nginx -->|/api| API[Django Backend(Gunicorn)]
        Nginx -->|/*| FE[React Frontend(Static Files)]

        API -->|Read/Write| DB[(PostgreSQL 16)]
        API -->|Cache/Queue| Redis[(Redis 7)]
        API -->|Async Tasks| Celery[Celery Worker]
        Celery --> Redis
        Celery -.->|Update| DB
    end
    
    subgraph Storage
        DB --> VolDB[Postgres Volume]
        API --> VolMedia[Media Volume]
        Nginx --> VolMedia
    end
```

## Core Components

### 1. Servers (Proxmox VMs)

- **OS**: Ubuntu Server 22.04 LTS (or later)
- **Environment**:
  - **Development VM**: Runs with hot-reloading enabled.
  - **Production VM**: Runs optimized, static builds.

### 2. Container Orchestration (Docker Compose)

We use a base `docker-compose.yml` file extended by environment-specific overrides.

#### Base Services (`docker-compose.yml`)

- **PostgreSQL**: Database service (Port 5432)
- **Redis**: Caching and message broker (Port 6379)
- **Celery**: Background task worker (e.g., expiry alerts)

#### Development Override (`docker-compose.dev.yml`)

- **Backend**: Runs with `python manage.py runserver 0.0.0.0:8000` (auto-reload).
- **Frontend**: Runs with `npm run dev` (Vite dev server, auto-reload).
- **Volume Mounts**: Source code mounted into containers for live editing.

#### Production Override (`docker-compose.prod.yml`)

- **Backend**: Runs with **Gunicorn** (`gunicorn config.wsgi:application`).
- **Frontend**: Built static files served by **Nginx**.
- **Nginx**: Acts as the web server and reverse proxy.
  - Serves static frontend assets.
  - Proxies `/api/` requests to the Django backend.
  - Serves media files (uploaded documents).
- **Restart Policy**: `restart: always` for high availability.

### 3. Networking & Security

- **Internal**: All services communicate on a private Docker network.
- **External**: Only **Nginx** (ports 80/443) is exposed to the host network in production.
- **CORS**: Configured to restrict API access to the frontend domain.
- **Media Files**: Served by Nginx but protected by application logic where necessary.

## Deployment Strategy

### Seamless Dev-to-Prod Workflow

1. **Develop**: Code locally or on Dev VM.
2. **Push**: Commit changes to Git.
3. **Deploy**:
    - SSH into Production VM.
    - `git pull origin main`
    - `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`
    - `docker compose exec backend python manage.py migrate` (if DB changes)
    - `docker compose exec backend python manage.py collectstatic --noinput`

## Scalability

- **Horizontal**: Can add more Celery workers or Backend replicas easily via Docker Compose.
- **Vertical**: Proxmox allows resizing VM resources (CPU/RAM) on the fly.

## Backup Strategy

- **Database**: Automated `pg_dump` via scheduled cron job on the host.
- **Media Files**: RSYNC media volume to backup storage.
