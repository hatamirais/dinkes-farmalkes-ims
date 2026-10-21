# Tailwind migration ledger

Updated 21 October 2026. **Wave 2 complete:** the authenticated desktop shell, Item List pilot, and desktop/Puskesmas dashboards load the approved Tailwind foundation. Other application surfaces retain their existing CSS.

| Surface | Source template | Base / CSS dependency | Interaction or form contract | Existing verification | Status |
| --- | --- | --- | --- | --- | --- |
| Desktop shell | `backend/templates/base_tailwind.html`; legacy `base.html` / `base_bootstrap.html` | Tailwind CSS on migrated pages; Bootstrap CSS and `style.css` on legacy | Shared sidebar and user-menu semantics; Bootstrap JS collapse, dropdown and toast bridge | Seven-profile browser link check; core tests; desktop/narrow screenshots | Tailwind active; legacy preserved |
| Desktop and Puskesmas dashboards | `backend/templates/dashboard.html`, `dashboard_puskesmas.html` | Tailwind desktop base | Server-computed quick links, transactions, expiry list, auditor reports, facility metrics and recent lists | Dashboard/core tests; GUDANG, PUSKESMAS and AUDITOR browser checks; seven-profile navigation check | Tailwind Wave 2 |
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
- The Item List and both dashboards load generated Tailwind CSS and Bootstrap Icons, without Bootstrap CSS. Legacy templates continue through `base.html` with Bootstrap CSS and `style.css`. Both desktop bases keep Bootstrap JavaScript and `app.js`; Alpine.js is deferred.
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

## Wave 2 dashboard completion

The dashboard baseline was captured before editing at 1440×900 and 390×900 for the configured GUDANG, PUSKESMAS, and AUDITOR accounts. The final pages were captured at the same sizes and compared with the approved `concepts/desktop-dashboard.png` and the live baseline. The Puskesmas variant has no separate concept; it follows the approved tokens and keeps its live facility summary, three LPLPO counts, last period, recent LPLPO list, and request list. Template-tag comparison confirmed that every Django condition, loop, URL, and value expression outside the base selection stayed in order.

| Comparison point | Result |
| --- | --- |
| Desktop dashboard | The navy shell, pale canvas, white surfaces, compact transaction table, semantic status labels, and quick-action hierarchy follow the approved direction. The existing ten transaction rows and ten expiry entries remain. |
| Puskesmas dashboard | The facility actions, four summary surfaces, recent document link, and request empty state remain visible; at 390px the cards and actions reflow without page overflow. |
| Concept differences | The concept has a second large page heading, a `Pengguna` transaction column, and an expiry table with extra columns. The live dashboard has the top-bar title and a linked expiry list; `Pengguna` appears only when the server's existing permission condition allows it. These were preserved without adding metrics, columns, or masked records. Live permissions also determine which quick actions appear. |
| Responsive and focus | At 390px the transaction table scrolls within its card (`356px` viewport, `620px` content), with a focusable named scroll region. At 1440px the expiry title and action remain on one row. Focus on a header link showed a 2px solid outline. No document overflow was measured. |

Wave 2 exit gate passed: the two dashboards and Item List load Tailwind without Bootstrap CSS; visited legacy transaction, LPLPO, and reports pages still load Bootstrap CSS; the shared navigation retained the prior six-role link counts (PUSKESMAS 7, GUDANG 25, KEPALA 29, ADMIN_UMUM 21, AUDITOR 7, ADMIN 34), and GUDANG2 retained 25. The shared Tailwind CSS URL cache key advances to `wave2` so browsers fetch the rebuilt stylesheet. Bootstrap JavaScript remains for the shared shell. Dashboard core tests cover authorization, context, empty states, and stylesheet isolation. Browser checks covered quick-link destinations, the auditor report landing, status text, narrow table scroll, mobile sidebar, collapse visibility, user dropdown Escape, console/CSP errors, and both dashboard variants at desktop/narrow widths. The existing five Playwright allocation regressions passed. No unrelated page template was migrated.

Wave 2 commands passed: `bun ci`, `bun run css:build`, `bun run css:check`, `.\venv\Scripts\python.exe backend/manage.py check`, `.\venv\Scripts\python.exe backend/manage.py findstatic css/app.tailwind.css --verbosity 0`, `.\scripts\run-django-test.ps1 -Target apps.core.tests.test_core.DashboardViewTests` (20 tests), `bun run playwright:test` (5 tests), and `git diff --check`. An initial dashboard test run failed two auditor assertions after a presentation-class cleanup removed the `dashboard-reports-landing` marker; the marker was restored and the 20-test rerun passed. URL-consistency tests were not rerun because no route changed. The Puskesmas unlinked-facility branch returns the existing 403 and was verified by a focused Django test; it has no accessible browser render.

## Verification record

- `bun ci`, `bun run css:build`, and `bun run css:check` exited successfully. A Windows scanner warning under `bunx --bun` was isolated with a one-rule probe: the same CLI under Node produced byte-identical CSS without the warning. The Bun commands now launch the Tailwind CLI through Node, and CI explicitly sets up Node 24. The final build/check output is clean. Node is a development/CI dependency only.
- `python manage.py check`, `findstatic css/app.tailwind.css`, and `collectstatic --noinput` passed. The final collectstatic run reported 212 unchanged files and 210 post-processed files.
- `run-django-test.ps1` passed focused core, users, items, and URL-consistency targets. The added stylesheet-isolation assertion passed after the final template update.
- The five existing Playwright allocation tests passed after installing the Chromium revision required by the locked Playwright version. Browser smoke checks covered the pilot and a legacy dashboard at desktop and narrow widths, seven local role profiles, shell interactions, flash dismissal, focus, CSS isolation, console health, and screenshot comparison.
- `git diff --check` passed. IDE diagnostic results were unavailable through this environment; Django checks, tests, and browser validation provide the recorded diagnostics.
