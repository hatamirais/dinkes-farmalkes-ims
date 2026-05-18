# Code Wiki

Baseline wiki for navigating the Healthcare IMS codebase.

## Audience

Use this wiki when you need to answer:

- Where a feature lives
- Which files are source of truth
- How document workflows mutate stock
- Which conventions must be preserved when changing behavior

## Pages

- [Architecture](architecture.md)
- [App Map](app-map.md)
- [Workflows and Stock Mutation](workflows-and-stock.md)
- [Conventions and Guardrails](conventions.md)

## Primary Source Files

Read these first before making non-trivial changes:

- `backend/config/settings.py`
- `backend/config/urls.py`
- `backend/apps/core/decorators.py`
- `backend/apps/users/access.py`
- `backend/apps/*/models.py`
- `backend/apps/*/urls.py`
- `backend/apps/receiving/admin.py`
- `backend/apps/distribution/services.py`
- `backend/apps/allocation/services.py`

## Fast Orientation

The project is a Django monolith with server-rendered templates and Bootstrap. Inventory is tracked at batch and location granularity, and stock movement history is append-only through `stock.Transaction`.

Most business logic sits in app-level `views.py`, selected `services.py` modules, and model validations. Admin import flows matter because they create live inventory state, especially in `receiving`.
