# Tailwind migration ledger

Updated 21 October 2026. The approved foundation is loaded by the authenticated Tailwind desktop shell and the Item List pilot. All other application surfaces retain their existing CSS.

| Surface | Source template | Base / CSS dependency | Interaction or form contract | Existing verification | Status |
| --- | --- | --- | --- | --- | --- |
| Desktop shell | `backend/templates/base_tailwind.html`; legacy `base.html` / `base_bootstrap.html` | Tailwind CSS on pilot; Bootstrap CSS and `style.css` on legacy | Shared sidebar and user-menu semantics; Bootstrap JS collapse, dropdown and toast bridge | Six-role browser link comparison; core tests; desktop/narrow screenshots | Tailwind pilot active; legacy preserved |
| Dashboard | `backend/templates/dashboard.html` and role-specific dashboard variants | Desktop base | Server-computed quick links, transactions, expiry list | Browser review; core tests | Legacy |
| Dense item list | `backend/templates/items/item_list.html` | Tailwind desktop base | Existing filters, XLSX export, create/edit/delete links, pagination, table scroll | Browser desktop/narrow, items tests | Tailwind pilot |
| Item form and quick-create modal | `backend/templates/items/item_form.html` | Desktop base; Bootstrap modal `data-bs-*` | Item form classes, lookup POST validation, native checkbox/toggle semantics | Browser review; items tests | Legacy |
| Distribution workflow detail | `backend/templates/distribution/distribution_detail.html` | Desktop base; Bootstrap collapse/modal `data-bs-*` | Server-authorized actions, `confirm-actions.js` print hook, SBBK print sheet | Browser review; distribution tests | Legacy |
| Login and lockout | `backend/templates/registration/login.html`, `lockout.html` | Desktop base public content; crispy Bootstrap authentication form | Existing login, lockout, errors, axes | Browser review; core auth tests | Legacy |
| Centralized errors | `backend/templates/errors/status.html` | Direct Bootstrap CSS link | Centralized status actions and error handling | Browser review; core error tests | Legacy |
| Mobile stock and approval | `backend/templates/mobile/base.html`, `stock_list.html`, `approval_inbox.html` | Mobile Bootstrap CSS/JS and `mobile.css` | Session/CSRF, bottom navigation, stock filters, approval access | Browser review; mobile tests | Legacy; mobile wave |
| SBBK print | Print section of `backend/templates/distribution/distribution_detail.html` | Existing `@media print` and Bootstrap table rules | Seven-column table, conditional metadata, two signature blocks | Print-media browser capture; distribution tests | Legacy; print wave |

## Foundation status

- `backend/static_src/css/app.css` contains approved tokens and reusable buttons, fields, tables, badges, alerts, pagination, focus, disabled, and print foundations.
- `backend/static/css/app.tailwind.css` is committed generated output. `bun run css:check` verifies it; CI runs this check on relevant source and configuration changes.
- The Item List loads generated Tailwind CSS and Bootstrap Icons, without Bootstrap CSS. Legacy templates continue through `base.html` with Bootstrap CSS and `style.css`. Both desktop bases keep Bootstrap JavaScript and `app.js`; Alpine.js is deferred.
- `components/navigation/desktop_navigation.html` owns the unchanged sidebar conditions, destinations, labels, and active-route expressions. `components/navigation/user_menu_items.html` owns the unchanged role text, password link, and logout form.
- Temporary Bootstrap JavaScript bridge selectors on the Tailwind shell: `.collapse`, `.collapsing`, `.show`, `.dropdown-menu`, `.dropdown-menu-end`, `.dropdown-item`, `.dropdown-divider`, `.toast`, `.toast-container`, `.toast-body`, and `.btn-close`. The sidebar bridge also overrides Tailwind's `.collapse` visibility utility for Bootstrap submenus. These cover sidebar navigation collapse, top-bar dropdowns, and flash toast dismissal used by the pilot. Modal, tooltip, and other component bridges await a page that uses them.
- The Item List keeps its existing fields, search/filter submission, rows, badges, export URL, create/edit/delete destinations, and pagination. The table scrolls inside its frame on narrow viewports; pagination links wrap within the footer so the edge controls remain reachable.

## Local navigation and interaction audit

The six role variants below are the rendered link counts for the configured local accounts on 20 October 2026. Counts can differ for other accounts because Django permissions and module scope remain authoritative. Sidebar link labels and destinations were identical between the legacy dashboard and Tailwind pilot for each role that could open `/items/`; Puskesmas retained its 403 on that route. The second Gudang profile also matched, with 25 links on each surface.

| Role | Local sidebar links | Distinguishing condition |
| --- | ---: | --- |
| PUSKESMAS | 7 | Facility workflow links and LPLPO; Item List denied |
| GUDANG | 25 | Operational stock, receiving, outbound, and reports |
| KEPALA | 29 | Operational links plus user management, delegation, and settings |
| ADMIN_UMUM | 21 | Operational links without recall/expired or settings in this account |
| AUDITOR | 7 | Reports group only, including direct Item List access without a sidebar entry |
| ADMIN | 34 | Broad operational, Puskesmas, administration, and settings links |

Checked interaction states: desktop sidebar widths 260px and 64px after transition; receiving submenu shown/hidden by Bootstrap collapse; user and notification dropdown open/Escape close; mobile sidebar and overlay open/close at 390px, including a persisted desktop collapsed preference; flash toast visible and hidden after dismissal; keyboard focus outline; Item List filter submission and internal table scroll. Review found and corrected an overlap between the brand and close button when the persisted collapsed preference was opened at 390px. No app console error was observed on accessible pilot pages. A 403 resource and a 404 resource were logged during the denied Puskesmas request; those were not attributed to the pilot shell.

## Pilot visual comparison

Reference: `concepts/dense-item-list.png` and `concepts/desktop-dashboard.png`. Browser evidence was captured at 1440×900, 390×844, and the dense-list concept width of 1620px; baseline screenshots were captured before editing. The current logo source and all live Indonesian labels take priority over concept placeholders.

| Point | Result |
| --- | --- |
| Shell hierarchy | Navy fixed sidebar, white top bar, pale canvas, and wide work area match the approved direction. |
| Palette and type | Approved tokens and system UI stack are used; the generated concept's larger apparent text varies with its 1620px capture. |
| List structure | Title and existing actions sit above a separate filter surface and dense seven-column table. |
| Density and overflow | Rows remain compact; horizontal scrolling is inside the table frame, with no document overflow at 390px. |
| Icons and logo | Existing Bootstrap Icons and configured/default logo are retained. Concept icon variations are illustrative. |
| Data and actions | Live record text, badges, both row actions, filters, and pagination remain; concept mask bars are intentionally absent. |

No content or behavior conflict beyond the planned visual change was found in this pilot.

## Verification record

- `bun ci`, `bun run css:build`, and `bun run css:check` exited successfully. A Windows scanner warning under `bunx --bun` was isolated with a one-rule probe: the same CLI under Node produced byte-identical CSS without the warning. The Bun commands now launch the Tailwind CLI through Node, and CI explicitly sets up Node 24. The final build/check output is clean. Node is a development/CI dependency only.
- `python manage.py check`, `findstatic css/app.tailwind.css`, and `collectstatic --noinput` passed. The final collectstatic run reported 212 unchanged files and 210 post-processed files.
- `run-django-test.ps1` passed focused core, users, items, and URL-consistency targets. The added stylesheet-isolation assertion passed after the final template update.
- The five existing Playwright allocation tests passed after installing the Chromium revision required by the locked Playwright version. Browser smoke checks covered the pilot and a legacy dashboard at desktop and narrow widths, seven local role profiles, shell interactions, flash dismissal, focus, CSS isolation, console health, and screenshot comparison.
- `git diff --check` passed. IDE diagnostic results were unavailable through this environment; Django checks, tests, and browser validation provide the recorded diagnostics.
