# App Map

This page answers "where should I look?" for each module.

## `core`

- Purpose: shared platform behavior, dashboard, settings, error pages, numbering, versioning
- Start with:
  - `backend/apps/core/views.py`
  - `backend/apps/core/decorators.py`
  - `backend/apps/core/models.py`
  - `backend/apps/core/numbering.py`
  - `backend/apps/core/tests/test_core.py`

## `users`

- Purpose: custom auth model, roles, module-scope fallback, user CRUD
- Start with:
  - `backend/apps/users/models.py`
  - `backend/apps/users/access.py`
  - `backend/apps/users/views.py`
  - `backend/apps/users/forms.py`
  - `backend/apps/users/management/commands/`

## `items`

- Purpose: item registry and reference data such as units, categories, facilities, suppliers, programs, funding sources, locations
- Start with:
  - `backend/apps/items/models.py`
  - `backend/apps/items/views.py`
  - `backend/apps/items/forms.py`
  - `backend/apps/items/admin.py`

## `stock`

- Purpose: current stock, immutable transactions, stock card, stock transfer
- Start with:
  - `backend/apps/stock/models.py`
  - `backend/apps/stock/views.py`
  - `backend/apps/stock/forms.py`
  - `backend/apps/stock/admin.py`
  - `backend/apps/stock/tests.py`

## `receiving`

- Purpose: receiving documents, planned receiving, quick-create endpoints, CSV import that creates stock and `Transaction(IN)`
- Start with:
  - `backend/apps/receiving/models.py`
  - `backend/apps/receiving/views.py`
  - `backend/apps/receiving/forms.py`
  - `backend/apps/receiving/admin.py`
  - `backend/apps/receiving/tests.py`

## `distribution`

- Purpose: outbound workflow for special requests and generated distribution documents
- Important distinction:
  - `special_request_create` is the user-facing manual creation path
  - `distribution_create` remains the generic/internal path
- Start with:
  - `backend/apps/distribution/models.py`
  - `backend/apps/distribution/views.py`
  - `backend/apps/distribution/services.py`
  - `backend/apps/distribution/forms.py`
  - `backend/apps/distribution/numbering.py`

## `allocation`

- Purpose: allocation planning and facility-level orchestration that generates child `Distribution` rows on approval
- Start with:
  - `backend/apps/allocation/models.py`
  - `backend/apps/allocation/views.py`
  - `backend/apps/allocation/services.py`
  - `backend/apps/allocation/forms.py`
  - `backend/apps/allocation/tests.py`

## `recall`

- Purpose: return stock to supplier
- Start with:
  - `backend/apps/recall/models.py`
  - `backend/apps/recall/views.py`
  - `backend/apps/recall/forms.py`
  - `backend/apps/recall/tests.py`

## `expired`

- Purpose: expired goods workflow, alerts, disposal audit reporting
- Start with:
  - `backend/apps/expired/models.py`
  - `backend/apps/expired/views.py`
  - `backend/apps/expired/services.py`
  - `backend/apps/expired/forms.py`

## `stock_opname`

- Purpose: physical stock counting and discrepancy completion
- Start with:
  - `backend/apps/stock_opname/models.py`
  - `backend/apps/stock_opname/views.py`
  - `backend/apps/stock_opname/forms.py`
  - `backend/apps/stock_opname/tests.py`

## `puskesmas`

- Purpose: facility-scoped ad-hoc requests
- Start with:
  - `backend/apps/puskesmas/models.py`
  - `backend/apps/puskesmas/views.py`
  - `backend/apps/puskesmas/forms.py`
  - `backend/apps/puskesmas/tests.py`

## `lplpo`

- Purpose: monthly reporting and request workflow for Puskesmas, with distribution generation on finalize
- Start with:
  - `backend/apps/lplpo/models.py`
  - `backend/apps/lplpo/views.py`
  - `backend/apps/lplpo/forms.py`
  - `backend/apps/lplpo/signals.py`
  - `backend/apps/lplpo/tests.py`

## `reports`

- Purpose: reporting UI and export logic across multiple domains
- Start with:
  - `backend/apps/reports/views.py`
  - `backend/apps/reports/forms.py`
  - `backend/apps/reports/exports.py`
  - `backend/apps/reports/tests.py`

## Cross-Cutting Files

- `backend/templates/`: server-rendered HTML
- `backend/static/js/`: page-specific client-side behavior
- `backend/seed/README.md`: CSV seed contract
- `scripts/run-django-test.ps1`: Windows test helper
