# Infrastructure Plan

Architecture and deployment notes for the current implementation, plus planned evolution.

Last verified: 2026-03-17
Verification sources: `docker-compose.yml`, `.env.example`, `backend/config/settings.py`, `backend/config/urls.py`, `backend/apps/reports/models.py`

## 1) Current Runtime Topology

### Application runtime

- Django app runs directly from host/developer environment (`python manage.py runserver`) from `backend/`.
- UI is server-rendered Django templates.

### Containerized services

- PostgreSQL 16 (`postgres:16-alpine`) via Docker Compose

### Notes

- `reports` module exists as route and view entry, but model layer is still placeholder.

## 2) Current docker-compose Baseline

From `docker-compose.yml`:

- Service `postgres`
  - env: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
  - host port `5432`
  - persistent volume `postgres_data`

No backend container is defined in current compose file.

## 3) Environment and Settings Coupling

### Environment keys

Documented in `.env.example` and consumed by settings:

- `DJANGO_SETTINGS_MODULE`
- `DJANGO_SECRET_KEY`
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
- `ALLOWED_HOSTS`
- `SECURE_SSL_REDIRECT`

### Security posture in settings

- `SECRET_KEY` is required from environment (`os.environ[...]`, fail-fast)
- `AUTH_USER_MODEL = "users.User"`
- Axes backend is first in `AUTHENTICATION_BACKENDS`
- `axes.middleware.AxesMiddleware` installed in middleware stack
- Production hardening enabled when `DEBUG=False`:
  - secure cookies
  - HSTS
  - frame deny
  - strict referrer policy

## 4) Production Target (Planned)

Planned direction (not fully implemented in repo):

- Gunicorn for Django process management
- Nginx reverse proxy and static/media serving
- Optional split frontend/API architecture if React + API layer is introduced later

Important implementation note:

- Do not document `/api/*` routing or React deployment as active until actual code and compose manifests exist.

## 5) Deployment Review Checklist

When preparing production docs and manifests:

1. Verify all environment variables in docs exist in settings or runtime scripts.
2. Verify all service names/ports in docs match compose files.
3. Verify security claims match `settings.py` branches (`DEBUG=True/False`).
4. Verify backup/restore steps are executable and include DB + media handling.
5. Verify runbooks mention migration order and rollback strategy.

## 6) Documentation Maintenance Plan

When infra or settings change:

1. Update this file.
2. Update root `README.md` setup sections.
3. Update `AGENTS.md` environment snapshot and source-of-truth pointers.
4. Cross-check with Context7 best-practice refs:
   - Django `/django/django`
   - django-axes `/jazzband/django-axes`

