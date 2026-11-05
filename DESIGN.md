# SIMFAS visual design contract

Status: approved direction on 20 October 2026. This file defines the approved visual system implemented across IMS in the v2.0.0 presentation release. The desktop and Puskesmas dashboards, Item List and Items forms/delete confirmation, Users list and account create/edit forms, general and numbering settings, Puskesmas Poli/Pustu list and forms, Puskesmas receiving/consumption/request lists, details, and forms, four desktop stock read-only screens, the Puskesmas stock report and stock self-check, stock transfer list/detail/create, procurement contract/amendment create/edit, receiving lists/details and active forms, allocation list/detail/create/edit, distribution create/edit forms, recall create/edit forms, expired/disposal create/edit form, procurement/distribution/recall/expired/stock-opname and LPLPO lists/details/forms, reports and numbering history, four Puskesmas read-only reports, user detail and delegation list/create/revoke, and authentication pages now render through the Tailwind base; centralized errors load Tailwind directly. All IMS pages now use Tailwind; Django Admin retains native styling. The nine approved visual references and review notes are in [the concept review](docs/css-refactoring/CONCEPT_REVIEW.md).

Current closeout and outstanding PWA/device acceptance: [migration closeout](docs/css-refactoring/MIGRATION_CLOSEOUT.md).

## Authority and conflict gate

- Application code and the owning app's `AGENTS.md` remain authoritative for routes, labels, fields, form controls, permission-driven actions, statuses, workflow, and data. This document governs presentation only.
- The former Bootstrap interface and approved Tailwind design differ in presentation. The completed CSS migration does not authorize future changes to content, controls or workflow behavior.
- Before changing a rendered UI, compare the live page and source template with this file and the owning workflow guidance. If the current UI's content, controls, visible actions, or behavior conflict with what these docs describe beyond the approved visual change, **ask the user before making that UI change**. Record the decision here or in the owning documentation; do not silently reinterpret the screen.
- Preserve the exact existing logo asset at `backend/static/img/default-logo.svg` or the configured system logo. Concept images approximate some logo edges and icon glyphs; source assets and current action labels take precedence.
- The implementation must not add fields, metrics, routes, actions, navigation entries, or product claims to match an image-generated artifact. Masked concept rows represent existing records, not loading placeholders to introduce into production.

## Design intent

Careful modernization for dense, table-driven government-health inventory work. Keep a fixed desktop sidebar and top bar, wide working canvas, operational row density, Indonesian product labels, and role-specific navigation. Keep the mobile/PWA shell distinct, with compact stock or approval cards and bottom navigation. Print documents remain formal and ink-efficient.

## Foundational tokens

These values translate the approved concepts into reproducible CSS tokens. They are target values for new Tailwind pages; they do not restyle the current Bootstrap templates during this stage.

| Use | Token | Value |
| --- | --- | --- |
| Main ink | `--color-ims-ink` | `#112538` |
| Muted text | `--color-ims-muted` | `#506179` |
| Page canvas | `--color-ims-canvas` | `#F4F8FB` |
| Surface | `--color-ims-surface` | `#FFFFFF` |
| Subtle surface | `--color-ims-surface-muted` | `#EEF4F8` |
| Border | `--color-ims-border` | `#D6E3ED` |
| Sidebar | `--color-ims-sidebar` | `#112538` |
| Primary action | `--color-ims-primary` | `#0069AC` |
| Primary hover | `--color-ims-primary-hover` | `#00598F` |
| Primary active | `--color-ims-primary-active` | `#004B79` |
| Focus outline | `--color-ims-focus` | `#007BA8` |
| Success text | `--color-ims-success` | `#127447` |
| Warning text | `--color-ims-warning` | `#9A5A00` |
| Danger text | `--color-ims-danger` | `#B4232A` |
| Info text | `--color-ims-info` | `#125D9A` |

Primary and semantic text colors above have at least 4.5:1 contrast on white under the WCAG relative-luminance formula. Use pale semantic backgrounds with the matching dark semantic text; labels and icons must reinforce color. Avoid color-only status cues.

- **Type:** `Segoe UI`, system UI, sans-serif for screen UI; no remote font. Base text 14px/1.5; secondary/help text 12px/1.45; labels and table headers 13px/1.4 with medium to semibold weight. Page headings 28px/1.2, section headings 18px/1.35. Preserve comfortable text scaling and do not fix content height to a single line.
- **Spacing:** use a 4px base rhythm. Primary steps are 4, 8, 12, 16, 24, and 32px. Keep table cells compact (about 10–12px vertical padding) while allowing labels to wrap. Forms use 16–24px between fields and 8px from label to control/help.
- **Shape:** 1px borders; 8px control and button radius; 12px section surfaces. Use a restrained low-elevation shadow only where a section needs separation. Modals may use a stronger shadow and dimmed backdrop.
- **Focus:** every interactive element has a visible 2px `--color-ims-focus` outline with 2px offset. Do not remove native focus without replacing it. Error borders and focus rings must remain distinguishable.

## Layout and responsive rules

- Desktop navigation keeps current groups and permission-controlled links. Use a dark navy rail with clear active state and a white top bar. Main content stays wide enough for operational tables; do not turn those tables into generic card grids.
- Lists use a filter row above a dense table. Maintain numeric alignment, table headings, row separators, status labels, edit actions, and horizontal scrolling when columns cannot fit. Keep existing sticky matrix and fragment-scroll behavior where used.
- On 3 November 2026, the user chose to remove request-level Program from the Puskesmas request list and detail, including the list filter and column. The create/edit form already omitted that field. Preserve item-level `[P]` markers; this presentation decision does not remove stored request data or change downstream workflow handling.
- The Puskesmas detailed-consumption create/edit matrix shows a Kategori separator before each group of item rows. This display decision was approved on 2 November 2026; every item and quantity input remains present, with the existing save contract.
- The matrix also shows `Stok LPLPO Terakhir` immediately after Satuan, using the selected facility's latest non-rejected LPLPO digital balance with the source period and status visible. This was approved on 2 November 2026. The value is informational and does not change consumption validation or imply real-time physical stock.
- The detailed-consumption Total column shows each item's sum across Poli/Pustu inputs as values change, and shows the saved sum on edit. It remains a display value; quantity validation and save behavior stay server-owned.
- Paginated operational tables show an inclusive record range and total, a labeled page-size selector, and Previous, Next, and numbered controls with the current page identified. Use the shared `ims-table-pagination`, `ims-pagination`, `ims-page-link`, `ims-label`, and `ims-control` styles; keep wide tables in an internally scrolling region. Offer 25, 50, 100, and 200 rows where that range fits the workflow, and reset to page 1 when size or filters change. Apply search and persisted-field sorting to the full filtered queryset before slicing it with Django `Paginator`; preserve active and unrelated URL query parameters across page changes. Elide long page ranges, disable unavailable directions, and keep keyboard focus visible.
- On editable tables, retain selected row IDs and entered values outside the currently rendered page and submit them together through the existing validated POST contract. If validation finds a selected row that is no longer visible or available, show its error and provide a per-row way to remove that selection while keeping other entries. A sort on unsaved input values may order only the visible page; label that scope so users do not mistake it for a global database sort. Pagination controls must never trigger the parent form's submit action.
- Standard forms use a narrower main surface with labels **above** their inputs, help text, grouped related controls, and errors adjacent to the affected field. The user confirmed this on 20 October 2026; it overrides the side-by-side label placement in the generated item-form concept. Preserve actual toggle, checkbox, select, and searchable-select controls.
- Workflow details keep metadata, status, action hierarchy, and item table visible. The server still decides which actions are present. Primary filled action represents the current checkpoint; secondary, print, and back actions are visually distinct.
- Mobile/PWA keeps its independent header, installation guidance, search/filter controls, stock or approval cards, and bottom navigation. Respect safe areas and avoid horizontal page overflow. Desktop tables may have internal horizontal scrolling; mobile cards remain cards.
- Login and centralized error pages use focused standalone layouts. Preserve existing form rendering, error messages, actions, and accessibility behavior.

## Reusable component treatment

Implement only families confirmed by the concepts and current application: buttons (primary, secondary, neutral, danger when an existing destructive action needs it), form labels/controls/help/errors, table foundations, status badges, alerts and flash messages, pagination, and modal foundations. Each family needs disabled, hover, active, and focus states where interactive. Disabled controls must remain legible and noninteractive; destructive styling never grants or implies permission.

Use the current functional icon vocabulary and the exact repository logo. Icons support a text label for important actions; the generated images are guidance for weight and spacing, not a replacement icon set.

## Print

The SBBK reference is a white A4 sheet with a centered document heading, metadata, a dense seven-column ruled table, total row, and two signature blocks. Favor black or dark ink, thin rules, adequate margins, and legible small type. Never print app navigation or decorative chrome. Preserve the actual document data and conditional sections from the Django template.

## Migration boundary

The generated `backend/static/css/app.tailwind.css` styles every IMS desktop, mobile and standalone print surface. `base.html` is a compatibility alias to `base_tailwind.html`. Bootstrap CSS, legacy desktop/mobile CSS, the Tom Select Bootstrap theme, Crispy packages, helpers and settings are removed. Forms render existing bound fields with the project-owned renderer; grouped radio/checkbox controls retain native semantics, field IDs, descriptions and errors. Bootstrap JavaScript, `data-bs-*` and their state bridge remain on desktop; Bootstrap Icons, Flatpickr, native Django Admin styling and CSP remain unchanged. Do not load Bootstrap CSS or introduce Alpine.js.

## Wave 7 mobile implementation

The server-rendered mobile/PWA shell and all five routed child templates load generated Tailwind CSS through `mobile/base.html`, with scoped source in `backend/static_src/css/mobile.css`. Bootstrap CSS and the unused Bootstrap bundle are absent from mobile pages; Bootstrap Icons and the unchanged `mobile.js` remain. The historical `backend/static/mobile/css/mobile.css` was removed during Wave 9. Manifest/service-worker behavior and routes are unchanged. The live brand, arrow search action, item names, counts, and permission-dependent navigation take precedence over masked rows and illustrative icon differences in `docs/css-refactoring/concepts/mobile-stock.png`. The compact card layout, safe-area padding, blue actions, semantic badges, and bottom navigation follow that approved direction.

## Wave 8 print and Admin implementation

Wave 8 standalone print pages load the generated Tailwind stylesheet with scoped rules in `backend/static_src/css/print.css`. Named A4 page rules keep stock cards and expired documents portrait, and wide Stock Opname, expired audit and LPLPO reports landscape. Repeated table headings, row/signature break protection and print-only control hiding are shared. Embedded desktop reports retain their content and report-specific styles while using named A4 page sizes and white paper backgrounds. Django Admin keeps native Admin CSS; only the two import-guide overrides load scoped `admin/css/ims-import.css`, without application Tailwind preflight. The existing institutional headers, data, Indonesian formatting, stock source layers, delegated signatures and signature slots remain authoritative. The stock-card timestamp remains a template-supplied CSS custom property; compiled CSS does not contain a generated timestamp. The user approved replacing the LPLPO queue print button’s CSP-blocked inline handler with the existing external print hook on 4 November 2026. No workflow or permission logic changes.
