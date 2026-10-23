# SIMFAS visual design contract

Status: approved direction on 20 October 2026. This file defines the **target** visual system for the incremental Tailwind migration. The desktop and Puskesmas dashboards, Item List, four desktop stock read-only screens, the Puskesmas stock report, receiving lists/details, procurement/distribution/allocation/recall/expired/stock-opname and LPLPO lists/details, and authentication pages now render through the Tailwind base; centralized errors load Tailwind directly. Other pages retain their existing Bootstrap CSS. The nine approved visual references and review notes are in [the concept review](docs/css-refactoring/CONCEPT_REVIEW.md).

## Authority and conflict gate

- Application code and the owning app's `AGENTS.md` remain authoritative for routes, labels, fields, form controls, permission-driven actions, statuses, workflow, and data. This document governs presentation only.
- The current Bootstrap interface and this target design intentionally differ in color, spacing, and component styling. That planned difference does not authorize a template or behavior change in the foundation stage.
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

The foundation defines tokens and reusable primitives in `backend/static_src/css/app.css` and commits the generated `backend/static/css/app.tailwind.css`. `base_tailwind.html` loads that output for the two dashboards, Item List, four desktop stock read-only screens, the Puskesmas stock report, receiving and other Wave 4 workflow lists/details, and authentication pages; centralized errors load it directly. Other templates retain the Bootstrap CSS base. Both desktop bases still load Bootstrap JavaScript, and crispy-bootstrap5 for legacy forms, Tom Select, Flatpickr, and the present CSP remain until their respective migration tasks. Do not load Bootstrap and Tailwind stylesheets together. Alpine.js is deferred. Each migrated surface must be compared with the approved concept and its live content before rollout.
