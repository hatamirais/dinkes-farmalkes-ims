# Tailwind foundation implementation

Root [`DESIGN.md`](../../DESIGN.md) is the approved visual contract. This file records its CSS implementation and usage rules. The classes below are defined in `backend/static_src/css/app.css`; `bun run css:build` produces the committed `backend/static/css/app.tailwind.css`. No production template imports the output in this stage.

The standalone [foundation preview](foundation-preview.html) is a static QA artifact for desktop and mobile-sized inspection. It is not an application template and contains no inventory records or working form submission.

## Tokens

Tailwind v4 `@theme static` emits the approved `--color-ims-*`, `--font-ims`, `--text-ims-*`, `--leading-ims-*`, `--spacing-ims-*`, `--radius-ims-*`, and `--shadow-ims-*` variables even before templates use them. The exact values and visual rationale are in `DESIGN.md`. Custom utilities may use complete literal classes such as `bg-ims-surface` or `text-ims-ink` after a Tailwind-only base is introduced. Do not interpolate fragments in Django templates or Python.

Primary, muted, and semantic foreground colors were checked against white using the WCAG relative-luminance formula; each is at least 4.5:1. Semantic badges and alerts pair color with readable text. The current `script-src 'self'` and `style-src 'self' 'unsafe-inline'` CSP settings remain; existing inline styles prevent claiming a tighter style policy.

## Reusable CSS families

| Family | Classes | Contract |
| --- | --- | --- |
| Actions | `ims-btn`, `ims-btn--primary`, `--secondary`, `--neutral`, `--danger`, `--print`, `--sm` | Add the base plus one variant. Use only server-authorized actions. Small size is for dense toolbars. |
| Fields | `ims-label`, `ims-control`, `ims-choice`, `ims-switch`, `ims-help`, `ims-error`, `ims-control--invalid` | Bind labels and error text to controls. Set `aria-invalid="true"` and `aria-describedby` when invalid. Keep native select, checkbox, and radio semantics; use `ims-switch` only for an existing toggle and retain checkbox keyboard behavior. |
| Tables | `ims-table-scroll`, `ims-table`, `ims-table-number` | Keep actual table markup. Wrap wide tables for horizontal scroll; use the number class on numeric columns. Add `tabindex="0"` and an accessible name to a scroll region when keyboard scrolling is needed. |
| Status | `ims-badge` plus `--success`, `--warning`, `--danger`, or `--info` | Render the existing status text alongside its color. Map statuses explicitly in templates; do not build class-name fragments. |
| Messages | `ims-alert` plus one semantic variant | Use existing server messages and alert semantics; styling never changes message meaning. |
| Pagination | `ims-pagination`, `ims-page-link` | Use real links; mark current page with `aria-current="page"`. A disabled link must omit its navigable `href` or have its activation suppressed; `aria-disabled` alone does not prevent navigation. |
| Print | `ims-print-sheet` | Only for confirmed print surfaces; it removes screen shadow and uses dark ink/rules. Preserve actual document layout and conditional content. |

Shared focus outlines cover buttons, controls, choices, page links, and focusable table scroll areas. Hover treatment is applied only on hover-capable devices; reduced-motion preferences remove button transitions. Disabled states remain legible. Existing workflow code, not CSS, controls whether an action can run.

## Source detection and integration

`@import "tailwindcss" source(none)` disables implicit repository scanning. Explicit `@source` declarations cover `backend/templates/**/*.html`, `backend/apps/**/*.py`, and `backend/static/js/**/*.js`. A temporary compile probe verified class detection in all three source types. Tailwind scans text and cannot resolve dynamically assembled names such as `bg-{{ status }}-600`; emit complete class literals or use these semantic component classes.

The next shared-shell task may load this CSS on a separate Tailwind base, with the exact logo, labels, roles, and actions from the existing Django templates. It must not load Bootstrap CSS and Tailwind CSS in one document. Bootstrap JavaScript remains until the later interaction migration; Tom Select, Flatpickr, and crispy forms require separate reviewed changes. Compare rendered desktop and mobile pages with the approved concept images before migrating each surface. If a content, control, action, or behavior conflict is discovered, follow the ask-first rule in `DESIGN.md`.

## Foundation visual QA

The built-in browser was used first on `foundation-preview.html` at desktop width and 390px mobile width. Local Playwright then saved the current [desktop](evidence/foundation-desktop.png) and [mobile](evidence/foundation-mobile.png) screenshots for direct `view_image` comparison with the approved [form](concepts/item-form-validation.png) and [mobile stock](concepts/mobile-stock.png) concepts. The Playwright capture was used for persistent local evidence after the browser's full-page capture timed out.

| Comparison point | Observation |
| --- | --- |
| Palette and surface | Preview primary computed as `rgb(0, 105, 172)` (`#0069AC`); white surfaces, pale canvas, and navy text follow the approved direction. |
| Typography and density | System UI text, compact labels, controls, badges, and table headers render readably. Full shell and operational row density await template migration. |
| Actions and focus | Filled, outline, neutral, dark print, danger, and disabled states render separately. Keyboard Tab showed a visible outline on the primary button. The initial pale-blue disabled fill made white text weak; it was replaced with muted dark text on a pale surface (measured 5.69:1). |
| Forms | Labels, help, error border/text, native checkbox, and existing-style program toggle render distinctly. The user confirmed that future forms keep labels above inputs, resolving the concept/current-UI mismatch. No application form was changed. |
| Status and tables | Semantic badge text remains visible alongside color. The table header, numeric alignment class, and pagination render without replacing table markup. |
| Responsive | At 390px, actions wrap, fields stay readable, and `document.documentElement.scrollWidth` measured 375px, below the 390px viewport. |

The specimen is a component check, not a claim of whole-page fidelity. Its missing sidebar, top bar, records, and bottom navigation are intentional because the shared shell and mobile templates remain out of scope.
