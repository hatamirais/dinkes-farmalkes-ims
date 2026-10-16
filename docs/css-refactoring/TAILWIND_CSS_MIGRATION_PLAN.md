# Tailwind CSS Migration Plan

Status: ready for review and execution planning  
Scope: CSS and visual-system migration only  
Deferred follow-up: Alpine.js and removal of Bootstrap JavaScript  
Application: Django server-rendered Healthcare IMS
Integration Branch: `chore/tailwind-migration`
Sub Branch : `tailwind/core`, `tailwind/error`, `tailwind/dashboard`, etc

## 1. Objective

Migrate the IMS visual layer from Bootstrap CSS 5.3.3 to Tailwind CSS through small, independently testable slices while preserving:

- Django server-rendered templates and URL behavior.
- Existing workflow rules, permissions, module scopes, and facility isolation.
- Existing form validation and submission contracts.
- Existing JavaScript behavior during the CSS migration.
- Desktop, mobile/PWA, print, authentication, and centralized error surfaces.
- WhiteNoise-based production static-file delivery.

The result of this project is a Tailwind-styled application that no longer loads or depends on Bootstrap CSS. It is not the Alpine.js migration.

## 2. Non-negotiable phase boundary

This migration is CSS-first.

During this project:

- Do not install Alpine.js.
- Do not add `x-data`, `x-show`, `x-on`, or other Alpine directives.
- Do not rewrite working interactions merely to remove Bootstrap JavaScript.
- Retain Bootstrap JavaScript temporarily where it currently controls collapse, dropdown, modal, toast, tooltip, or dismiss behavior.
- Retain the existing `data-bs-*` behavior hooks until a later Alpine migration replaces them.
- Replace Bootstrap presentation classes with Tailwind utilities or project-owned component classes.
- Supply the minimal project-owned CSS required for Bootstrap JavaScript state classes such as `.show`, `.collapsing`, modal backdrops, and dropdown positioning after Bootstrap CSS is absent.

The later Alpine project begins only after the completion criteria in section 18 are satisfied. Bootstrap JavaScript removal belongs to that later project.

## 3. Decisions already made

| Decision | Selected approach | Consequence |
| --- | --- | --- |
| Visual scope | Careful modernization | Preserve information architecture and workflow density while introducing an approved, coherent Tailwind design system. |
| Rollout | Incremental vertical slices | Legacy Bootstrap pages and migrated Tailwind pages coexist through separate base templates. |
| Production assets | Commit compiled CSS | Production remains Python-only; WhiteNoise serves the committed Tailwind output after `collectstatic`. |
| Interaction framework | Deferred | Bootstrap JavaScript remains the behavior runtime during this CSS project; Alpine is not introduced yet. |
| Application architecture | Preserve server-rendered Django | Do not introduce React, a SPA shell, or a new general-purpose API. |

## 4. Verified repository baseline

The following facts were confirmed from the repository before writing this plan.

### 4.1 Template and stylesheet footprint

- There are 114 HTML templates under [`backend/templates/`](../../backend/templates/).
- 103 templates extend another template.
- 87 templates extend [`backend/templates/base.html`](../../backend/templates/base.html).
- 5 templates extend [`backend/templates/mobile/base.html`](../../backend/templates/mobile/base.html).
- 20 templates contain `data-bs-*` attributes.
- 18 templates use crispy-forms tags.
- 51 templates contain at least one inline `style` attribute; there are 346 inline style attributes in total.
- 33 templates contain a `<style>` block.
- [`backend/static/css/style.css`](../../backend/static/css/style.css) has 1,779 lines and directly overrides Bootstrap components.
- [`backend/static/mobile/css/mobile.css`](../../backend/static/mobile/css/mobile.css) has 826 lines.
- The vendored Bootstrap minified stylesheet is approximately 233 KB before WhiteNoise compression.

### 4.2 Runtime coupling

Bootstrap is not only a stylesheet dependency.

- [`backend/static/js/app.js`](../../backend/static/js/app.js) calls Bootstrap Alert, Toast, and Tooltip APIs.
- Additional scripts call Bootstrap Modal, Tooltip, or Toast APIs:
  - [`backend/static/js/distribution-form.js`](../../backend/static/js/distribution-form.js)
  - [`backend/static/js/item-form.js`](../../backend/static/js/item-form.js)
  - [`backend/static/js/quick-create.js`](../../backend/static/js/quick-create.js)
  - [`backend/static/js/rekap-filter.js`](../../backend/static/js/rekap-filter.js)
  - [`backend/static/js/user-form.js`](../../backend/static/js/user-form.js)
  - [`backend/static/js/user-list.js`](../../backend/static/js/user-list.js)
- Bootstrap behavior attributes currently cover dismiss, toggle, target, placement, title, autohide, and delay.
- [`backend/templates/base.html`](../../backend/templates/base.html) loads both Bootstrap CSS and `bootstrap.bundle.min.js`.
- [`backend/templates/mobile/base.html`](../../backend/templates/mobile/base.html) also loads Bootstrap CSS and JavaScript.
- Tom Select uses [`backend/static/vendor/tom-select/tom-select.bootstrap5.min.css`](../../backend/static/vendor/tom-select/tom-select.bootstrap5.min.css), which depends on Bootstrap custom properties.
- Bootstrap Icons 1.11.3 are independently vendored under [`backend/static/vendor/bootstrap-icons/`](../../backend/static/vendor/bootstrap-icons/).

### 4.3 Forms and Python-side presentation coupling

- [`backend/config/settings.py`](../../backend/config/settings.py) configures `CRISPY_TEMPLATE_PACK = "bootstrap5"`.
- `crispy-bootstrap5` and `django-crispy-forms` are pinned in [`requirements.txt`](../../requirements.txt) and [`backend/requirements.txt`](../../backend/requirements.txt).
- Forms across most workflow apps inject classes including `form-control`, `form-select`, `form-control-sm`, grid classes, input-group classes, and Bootstrap button classes from Python.
- Some tests intentionally verify crispy form helpers or exact Bootstrap-era HTML.
- Authentication must continue to use the project authentication form rather than hand-coded username/password fields, as required by [`backend/apps/core/AGENTS.md`](../../backend/apps/core/AGENTS.md).

### 4.4 Static build and deployment constraints

- [`package.json`](../../package.json) currently contains Playwright scripts only.
- There is no Tailwind, PostCSS, Vite, or other frontend build step.
- [`backend/config/settings.py`](../../backend/config/settings.py) collects files from `backend/static` into `backend/staticfiles`.
- WhiteNoise serves collected static assets in production.
- The current release workflow in [`.github/workflows/release-on-version-change.yml`](../../.github/workflows/release-on-version-change.yml) configures Python but does not configure Node.
- Committed CSS output is therefore the selected deployment-compatible model.

### 4.5 Security constraints

- [`backend/config/settings.py`](../../backend/config/settings.py) enforces `script-src 'self'`.
- `style-src` currently includes `'unsafe-inline'`.
- Removing Bootstrap does not by itself permit removing `'unsafe-inline'` because many templates contain inline style attributes and style blocks.
- CSP tightening is allowed only after a separate inline-style inventory reaches zero or an explicitly documented safe remainder.

### 4.6 Existing verification coverage

- Django tests frequently assert visible text and workflow contracts.
- Some tests assert exact CSS classes, static asset URLs, and markup fragments, particularly in [`backend/apps/core/tests/test_core.py`](../../backend/apps/core/tests/test_core.py).
- The committed browser suite currently has a single allocation-form specification under [`playwright/`](../../playwright/).
- Browser coverage must be expanded before removing the legacy visual layer.

## 5. Source-of-truth documentation

Agents must verify current syntax against official documentation at implementation time and pin the installed versions in [`package-lock.json`](../../package-lock.json). Do not infer a package version from this plan.

- [Tailwind CSS CLI installation](https://tailwindcss.com/docs/installation/tailwind-cli)
- [Tailwind CSS source detection](https://tailwindcss.com/docs/detecting-classes-in-source-files)
- [Tailwind CSS functions and directives](https://tailwindcss.com/docs/functions-and-directives)
- [Tailwind CSS Preflight](https://tailwindcss.com/docs/preflight)
- [Django static-file deployment](https://docs.djangoproject.com/en/6.0/howto/static-files/deployment/)
- [WhiteNoise Django integration](https://whitenoise.readthedocs.io/en/stable/django.html)

The repository code remains authoritative for current application behavior.

## 6. Target architecture

### 6.1 Source and generated files

Use separate source and generated locations:

```text
backend/
  static_src/
    css/
      app.css                 # Tailwind source, tokens, component layers, bridge CSS
  static/
    css/
      app.tailwind.css        # committed generated production output
      style.css               # legacy Bootstrap-era styles during migration only
      mobile.css              # existing mobile stylesheet during migration only
```

Requirements:

- `backend/static_src` must not be added to Django `STATICFILES_DIRS`.
- `backend/static/css/app.tailwind.css` must be committed.
- Generated CSS must include a header warning that it is generated and must not be edited directly.
- Source maps should not be committed unless the team explicitly chooses to ship them.
- Build output must be deterministic from [`package-lock.json`](../../package-lock.json).

### 6.2 NPM scripts

Add scripts with these responsibilities; exact command syntax must follow the installed official Tailwind CLI version:

| Script | Responsibility |
| --- | --- |
| `css:watch` | Watch Tailwind sources during local development. |
| `css:build` | Produce minified committed CSS for production. |
| `css:check` | Rebuild and fail when the committed output differs. |
| `playwright:test` | Preserve the existing browser test command. |

Do not require Node at Django application startup. Developers run the watcher separately when changing styles.

### 6.3 Template bases during migration

Create two isolated rendering paths:

```text
backend/templates/base_bootstrap.html   # frozen legacy base
backend/templates/base_tailwind.html    # migrated shell; Tailwind CSS + temporary Bootstrap JS
backend/templates/base.html             # compatibility decision documented per milestone
```

Recommended transition:

1. Copy the current base to `base_bootstrap.html` without changing its behavior.
2. Keep legacy pages on `base_bootstrap.html`.
3. Build `base_tailwind.html` from the same permission and navigation contracts.
4. Move one template at a time to `base_tailwind.html`.
5. Once all templates are migrated, make `base.html` the Tailwind base or remove the temporary naming layer in one reviewed cleanup.

Do not load Bootstrap CSS and Tailwind CSS in the same HTML document. This avoids reset, utility, and component cascade conflicts.

### 6.4 Shared shell logic

Do not duplicate the long permission-sensitive navigation logic between bases. Extract semantic partials where this can be done without changing authorization behavior, for example:

```text
backend/templates/components/navigation/
  desktop_sidebar_bootstrap.html
  desktop_sidebar_tailwind.html
  desktop_navigation_items.html
  user_menu_items.html
```

The shared partial owns destinations, labels, permission conditions, active-route conditions, and accessible names. Presentation-specific wrappers own classes and layout.

Test all role-specific navigation assertions after any extraction. In particular, preserve the special report-only Auditor sidebar and Puskesmas-specific entries.

## 7. CSS ownership model

Every class encountered during migration must be placed in one of these categories.

### 7.1 Tailwind utilities

Use utilities for one-off layout and presentation:

- display, flex, grid, gap, alignment, and positioning;
- spacing and sizing;
- typography and color;
- border, radius, shadow, background, and responsive behavior;
- visible focus, hover, active, disabled, and print variants.

### 7.2 Project component classes

Use project-owned component classes for repeated, semantically stable patterns whose full utility lists would otherwise be copied across many templates:

- buttons and icon buttons;
- form controls, labels, help text, and errors;
- cards/panels only where the accepted design calls for them;
- data tables and responsive table containers;
- status badges;
- alerts and flash messages;
- pagination;
- sidebar navigation;
- dialogs/modals during the Bootstrap-JavaScript bridge;
- Tom Select integration;
- print-document structures.

Define these in Tailwind source layers with tokens and `@apply` where supported. Do not recreate all of Bootstrap under new names.

### 7.3 Behavior hooks

Behavior hooks must not carry visual meaning:

- IDs used by scripts;
- `js-*` classes;
- `data-*` hooks;
- temporary `data-bs-*` hooks;
- temporary state classes required by Bootstrap JavaScript.

Do not rename or remove these in a CSS-only slice unless tests prove that no JavaScript references them.

### 7.4 Legacy classes

Bootstrap presentation classes are legacy dependencies. Track their removal, including:

- `btn*`, `card*`, `table*`, `alert*`, and `badge*`;
- `form-control*`, `form-select*`, `input-group*`, and validation classes;
- grid and responsive column classes;
- spacing, display, flex, typography, background, and border utilities;
- pagination and navigation classes;
- modal, toast, dropdown, collapse, and tooltip presentation classes.

Some names such as `modal`, `collapse`, `dropdown-menu`, `show`, and `fade` remain temporarily as behavior contracts. Document these exceptions instead of counting them as completed presentation migration.

## 8. Tailwind source detection rules

Tailwind scans source files as text. It does not evaluate Django template conditions or Python string concatenation.

Agents must follow these rules:

- Register all relevant Django templates, Python form files, and project JavaScript sources explicitly when automatic detection is insufficient.
- Prefer full literal classes in templates.
- Never construct partial Tailwind tokens such as `bg-{{ color }}-600`.
- Map server-side values to complete literal classes or stable semantic component classes.
- Keep a small explicit source/safelist only for classes that genuinely cannot appear literally.
- Add a test or build assertion for any server-generated class map.

For example, the dynamic Bootstrap flash class in [`backend/templates/base.html`](../../backend/templates/base.html) must not become a dynamically interpolated Tailwind class. Use an explicit conditional that emits complete classes or a semantic mapping such as `flash--success`.

## 9. Design-system preparation gate

The selected scope is careful modernization, so implementation must not begin by mechanically translating every Bootstrap class.

Before the first Tailwind page is coded:

1. Capture the current UI at representative desktop and mobile viewports.
2. Record exact visible copy and navigation labels.
3. Produce visual concepts for the minimum representative set:
   - authenticated desktop shell and dashboard;
   - dense list/table page;
   - standard form with validation;
   - workflow detail page with status and actions;
   - modal/confirmation state;
   - login/lockout state;
   - centralized error page;
   - mobile/PWA stock or approval surface;
   - one print document.
4. Obtain user approval before translating the concepts into tokens and components.
5. Record the approved palette, typography, spacing, density, border, radius, shadow, icon, focus, and responsive rules.

Do not invent new workflows, metrics, fields, navigation entries, or visible product claims in the concepts.

## 10. Bootstrap JavaScript bridge

Bootstrap JavaScript remains temporarily loaded on Tailwind pages. This is an intentional compatibility layer, not the target architecture.

### 10.1 Required bridge coverage

Tailwind source must provide the visual/state CSS needed by current Bootstrap JavaScript for:

- sidebar and navigation collapse;
- dropdown menus and Popper positioning;
- modal container, dialog, backdrop, open state, scroll lock, and transitions;
- toast placement, visible/hidden states, and dismissal;
- alert dismissal;
- tooltip rendering and placement;
- `.show`, `.fade`, `.collapsing`, and related state contracts used at runtime.

### 10.2 Bridge restrictions

- Keep the bridge in one clearly labeled source section or file.
- List every retained Bootstrap behavior selector in a migration ledger.
- Do not copy Bootstrap CSS wholesale.
- Implement only the selectors exercised by this repository.
- Verify keyboard focus, Escape dismissal, focus restoration, backdrop clicks, and body scroll behavior.
- Add browser coverage before considering a bridged component complete.

### 10.3 Exit condition

The bridge remains until the later Alpine project replaces the corresponding Bootstrap JavaScript component. Removing it is explicitly outside this CSS plan.

## 11. Forms migration strategy

Forms are the largest cross-cutting dependency and must be migrated deliberately.

### 11.1 Shared rendering contract

Create reusable Django rendering primitives for:

- label and required indicator;
- input/select/textarea presentation;
- help text;
- field errors and non-field errors;
- disabled and read-only states;
- checkbox/radio controls;
- file inputs;
- date and datetime controls;
- formsets and deletion rows;
- compact table-row controls;
- input-with-button patterns;
- accessible `aria-describedby` and invalid-state wiring.

Do not hand-code authentication fields. Render the existing form fields through the shared contract.

### 11.2 Python form cleanup

For each migrated form:

1. Preserve semantic widget attributes such as `type`, `min`, `max`, `step`, `rows`, `maxlength`, `autocomplete`, and `readonly`.
2. Preserve `js-*` behavior hooks.
3. Remove Bootstrap presentation classes from Python.
4. Avoid replacing them with long page-specific Tailwind strings in Python.
5. Prefer shared widget classes or the shared renderer.
6. Update exact-markup tests only when the new contract is intentional and visually verified.

### 11.3 Crispy migration

- Keep `django-crispy-forms` and `crispy-bootstrap5` available while legacy templates still need them.
- Do not configure one global Tailwind crispy pack while Bootstrap pages remain unless compatibility is proven.
- Migrate one form/template pair at a time to the shared Tailwind renderer.
- Remove `crispy-bootstrap5` only after no template, helper, layout, or test depends on it.
- Remove `django-crispy-forms` only if the final implementation has no remaining project use; do not assume both packages must be removed together.

## 12. Third-party and icon strategy

### 12.1 Tom Select

- Keep the existing JavaScript library during this project.
- Replace the Bootstrap-specific stylesheet with a project-owned Tailwind-compatible theme.
- Preserve focus, disabled, invalid, multi-select, clear-button, optgroup, and dropdown behavior.
- Verify high-density table/form usage, not only standalone selects.

### 12.2 Flatpickr

- Keep the locally vendored Flatpickr assets and Indonesian locale.
- Preserve the native `datetime-local` no-JavaScript fallback required by [`backend/apps/users/AGENTS.md`](../../backend/apps/users/AGENTS.md).
- Restyle only its surrounding form integration unless an explicit Flatpickr theme migration is approved.

### 12.3 Bootstrap Icons

Bootstrap Icons are a separate dependency from Bootstrap CSS and JavaScript.

- They may remain during the CSS migration to reduce scope.
- Decide the long-term icon system during design approval.
- Do not replace hundreds of icons mechanically without verifying metaphor, stroke/fill style, alignment, and accessible labels.
- Bootstrap CSS removal is not blocked by temporarily retaining Bootstrap Icons.

## 13. Migration waves

Each wave is a separate reviewable change set. Read the repository-level [`AGENTS.md`](../../AGENTS.md) and the owning app guide before editing that app.

### Wave 0: Baseline and safety net

Deliverables:

- Route/screen inventory grouped by role and workflow.
- Current screenshots at agreed desktop and mobile dimensions.
- Interaction inventory for all `data-bs-*` and `bootstrap.*` usages.
- Visual regression/smoke scenarios for the representative surfaces.
- Migration ledger with columns: surface, template, base, Bootstrap CSS dependencies, JavaScript hooks, form renderer, test coverage, migration status.
- Approved design concepts and token specification.

Exit gate:

- Current behavior is reproducible.
- High-risk workflows and screenshots are recorded.
- Visual direction is approved.

### Wave 1: Toolchain and design tokens

Deliverables:

- Tailwind CLI dependency and locked transitive dependencies.
- Source and generated CSS locations from section 6.
- `css:watch`, `css:build`, and `css:check` scripts.
- Explicit source detection for Django templates, relevant Python files, and JavaScript.
- Base tokens for color, typography, spacing, radius, shadow, focus, status, and print.
- CI check that the committed generated CSS is current.
- Documentation in [`README.md`](../../README.md) and [`docs/developer_guide.md`](../developer_guide.md).

Exit gate:

- A clean checkout can reproduce the committed CSS.
- `collectstatic` includes the generated file.
- No production Node runtime is required.

### Wave 2: Dual bases and desktop shell pilot

Pilot surfaces:

- authenticated desktop shell;
- dashboard;
- one representative read-oriented list, recommended: item list;
- flash messages;
- sidebar collapse and user dropdown using the Bootstrap JavaScript bridge.

Deliverables:

- Frozen legacy base and new Tailwind base.
- Shared navigation semantics without duplicated permission logic.
- Tailwind sidebar, header, content container, buttons, status styles, table primitive, pagination, empty state, and loading/disabled states.
- Browser tests for role-specific navigation and responsive shell behavior.

Exit gate:

- Pilot pages do not load Bootstrap CSS.
- Legacy pages remain visually and functionally unchanged.
- All six roles receive the correct navigation.

### Wave 3: Authentication and centralized errors

Surfaces:

- login;
- lockout;
- password change and completion;
- 400, 403, 404, 429, 500, and 503 pages.

Special checks:

- Preserve axes behavior and generic credential failure messaging.
- Preserve form autocomplete attributes and password-toggle behavior.
- Preserve standalone error rendering when the authenticated shell is unavailable.
- Replace inline error-page styles with the Tailwind source where practical.

### Wave 4: Read-only lists, details, and reports

Prioritize surfaces with low mutation risk:

- stock lists/cards and transaction history;
- receiving, procurement, distribution, allocation, recall, expired, and stock-opname lists/details;
- reports and numbering history;
- Puskesmas read-only reports;
- user detail and read-only settings views.

Preserve dense table layouts. Do not convert operational tables into card grids unless the approved responsive design explicitly calls for it.

### Wave 5: Simple CRUD forms

Suggested order:

1. Items.
2. Users.
3. Shared settings and numbering settings.
4. Puskesmas subunits.
5. Simple filters and search forms.

This wave proves the shared field renderer before high-risk formsets are attempted.

### Wave 6: Complex workflow forms and Bootstrap components

Migrate forms with formsets, dependent selectors, modals, and higher workflow risk:

- procurement contracts and amendments;
- receiving and planned receiving;
- allocation;
- distribution;
- recall;
- expired/disposal;
- stock opname;
- Puskesmas receiving, consumption, and requests;
- LPLPO create/edit/review/import;
- authority delegation.

For every owning app:

- Read its app-level `AGENTS.md` first.
- Preserve workflow status checks and POST contracts.
- Preserve `js-*`, IDs, hidden management fields, and formset prefixes.
- Verify add/remove row behavior, validation, disabled states, and confirmation modals.

### Wave 7: Mobile/PWA

Migrate [`backend/templates/mobile/base.html`](../../backend/templates/mobile/base.html) and its child templates only after desktop primitives are stable.

Requirements:

- Preserve `/mobile/` entry policy and existing session authentication.
- Preserve safe-area insets, manifest, install prompt, bottom navigation, and approval permissions.
- Preserve touch-target sizing and narrow-screen table/list behavior.
- Follow [`backend/apps/mobile/AGENTS.md`](../../backend/apps/mobile/AGENTS.md).

### Wave 8: Print and standalone surfaces

Migrate print/report templates separately because screen utilities are not an adequate print system.

Requirements:

- Define print-specific tokens, page margins, table borders, signatures, page breaks, and hidden controls.
- Verify document numbers, dates, totals, signatures, and Indonesian number formatting.
- Render representative print outputs to PDF or browser print preview for comparison.
- Treat Django Admin override templates as a separate compatibility surface; do not unintentionally restyle the entire Django Admin.

### Wave 9: Bootstrap CSS removal

Only after every surface has passed its wave gate:

- Remove Bootstrap CSS links from all templates.
- Remove the vendored Bootstrap CSS directory.
- Remove Bootstrap-specific custom-property usage.
- Remove `style.css` rules that only override Bootstrap.
- Remove the Tom Select Bootstrap theme.
- Remove crispy-bootstrap5 after proving zero remaining use.
- Update tests and documentation.

Bootstrap JavaScript, `data-bs-*`, and behavior bridge selectors remain explicitly tracked for the later Alpine project.

## 14. Per-template execution checklist

For every migrated template:

1. Identify its parent base, owning app, route, roles, module scopes, and responsive expectations.
2. Read the owning app `AGENTS.md`.
3. List Bootstrap presentation classes and behavior hooks separately.
4. List linked CSS/JavaScript and inline styles.
5. Preserve Django template conditions, URLs, CSRF tokens, hidden inputs, and form prefixes.
6. Replace presentation classes with approved Tailwind utilities/components.
7. Keep required JavaScript IDs, `js-*` classes, and temporary `data-bs-*` hooks.
8. Replace dynamically generated visual classes with complete literal mappings.
9. Verify empty, populated, validation-error, disabled, and permission-restricted states.
10. Verify desktop and mobile rendering in the browser.
11. Run the owning app tests.
12. Update the migration ledger.

## 15. Testing and verification strategy

### 15.1 Static/build checks

Run or add checks that prove:

- Tailwind source compiles successfully.
- Production output is minified.
- Generated CSS is committed and current.
- The output file is found by Django staticfiles.
- `collectstatic` succeeds using the production storage backend.
- No Tailwind class needed at runtime is missing due to dynamic construction.

### 15.2 Django checks

Minimum commands per change set:

```powershell
./scripts/run-django-test.ps1 -Target apps.core.tests.test_url_consistency -KeepDb
./scripts/run-django-test.ps1 -Target <owning.app.test.path> -KeepDb
```

Also run Django system checks and broader tests in proportion to the affected shell or shared form-renderer blast radius.

Do not report tests as passing unless they were executed successfully in the configured environment.

### 15.3 Browser checks

Use the existing Playwright authentication profiles for:

- `PUSKESMAS`
- `GUDANG`
- `KEPALA`
- `ADMIN_UMUM`
- `AUDITOR`
- `ADMIN`

At minimum, verify:

- desktop shell at a common laptop viewport;
- narrow mobile viewport;
- sidebar open/close and scroll behavior;
- dropdowns, collapse, modals, toasts, alerts, and tooltips;
- one list, detail, create/edit form, validation failure, and destructive confirmation;
- mobile stock and approval navigation;
- print preview for representative official documents.

### 15.4 Accessibility checks

For each component family, verify:

- keyboard reachability and logical focus order;
- visible focus indicators;
- accessible names for icon-only controls;
- modal focus entry, Escape behavior, focus restoration, and background isolation;
- labels, descriptions, and errors connected to fields;
- sufficient text/status contrast;
- status not communicated by color alone;
- responsive zoom without clipped primary actions;
- reduced-motion behavior where transitions are present.

### 15.5 Visual fidelity ledger

For each wave, compare the approved concept with current browser screenshots and record at least:

- shell/layout hierarchy;
- typography;
- spacing and density;
- palette and status colors;
- tables/forms;
- component states;
- responsive behavior;
- icon treatment.

Record every remaining mismatch as fixed, intentionally deferred, or blocked with evidence.

## 16. Search-based audit commands

Use targeted searches throughout the migration. Adjust exclusions only when justified.

```powershell
# Bootstrap CSS references
rg -n "vendor/bootstrap/css|bootstrap\.min\.css" backend

# Bootstrap presentation and behavior attributes
rg -n "data-bs-|\b(btn|card|table|alert|badge|modal|toast|dropdown|collapse|form-control|form-select|input-group)(-|\b)" backend/templates backend/apps

# Direct Bootstrap JavaScript API calls; expected to remain until the Alpine project
rg -n "\bbootstrap\." backend/static/js

# Crispy dependencies
rg -n "crispy|CRISPY_" backend requirements.txt

# Bootstrap custom properties and Tom Select theme coupling
rg -n -- "--bs-|tom-select\.bootstrap5" backend

# Inline styles that continue to block CSP tightening
rg -n "style=|<style" backend/templates

# Tailwind class interpolation hazards
rg -n "(bg|text|border|ring|shadow|grid-cols|col-span)-.*({{|{%|\+)" backend/templates backend/apps backend/static/js
```

Search results are evidence, not an automatic deletion list. The word `bootstrap` also appears in unrelated domain terminology such as the LPLPO January bootstrap baseline.

## 17. Risk register

| Risk | Evidence | Mitigation |
| --- | --- | --- |
| CSS migration breaks JavaScript components | Bootstrap APIs and `data-bs-*` are used across templates/scripts. | Preserve behavior hooks and implement the temporary state-style bridge; test each component in a browser. |
| Tailwind omits runtime classes | Django currently generates conditional class fragments. | Emit complete literal classes or semantic component classes; add source detection and build tests. |
| Permission-sensitive navigation changes | Base template contains extensive role/scope conditions. | Extract semantic navigation carefully and run all role-specific assertions and browser checks. |
| Forms lose validation/accessibility | Classes are injected in Python and crispy helpers. | Introduce a shared renderer, migrate one form at a time, and test error/disabled/help states. |
| Legacy and Tailwind CSS interfere | Both define resets and common class names. | Never load both stylesheets on the same page; use separate bases. |
| Production serves stale CSS | Deployment has no Node build. | Commit generated CSS and require `css:check` in CI. |
| Tom Select becomes visually or functionally inconsistent | Current theme depends on `--bs-*` variables. | Create and test a project-owned theme before removing Bootstrap CSS from affected pages. |
| Visual modernization harms operational density | Many pages contain dense tables and formsets. | Approve representative concepts and preserve table-driven workflows. |
| Exact-markup tests create false regressions | Tests assert current classes and asset names. | Change assertions only with intentional contract changes; prefer semantic hooks for new tests. |
| CSP is tightened prematurely | 346 inline style attributes and 33 style blocks remain. | Track inline styles separately; do not remove `'unsafe-inline'` without evidence. |
| Print output regresses | Several official documents use standalone styles. | Migrate print templates as a separate wave and compare rendered output. |

## 18. Tailwind migration definition of done

The CSS migration is complete only when all of the following are true:

- Every IMS template has an explicit migration status.
- All IMS desktop and mobile pages load the committed Tailwind output.
- No IMS page loads Bootstrap CSS.
- No project-owned template or Python form depends on Bootstrap presentation utilities.
- Bootstrap custom properties are absent from project-owned runtime CSS.
- Tom Select no longer uses its Bootstrap theme.
- Crispy Bootstrap rendering has zero remaining use, or any retained use is explicitly documented outside the migrated IMS surface.
- All six roles have passed navigation and representative workflow browser checks.
- Required Django tests, URL consistency tests, CSS build checks, and `collectstatic` pass.
- Representative desktop, mobile, validation, modal, and print states have passed visual review.
- The migration ledger contains no unexplained Bootstrap CSS dependency.
- Documentation describes CSS development, build, verification, and committed-output policy.
- Bootstrap JavaScript and its bridge are clearly documented as the only intentional Bootstrap remainder for the Alpine follow-up.

## 19. Alpine follow-up entry criteria

The separate Alpine migration may begin only after section 18 is met and accepted.

Its initial inventory must include:

- every remaining `data-bs-*` attribute;
- every `bootstrap.*` call;
- every retained Bootstrap state selector in the bridge;
- every custom vanilla interaction that might or might not benefit from Alpine;
- CSP compatibility requirements;
- accessibility behavior for dropdowns, disclosures, dialogs, notifications, and tooltips.

Do not assume every existing JavaScript function should be rewritten in Alpine. The follow-up must replace behavior selectively and preserve domain-oriented JavaScript where Alpine adds no value.

## 20. Agent operating rules

Any AI agent executing this plan must:

1. Work on one approved wave and one coherent slice at a time.
2. Read repository and owning-app instructions before editing.
3. Inspect the current code and tests rather than guessing markup or behavior.
4. Preserve unrelated user changes in the working tree.
5. Avoid editing already-applied migrations.
6. Keep behavior, permissions, route names, form submission, and workflow transitions unchanged unless separately authorized.
7. Use current official Tailwind documentation for syntax and installation choices.
8. Record the exact installed dependency versions from the package manager rather than inventing them.
9. Run proportional tests and browser verification before marking a slice complete.
10. Report confirmed results separately from assumptions or unexecuted validation steps.
11. Stop and request input when a visual or operational choice would materially change the product.
12. Never introduce Alpine during this CSS migration.

## 21. Inputs still required before Wave 0 visual approval

The architecture and execution order are sufficiently defined. The remaining product inputs are:

- preferred visual references or products whose density and tone are appropriate;
- whether the existing logo and core teal/blue identity must remain unchanged;
- minimum supported desktop browsers and mobile OS/browser versions;
- the preferred pilot workflow if Item List is not acceptable;
- reviewers who can approve the desktop shell, form system, mobile surface, and print output.

These inputs do not block inventory or test-baseline work, but visual implementation must not pass the design-system gate without them.
