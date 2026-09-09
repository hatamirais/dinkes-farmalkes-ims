# Changelog
<!-- markdownlint-disable MD024 -->

All notable changes to this project are documented in this file.

The format is based on Keep a Changelog and follows Semantic Versioning (`MAJOR.MINOR.PATCH`).

## [Unreleased]

### Added

- Added an initial server-rendered mobile/PWA stock surface under `/mobile/`, with mobile stock search, program/therapeutic filters, and item stock-card access using the existing Django session and stock permissions.
- Added PWA install/discovery prompts so stock users can find the mobile surface from the desktop shell and install it from mobile browsers that support PWA installation.

### Removed

- Retired the experimental DRF reporting API surface, including `/api/v1/reporting/`, generated OpenAPI docs routes, bearer-secret reporting settings, and unused DRF/drf-spectacular dependencies.

## [1.31.11] - 2026-09-07

### Fixed

- Item quick-create modals now read the CSRF token from the rendered page token instead of the HttpOnly CSRF cookie, restoring therapeutic class creation when `CSRF_COOKIE_HTTPONLY=True`.

## [1.31.10] - 2026-09-04

### Fixed

- Core login-page asset version tests now follow the configured app version so release checks continue to pass after version bumps.

## [1.31.9] - 2026-09-02

### Added

- Item list pagination now includes a bottom rows-per-page selector with 25, 50, and 100 row options.

### Changed

- Redesigned the item list page with labeled filters, a denser table layout, and a single bottom pagination toolbar that combines row range, page size, and page navigation.
- Item list minimum stock values now hide unnecessary trailing zero decimals.
- Procurement and planned receiving quantity summaries now show plain decimal values without localized thousand separators or forced trailing zeroes.
- Procurement contract detail links to the linked receiving plan now open in a new tab.
- Procurement SPJ input forms now use a wider card layout and give the Barang contract-line field more room while preserving usable horizontal scrolling on narrow screens.
- Procurement and receiving date inputs now use `DD/MM/YYYY` text entry for Indonesian users while preserving calendar picker controls.

### Fixed

- SPJ detail pages now hide the `Batalkan SPJ` action after the linked receiving plan has receiving activity or is already partially/fully received or closed.
- Procurement and receiving unit price inputs now accept comma decimals and reject dot decimal separators with a clear Indonesian validation message.
- Barang autocomplete dropdowns now stay usable near the bottom of procurement and receiving forms without clipping or trapping page scroll.

## [1.31.8] - 2026-08-26

### Added

- Expired document detail pages now show each batch's expiry date next to the Batch column.
- Stock opname detail pages now include a refreshed `Stok Update` column alongside the frozen `Stok Sistem` snapshot and the counted `Stok Fisik` value.
- Added a full stock opname print report at `/stock-opname/<pk>/report/`, including all counted rows and signature blocks for `KEPALA` plus every assigned stock-opname user.

### Fixed

- Expired alert bulk-create selections now submit raw stock IDs instead of localized IDs with thousand separators, so selected rows prefill the create form correctly.
- Stock opname input now preserves already-entered physical counts when users reopen `Input Hitung`.
- Stock opname input now accepts existing actual quantities without localized thousand separators causing validation failures.
- Stock opname saves now redirect back to the stock opname detail page.
- Stock opname discrepancy counts and discrepancy print reports now compare `Stok Fisik` against refreshed current stock after operational corrections, while keeping `Stok Sistem` as the frozen snapshot.
- Completed stock opname detail and print reports now use the completion-time `Stok Update` snapshot instead of recalculating against later live stock movements.
- Completed stock opname migration backfills now preserve legacy rows with the frozen `Stok Sistem` quantity when completion-time stock identity cannot be proven from historical snapshot fields.
- Stock opname status and completion audit fields are now read-only in Django Admin, and admin-created documents are forced to `DRAFT` so snapshot workflows cannot be bypassed by direct admin status edits.
- Stock opname completion buttons now remain visible for Django-permission users without module-scope fallback when no refreshed discrepancy remains.
- Completed stock opname detail pages now hide the `Refresh Stok Update` button.

### Changed

- Stock opname tables now use the clearer `Stok Fisik` label, hide the compacted `Kode` column, show `Sumber Dana`, and keep `Dokumen Sumber` as compact source-layer text for row disambiguation.
- Stock opname completion now allows `GUDANG` / operate-scope users to complete only when no refreshed current discrepancy remains; completion with remaining discrepancies still requires approve scope.

## [1.31.7] - 2026-08-24

### Changed

- Regular receiving item tables now mark required columns clearly and label expiry as required only when the selected item requires it.
- Manual regular receiving now normalizes blank Batch/Lot values to `"-"` before posting receiving items, stock rows, and transactions.

### Fixed

- Non-expiring items now gray out blank expiry-date inputs on manual receiving rows.
- Regular receiving correction now preserves existing expiry metadata for non-expiring items when the browser omits the optional expiry field.
- Regular receiving correction now shows hidden formset row errors, such as stale item-row IDs after another user has already submitted a correction.

## [1.31.6] - 2026-08-21

### Added

- Added soft cancellation for SPJ / Pengadaan documents, including required cancellation reason plus actor and timestamp audit metadata.
- Added cancellation support for approved SPJ only when the linked planned receiving has no receipt rows and no received quantities.
- Added cancellation metadata visibility on linked planned receiving detail pages.

### Changed

- Planned procurement receiving now starts from approved SPJ / Pengadaan; the legacy receiving-side manual plan create route redirects to SPJ creation.
- Reordered receiving navigation so SPJ / Pengadaan appears before Rencana Penerimaan.
- Rencana Penerimaan copy now presents manual no-contract planned receiving as legacy compatibility while keeping existing legacy rows executable.
- SPJ cancellation now honors the documented Django-permission-or-module-scope fallback used by other procurement mutations.

### Fixed

- Prevented stale procurement transitions, edits, amendment creation, amendment edits, and planned receiving execution from resurrecting or mutating cancelled SPJ / linked receiving plans.
- Added cancelled planned receiving records to the Rencana Penerimaan status filter.
- Blocked cancellation once procurement receiving has any recorded realization.

### Security

- Updated Django from `6.0.7` to `6.0.8`.

## [1.31.5] - 2026-08-19

### Added

- Added auditable edit and cancel actions for verified regular receiving documents at `/receiving/<pk>/edit/` and `/receiving/<pk>/delete/`.
- Added `CANCELLED` receiving status plus cancellation actor, timestamp, and reason metadata.
- Added `RECEIVING_MUTATION_RATE_LIMIT` for regular receiving correction and cancellation POST endpoints.
- Added posted stock-layer tracking on receiving items so CSV-imported row-level funding overrides can be reversed deterministically.

### Changed

- Regular receiving edit and cancel now use append-only stock correction transactions instead of mutating historical receiving ledger rows.
- Regular receiving corrections reverse the current posted stock layer, preserve original `Transaction(IN)` rows, and append correction `Transaction(OUT)` / replacement `Transaction(IN)` rows as appropriate.
- Regular receiving edit keeps the document number immutable once stock exists and preserves historical receiving type choices when correcting older documents.
- Receiving correction forms now render unit prices without unnecessary trailing precision and use more flexible item-table column sizing.

### Fixed

- Regular receiving rows can now be edited or operationally cancelled when their originally received stock is still fully available.
- Receiving correction and cancellation are blocked when stock has been consumed, reserved, or cannot be reversed without making stock invalid.
- Cancelled receiving rows are excluded from receiving reports, and inventory summaries account for receiving reversal transactions.
- Correction actions are hidden unless the user also has receiving operate access, matching endpoint authorization.
- Correction reposting handles same-source metadata mismatch validation without returning HTTP 500.
- Zero-quantity stock layers referenced by draft workflows are preserved instead of deleted during valid receiving reversals.
- Correction-only zero-stock metadata rewrites are restricted away from planned receiving execution and are recorded through django-auditlog.

### Documentation

- Updated receiving, stock, system model, README, developer, and onboarding documentation for the regular receiving correction workflow, stock mutation semantics, routes, permissions, status values, import semantics, and rate-limit setting.

## [1.31.4] - 2026-08-18

### Added

- Receiving type dropdowns now use `ReceivingTypeOption` lookup rows for both regular receiving and receiving plan forms.
- Added quick-create support for custom receiving type options from receiving forms.

### Changed

- System receiving type rows are seeded and protected for `PROCUREMENT` / `Pengadaan` and `GRANT` / `Hibah`.
- Receiving list, detail, form, admin, and CSV import flows now resolve receiving type labels from table-backed options while preserving historical fallback labels.

### Fixed

- Receiving plan creation no longer blocks `PROCUREMENT` while regular receiving allows it.
- Receiving type migrations now preserve legacy `RETURN_RS` history without reintroducing it into active dropdowns.
- Existing or deleted historical custom receiving type values are preserved as inactive lookup rows during migration.
- Legacy system-code lookup rows are restored to canonical defaults during migration so `PROCUREMENT` remains active and supplier-required.
- Django admin can no longer promote arbitrary custom receiving type rows into protected system rows.

### Security

- Updated `sqlparse` from `0.5.3` to `0.6.0`.

## [1.31.3] - 2026-08-13

### Changed

- Non-Puskesmas dashboards now focus on operational work by removing the top KPI cards, secondary KPI cards, and stock-movement summary.
- The operational dashboard layout now keeps `Transaksi Terakhir` on the left, with `Aksi Cepat` above `Mendekati Kedaluwarsa` on the right.
- Auditor dashboards now show a report-focused landing surface instead of operational drill-through sections.

### Fixed

- Auditor dashboard access now honors both Django `reports.view_reports` permission grants and REPORTS module-scope fallback.
- Added a production-provisioned unmanaged `reports.ReportPermission` marker so administrators can assign `reports.view_reports` in deployed databases instead of relying on test-only permission setup.

### Security

- Updated `tablib` from `3.9.0` to `3.10.0` to pick up the HTML export stored-XSS fix for CVE-2026-9318.

### Documentation

- Updated the system model to document the reports permission marker.

## [1.31.2] - 2026-08-11

### Changed

- Opening-balance CSV reimports can now reuse a posted `document_number` to complete partial imports: exact existing stock-layer totals are skipped, higher cumulative totals post only the delta, and lower totals are rejected before confirmation.
- Opening-balance reimport previews now distinguish `New`, `Skipped`, and `Delta` rows, and show both the posted quantity delta and requested cumulative total before admins confirm stock-changing writes.

### Fixed

- Opening-balance reimports no longer reject valid same-document updates solely because the `document_number` already exists on an opening-balance import or retained migrated receiving claim.
- Migrated receiving/opening-balance document-number collisions continue to post new opening-balance rows onto their disambiguated `OBI-...` source layer, including cases where the original posted receiving header was later deleted but its receiving claim remains.
- Duplicate stock-layer rows in one opening-balance CSV are rejected so repeated or split same-key quantities cannot be silently undercounted across partial reimports.
- Opening-balance collision detection no longer treats an unrelated predictable `OBI-...` opening-balance claim as evidence that a normal document is a migrated receiving collision.

### Documentation

- Updated stock, system model, seed, and developer documentation for opening-balance partial reimport behavior, duplicate-row validation, and migrated source-layer compatibility.

## [1.31.1] - 2026-08-07

### Changed

- Login page branding now uses configurable system settings for the platform label and logo, with a static default logo fallback when no tenant logo is configured.
- Login and lockout pages now use fixed logo containers with contained image rendering for more consistent presentation.

### Fixed

- Login form rendering now uses correct browser autocomplete hints for username and current password without prefilled privileged usernames.
- Failed login attempts now render a generic visible Bootstrap error state with per-field invalid styling and accessible live-region behavior.
- Password policy copy is now persistent helper text, the password visibility toggle uses vanilla event listeners, and submit disables with a spinner to prevent duplicate POSTs.
- django-axes lockout copy now reflects the configured cooldown duration instead of hardcoded timing.

### Security

- Login POST requests are now covered by `django-ratelimit` through `LOGIN_RATE_LIMIT` while keying attempts by submitted username to avoid collapsing shared-address staff logins into one anonymous IP bucket.

### Documentation

- Documented the `LOGIN_RATE_LIMIT` setting in environment, system model, developer, README, and agent guidance.

## [1.31.0] - 2026-08-06

### Added

- Baris stok dan transaksi stok sekarang menyimpan `source_document_number`, sehingga stok dengan barang/lokasi/batch/sumber dana yang sama tetap dipisahkan per dokumen sumber.
- Ditambahkan registry klaim nomor dokumen sumber agar nomor dokumen penerimaan dan saldo awal tidak bisa dipakai ulang lintas workflow sumber stok.
- Import CSV saldo awal sekarang menerima delimiter koma dan titik koma, serta menampilkan masalah validasi sebelum tahap preview/confirm.
- Ditambahkan helper bersama untuk harga satuan presisi tinggi, nilai hasil kalkulasi, format tampilan Indonesia, dan teks ekspor yang tetap presisi.

### Changed

- Posting stok untuk penerimaan, transfer, pengeluaran, kedaluwarsa, recall, alokasi, dan saldo awal sekarang memakai nomor dokumen sumber sebagai bagian dari identitas stok, bukan merata-ratakan atau menggabungkan layer harga antar dokumen.
- Kartu stok, cetak kartu stok, dan laporan persediaan rincian sekarang menampilkan identitas layer sumber agar baris yang mirip tetap bisa dibedakan berdasarkan dokumen sumber, lokasi, dan batch.
- Field `unit_price` tersimpan di stok, transaksi, import saldo awal, penerimaan, pengadaan, snapshot distribusi, penerimaan Puskesmas, dan LPLPO sekarang mendukung sampai 10 angka desimal dengan kalkulasi `Decimal` yang tetap presisi.
- Jalur laporan dan ekspor sekarang menghitung dari harga presisi tinggi yang tersimpan dan mempertahankan nilai desimal persis pada area yang dipakai untuk rekonsiliasi, sementara pembulatan mata uang hanya dilakukan pada batas tampilan yang memang disengaja.

### Fixed

- Validasi import saldo awal sekarang menangkap jumlah kolom yang salah, presisi desimal yang tidak valid, referensi yang tidak dikenal, serta konflik harga/kedaluwarsa dalam dokumen yang sama sebelum menulis ke database.
- Alur import/form saldo awal dan penerimaan sekarang mempertahankan harga presisi tinggi dengan koma desimal seperti `8893,31985`, bukan membulatkan atau menolaknya pada dua angka desimal.
- Validasi import saldo awal sekarang menolak `document_number` yang sudah dipakai dokumen penerimaan agar layer dokumen sumber tidak bertabrakan antar workflow.
- Pembuatan/import penerimaan sekarang menolak `document_number` yang sudah dipakai import saldo awal, dan nomor penerimaan otomatis melewati nomor `RCV-YYYY-NNNNN` milik saldo awal.
- Nomor dokumen penerimaan tidak bisa lagi diubah setelah dokumen tersebut memiliki baris stok atau transaksi ledger.
- Penghapusan draft penerimaan yang belum posting sekarang melepas klaim nomor dokumen sumber yang belum terpakai, tetapi tetap menahan klaim untuk dokumen yang sudah menghasilkan stok atau transaksi ledger.
- Resolusi dokumen sumber penerimaan sekarang memakai ulang alias collision hasil migrasi untuk penerimaan parsial berikutnya, sehingga satu dokumen historis tidak mendapat beberapa identitas sumber.
- Migrasi stok historis sekarang mempertahankan saldo agregat multi-dokumen yang ambigu dalam layer sumber legacy, bukan menetapkan seluruh saldo ke satu dokumen penerimaan.
- Migrasi stok historis sekarang memisahkan tabrakan nomor dokumen penerimaan/saldo awal yang sudah ada sebelum laporan berbasis layer sumber diaktifkan.
- Migrasi stok historis sekarang mempertahankan layer sumber saldo awal melalui transfer stok yang dibuat sebelum upgrade.
- Migrasi transaksi historis sekarang memetakan semua pergerakan untuk satu layer stok agregat legacy ke sumber legacy tersebut walaupun penerimaan lama penyusunnya memiliki harga berbeda.
- Baris laporan persediaan rincian dan ekspor Excel sekarang menampilkan `source_document_number` ketika grouping layer sumber memisahkan baris yang sebelumnya tampak identik.
- Kartu stok sekarang memisahkan baris dengan sumber dana sama berdasarkan `source_document_number` dan menampilkan dokumen sumber agar harga per layer tetap terlihat dan akurat.
- Kartu stok sekarang tetap menampilkan layer saldo awal yang tidak memiliki transaksi dalam filter tanggal, serta memberi label lokasi dan batch pada header detail/cetak ketika tidak ada transaksi dalam periode.
- Recovery distribusi LPLPO yang digenerate sekarang mempertahankan pilihan stok/batch dan catatan yang masih valid dari dokumen submitted, sambil membangun ulang hanya baris item yang tidak tersedia.
- Ekspor/import XLSX LPLPO sekarang mempertahankan `harga_satuan` presisi tinggi secara lossless, termasuk nilai dengan digit signifikan yang melebihi batas aman angka Excel.
- Agregasi rekap, negasi nilai keluar/kedaluwarsa, dan total laporan sekarang memakai konteks presisi yang lebih lebar agar nilai besar dengan harga 10 desimal tidak terpotong.
- Tampilan HTML/cetak yang dipakai rekonsiliasi sekarang menampilkan harga atau nilai presisi penuh pada kartu stok, laporan rincian/rekap, detail penerimaan, pengadaan, detail distribusi, penerimaan Puskesmas, checklist Puskesmas, stock opname, LPLPO, dan print audit kedaluwarsa.

## [1.30.0] - 2026-07-29

### Added

- Stock Admin: added a dedicated opening-balance CSV import workflow for one-time initial stock seeding, separate from regular receiving imports.
- Stock Admin: added opening-balance import preview and confirmation steps so admins can inspect parsed rows before stock is posted.
- Stock Admin: added `OpeningBalanceImport` and `OpeningBalanceImportItem` records to keep imported opening-balance documents auditable after posting.
- Stock ledger: opening-balance imports now create stock quantities and `Transaction(IN, reference_type=INITIAL_IMPORT)` rows without linking them to a receiving document.
- Documentation: added opening-balance CSV guidance and an example template for initial seeding operations.

### Changed

- Reports: yearly stock recap now treats January 1 opening-balance rows as the selected year's initial stock and treats later opening-balance rows inside the same year as inbound movement.
- Reports: subsequent-year recap continues from the previous year's final stock calculation instead of requiring the opening-balance CSV to be re-imported every year.
- Stock Admin: direct stock add, edit, and delete operations are disabled so stock remains controlled by ledger-producing workflows.
- Opening-balance import UI now follows the existing admin import layout, including format guidance, preview table, and confirm-import action.

### Fixed

- Opening-balance import navigation now exposes the import action from the Stock admin screen instead of requiring admins to manually visit the import URL.
- Opening-balance import validation now rejects future effective dates, malformed rows, unknown references, duplicate/conflicting batch-price rows, non-integer quantities, invalid integer precision, and unsupported receiving/supplier columns.
- Opening-balance CSV handling now supports items that do not require expiry dates while still enforcing expiry dates for expiring catalog items.
- Posted opening-balance rows are traceable through the stored import document and generated stock transactions for audit and manual correction review.

### Security

- Opening-balance import remains restricted to admin/superuser stock administration paths and does not expose initial seeding through regular receiving flows.
- Stock mutation controls were tightened so admin users cannot bypass workflow validation by editing stock rows directly.

### Platform Notes

- Database migrations are required for the new opening-balance import tables.
- Existing regular receiving imports are unchanged; opening-balance CSV files should leave `receiving_type` and `supplier_code` empty because those columns are not used by the initial seeding workflow.
- Project agent guidance was refreshed, including app-specific `AGENTS.md` files for stock and related workflow modules.

## [1.29.3] - 2026-07-24

### Changed

- Login page rendering now uses a crispy-backed Django `AuthenticationForm` instead of duplicating username/password inputs in the template.

### Security

- Authentication and centralized error audit logs now ignore spoofed `X-Forwarded-For` headers unless the immediate peer is explicitly trusted through `AUTH_AUDIT_TRUSTED_PROXIES`.

### Tests

- Added regression coverage for crispy login form rendering, failed-login form errors, safe `next` redirects, and unsafe external `next` fallback behavior.
- Added regression coverage for login success/failure audit IP logging with default `REMOTE_ADDR`, spoofed forwarded headers, trusted proxy forwarding, and malformed forwarded chains.

### Documentation

- Documented the trusted-proxy requirement for authentication audit IP derivation in deployment and system docs.

## [1.29.2] - 2026-07-24

### Security

- Login brute-force protection now locks by username through django-axes, closing the gap where distributed attempts against the same username could avoid the previous username/IP-combination counter without adding proxy-sensitive IP-wide lockouts.
- Public login and lockout copy no longer discloses the exact failed-attempt threshold, reducing operational detail exposed to unauthenticated users.

### Tests

- Added regression coverage for distributed username spraying and public login copy that avoids precise lockout tuning disclosure.

### Documentation

- Updated `AGENTS.md`, `README.md`, and `SYSTEM_MODEL.md` to document the active username-based login lockout policy.

## [1.29.1] - 2026-07-24

### Fixed

- Admin/static assets: serve collected static files with WhiteNoise so deployed Django admin pages load their CSS and JavaScript correctly instead of rendering as unstyled fallback HTML.

## [1.29.0] - 2026-07-22

### Added

- Puskesmas: new read-only stock self-check page for operators that compares the latest usable LPLPO digital stock against the same document's recorded physical warehouse stock without mutating inventory.
- Receiving admin: new CSV template download alongside the admin CSV import flow, making the supported import format easier to follow operationally.
- Items: optional unique `barcode` support on the item catalog, preserved through legacy import paths for future scanner-oriented workflows.
- Auditability: added `django-auditlog` object history for selected critical models and row-by-row audit coverage for user bulk active/inactive status changes.
- Playwright: expanded local multi-role browser support to cover all six operational roles, with updated helper configuration and docs for local regression and manual workflow checks.

### Changed

- Procurement/SPJ: contract and amendment workflows were completed and tightened, including contract-aware amendment management, scoped amendment numbering using `{SPJ}-A{seq}`, quick-create supplier/funding-source flows, and explicit approval gating so `GUDANG` can operate procurement documents but cannot approve them.
- Receiving/procurement coordination: SPJ-linked planned receiving leftovers must now be corrected through procurement amendments rather than receiving-side close-items actions, while procurement-linked execution documents continue to auto-sync from approved contracts or amendments.
- Distribution workflow: assigned warehouse staff can now fulfill standalone distributions directly, while generated LPLPO return-to-Puskesmas actions and step-back visibility follow the same assignee/fallback and role-gated authorization rules more strictly.
- Puskesmas/LPLPO reporting: `Rincian Persediaan` and related LPLPO-backed stock reporting now align around the same LPLPO baseline plus confirmed receipts and detailed consumption, with better query efficiency and more consistent facility aggregation.
- Navigation/UI: `Distribusi` was renamed to `Riwayat Distribusi` in the user-facing navigation, auditor navigation was reduced to a report-focused surface, admin history placeholders were removed, and Puskesmas/LPLPO sidebar visibility was tightened to match actual role policy.
- Core/settings access: `/settings/` is now explicitly limited to superusers plus `ADMIN` and `KEPALA`, and the dashboard/sidebar facility-linked navigation rules were aligned with that policy.

### Fixed

- Procurement: clarified amendment contract context, restored contract-line and amendment-line dynamic form controls, reserved suffix space for manual SPJ numbers, and limited manual SPJ numbers so amendment suffixes still fit safely.
- Receiving: hardened admin CSV import validation, rejected malformed or unsupported CSV rows earlier, and improved planned receiving detail behavior for SPJ-linked leftovers.
- Distribution/LPLPO: corrected generated LPLPO return actions, queue ordering and created-date presentation, and ensured role-based action visibility no longer exposes invalid revert/step-back paths.
- Expired workflow: allowed `GUDANG` users with the correct expired operate scope to finalize already verified disposal documents, while keeping approval and posting logic restricted appropriately.
- Puskesmas reports: fixed all-facility persediaan aggregation, preserved zero-valued category ordering, and eager-loaded LPLPO-backed report rows to avoid unnecessary query churn.
- Security/UI hardening: refreshed Playwright/session handling to avoid stale Puskesmas auth state, tightened public navigation exposure, and kept delete/redirect flows aligned with the latest hardened role rules.

### Removed

- Removed the unfinished `Administrasi` placeholder pages for `Riwayat Penerimaan` and `Riwayat Pengeluaran`; users should use the implemented operational screens and `Laporan` module instead.

## [1.28.0] - 2026-07-13

### Added

- Procurement: new authoritative `SPJ / Pengadaan` module with `ProcurementContract` and `ProcurementAmendment` workflows, dedicated list/detail/create/edit screens, approval actions, rate limiting, and full permission-gated navigation.
- Procurement: supplier and funding-source quick-create lookups are now available directly from procurement contract create/edit flows, matching the receiving-side lookup experience.
- Receiving/procurement integration: approved procurement contracts and amendments now auto-create or re-sync exactly one linked planned procurement receiving document, so execution documents stay aligned with the current contract state.
- Distribution/allocation: outbound stock workflows now track row-level `reserved_quantity` on `DistributionItem`, enabling explicit stock reservation during verification and deterministic release on reversals, step-backs, deletes, and allocation rollback.
- Items/stock: catalog items now carry `requires_expiry_date` so receiving, stock, and import flows can distinguish expiring versus non-expiring items.
- Tooling: added a local Playwright multi-role launcher, committed browser-regression config, and supporting scripts for manual multi-role verification from the repository root.

### Changed

- Receiving: procurement-linked planned receiving is now contract-driven instead of manually approved; new procurement plans cannot be created from generic planned-receiving forms, while legacy manual planned rows remain available through compatibility paths.
- Receiving validation: custom receiving types now require explicit selection, reserve the internal `RETURN_RS` code, keep string-label compatibility for existing custom options, and centralize validation to avoid inconsistent save behavior.
- Stock workflow: transfer creation and completion now apply stronger transactional locking and finite-quantity validation, while stock-card views keep zero opening balances visible and batch related metadata lookups more efficiently.
- Allocation/distribution workflow: allocation-generated child distributions now reserve stock immediately on approval, release it on parent step-back, and surface reservation conflicts as workflow errors instead of drifting stock availability silently.
- Navigation/authorization: Puskesmas dashboard/sidebar visibility now honors facility-linked policy more strictly, the LPLPO sidebar link routes operators to their scoped `my-list`, and `/settings/` is explicitly restricted to superusers plus `ADMIN` and `KEPALA`.
- Documentation/config: project docs, environment examples, and settings guidance were updated for Django `6.0.7`, procurement, optional expiry dates, item/procurement mutation throttles, and Playwright helper usage.

### Fixed

- Receiving: fixed dynamic typeahead row validation and selection persistence on submit, refreshed the cached client-side validator asset, rejected non-positive CSV import quantities, and hardened quick-create lookup endpoints.
- Receiving concurrency: planned receipt posting now locks quantities more narrowly, inbound stock increments are concurrency-safe, and procurement-linked receiving enforces the single-plan-per-contract invariant.
- Procurement/reporting: corrected procurement receipt numbering/date behavior, restored contract-line and amendment-line formset controls, and included partial procurement receipts plus SPJ references in procurement reporting.
- Optional expiry handling: backfilled legacy non-expiring items, normalized downstream sentinel expiry history, prevented mixed-expiry stock merges during concurrent receiving, and aligned stock import identifiers with the canonical unique constraint.
- Security: hardened admin sidebar external links, user delete modal behavior, expired-alert redirect handling, and item lookup redirect targets, including rejection of scheme-relative and backslash-based redirect paths flagged by code scanning.
- Users/expired/stock: restored the single-delete mutation endpoint, kept expired-alert submissions on fixed safe forms, and improved stock-card output by preserving zero opening balances and showing receiving counterparties on stock-card rows.

## [1.27.0] - 2026-06-28

### Added

- Puskesmas: new detailed `Pemakaian` breakdown workflow with facility-scoped list, create, edit, and detail screens, historical reference preservation, and supporting tests.
- Puskesmas: new receipt-confirmation workflow for LPLPO receiving follow-up, including checklist-style drafts, discrepancy notes, split validation, and synchronized operational handling for confirmed documents.
- LPLPO: new XLSX import/export support with hardened file handling, rate limiting, and expanded offline test coverage for spreadsheet workflows.
- Items: new therapeutic class master-data support plus item-form/admin integration, seed template coverage, and related regression tests.
- Items: new essential-item list filter and XLSX export support for item master-data review.
- Stock: redesigned stock list surface with richer filtering, expiry tracking, and analytics-focused summary behavior for Instalasi Farmasi operations.
- Stock: new read-only `Stok Puskesmas` report-ledger surface under `/stock/puskesmas-stock/` with dedicated `Penerimaan`, `Pemakaian`, and `Stok Saat Ini` tabs for Instalasi Farmasi-side lookup and review.
- Stock: compact GET-driven ledger filters for year, Puskesmas, item search, active tab, and tab-specific pagination on the same route.
- Stock tests: expanded coverage for stock list analytics, tab switching, facility/item filtering, receiving aggregation, yearly consumption summaries, current-stock math, and active-tab pagination behavior.

### Changed

- LPLPO access for Instalasi Farmasi was reworked so submitted documents are reachable again under the intended workflow stage gates, while cross-facility access remains constrained by the updated authorization rules.
- LPLPO monthly carry and suggestion logic now better handles months that have both `penerimaan` and `pemakaian`, and January bootstrap suggestions now prefer confirmed receipt values where available.
- Puskesmas receipt confirmation was simplified from the earlier heavier flow into checklist-oriented drafts with document-level discrepancy notes and cleaner mutation behavior.
- `Stok Puskesmas` no longer presents as a client-side snapshot dashboard; it now uses a formal report-ledger layout with server-rendered tables, compact summary strip, and low-chrome tabbed navigation.
- `Penerimaan` now reads from confirmed `PuskesmasReceiptConfirmationItem` rows and aggregates yearly totals per facility, item, batch, expiry date, and unit price.
- `Pemakaian` now reads from `PuskesmasConsumptionEntry` rows and summarizes yearly per-item usage per facility instead of mixing that view into the stock snapshot table.
- `Stok Saat Ini` keeps the operational source rule of latest usable LPLPO closing stock plus later confirmed receiving minus later detailed consumption, while remaining searchable and paginated in the new ledger shell.
- Stock list filtering now preserves quick-filter context more reliably and aligns expiry bucket behavior with the canonical expired-item semantics used elsewhere in the system.
- Documentation and seed references were expanded for the new item, stock, and LPLPO workflows, including design guidance for the updated inventory-table UI.

### Fixed

- Puskesmas: fixed consumption-review regressions and preserved historical consumption references during later edits and detail inspection.
- Puskesmas receipt confirmation: fixed legacy edit compatibility, preview throttling behavior, create-time discrepancy-note validation, permission compatibility, and aggregate validation on split confirmation flows.
- Error handling: guarded centralized error handlers so they degrade safely when `request.user` is unavailable.
- Stock opname: hardened completion audit handling, preserved deactivated assignees in edit flows, refreshed item audit timestamps correctly, and stabilized snapshot timestamp persistence.
- Migrations: reconciled outstanding model drift in `users`, `receiving`, and `lplpo`, and fixed stock-opname migration compatibility issues.
- Expired workflow: hid approval actions from non-approver roles and aligned approval endpoints with the restricted UI behavior.
- Removed the old `Stok Puskesmas` client-side toolbar/search/export dependency so the page no longer relies on JavaScript-only row filtering for its primary reporting workflow.
- Preserved strict filter validation and permission behavior while preventing invalid year, facility, or tab inputs from widening the rendered report scope.

## [1.26.0] - 2026-06-12

### Added

- Puskesmas SBBK module: new `PuskesmasSBBK` and `PuskesmasSBBKItem` models for tracking local receipt records with CRUD screens, facility-scoped authorization, form validation, structured logging, and dedicated mutation rate limiting.
- SBBK receiving flow: create, edit, detail, delete, and list views with integrated LPLPO penerimaan/harga_satuan sync on every mutation.

### Changed

- LPLPO `penerimaan` and `harga_satuan` autofill now sources from same-month SBBK aggregates instead of distribution data, with January remaining a manual bootstrap period and February onward auto-filled from `PuskesmasSBBKItem` totals.
- SBBK save/edit/delete atomically re-syncs editable (`DRAFT`/`REJECTED_PUSKESMAS`) LPLPO rows; mutations are blocked once the facility-month LPLPO is `SUBMITTED` or beyond.
- Puskesmas receiving report now displays SBBK history instead of distribution-based data.
- Updated documentation (`AGENTS.md`, `README.md`, `SYSTEM_MODEL.md`, `docs/developer_guide.md`) for new SBBK workflow and settings.

### Fixed

- SBBK document numbering now derives from `received_date` instead of server time so backdated/future-dated receipts keep correct `YYYYMM` prefix with retry-on-collision handling.
- SBBK quantities validated as whole numbers in both form and model layers.
- Puskesmas top-nav back button corrected for receiving detail/edit flows and report pages.

## [1.25.0] - 2026-06-09

### Added

- Distribution: added a dedicated manual LPLPO create route at `/distribution/lplpo/create/` so Instalasi Farmasi can issue LPLPO-bucket distributions during rollout or catch-up work without forcing immediate backfill of historical Puskesmas documents.
- Puskesmas: added and expanded operational reporting and request-management surfaces, including dedicated views for penerimaan, pemakaian, persediaan, and rekap persediaan.
- LPLPO/reporting: added an asset-valuation dimension derived from `harga_satuan`, improving stock-value visibility in Puskesmas-side reporting.
- Security hardening: added configurable rate limiting for sensitive authenticated POST endpoints, with throttled requests routed through the centralized `429` error page.

### Changed

- Security hardening: tightened `puskesmas` and `lplpo` facility tenancy so all non-superusers now require a linked `facility` on affected operational, review, print, prefill, and reporting surfaces, while cross-facility access remains restricted to superusers.
- LPLPO/distribution workflow: tightened the review handoff and downstream distribution coordination, while keeping LPLPO-generated draft distributions source-driven and quantity-locked where intended.
- Distribution: the LPLPO list page now exposes a `Buat Distribusi LPLPO` action, and generated LPLPO distributions now support the intended operational fallback and reversal flow back to Puskesmas when needed.
- Reporting UX: improved outbound reporting filters, tab behavior, and print readability across the dedicated distribution report variants.
- Dashboard: refreshed the inbound/outbound movement visualization and cleaned up transfer-related movement metrics in summary cards.
- Platform/docs: updated to Django `6.0.6`, normalized `backend/requirements.txt`, and expanded developer/internal documentation for the current stack and workflows.

### Fixed

- Security hardening: neutralized CSV and XLSX formula injection risks across custom exports and django-import-export admin downloads by sanitizing formula-prefixed cell values.
- Security hardening: moved receiving document attachments behind authenticated private access and tightened upload validation plus audit logging around file-handling paths.
- Security hardening: restricted Puskesmas report export cross-facility scope to superusers and aligned distribution reset-to-draft, step-back, and delete with the existing assignee-aware object authorization rule.
- LPLPO/Puskesmas authorization: closed facility-scoping gaps across queue, detail, print, review, and prefill surfaces, including follow-up DRY/CodeQL cleanup and ADMIN-role exemption fixes.
- Stock/data validation: rejected non-finite decimal values earlier in stock-affecting workflows before business-rule comparisons and calculations run.
- Distribution/reporting: corrected transfer movement noise, distribution form regressions, and related LPLPO-driven workflow edge cases.
- Quality: expanded automated test coverage substantially across `core`, `distribution`, `lplpo`, `puskesmas`, `receiving`, `reports`, and `users` to lock in the updated behavior.

## [1.24.0] - 2026-05-21

### Added

- Expired module: new expired audit report and print-friendly output, including filtered reporting, CSV export, and browser-print/PDF save support.
- LPLPO workflow: current-year sequential document creation enforcement so each facility must create the earliest missing month first.
- LPLPO workflow: explicit January bootstrap guidance on create and edit screens, clarifying manual opening-stock entry for `stock_awal`.
- LPLPO workflow: January `penerimaan` now stays manually entered and is no longer auto-filled from distribution records.
- User management: stronger account-management UX with password strength meter, password generator/reset actions, keyboard shortcuts, responsive mobile cards, CSV export, and a richer tabbed form layout.
- Documentation: new internal code wiki pages covering architecture, app map, conventions, and workflow/stock behavior.

### Changed

- LPLPO workflow is now `DRAFT -> SUBMITTED -> PIC_VERIFIED -> REVIEWED -> APPROVED -> CLOSED`, with dedicated rejection loops and header-level audit fields for verification, review, and approval checkpoints.
- LPLPO item handling now includes procurement-source support and updated quantity/computed-field behavior across create, review, detail, and print flows.
- LPLPO distribution handoff and numbering behavior were reworked to tighten generated-document uniqueness and downstream distribution coordination.
- Dashboard stock summaries now consistently use available stock semantics, and the near-expiry KPI excludes already expired batches.
- Stock card and transfer views now present clearer transfer semantics in both on-screen and print outputs.
- Distribution and allocation workflow gates were aligned so generated downstream documents follow the intended approval/delivery checkpoints.

### Fixed

- LPLPO: super admin can manage all Puskesmas LPLPO records as intended, while facility isolation for operator-scoped actions remains intact.
- LPLPO: carry-over logic now reads from the immediately previous valid month without waiting for that document to reach `CLOSED`.
- LPLPO: January bootstrap period stability, create-flow carry-over behavior, and finalize-time status revalidation under lock were corrected.
- Users/UAC: hardened privileged-account management paths and closed a scope-escalation gap caused by mismatched direct-permission and module-scope checks.
- Stock opname: rejected non-finite quantities, preserved location-filter state, and clarified empty-category/missing-category display states.
- Expired alerts page now enforces the correct access restrictions.
- Dashboard transaction helper text/count handling and available-stock KPI calculation were corrected.
- Security hardening: client-side DOM text handling was tightened to address CodeQL-reported unsafe rendering patterns.

## [1.23.2] - 2026-05-07

### Added

- User list: color-coded role badges matching each jabatan (Admin, Kepala, Admin Umum, Petugas Gudang, Auditor, Operator Puskesmas) for quick visual scanning.
- User list: avatar initials circle derived from user's full name with per-letter color mapping.
- User list: `Login Terakhir` column showing relative time since last login with absolute timestamp tooltip.
- User list: inline AJAX active-status toggle switch replacing the static Aktif/Nonaktif badge, with optimistic UI and fallback on failure.
- User list: sortable column headers (Nama Pengguna, Nama Lengkap, Jabatan, Login Terakhir, Status) with ascending/descending toggle and visual sort indicators.
- User list: filter-preserving pagination that retains search, jabatan, and status filters across page navigation.
- User list: wider pagination range displaying 3 pages before and after the current page.
- User list: total pengguna count badge in the table header.
- User list: checkbox column with select-all and bulk action bar for activate, deactivate, and delete operations on multiple users.
- User list: Bootstrap modal confirmation for single and bulk delete, replacing the browser-native `confirm()` dialog.
- New read-only `/users/<pk>/` detail page showing user profile, role badge, active status, facility, NIP, email, account timestamps, and a complete UAC module scope matrix with color-coded scope badges.

### Changed

- User list: username now links to the new user detail page for quick inspection.

### Fixed

- AJAX active toggle: replaced `innerHTML` badge rendering with safe DOM API (`createElement` + `textContent`) to resolve CodeQL `js/xss-through-dom` alert.
- Delete modal: URL validation via `getSafeDeleteUrl()` to prevent open-redirect risks on delete action URLs.

## [1.23.1] - 2026-05-06

### Changed

- Item pickers on Distribution, Permintaan Khusus, Recall, Alokasi, Penerimaan, Rencana Penerimaan, Kedaluwarsa, and Permintaan Puskesmas now show item names without item codes or trailing `[P]` / `[E]` picker suffixes.

### Fixed

- Typeahead item pickers now render as detached floating overlays so search results are no longer clipped inside transaction tables and stay aligned during scroll and resize.
- Shared transaction item tables now keep dependent inputs disabled until an item is selected, restore consistent reset behavior when rows are cleared, and show inline quantity validation before submit on the staged create flows.

## [1.23.0] - 2026-05-05

### Fixed

- GitHub issue #26: Django URL patterns causing test failures due to missing trailing slashes (301 redirects). Debug catch-all route now conditional on `DEBUG` setting to allow `APPEND_SLASH` middleware to work correctly. Added explicit `APPEND_SLASH = True` setting and automated URL consistency validation tests.

## [1.22.0] - 2026-05-05

### Added

- `Procurement Source` column (`procurement_source`) on LPLPO item matrix with choice values `BLUD`, `APBD`, `BHP`, `Hibah`, and `Lainnya`. Field appears on create, edit, detail, review, and print views.
- Admin role can now view all Puskesmas LPLPO pages (list, detail, print) alongside Puskesmas operators, with facility isolation preserved for edit/delete actions.
- Centralized `400/403/404/500` error-page handling with shared standalone layout, contextual fallback navigation, and `/maintenance/` preview route returning `503`.

### Changed

- Admin-panel and Puskesmas authorization denials now flow through centralized forbidden-page path instead of raw inline HTML fragments.
- Error-page navigation compatible with strict CSP via external script instead of inline JavaScript.

### Fixed

- LPLPO draft mutations restricted to Puskesmas-only with proper role-enum guards and submit/delete access controls.
- LPLPO print category header colspan alignment.
- Custom 404 page renders correctly in `DEBUG=True` mode.
- Stock API totals remain numeric (no type coercion issues).
- **HIGH/CRITICAL audit fixes**: `transaction.atomic()` on distribution create/edit, N+1 elimination in item search and stock card, batch_lot prefetch optimization, DB-level opening balance aggregate, permission checks added to 17+ views (AJAX quick-create, receiving, stock).
- **MEDIUM/LOW audit fixes**: `bulk_update` in LPLPO edit, `bulk_create` for receiving transactions, IntegrityError retry on stock transfer document number collision, narrowed bare exceptions, deprecated `role_required` decorator removal, query optimizations across dashboard and stock card, permission enforcement on item list and system settings.

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
