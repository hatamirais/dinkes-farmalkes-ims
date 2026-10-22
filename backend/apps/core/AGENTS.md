# core AGENTS.md

App-specific guidance for shared configuration, permissions, numbering, error handling, and infrastructure.

## Purpose

`core` owns shared abstractions, the dashboard, system settings, centralized error handlers, maintenance mode, trusted client-IP resolution, rate-limit plumbing, app versioning, and official document numbering.

## Permission And Error Infrastructure

- `@perm_required` allows access when either the required Django permission or sufficient `ModuleAccess` scope grants it.
- Permission failures raise `PermissionDenied` and flow through the centralized `handler403`; do not return ad-hoc denial fragments.
- `/settings/` and `/settings/numbering/` do not use module-scope fallback. They allow only superusers and users whose role is `ADMIN` or `KEPALA`.
- Throttled requests use the centralized error pipeline and render HTTP `429`.

## Document Numbering

- `DocumentNumberRule`, `DocumentNumberSequence`, `DocumentNumberIssue`, and `apps.core.numbering` are the source of truth for official non-Puskesmas numbering.
- Rules are configured at `/settings/numbering/`; counters are internal and cannot be edited through workflow forms.
- Template validation reserves space for the full 19-digit `PositiveBigIntegerField` sequence, not merely the configured minimum padding.
- Period selection uses the workflow business date. Live issue/void timestamps use server time for audit.
- Once an issue exists, its exact business date and scope are immutable. Repeated issuance must reject date/scope mismatches.
- Issued strings are globally unique across rules and never reused after voiding. Database uniqueness and collision retry protect concurrent counters.
- `DocumentNumberIssue.issued_at` is nullable. Migrated history with no reconstructable checkpoint remains unknown; never substitute migration time.
- Historical cross-workflow duplicates remain unrenumbered: one issue is canonical, additional copies are marked `is_legacy_duplicate`, and every copy reserves the value while the conditional constraint protects normal/new rows.
- Legacy Distribution `BORROW_RS` and `SWAP_RS` rows stay outside active rules, but their nonblank numbers remain global reservations during preview and issuance.
- Legacy Distribution templates that fail current validation fall back to safe defaults during migration; valid custom templates are preserved.
- Puskesmas documents and the LPLPO parent document remain outside this numbering system.

Workflow-specific issuance checkpoints, dates, migration metadata, and delete/void rules live in each workflow app's `AGENTS.md`.

## Authentication, Client IP, And Throttling

- `django-axes` controls login brute force by username and resolved source IP using `AXES_LOCKOUT_PARAMETERS = ["username", "ip_address"]` and the configured `AXES_CLIENT_IP_CALLABLE`.
- `AXES_RESET_ON_SUCCESS=False`; project-owned successful-login cleanup deletes only the successful username's failed attempts, never unrelated attempts sharing an IP.
- Login uses Django `LoginView` with `apps.core.forms.CrispyAuthenticationForm`; the Tailwind template renders its bound fields and keeps their widget attributes and generic errors. Do not hand-code username/password inputs in `registration/login.html`.
- Authentication and centralized error logs use `apps.core.client_ip.get_client_ip()`. Trust `X-Forwarded-For` only when the immediate peer matches `AUTH_AUDIT_TRUSTED_PROXIES`; otherwise use `REMOTE_ADDR`.
- Authenticated POST throttling uses `django-ratelimit`, `CACHES["default"]`, and `RATELIMIT_USE_CACHE`. `RATELIMIT_FAIL_OPEN=True` is the default graceful-degradation policy.
- Settings-backed limits include `LOGIN_RATE_LIMIT`, `USER_BULK_ACTION_RATE_LIMIT`, `USER_MUTATION_RATE_LIMIT`, `ITEM_MUTATION_RATE_LIMIT`, `RECEIVING_MUTATION_RATE_LIMIT`, `USER_PASSWORD_RESET_RATE_LIMIT`, `PASSWORD_CHANGE_RATE_LIMIT`, `PUSKESMAS_RECEIPT_CONFIRMATION_MUTATION_RATE_LIMIT`, `PUSKESMAS_CONSUMPTION_MUTATION_RATE_LIMIT`, `PROCUREMENT_MUTATION_RATE_LIMIT`, and `LPLPO_IMPORT_RATE_LIMIT`. `PUSKESMAS_SBBK_MUTATION_RATE_LIMIT` remains a compatibility fallback.

## Configuration Documentation

- Keep `AUTH_USER_MODEL` explicit and `SECRET_KEY` environment-driven.
- Keep `DJANGO_DEBUG=False` production guidance, WhiteNoise middleware, and `STORAGES["staticfiles"]` documentation aligned with settings.
- Keep import documentation aligned with django-import-export dry-run/confirm semantics.
- Keep axes backend/middleware, trusted-proxy behavior, rate-limit behavior, and centralized `429` documentation synchronized with implementation.
