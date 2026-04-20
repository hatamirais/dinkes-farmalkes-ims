# Changelog
<!-- markdownlint-disable MD024 -->

All notable changes to this project are documented in this file.

The format is based on Keep a Changelog and follows Semantic Versioning (`MAJOR.MINOR.PATCH`).

## [1.12.3] - 2026-04-19

### Changed

- Planned `Penerimaan` follow-up screens now focus only on outstanding order
  lines. Fully received items are removed from the `Terima Barang` page, while
  partially received items now show only the remaining quantity under `Sisa
  Rencana`.
- Planned receiving line labels on the `Terima Barang` page were simplified for
  faster operator scanning: `Item Pesanan` and `Lokasi` now display names only,
  without internal reference codes.
- Saving a planned receiving document now presents an explicit confirmation
  warning so operators re-check `Harga Satuan` before the plan is created.

### Fixed

- Planned receiving submissions no longer fail because formatted read-only
  quantity displays such as `10.000,00` were being re-validated as raw numeric
  input during POST processing.
- Mixed partial and full receipt submissions now complete correctly in one
  transaction, preserving the intended `PARTIAL` workflow when only some order
  quantities remain outstanding.
- Invalid planned receipt submissions now re-render with bound field values and
  inline row-level errors, replacing the previous generic toast-only failure
  path that discarded user input and obscured the actual validation problem.
- Zero-quantity receipt rows are now treated as intentional no-op lines instead
  of forcing supporting fields or incorrectly pushing the parent plan into
  `PARTIAL` state.
- Planned receiving line items now reject empty or zero `Harga Satuan` during
  plan creation, preventing ambiguous downstream receipt pricing.

## [1.12.1] - 2026-04-16

### Changed

- Regular and planned `Penerimaan` create forms no longer expose the `facility`
  field for generic Instalasi Farmasi receiving.
- Receiving form headers now mark required fields more clearly and show a
  document-number placeholder indicating that the number will be auto-generated
  when left blank.

### Fixed

- Generic receiving screens now better reflect the warehouse receiving flow,
  reducing data entry noise and preventing users from inferring that a facility
  selection is required for standard receiving.

## [1.12.0] - 2026-04-14

### Security Audit

This release completes a comprehensive security hardening audit focused on
enabling a strict Content Security Policy, establishing automated vulnerability
detection, and improving production operational logging.

### Added

- **Content Security Policy (CSP) Enforcement**: New `CSPMiddleware` injects a
  strict `Content-Security-Policy` header on every HTTP response. The policy
  enforces `script-src 'self'` which blocks all inline JavaScript execution,
  mitigating the primary XSS attack vector. The full policy also restricts
  `frame-ancestors`, `form-action`, and `base-uri` to `'self'` for defense in depth.
- **10 External JavaScript Modules**: All interactive logic previously embedded
  as inline `<script>` blocks has been extracted into dedicated external `.js`
  files (`confirm-actions.js`, `quick-create.js`, `distribution-form.js`,
  `item-form.js`, `puskesmas-form.js`, `lplpo-edit.js`, `expired-alerts.js`,
  `rekap-filter.js`, `user-form.js`, `login.js`) loaded via `<script src>` tags.
- **Declarative UI Event Handling**: Replaced all 40+ inline event handlers
  (`onclick`, `onsubmit`, `onchange`) across 27 templates with data-attribute
  driven patterns (`data-action`, `data-confirm-submit`, `data-confirm-click`,
  `data-action-remove-row`, `data-quick-create`) processed by a single global
  handler module.
- **Security Audit Logging**: Signal-based logging for authentication events
  (`login_success`, `logout`, `login_failed`) with structured metadata including
  username, client IP (proxy-aware via `X-Forwarded-For`), and user agent.
- **Automated Dependency Scanning**: GitHub Actions CI workflow using `pip-audit`
  that runs on every push and pull request to protected branches, failing the
  pipeline on any known vulnerability (`--strict` mode).
- **Custom Error Pages**: Production-safe `404.html` and `500.html` templates
  that prevent Django debug information from leaking in production.

### Changed

- **DEBUG Default Hardened**: `DEBUG` environment variable now defaults to
  `False` instead of `True`. Development environments must explicitly opt in
  with `DEBUG=True` in `.env` to prevent accidental production exposure.
- **Structured Logging to stdout**: All Django logging (`django`, `django.request`,
  `security`, `axes`) now routes exclusively to stdout via `StreamHandler`,
  replacing any file-based logging. This ensures compatibility with Docker log
  drivers and centralized log aggregation without filesystem dependencies.
- **Templates Refactored for CSP**: 27 templates across all application modules
  (receiving, distribution, items, users, puskesmas, lplpo, expired, recall,
  stock opname, reports) updated to reference external JS files and use
  declarative `data-*` attributes in place of inline JavaScript.

## [1.11.0] - 2026-04-09

### Added

- **Issued Batch and Book-Value Snapshots**: Distribution lines now preserve the issued batch, expiry, funding source, and unit value at the time stock is distributed for stronger audit visibility.

### Changed

- Project documentation now reflects the issued batch and book-value snapshot model used for audit tracking.

## [1.9.0] - 2026-04-07

### Added

- **Dynamic System Settings**: Introduced a centralized configuration module (`SystemSettings`) allowing administrators to personalize the application profile.
- **Personalized Dashboard & Headers**: Support for custom facility names, logos, and document header titles that automatically propagate to all printable reports (Stock Opname, LPLPO, and Inventory Reports).
- **Global Context Integration**: Implemented a global context processor ensuring consistent branding across the entire UI lifecycle.

### Changed

- Refactored all report templates to utilize dynamic system settings instead of hardcoded placeholders.
- Updated sidebar to include "Pengaturan" module for Admin users.

## [1.6.1] - 2026-04-03

### Changed

- Notification UX now uses a compact navbar dropdown that summarizes actionable activity counts per module instead of rendering the full notification panel on the dashboard.
- Notification aggregation now stays focused on items that still require user attention, with terminal workflow states excluded from both the navbar badge and dropdown summary.

### Fixed

- Dashboard rendering no longer performs the extra grouped notification queries previously used for the inline notification center, reducing page-level notification overhead.

## [1.6.0] - 2026-04-02

### Added

- **Unified Notification Center** providing at-a-glance visibility into pending documents across all workflows. The notification hub aggregates pending Penerimaan, Distribusi, Recall/Retur, Kadaluarsa, Stock Opname, Permintaan Puskesmas, and LPLPO records with document-number, status, and date for up to three recent items per module. Administrators and workflow operators can now quickly navigate to precise action items without manual list traversal.
- **Persistent Notification Badge** in the top navigation bar (bell icon) displaying real-time count of documents awaiting action, respect-ing each user's module access level. Badge visibility is filtered by role (PUSKESMAS users do not see the badge) and access grants, ensuring end-users only see actionable items relevant to their authority.
- **Global Notification Context Processor** (`nav_notifications`) that efficiently computes pending-document counts on every page request using optimized COUNT queries, reducing latency and providing consistent notification state across the application.

### Changed

- Dashboard layout now prioritizes actionable intelligence by moving the Notification Center to the top of the page above all KPI cards, surfacing time-sensitive workflow items immediately upon authentication.

## [1.5.1] - 2026-04-02

### Changed

- Release workflow now provisions PostgreSQL for Django test execution during version verification.

## [1.5.0] - 2026-04-02

### Changed

- LPLPO behavior for Puskesmas operators now uses facility-scoped dashboard data, role-specific status wording, and stricter navigation/access boundaries around review and distribution flows.
- Permintaan Khusus behavior for Puskesmas operators now auto-binds requests to the operator's own facility and simplifies barang selection labels to item names only.

## [1.4.5] - 2026-04-01

### Added

- LPLPO test coverage for facility isolation, penerimaan prefill, stock carry-forward, finalize flow, and distribution auto-close behavior.

### Changed

- LPLPO access control now consistently enforces facility-scoped visibility for Puskesmas users across read and edit flows.
- LPLPO review stock display now uses available stock instead of total stock quantity.
- Puskesmas group provisioning now grants LPLPO permissions instead of distribution visibility.

## [1.0.4] - 2026-03-23

### Added

- Bootstrap toast-based flash message display in the authenticated UI, including client-side handling and styling updates.

### Changed

- Distribution reset-to-draft status check now includes `DISTRIBUTED` in `distribution_detail` flow conditions.

## [1.1.1] - 2026-03-23

### Added

- Distribution print view: include stock batch, expiry date columns and "Kepala Instalasi Farmasi" signature field.

### Changed

- Print layout updated to support three signature columns and display assigned staff and kepala instalasi.

## [1.0.3] - 2026-03-23

### Added

- GitHub Actions workflow `.github/workflows/release-on-version-change.yml` to automatically verify versioning, create tag `v<version>`, and publish a GitHub Release when `VERSION` changes on `main`.
- Pull request template checklist item requiring `VERSION` and `CHANGELOG.md` updates for release-impacting changes.

### Changed

- Updated `README.md` with automatic release behavior for `VERSION` bumps.
- Updated `.gitignore` to allow tracking `.github/` workflow files.

## [1.0.2] - 2026-03-18

### Added

- Root `VERSION` file as the single source of truth for application version.
- Semantic version helpers in `backend/apps/core/versioning.py`.
- Django management command `python manage.py app_version` with `--major`, `--minor`, `--patch`, and `--set` options.
- Template context processor to expose app version in templates.
- Header badge in authenticated UI showing the active app version.
- Unit tests for semantic version parsing, bumping, and file read/write behavior.

### Changed

- Settings now load `APP_VERSION` from the root `VERSION` file.
- Project documentation updated to include the versioning workflow and command usage.

### Notes

- `app_version` command name is used to avoid collision with Django's built-in `version` command.
