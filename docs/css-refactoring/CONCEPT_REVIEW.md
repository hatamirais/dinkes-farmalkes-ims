# Tailwind visual direction

Status: **Visual direction approved by the user on 20 October 2026.** These images are visual concepts, not screenshots of rendered Tailwind pages. Root [`DESIGN.md`](../../DESIGN.md) is the target visual contract. The shared desktop shell, Item List, both dashboard variants, authentication/errors, and the first desktop stock read-only slice have since migrated using this direction.

The concepts were grounded in the live local dashboard, item list and form, distribution detail, quick-create modal, login, centralized 404, mobile stock page, and a print-media capture of the SBBK. They preserve the existing Indonesian information architecture and show record-specific content as neutral masks to avoid inventing operational data. The current logo source remains [`backend/static/img/default-logo.svg`](../../backend/static/img/default-logo.svg); implementation must use that asset exactly, even where image generation approximated its edges.

The user confirmed on 20 October 2026 that migrated forms should keep labels **above** inputs, as the current UI does. This instruction overrides the side-by-side labels shown in the generated item-form concept.

| Surface | Concept |
| --- | --- |
| Authenticated desktop shell and dashboard | [Desktop dashboard](concepts/desktop-dashboard.png) |
| Dense operational table | [Item list](concepts/dense-item-list.png) |
| Form validation | [Item form](concepts/item-form-validation.png) |
| Workflow detail, status and actions | [Distribution detail](concepts/workflow-detail.png) |
| Modal state | [Quick-create unit modal](concepts/quick-create-modal.png) |
| Login error state | [Login](concepts/login-error.png) |
| Centralized error page | [404](concepts/centralized-404.png) |
| Mobile stock surface | [Mobile stock](concepts/mobile-stock.png) |
| Print document | [SBBK](concepts/sbbk-print.png) |

## Proposed direction

- **Palette:** deep navy sidebar and dark text; white working surfaces on a very pale blue-gray page; restrained blue-teal primary actions. Keep green for success, amber for warning, and red for danger. Status colors carry labels as well as color.
- **Typography:** a system UI sans stack for application chrome and body copy, with firm but compact headings. Use a plain, legible print face. No new web-font dependency is proposed.
- **Spacing and density:** maintain compact table rows and the current sidebar hierarchy. Give forms and detail sections more consistent internal spacing without reducing the number of visible operational rows.
- **Container model:** fixed desktop sidebar and top bar with a wide main work area; narrower centered form surface; independent mobile/PWA shell. Dense tables stay tables and may scroll horizontally.
- **Tables:** clear header band, hairline row separators, aligned numeric cells, legible status chips, compact edit/action cells, and persistent table context on narrow screens.
- **Forms:** visible labels, short help text, consistent control heights, required/error states beside the affected control, and a strong keyboard focus ring. Preserve existing toggle, checkbox, select, and searchable-select behavior.
- **Actions:** one filled primary action per working context, outline secondary actions, neutral cancel/back, and dark print action where present. Visibility and authorization still come from existing server policy.
- **Responsive and icons:** retain the separate mobile stock and approval navigation. Keep the current functional icon direction and existing logo; icon details in the generated art are illustrative. Avoid replacing the mobile card layout with a desktop table.
- **Print:** white A4 sheet, black/dark ink, thin rules, dense seven-column SBBK table, and the existing two signature blocks. No app navigation or colored UI chrome in print.

The user approved this direction on 20 October 2026. The foundation translated it into tokens and component CSS under root `DESIGN.md`; the subsequent shared-shell and dashboard slices load the generated Tailwind CSS through a separate base. The concepts remain references, while live content, authorized actions, and the approved logo remain authoritative.
