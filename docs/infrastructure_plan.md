# Infrastructure Plan

Architecture and deployment notes for the current implementation, plus planned evolution.

Last verified: 2026-06-11
Verification sources: `docker-compose.yml`, `.env.example`, `backend/Dockerfile`, `backend/entrypoint.sh`, `backend/config/settings.py`

## 1) Current Runtime Topology

### Application runtime

- Local development still runs Django directly from `backend/` with `python manage.py runserver`.
- UI is server-rendered Django templates.

### Containerized services

- Baseline local compose: PostgreSQL 16 (`postgres:16-alpine`) via root `docker-compose.yml`

### Notes

- `reports` module exists as route and view entry, but model layer is still placeholder.

## 2) Current docker-compose Baseline

From `docker-compose.yml`:

- Service `postgres`
  - env: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
  - host port `5432`
  - persistent volume `postgres_data`

No backend container is defined in the root compose file.

## 3) Environment and Settings Coupling

### Environment keys

Documented in `.env.example` and consumed by settings:

- `DJANGO_SETTINGS_MODULE`
- `DJANGO_SECRET_KEY`
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
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
  - proxy HTTPS detection via `SECURE_PROXY_SSL_HEADER`

## 4) Deployment Notes

Important implementation note:

- Do not document `/api/*` routing or React deployment as active until actual code and compose manifests exist.

## 5) Deployment Review Checklist

When preparing production docs and manifests:

1. Verify all environment variables in docs exist in settings or runtime scripts.
2. Verify all service names/ports in docs match compose files.
3. Verify security claims match `settings.py` branches (`DEBUG=True/False`).
4. Verify backup/restore steps are executable and include DB + media handling.
5. Verify runbooks mention migration order and rollback strategy.
6. Verify documented deployment examples stay aligned with the actual tracked runtime assets.

## 6) Documentation Maintenance Plan

When infra or settings change:

1. Update this file.
2. Update root `README.md` setup sections.
3. Update `AGENTS.md` environment snapshot and source-of-truth pointers.
4. Cross-check with Context7 best-practice refs:
   - Django `/django/django`
   - django-axes `/jazzband/django-axes`

