# Changelog
<!-- markdownlint-disable MD024 -->

All notable changes to this project are documented in this file.

The format is based on Keep a Changelog and follows Semantic Versioning (`MAJOR.MINOR.PATCH`).

## [1.10.0] - 2026-04-09

### Added

- **Rumah Sakit Borrow/Swap Workflow**: Added `Pinjam RS` and `Tukar RS` distribution types so Instalasi Farmasi can record outbound RS documents without creating a separate module yet.
- **RS Return Settlement Tracking**: Added `Pengembalian RS` as a receiving type with line-level linkage back to the originating RS distribution item, allowing the system to track outstanding quantities from actual documents instead of manual reminders.
- **Issued Batch and Book-Value Snapshots**: Distribution lines now preserve the issued batch, expiry, funding source, and unit value at the time stock is distributed for stronger audit visibility.
- **Outstanding RS Monitoring UI**: Added dashboard and distribution-detail visibility for outstanding RS quantities and carrying values.

### Changed

- RS settlement is intentionally strict for this release: returns may use different batch and expiry data, but must settle the same item as the original RS distribution line.
- Project documentation now reflects the RS borrowing/return workflow and the settlement-link model used for audit tracking.

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
