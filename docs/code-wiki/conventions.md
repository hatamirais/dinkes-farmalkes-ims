# Conventions and Guardrails

## Source of Truth

If documentation and code disagree, code wins until docs are corrected.

- Schema: `backend/apps/*/models.py`
- Routes: `backend/config/urls.py` and `backend/apps/*/urls.py`
- Permissions: `backend/apps/core/decorators.py` and `backend/apps/users/access.py`
- Settings and security: `backend/config/settings.py`
- Versioning: `VERSION` and `backend/apps/core/versioning.py`
- Receiving CSV import behavior: `backend/apps/receiving/admin.py`

## URL Rules

All URL patterns must end with `/`.

- Good: `path("create/", ...)`
- Bad: `path("create", ...)`

The project intentionally keeps `APPEND_SLASH = True`, and `backend/apps/core/tests/test_url_consistency.py` enforces the convention.

## Permission Model

Authorization is hybrid:

1. Django permissions via `has_perm`
2. Module-scope fallback via `ModuleAccess`

When denying access in views, raise `PermissionDenied` so the centralized 403 page is used.

## Facility Isolation

Puskesmas-oriented flows are intentionally strict.

- `puskesmas` and `lplpo` enforce facility matching
- Users with the `OPERATOR PUSKESMAS` role must not gain cross-facility read or write access

## Stock Safety Rules

- Never mutate historical `Transaction` rows
- Prefer explicit workflow actions over hidden side effects
- Be careful with batch, location, and funding-source snapshots

## Testing Entry Points

- Windows helper: `scripts/run-django-test.ps1`
- URL consistency tests: `backend/apps/core/tests/test_url_consistency.py`
- Workflow regression tests live inside each app's `tests.py`

## When Docs Must Be Updated

Update the relevant docs in the same change when you modify:

- Models or table semantics
- URL patterns
- Permission logic
- Settings or environment variables
- Import behavior

At minimum, check:

- `README.md`
- `AGENTS.md`
- `SYSTEM_MODEL.md`
- `docs/developer_guide.md`
- `backend/seed/README.md` when CSV contracts change
