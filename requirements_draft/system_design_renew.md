# Healthcare IMS - System Design (Current-State Revision)

This document describes the current implemented design and the plan used to continuously audit and revise repository documentation.

Last verified: 2026-03-17
Verification sources: `SYSTEM_MODEL.md`, `backend/apps/*/models.py`, `backend/config/urls.py`, `backend/apps/*/urls.py`, `backend/config/settings.py`, `backend/apps/*/admin.py`, `scripts/`

## 1) Executive Summary

Healthcare IMS is a Django server-rendered application for government-health inventory operations. It manages master data, inbound/outbound document workflows, and batch-level stock movements with immutable transaction logging.

The implementation currently prioritizes operational correctness and traceability:

- append-only stock movement journal (`transactions`)
- workflow-driven mutation checkpoints
- hybrid authorization (Django permissions + module scope fallback)
- import tooling that supports controlled bootstrap and dry-run validation

## 2) Current Architecture

### Runtime model

- Django monolith (templates + function-based views)
- PostgreSQL 16 as primary datastore
- Redis 7 present for cache/broker readiness
- Django Admin used for operational and import workflows

### Deployed components in repository

- `docker-compose.yml`: postgres + redis services
- backend process started outside compose (local `runserver` flow)

### Planned but not yet active

- Dedicated production compose override for backend/web process orchestration
- Celery workers for periodic jobs/alerts
- React/API split (future only)

## 3) Functional Modules and Workflow State

### 3.1 Implemented modules

- Item master and lookups
- Stock list and movement history
- Receiving (regular + planned)
- Distribution
- Recall
- Expired/disposal
- Stock transfer
- Stock opname
- User management with module access scopes

### 3.2 Placeholder module

- Reports (route exists; model layer placeholder)

### 3.3 Workflow status snapshots

- Receiving planned: `DRAFT -> SUBMITTED -> APPROVED -> PARTIAL/RECEIVED -> CLOSED`
- Distribution: `DRAFT -> SUBMITTED -> VERIFIED -> PREPARED -> DISTRIBUTED` (or `REJECTED`)
- Recall: `DRAFT -> SUBMITTED -> VERIFIED -> COMPLETED`
- Expired: `DRAFT -> SUBMITTED -> VERIFIED -> DISPOSED`
- Stock transfer: `DRAFT -> COMPLETED`
- Stock opname: `DRAFT -> IN_PROGRESS -> COMPLETED`

## 4) Data and Mutation Design

### 4.1 Core model principles

- Batch/location stock in `stock`
- Funding source traceability at stock-batch level (`sumber_dana` FK)
- Immutable journal entries in `transactions`
- Document headers and line-items separated by module

### 4.2 Mutation checkpoints

- Receiving posting creates/updates stock and writes `Transaction(IN)`
- Distribution prepare currently only updates Distribution status (no `stock.reserved` mutation); distribute performs stock decrement and posts `Transaction(OUT)`
- Recall verify and Expired verify reduce stock and post `Transaction(OUT)`
- Transfer complete performs paired source `OUT` and destination `IN`

### 4.3 Import integration

- django-import-export model resources for lookups/items/stock
- custom receiving CSV endpoint for bootstrap posting in one transaction

## 5) Access Control Design

Authorization is intentionally hybrid:

1. Django permission checks (`has_perm`)
2. ModuleAccess scope fallback via `@perm_required`

Scope taxonomy:

- `NONE`, `VIEW`, `OPERATE`, `APPROVE`, `MANAGE`

Role defaults are seeded in `backend/apps/users/access.py` and can be tuned per user.

## 6) Security Design (Current)

From settings and operational behavior:

- environment-driven `SECRET_KEY` (required)
- explicit custom user model (`AUTH_USER_MODEL`)
- django-axes backend ordering and middleware wiring
- lockout and cooldown policy in settings
- hardened cookies and production-only secure headers when `DEBUG=False`

## 7) Documentation Audit and Revision Plan

This is the governing plan for documentation maintenance.

### 7.1 Document inventory

Primary docs:

- `README.md`
- `AGENTS.md`
- `SYSTEM_MODEL.md`
- `backend/seed/README.md`
- `requirements_draft/README.md`
- `requirements_draft/erd.md`
- `requirements_draft/infrastructure_plan.md`
- `requirements_draft/system_design_renew.md`

### 7.2 Source-of-truth mapping

- Schema claims -> `backend/apps/*/models.py`
- Route claims -> `backend/config/urls.py`, `backend/apps/*/urls.py`
- Permission claims -> `backend/apps/core/decorators.py`, `backend/apps/users/access.py`
- Security/settings claims -> `backend/config/settings.py`
- Import claims -> `backend/apps/*/admin.py`
- Script claims -> `scripts/`

### 7.3 Review workflow

1. Parse docs and extract factual claims.
2. Validate each claim against code source.
3. Classify drift:
   - critical: wrong schema/auth/workflow/security
   - major: wrong routes/commands/env/import columns
   - minor: wording/terminology/format
4. Fix canonical docs first (`SYSTEM_MODEL.md`, `README.md`, `AGENTS.md`).
5. Cascade fixes to `requirements_draft/` and seed docs.
6. Add/update "Last verified" + verification-source paths.

### 7.4 Context7 alignment policy

Primary third-party references:

- Django: `/django/django`
- django-import-export: `/websites/django-import-export_readthedocs_io_en`
- django-axes: `/jazzband/django-axes`

Applied rules:

- keep `AUTH_USER_MODEL` and custom-user guidance explicit
- keep `SECRET_KEY` environment guidance explicit
- keep `DEBUG=False` hardening behavior synchronized with settings
- keep django-import-export dry-run/confirm semantics documented
- keep django-axes backend order and middleware placement documented

### 7.5 PR-level documentation gate

Any PR that changes models, routes, settings, import behavior, or scripts must include doc updates in the same PR.

## 8) Gap Register (Current)

- Reports domain remains intentionally lightweight/placeholder.
- Celery alert jobs are not yet active in standard runtime.
- Production deployment docs describe target architecture; final executable runbook requires production manifests.

## 9) Recommended Next Documentation Iteration

1. Add migration-aware release note template for schema/permission changes.
2. Add a compact route catalog appendix generated from URLconfs.
3. Add periodic verification checklist automation (CI doc lint against known claims).
4. Keep `VERSION` and semantic-version bump workflow (`python manage.py app_version --major|--minor|--patch`) in release docs.
