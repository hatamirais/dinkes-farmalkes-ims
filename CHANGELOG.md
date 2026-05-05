# Changelog
<!-- markdownlint-disable MD024 -->

All notable changes to this project are documented in this file.

The format is based on Keep a Changelog and follows Semantic Versioning (`MAJOR.MINOR.PATCH`).

## [Unreleased]

## [1.21.0] - 2026-05-05

### Added

- Centralized `400/403/404/500` error-page handling with a shared standalone layout, contextual fallback navigation, and a dedicated `/maintenance/` preview route that returns `503 Service Unavailable`.
- New standalone templates for `400`, `403`, and `503`, plus a shared `errors/status.html` shell and CSP-safe `backend/static/js/error-page.js` for back-navigation fallback behavior.
- Focused regression coverage for the error-page flow, including anonymous 404 fallback, permission-denied rendering, admin middleware denial, bad-request fallback behavior, and the maintenance route.

### Changed

- Documentation now records the centralized error handlers, the maintenance preview route, and the expectation that permission denials should flow through the shared `403` experience.
- Admin-panel access denial in middleware and Puskesmas request authorization failures now use the centralized forbidden-page path instead of returning raw inline HTML fragments.

### Fixed

- Error-page navigation is now compatible with the repository's strict `Content-Security-Policy` by moving client-side fallback logic into an external script instead of inline JavaScript.
- Common production error states now present a consistent recovery path back to the previous page or the appropriate authenticated fallback destination instead of a hardcoded dashboard-only link.

## [1.20.2] - 2026-05-04

### Changed

- Distribution documentation now explicitly records `special_request_create` as the user-facing manual create path while keeping the generic `distribution_create` route reserved for internal or compatibility orchestration flows.

### Fixed

- Distribution list, Special Request list, and distribution detail pages now require `distribution.view_distribution`, so only Instalasi Farmasi users with assigned distribution access can open those read routes.
- Added regression coverage for the versioned Special Request form asset so stale cached browser validation is less likely to slip back in unnoticed.

## [1.20.1] - 2026-05-04

### Fixed

- Special Request distributions now allow `Kuantitas Disetujui` to exceed `Kuantitas Diminta` when operators need to fulfill a larger approved quantity, while still preserving the existing batch stock availability check.
- Removed the stale browser-side validation that kept flagging Special Request approved quantities as invalid after the server-side rule changed.
- Versioned the Special Request form script include so browsers stop reusing cached validation logic after frontend updates.
- Restored the main dashboard response path for non-Puskesmas users so `/` no longer raises `ValueError` by falling through without an `HttpResponse`.

## [1.20.0] - 2026-05-04

### Added

- New `Administrasi` sidebar entries for `Riwayat Penerimaan` and `Riwayat Pengeluaran`, each backed by an MVP placeholder page to separate archive work from the operational transaction screens.

### Changed

- Documentation now records the new administration history routes and their intended follow-up scope as part of the feature baseline.

## [1.19.6] - 2026-05-04

### Changed

- Permintaan Khusus now preloads the next document number from the active numbering rule so operators can confirm the value before saving.

### Fixed

- Manual edits to Permintaan Khusus document numbers are now gated behind an explicit warning modal, while unchanged suggested values still follow the normal auto-generation path.

## [1.19.4] - 2026-04-28

### Fixed

- **Allocation-generated distributions dead-end status**: Replaced `GENERATED` (Dibuat Otomatis) status with `VERIFIED` (Terverifikasi) for allocation-generated distributions, since the allocation approval already validates stock, batch, and quantities. This eliminates the dead-end where no workflow actions were available on the distribution detail page.
- **Allocation distributions showing disruptive actions**: Distribution detail page now hides Edit, Delete, Reset to Draft, and Step Back for allocation-type distributions. These lifecycle actions belong to the parent allocation. A "Lihat Alokasi Induk" link is shown instead.

### Changed

- Allocation-generated distributions now record the allocation approver as `verified_by` with `verified_at` timestamp.
- Data migration 0007 converts existing `GENERATED` rows to `VERIFIED`.

## [1.19.3] - 2026-04-28

### Fixed

- **Jumlah Disetujui exceeding Jumlah Diminta** (closes [#11](https://github.com/hatamirais/dinkes-farmalkes-ims/issues/11)): Added model-level `DistributionItem.clean()` validation that raises `ValidationError` when `quantity_approved > quantity_requested`, enforcing the constraint at all layers (admin, ORM, service).
- **No real-time feedback on Distribution form**: Added client-side JS validation that shows an inline red error and disables the submit button immediately when approved quantity exceeds requested quantity, without requiring a full form POST round-trip.

## [1.19.2] - 2026-04-28

### Added

- **Government-style Kartu Stok print template**: New standalone print page (`/stock/stock-card/<id>/print/`) renders per-sumber-dana stock cards matching the official physical Kartu Stok form layout, with institutional header (kop surat) from `Pengaturan Sistem`, A4 portrait page setup, and CSS page numbering.
- **Per-Sumber-Dana stock cards**: Kartu Stok now groups transactions by funding source, rendering each `Sumber Dana` as its own collapsible card on screen and a separate page when printing.
- **9-column transaction table**: Kartu Stok table columns now match the physical form: TGL, DOKUMEN, DARI/KEPADA, NO BATCH, EXP DATE, TERIMA, KELUAR, SISA, KETR.
- **Sumber Dana filter**: Kartu Stok screen view now includes a `Sumber Dana` dropdown alongside the existing date and location filters.
- **DARI/KEPADA column**: Transactions now display the supplier name (for receivings) or facility name (for distributions) in a dedicated column.
- **Tahun Anggaran per card**: Each sumber dana card displays the fiscal year derived from the earliest receiving date for that funding source and item.

### Fixed

- **Unit price Rp 0 on initial-import funding sources**: Unit price lookup now uses a 3-tier fallback (ReceivingItem → Stock.unit_price → Transaction.unit_price), resolving cases where the Receiving header sumber_dana differs from the Stock entry sumber_dana (e.g., initial SALDOAWAL imports).
- **Year displayed as "2.026"**: Prevented Django's `USE_THOUSAND_SEPARATOR` from formatting year integers with thousand separators in Kartu Stok metadata fields.
- **Cetak button blocked by CSP**: Replaced inline `onclick="window.print()"` with the CSP-compliant `data-action="print"` pattern on the stock card print page.

## [1.19.1] - 2026-04-27

### Added

- `Pengaturan Sistem` now includes a live numbering-rule preview card so administrators can see sample LPLPO and Permintaan Khusus document numbers while editing templates.

### Changed

- The settings sidebar is reordered to show `Informasi`, `Logo Saat Ini`, and `Preview Rule` in a clearer sequence.

### Fixed

- Anonymous access to `/settings/` now redirects to the login page instead of raising an `AttributeError`.
- Numbering preview examples on the settings page now update live as template values change.

## [1.19.0] - 2026-04-27

### Added

- Institutional numbering rules for generated `LPLPO` and `Permintaan Khusus` distribution documents using `440/{seq}/SBBK.RF/{year}` and `440/{seq}/KD.F/{year}` with separate yearly counters per document type.
- New `Laporan > Riwayat Penomoran` page for LPLPO and Permintaan Khusus numbering history, including status display, summary modal, and a button to open the full workflow in a new tab.
- Items can now be marked as essential with a dedicated `[E] Esensial` tag surfaced in item management screens and imports.
- `Pengaturan Sistem` now lets administrators edit the numbering templates for LPLPO and Permintaan Khusus distribution documents using `{seq}` and `{year}` placeholders.

### Changed

- Distribution document numbering is now generated through a shared helper so rule-based numbering and legacy fallback numbering are managed from one place.
- Rule-based distribution numbering now reads from dynamic system settings, and yearly counters are computed from the active template even when `{year}` is not placed at the end of the format.

## [1.18.0] - 2026-04-24

### Added

- New `Permintaan Khusus` submenu under `Pengeluaran` that opens a dedicated special-request flow backed by the existing distribution models and form.
- Special-request create/edit reuses the generic distribution form but forces `distribution_type = SPECIAL_REQUEST` and hides the `Distribution Type` field from the UI.
- `Distribusi` list is now explicitly a history view for all pengeluaran with filters and a new `Laporan Pengeluaran` button to generate/export a report (links to the existing reports view).
- Dashboard quick action updated to create a `Permintaan Khusus` directly.
- Focused tests added for the special-request create flow, list filtering, and report-button visibility.

### Changed

- `Distribusi` under the Pengeluaran menu is now primarily a read-only history/reporting surface rather than the primary create entry point; creation for special requests is served via `Permintaan Khusus`.

## [1.17.0] - 2026-04-23

### Security

- Sanitize `system_settings.logo` rendering to prevent XSS via crafted logo URLs. The fix centralizes URL validation in a template filter `safe_media_url` and uses it across the login, base layout, settings form, and report print headers.

### Fixed

- Removed an unregistered template tag usage that caused template loading errors in some deployments; consolidated the filter into the existing `number_format` templatetag module.

## [1.16.2] - 2026-04-23

### Changed

- Allocation distribution tracking cards now open the Distribution detail in a new browser tab to preserve the current Allocation view when operators navigate to child distributions.
- The generic Distribution create/edit form no longer exposes `Alokasi` as a manual `distribution_type` option; `ALLOCATION` distributions are system-generated from `Allocation` approval flows only.

## [1.16.1] - 2026-04-23

### Fixed

- Prevent DOM-based XSS by replacing unsafe `innerHTML` usage with explicit DOM construction and `textContent` in search and allocation UIs.

### Security

- Hardened redirect handling by using the `URL` API for client-side navigation and constructing server-side redirect targets via `reverse()` with encoded query parameters.

## [1.16.0] - 2026-04-22

### Added

- Allocation approvers can now step an allocation back one stage from `Disetujui` to `Diajukan`, which removes the auto-generated child distributions so approval can be re-run cleanly.

### Changed

- Allocation detail now treats distribution tracking cards as direct navigation targets to the matching `Detail Distribusi` page while preserving the inline workflow action buttons on each card.

## [1.15.1] - 2026-04-21

### Changed

- Allocation no longer stores a header-level `sumber_dana`; item selection can now span all available stock sources while downstream distribution and transaction records still inherit funding source from the selected stock batch.
- Allocation create flow now includes an optional `Judul Alokasi` document header field for clearer reporting and future print output.

### Fixed

- Allocation facility and staff multi-select controls now correctly apply `Pilih Semua`, `Bersihkan`, and selection summary updates.
- Allocation create form now renders the document date in HTML date input format and shows richer facility and staff picker labels for faster operator review.

## [1.15.0] - 2026-04-21

### Added

- **Orchestrator Architecture**: `Allocation` approval now atomically auto-generates `Distribution` records (status: `GENERATED`) for each facility.
- **Wizard Form**: Replaced the previous single-page entry with a robust 4-step wizard form for Allocation creation featuring a dynamic client-side allocation matrix.
- **Auto-closing Lifecycle**: Allocations automatically transition to `PARTIALLY_FULFILLED` and `FULFILLED` based on child distribution delivery progress.
- **UI Enhancements**: Visual status timeline and interactive distribution tracking cards added to the detail view; delivery progress visualization and `sumber_dana` filtering added to the list view.

### Changed

- **Deferred Stock Deduction**: Stock is no longer deducted at Allocation approval. It is now correctly deducted only when individual child `Distribution` records are marked as delivered.
- **Feature Flag Runtime Removal**: Allocation runtime access no longer branches on `FEATURE_ALLOCATION_UI_ENABLED`; the module is governed by `ModuleAccess` scopes, while the setting remains for compatibility and tests.

## [1.13.0] - 2026-04-20

### Changed

- New `allocation` module foundation with dedicated models, migrations, module
  access scope, admin registration, and separate routing from generic
  Distribusi.
- Initial Alokasi list, detail, create, and edit screens with header-level
  multi-facility selection, multi-staff `Petugas` assignment, and one-row-one-
  facility item entry.
- Allocation-specific tests covering document numbering, validation, routing,
  access control, create flow, and edit flow behavior.
- LPLPO-generated distributions are now treated as system-generated workflow
  outputs instead of a normal manual distribution method in the generic
  Distribusi form.
- Instalasi Farmasi navigation now surfaces submitted LPLPO processing under the
  outbound transaction flow instead of placing it in the Puskesmas section.
- The main LPLPO queue for Instalasi Farmasi now focuses on documents that have
  already been submitted by Puskesmas operators.

### Added

- Submission-month and submission-year filters on the Instalasi Farmasi LPLPO
  queue for faster operational review.
- Printable submitted-LPLPO report view based on the current queue filters.

### Fixed

- Manual creation of `distribution_type=LPLPO` is now blocked for regular
  distribution create/edit flows, ensuring the type is reserved for finalized
  LPLPO documents only.

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

- **Global Context Integration**: Implemented a global context processor ensuring consistent branding across the entire UI lifecycle.

### Changed

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
