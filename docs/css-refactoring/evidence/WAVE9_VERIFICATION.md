# Wave 9 verification — 5 November 2026

Branch: `tailwind/wave9-css-removal`, from local `main` at `1c51be6`. The user authorized review, commit, push and PR creation on 5 November 2026 after the visual-check handoff.

## Environment and scope

Windows; Bun 1.3.14, Node 24.12.0, Tailwind CLI 4.3.3. Django project checks use the existing `venv` and configured PostgreSQL test database. Browser checks use the locally installed Playwright and existing local role credentials; no account credentials or environment contents are recorded here. Browser plugin unavailable. Local preview: `http://127.0.0.1:8000/`.

The flow under test is: existing role login → desktop/mobile navigation and forms → unchanged rendered controls, validation, Bootstrap interactions and standalone print output using Tailwind without Bootstrap CSS. No successful workflow submission, stock mutation or permission change is part of this wave. The invalid delegation POST exercises validation without creating a delegation.

## Static and build gate

- `bun ci`: passed; 35 installs across 76 packages checked without lockfile changes.
- `bun run css:build` and `bun run css:check`: passed with the pinned CLI under Node. Generated minified output is included in the working tree.
- `venv/Scripts/python.exe backend/manage.py check`: passed.
- `findstatic css/app.tailwind.css --verbosity 0`: resolved the committed generated asset.
- `collectstatic --noinput --verbosity 0`: passed using configured WhiteNoise storage. A fresh temporary STATIC_ROOT collection contained Tailwind and no removed Bootstrap/legacy CSS. Django setup, system checks, all template compilation and fresh collection also passed while a Python import finder deliberately rejected both Crispy packages, proving the installed local extras are not hiding a runtime dependency.
- All 118 project templates compiled with Django's template loader; [the per-template inventory](wave9-template-inventory.json) records each rendering path and dependency status.
- Protected Django condition/loop/value/URL/CSRF token sequences matched the branch base in all 115 comparable existing templates, excluding only the planned renderer/alias changes.
- Form AST comparison against the branch base, ignoring widget class values/date-widget class arguments and removed Crispy helper statements/imports, found no other logic changes. LPLPO's removed initializer contained only its now-unused helper.
- `git diff --check`: passed at implementation checkpoints; final check recorded below.

## Browser and visual gate

34 role/page/viewport checks at 1440×900 and 390×900 covered ADMIN, PUSKESMAS, GUDANG, KEPALA, ADMIN_UMUM and AUDITOR. Stable-width checks had meaningful page content and no document overflow. Sidebar link counts match the earlier ledger: 34, 7, 25, 29, 21 and 7 respectively. Application pages load generated Tailwind plus Bootstrap Icons (and Flatpickr on delegation); Admin retains native CSS without app preflight. PUSKESMAS mobile stock is deliberately denied with HTTP 403; authorized mobile stock navigation is checked using ADMIN.

Interaction checks passed for quick-create modal focus entry, Escape, focus restoration, sidebar collapse, user dropdown/Escape, mobile sidebar, redirect flash toast dismissal, tooltip rendering, report-alert dismissal and authorized mobile stock → stock card. The interaction run had no console or script errors. A focused control computed a 2px solid outline, reduced-motion mode removed button transitions, and the 720 CSS-pixel reflow check had no document overflow. This is a logical-viewport reflow check, not a claim of operating native browser zoom. The mobile discovery button computed white text on the approved blue background. Delegation duration switches hide/disable and restore the end field, and invalid submission displays five field errors.

Baseline comparison is valid for the PUSKESMAS consumption/receiving/LPLPO pages. Initial ADMIN baseline captures were login screens because the existing launcher landed on Admin's separate login page; those captures are excluded. The temporary verification harness explicitly logs in through the existing application login and rejects login-page captures. No production launcher change is included.

Compared with the approved dense-list, form, modal, mobile and print concepts: the navy shell, white panels, pale canvas, dense matrices, labels above controls, real icons/logo and internal table scrolling remain. Existing labels/data/actions take precedence over illustrative concept content. The Crispy replacement retains required markers, help/errors, native groups and numeric alignment. A blue-on-blue mobile discovery button collision was corrected. Resize-transition captures are excluded; stable-width screenshots wait for the existing transition.

Stock Opname landscape, stock-card portrait and LPLPO standalone print routes returned HTTP 200 with only generated Tailwind CSS, repeated table headings and no app navigation. Print-media screenshots were inspected. Item delete confirmation returned HTTP 200 with its CSRF-protected form; it was not submitted. Physical printing and native PWA installation/device verification remain unperformed.

## Screenshot evidence

- [Delegation desktop](wave9/delegation-desktop.png) and [narrow](wave9/delegation-mobile.png).
- [Consumption matrix](wave9/consumption-desktop.png): required markers, labels and numeric alignment.
- [Quick-create modal](wave9/quick-create-modal.png), [mobile stock](wave9/mobile-stock.png), and [Stock Opname print](wave9/stock-opname-print.png).

## Test results

Tailwind source registration and project component layers follow the [official Tailwind source-detection documentation](https://tailwindcss.com/docs/detecting-classes-in-source-files) and [custom-style guidance](https://tailwindcss.com/docs/adding-custom-styles), checked through Context7.

| Django target | Tests | Final result |
| --- | ---: | --- |
| `apps.core.tests` | 149 | Passed |
| `apps.users.tests` | 77 | Passed |
| `apps.users.test_authority_delegation` | 32 | Passed |
| `apps.items.tests` | 44 | Passed |
| `apps.stock.tests` | 144 | Passed on corrected full rerun |
| `apps.receiving.tests` | 166 | Passed on corrected full rerun; focused 93-test group also passed |
| `apps.procurement.tests` | 64 | Passed |
| `apps.allocation.tests` | 51 | Passed |
| `apps.distribution.tests` | 138 | Passed |
| `apps.recall.tests` | 29 | Passed |
| `apps.expired.tests` | 55 | Passed |
| `apps.stock_opname.tests` | 58 | Passed on corrected full rerun |
| `apps.puskesmas.tests` | 142 | Passed |
| `apps.lplpo.tests` | 124 | Passed |
| `apps.mobile.tests` | 39 | Passed |
| `apps.reports.tests` | 41 | Passed |
| `apps.core.tests.test_css_migration` | 5 | Passed |
| `apps.core.tests.test_url_consistency` | 5 | Passed again sequentially |

All 12 tests across the six committed Playwright specifications passed. They cover allocation wizard/popover/matrix/fragment behavior and distribution/recall/expired form layout and stylesheet isolation. The final six-role browser rerun after refreshing static files and restarting the preview also passed.

Final `check`, `css:check` and `git diff --check` passed. All listed suites and guards are green; the final 166-test receiving rerun passed. No tests are left running.

## Corrections found during verification

- The initial class conversion touched a `row` expression inside template class attributes. Stock tests caught the template error; protected Django expressions and JavaScript interpolation expressions were restored. The 144-test stock rerun passed.
- Receiving tests found three old date-widget class strings outside widget dictionaries; these now emit project controls while retaining native-picker and date-mask hooks. The focused 93-test cleanup rerun passed.
- The Stock Opname replacement assertion initially read `widget.attrs["type"]`; Django moves that value to `widget.input_type`. The assertion was corrected and all 58 tests passed on the full rerun.
- Native Tailwind `col-span-*` classes were excluded from the Bootstrap column rename; stock summary and user-detail spans remain native utilities. The refreshed browser confirmed summary spans of one desktop/two narrow columns and user-detail spans of five/seven desktop columns with narrow stacking.
- Two committed browser tests still expected Bootstrap on previously migrated forms. Their stylesheet assertions now require Tailwind and reject Bootstrap; all 12 committed browser tests passed.
- Playwright's initial transform cache was not writable. Reruns use `$env:PWTEST_CACHE_DIR = Join-Path $env:TEMP 'ims-wave9-pw-cache'`; no elevated browser permissions or dependency change was needed.
- A combined routing test command attempted to initialize the shared test database while the workflow suite was running and could not do so. Routing must run sequentially after the app suites; that attempt is not a passing test result.

## Reproduction

From the repository root:

```powershell
bun ci
bun run css:build
bun run css:check
.\venv\Scripts\python.exe backend/manage.py check
.\venv\Scripts\python.exe backend/manage.py findstatic css/app.tailwind.css --verbosity 0
.\venv\Scripts\python.exe backend/manage.py collectstatic --noinput --verbosity 0
.\scripts\run-django-test.ps1 -Target apps.core.tests,apps.users.tests,apps.users.test_authority_delegation,apps.items.tests,apps.stock.tests,apps.receiving.tests,apps.procurement.tests,apps.allocation.tests,apps.distribution.tests,apps.recall.tests,apps.expired.tests,apps.stock_opname.tests,apps.puskesmas.tests,apps.lplpo.tests,apps.mobile.tests,apps.reports.tests -KeepDb
$env:PWTEST_CACHE_DIR = Join-Path $env:TEMP 'ims-wave9-pw-cache'
bun run playwright:test
git diff --check
```

Run Django suites sequentially against the preserved test database. The committed core tests include URL consistency and the new migration/renderer guards. Browser specs require the configured local server and existing `.env.playwright.local` accounts, as documented in `playwright/README.md`.

## Acceptance

The user released the visual-check hold and authorized review, commit, push and PR creation on 5 November 2026. This records authorization to proceed, without claiming that every page was manually inspected. The inherited Wave 7 physical-device/install checks remain pending, so the entire migration is not marked complete.

## Pre-commit review

The review found no blocking regressions in the final patch. It covered the shared renderer and grouped/hidden widgets, Python form attributes and helper removal, template contracts and retained Bootstrap data hooks, dynamic JavaScript presentation classes, CSS selectors, removed assets/configuration, native Admin isolation, and test/evidence changes. No models, workflow services, views, routes or migrations changed.

The review-time audit confirmed unchanged Django contracts and Bootstrap data hooks across 115 comparable templates. All five migration/renderer guards, Django system checks, generated-CSS consistency and `git diff --check` passed again. A fresh fetch confirmed `origin/main` remains `1c51be6`, the branch base. Earlier full app/browser/static verification results above remain valid; no runtime code changes were needed during review.
