# AGENTS.md - Healthcare IMS

Onboarding guide for coding agents working in this repository.

## Purpose

This project is a Django-based healthcare inventory system used by internal government-health staff. The codebase language is English-first for engineering consistency, while product-facing labels are mostly Indonesian.

## Environment Snapshot

| Item | Value |
| --- | --- |
| Python | 3.13+ |
| Django | 6.0.5 |
| Database | PostgreSQL 16 |
| Cache/Broker | None (In-Memory / LocMemCache) |
| UI | Django templates + Bootstrap 5 |
| Auth model | `apps.users.User` |
| Settings | `backend/config/settings.py` |
| Root URLs | `backend/config/urls.py` |

## Repository Map

```text
.
|- README.md
|- AGENTS.md
|- SYSTEM_MODEL.md
|- docker-compose.yml
|- .env.example
|- backend/
|  |- manage.py
|  |- requirements.txt
|  |- config/
|  |- apps/
|  |- templates/
|  |- static/
|  |- seed/
|  `- tests/
`- scripts/
```

## Source of Truth Rules

- Schema truth: `backend/apps/*/models.py`
- Route truth: `backend/config/urls.py` + `backend/apps/*/urls.py`
- Auth/permission truth: `backend/apps/core/decorators.py`, `backend/apps/users/access.py`
- Security/config truth: `backend/config/settings.py`
- App version truth: root `VERSION` and `backend/apps/core/versioning.py`
- Operational script truth: `scripts/`
- CSV import behavior truth: `backend/apps/*/admin.py` and resource classes

If documentation conflicts with code, code is authoritative until docs are corrected.

## Active Django Apps

- `core`: shared abstractions, dashboard, dynamic system settings (login platform label, logo/headers, and configurable distribution numbering templates), placeholder administration history pages for receiving and distribution archives, plus centralized `400/403/404/500` handlers and a `/maintenance/` `503` view
- `users`: custom user and `ModuleAccess` scope model
- `items`: master data and item catalog; items may be flagged as program item `[P]` (`is_program_item`) or essential `[E]` (`is_essential`)
- `stock`: stock entries, immutable transactions, stock card, location-based stock search, and stock transfer
- `receiving`: regular and planned receiving flows, custom CSV import endpoint in admin, quick-create lookup endpoints, custom `ReceivingTypeOption` support, and authenticated download links for `ReceivingDocument` attachments stored under `PRIVATE_MEDIA_ROOT`
- `distribution`: outbound distribution workflow, step-back/reset actions before distribution, issued batch/value snapshots on `DistributionItem`, object-level preparer assignment for regular/special-request preparation, and special-request numbering UI that preloads the next suggested number while requiring confirmation before manual override. LPLPO-generated draft distributions now lock item identity plus requested/approved quantities during edit so that the edit step is used only for batch selection, notes, and staffing. They also provide a dedicated reversal action that cancels the generated distribution and returns the parent LPLPO to `REJECTED_PUSKESMAS` with a required reason while the document is still pending distribution. User-facing manual create paths are `special_request_create` for permintaan khusus and `manual_lplpo_create` for manual LPLPO rollout/catch-up distributions; keep the generic `distribution_create` route reserved for internal or compatibility flows tied to broader distribution orchestration. Reset-to-draft, step-back, and delete now follow the same object-level assignee/fallback authorization rule as edit, prepare, and submit.
- `allocation`: pre-distribution planning and orchestration. Draft→Submitted→Approved lifecycle auto-generates one `Distribution` per facility on approval. Approved allocations may be stepped back to Submitted by approvers, which deletes the auto-generated child distributions so approval can be re-run cleanly. Allocation no longer stores a header-level funding source; item batch selection can span all available stock sources. Stock deduction deferred to delivery confirmation per distribution. Module is active and gated by `ModuleAccess` scopes like all other modules.
- `recall`: supplier return workflow
- `expired`: expired/disposal workflow and alerts page
- `stock_opname`: physical counting workflow
- `puskesmas`: ad-hoc requests from Puskesmas plus SBBK receiving input. All operational and report-facing surfaces now require a linked `user.facility` for every non-superuser account and enforce same-facility object access. Puskesmas `Riwayat Penerimaan` is sourced from `PuskesmasSBBK` / `PuskesmasSBBKItem`.
- `lplpo`: monthly reporting and stock requests from Puskesmas. All non-superuser queue, detail, print, verification, review, reject, finalize, and prefill surfaces now require a linked `user.facility` and are scoped to that facility. February onward, `penerimaan` autofill is sourced from same-facility/month SBBK rows and `harga_satuan` autofill uses the weighted average SBBK unit price, with the existing previous-month fallback when no SBBK exists.
- `reports`: report index with rekap, hibah receiving, procurement, expiry, outbound reporting views, and document numbering history for LPLPO/Special Request distributions. The combined outbound report remains on `/reports/pengeluaran/`, while the distribution module owns dedicated route-based report variants at `/distribution/report/`, `/distribution/report/special-requests/`, `/distribution/report/allocation/`, and `/distribution/report/lplpo/`.
  Puskesmas-side `Rekap Laporan Persediaan` also carries an LPLPO-derived asset valuation dimension summarized per kategori from per-line `harga_satuan`.
  Puskesmas-side `Rincian` and `Rekap Laporan Persediaan` filters use yearly, triwulan, and semester periods rather than a raw month selector.

## Permissions Model

There are two permission layers:

1. Django `has_perm` checks (groups/permissions)
2. Module scope fallback (`ModuleAccess`) used by `@perm_required`

`@perm_required` in `backend/apps/core/decorators.py` allows access if either layer grants permission. Keep this hybrid model in mind before changing authorization logic.

Permission denials should raise `PermissionDenied` so requests flow through the centralized `handler403` page instead of returning raw HTML fragments.

Module scopes:

- `NONE`, `VIEW`, `OPERATE`, `APPROVE`, `MANAGE`

Default scopes per role are defined in `backend/apps/users/access.py`.

### Specialized Roles (e.g. OPERATOR PUSKESMAS)

- `OPERATOR PUSKESMAS` role uses `facility` matching. Views in `puskesmas` and `lplpo` enforce strict facility isolation so that operators from one facility cannot read/write another facility's documents.
- Every non-superuser account using `puskesmas` or `lplpo` operational surfaces must have a linked `facility`; otherwise the request is denied with `403`.
- Super Admin (`is_superuser` / role `ADMIN`) is the only role exempt from `puskesmas` and `lplpo` facility scoping and may cross facility boundaries on those modules.
- Puskesmas report routes require `reports.view_reports` (or REPORTS module-scope VIEW fallback). Superusers may query all facilities; any non-superuser user is forced to their linked `facility` on those report querysets and receives `403` when no facility is linked.

## Workflow and Data Mutation Rules

- Never mutate historical `Transaction` rows; append-only behavior is expected.
- Stock-changing checkpoints happen during workflow actions (verify/prepare/distribute/complete depending on module), not arbitrary model saves.
- Stock transfer completion writes paired `OUT` and `IN` transactions.
- Receiving admin CSV import writes `Receiving`, `ReceivingItem`, updates/creates `Stock`, and writes `Transaction(IN)`.
- Receiving supports built-in and custom type codes; UI labels for non-built-in types are resolved from `ReceivingTypeOption`.
- `Distribution(distribution_type=LPLPO)` is normally system-generated from the PIC review submission in `lplpo_review`; the legacy `lplpo_finalize` route remains only to finish older `REVIEWED` rows and should not be treated as the primary workflow path. A separate `manual_lplpo_create` distribution route exists as a permanent operational fallback for mid-year rollout/catch-up work when Puskesmas LPLPO documents have not been backfilled yet. Do not expose `LPLPO` as a manual distribution type in the generic distribution create/edit flow.
- LPLPO workflow is `DRAFT -> SUBMITTED -> PIC_VERIFIED -> APPROVED -> CLOSED` for active documents. PIC review now records the review audit fields and immediately creates the linked draft `Distribution`, so there is no active Kepala approval checkpoint in the normal path. Legacy rows may still exist in `REVIEWED` or `REJECTED_PIC`, and the compatibility finalize/reject actions remain only for those older documents. Approved LPLPO documents that already spawned a draft distribution can still be explicitly returned to `REJECTED_PUSKESMAS` by cancelling that generated distribution before any stock distribution completes.
- LPLPO creation for each Puskesmas facility is locked to the active server-calendar year and must be contiguous from January. Users cannot skip months; the next create action must always target the earliest missing month in that same year.
- The first active-year January LPLPO is the yearly bootstrap baseline. Create/edit pages must explain that January `stock_awal` is entered manually from opening stock records, while February onward carries forward from the previous month's `stock_keseluruhan`, including negative balances when the prior period closed below zero.
- The same January bootstrap rule applies to `penerimaan`: January is entered manually and must not be auto-filled from SBBK rows; February onward uses same-facility/month `PuskesmasSBBKItem` totals as the autofill source.
- LPLPO no longer tracks `pembelian_puskesmas`; computed `persediaan` is `stock_awal + penerimaan`, so negative ending stock now acts as the safeguard for underreported balances.
- Saving, editing, or deleting an SBBK atomically re-syncs the same-month editable (`DRAFT` / `REJECTED_PUSKESMAS`) LPLPO rows only. Once a facility-month LPLPO is `SUBMITTED` or beyond, SBBK mutation for that period is blocked.
- The same January bootstrap rule now applies to `harga_satuan`: January is entered manually as the yearly asset-valuation baseline; February onward prefers a weighted average of distributed `issued_unit_price` for that facility/month and falls back to the previous month's LPLPO unit price when no new receipt exists.
- LPLPO creation auto-fills `stock_awal` from the immediately previous month's LPLPO for the same facility when one exists and is not `REJECTED_PUSKESMAS` or `REJECTED_PIC`; the carry-over no longer waits for the prior document to reach `CLOSED`.
- LPLPO-generated draft distributions preserve `quantity_requested=permintaan_jumlah` and `quantity_approved=pemberian_jumlah`, but those line quantities and item rows are locked on the distribution edit screen; staff use that step only to choose stock batches, update notes, and adjust staff/header metadata before preparation. Manually created LPLPO distributions do not have an `lplpo_source` document and therefore remain editable like normal draft distributions while still using the LPLPO numbering/report bucket.
- Regular and special-request distributions now use the preparation sequence `DRAFT/REJECTED -> PREPARED -> SUBMITTED -> VERIFIED -> DISTRIBUTED`. Assigned `DistributionStaffAssignment` users control draft/rejected preparation and submission; when no preparers are assigned, approve-scope users remain the fallback managers. The same assignee-or-approve fallback rule also gates reset-to-draft, step-back, and delete for mutable distributions.
- Distribution numbering templates for `LPLPO` and `SPECIAL_REQUEST` are user-configurable through `SystemSettings`; supported placeholders are `{seq}` and `{year}` and sequence counters remain scoped per distribution type and matched against the active template.
- `Distribution(distribution_type=ALLOCATION)` is system-generated from `allocation` approval; one per facility, starts in `VERIFIED` status, quantities are locked and cannot be edited.
- Allocation approval atomically creates `Distribution` + `DistributionItem` records for each facility. Stepping an allocation back from `APPROVED` to `SUBMITTED` deletes those child distributions so they can be regenerated on the next approval. Stock deduction is deferred to per-distribution delivery confirmation.
- Allocation auto-transitions to `PARTIALLY_FULFILLED` when any child distribution is delivered, and `FULFILLED` when all are delivered.
- Availability checks across distribution, recall, expired, transfer, and several selectors use `Stock.available_quantity` (`quantity - reserved`), but current workflows do not automatically increment or decrement `reserved` during distribution processing.

## Documentation Maintenance Contract

When code changes affect schema, routes, permissions, settings, or scripts, update all impacted docs in the same PR:

- `README.md`
- `AGENTS.md`
- `SYSTEM_MODEL.md`
- `docs/developer_guide.md` when setup, testing, release, or documentation process guidance changes
- `backend/seed/README.md` (if CSV schema/semantics changed)

## Context7 Reference Policy

Use Context7 as primary guidance for third-party best practices. Current reference library IDs:

- Django: `/django/django`
- django-import-export: `/websites/django-import-export_readthedocs_io_en`
- django-axes: `/jazzband/django-axes`

Apply these principles:

- Keep `AUTH_USER_MODEL` explicitly configured before relying on auth migrations.
- Keep `SECRET_KEY` environment-driven.
- Keep `DEBUG=False` production hardening documented and synchronized with settings.
- Keep import workflow docs aligned with dry-run/confirm semantics from django-import-export.
- Keep axes backend ordering and middleware placement documented exactly as configured.
- Keep sensitive POST throttling settings and the centralized `429` behavior documented exactly as configured.

## Development Commands

```bash
docker compose up -d
cd backend
python manage.py migrate
python manage.py runserver
python manage.py app_version
```

Windows test helper:

```powershell
.\scripts\run-django-test.ps1 -Target apps.items
.\scripts\run-django-test.ps1 -Target apps.core.tests -KeepDb
```

## Quality Checklist for Agent PRs

Before opening a PR, verify:

- Routes documented in markdown exist in URLconfs.
- All model/table names in docs match current models.
- Env vars in docs exist in `.env.example` or settings usage.
- Security behavior in docs mirrors `backend/config/settings.py`.
- CSV column docs match actual import resources/forms/admin parser logic.

## Sensitive POST Throttling

- `django-axes` remains the login brute-force control.
- Additional authenticated POST throttling uses `django-ratelimit`.
- Counters use a local memory cache (`CACHES["default"]` → `RATELIMIT_USE_CACHE`) so limits are tracked in-process.
- `RATELIMIT_FAIL_OPEN=True` is the default so rate-limiting degrades gracefully if there are issues with the cache.
- Current settings-backed knobs are `USER_BULK_ACTION_RATE_LIMIT`, `USER_MUTATION_RATE_LIMIT`, `USER_PASSWORD_RESET_RATE_LIMIT`, `PASSWORD_CHANGE_RATE_LIMIT`, and `PUSKESMAS_SBBK_MUTATION_RATE_LIMIT`.
- Throttled requests must continue through the centralized error pipeline and render as HTTP `429`.
- `@user_mutation_ratelimit` covers all user mutation endpoints: create, update, toggle-active, and delete.

## URL Routing Convention

**All URL patterns MUST end with a trailing slash (`/`)** to prevent 301 redirects caused by Django's `APPEND_SLASH` middleware.

### Rules

1. **URL patterns in `urls.py`**: Every `path()` must end with `/`
   - ✅ `path("create/", views.create, name="create")`
   - ✅ `path("<int:pk>/", views.detail, name="detail")`
   - ❌ `path("create", views.create, name="create")`
   - ❌ `path("<int:pk>", views.detail, name="detail")`

2. **Test client calls**: Use `reverse()` when possible, or ensure hardcoded URLs have trailing slashes
   - ✅ `self.client.get(reverse("app:create"))`
   - ✅ `self.client.get("/app/create/")`
   - ❌ `self.client.get("/app/create")`

3. **Templates**: Always use `{% url %}` template tag (which resolves correctly)
   - ✅ `<a href="{% url 'app:create' %}">`
   - ❌ `<a href="/app/create">`

4. **Settings**: `APPEND_SLASH = True` is explicitly set in `backend/config/settings.py`

### Validation

URL consistency tests in `apps.core.tests.test_url_consistency` automatically verify:
- All URL patterns end with trailing slashes
- No hardcoded test URLs are missing trailing slashes

Run with: `.\scripts\run-django-test.ps1 -Target apps.core.tests.test_url_consistency`

## Notes

- Do not claim REST API/React production paths as implemented; those are planned.
- Keep terminology consistent: use "module scope" for `ModuleAccess` and "Django permissions" for `has_perm` checks.
