# Architecture

## Runtime Shape

- Framework: Django 6 monolith
- UI: Django templates plus Bootstrap 5
- Database: PostgreSQL
- Cache and broker: Redis
- Auth model: `apps.users.User`
- Root settings: `backend/config/settings.py`
- Root routes: `backend/config/urls.py`

## High-Level Layers

### Entry and platform

- `backend/manage.py`: Django entrypoint
- `backend/config/settings.py`: installed apps, middleware, auth backends, security hardening, environment keys
- `backend/config/urls.py`: global route includes, auth pages, global error handlers

### Shared platform code

- `backend/apps/core/models.py`: shared timestamp base and system settings singleton
- `backend/apps/core/views.py`: dashboard, system settings, centralized error handlers, maintenance page
- `backend/apps/core/decorators.py`: hybrid authorization decorators
- `backend/apps/core/middleware.py`: admin panel access and CSP middleware
- `backend/apps/core/numbering.py`: generic template-based document numbering helpers
- `backend/apps/core/versioning.py`: app version parsing and persistence

### Domain apps

- `items`: master data and item catalog
- `stock`: stock ledger, stock card, transaction journal, stock transfer
- `receiving`: inbound documents and CSV import-to-stock path
- `distribution`: outbound distribution workflow
- `allocation`: pre-distribution planning that generates child distributions
- `recall`: supplier return workflow
- `expired`: expiry and disposal workflow
- `stock_opname`: physical counting workflow
- `puskesmas`: ad-hoc requests from facilities
- `lplpo`: monthly reporting and request flow
- `reports`: read-heavy reporting and exports
- `users`: custom user model, role logic, module scopes, user management UI

## Request Flow

Typical request path:

1. Route enters through `backend/config/urls.py` or app `urls.py`.
2. Access is enforced by Django auth, custom middleware, and `@perm_required`.
3. View logic in `views.py` coordinates forms, querysets, and workflow actions.
4. For heavier workflow transitions, services in `distribution/services.py` and `allocation/services.py` execute business rules.
5. Templates under `backend/templates/` render the final response.

## Data Shape

The central inventory spine is:

- `items.Item`
- `stock.Stock`
- `stock.Transaction`

Document apps reference those tables rather than duplicating inventory state. Batch and funding-source snapshots are captured where needed on document items so later reporting remains stable after stock changes.

## Security Model

- `AUTH_USER_MODEL` is `users.User`
- Auth backends are `axes` first, then Django model backend
- `APPEND_SLASH = True` is an explicit project rule
- Production hardening is enabled when `DEBUG=False`
- Permission failures should raise `PermissionDenied` so centralized 403 handling remains consistent
