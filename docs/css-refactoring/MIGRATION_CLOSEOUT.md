# Bootstrap CSS → Tailwind closeout

Verified 5 November 2026 against merged `main` at `1a7c305` (PR #311). Release version: `2.0.0`.

The CSS implementation is closed: all nine implementation waves are merged, all IMS surfaces use generated Tailwind, and Bootstrap CSS/Crispy dependencies are removed. This is not an unconditional pass of the original acceptance gate: native PWA installation and physical-device checks remain pending, with installation-prompt issue [#309](https://github.com/hatamirais/dinkes-farmalkes-ims/issues/309) still open when checked on 5 November. No device result or root cause is inferred from that issue.

## Definition-of-done audit

This table follows section 18 of [the migration plan](TAILWIND_CSS_MIGRATION_PLAN.md). “Recorded” refers to executed checks in [the Wave 9 evidence](evidence/WAVE9_VERIFICATION.md) and the [ledger](MIGRATION_LEDGER.md), not newly repeated full app/browser suites for this documentation/version change.

| Requirement | Result and evidence |
| --- | --- |
| Every template has a migration status | Recorded: [118-template inventory](evidence/wave9-template-inventory.json), including shared fragments, error/print surfaces and native Admin. |
| IMS desktop/mobile pages load generated Tailwind | Recorded template audit and six-role browser checks; standalone print/error pages load it directly. Admin remains native. |
| No IMS page loads Bootstrap CSS | Migration guard checks templates and CSS sources; vendored CSS directory and legacy stylesheets are absent. |
| No dependency on Bootstrap presentation utilities | Project-owned `ims-*` components and Tailwind utilities supply presentation. Retained names are documented behavior hooks, shell compatibility selectors or stock/status adapters supplied by project CSS. |
| No Bootstrap custom properties in project runtime CSS | Migration guard and source audit find no `--bs-*` references in project CSS/templates. Vendored Bootstrap JavaScript is intentionally retained. |
| No Tom Select Bootstrap theme | Theme removed; Items uses the scoped project theme. |
| No Crispy Bootstrap rendering | Packages, settings, imports, helpers and template rendering removed. Django/template/static checks also passed with Crispy imports blocked. `CrispyAuthenticationForm` is only the existing compatibility class name. |
| Six-role navigation/workflow browser checks | Recorded: 34 desktop/narrow page states, matching role navigation counts, representative forms and permission denial. |
| Django, URL, CSS and static collection checks | Recorded app suites, URL checks and WhiteNoise collection passed; closeout checks are listed below. |
| Reproducible Bun installation and current compiled CSS | Recorded `bun ci` and build/check passed without lockfile changes; generated output is committed. |
| All committed Playwright specs pass | Recorded: 12 tests across six specs, including allocation popover geometry, row removal, sticky matrices and fragment return. |
| Representative visual states accepted | Desktop/narrow, validation, modal, mobile and print evidence recorded; user released the visual-check hold and authorized publication. Native PWA/device acceptance remains pending; no every-page manual inspection is claimed. |
| No unexplained Bootstrap CSS dependency | Current dependency inventory and intentional remainder are in the ledger and design system. |
| CSS build/deployment policy documented | Root README/AGENTS, developer guide and design system describe committed output and Python-only production runtime. |
| Bun commands and remaining Node needs documented | `bun.lock` is authoritative; npm lockfile removed. Node remains a development/CI runtime for Tailwind and Playwright helpers. |
| Intentional Bootstrap remainder documented | Desktop Bootstrap JavaScript and behavior CSS remain; independent Bootstrap Icons also remain by design. No Alpine was introduced. |

## Intentional remainder and deferred work

- Bootstrap JavaScript and `data-bs-*` remain for collapse, dropdown, modal, toast, alert, tab and tooltip behavior. The ledger records 133 behavior attributes and seven scripts calling Bootstrap APIs. Project-owned bridge selectors and application hooks must survive until a separately authorized interaction migration replaces them.
- Bootstrap Icons, Flatpickr and native Django Admin styling remain. Removing the icon library or restyling Admin was never a CSS migration completion requirement.
- Alpine.js, Bootstrap JavaScript removal and CSP tightening remain outside this project. Inline styles still require the current style policy; CSS cleanup does not prove a tighter CSP is safe.
- Physical-printer/driver behavior is not established by Chromium print-media/PDF checks. Preserve that limitation from Wave 8.
- The supported browser/mobile OS matrix has not been formally fixed. Existing Chromium and narrow-viewport evidence must not be presented as cross-browser or physical-device certification.

## Remaining device/install acceptance

Track actual results under [issue #309](https://github.com/hatamirais/dinkes-farmalkes-ims/issues/309) and the ledger's “Pending device checks and Wave 7 exit gate” section. Required evidence includes the affected deployment URL/scheme, device/OS/browser versions, installation/standalone state, dismissal state, separate banner/button/native-dialog observations, manifest/service-worker status, and whether a genuine `beforeinstallprompt` event fires. Verify manual installation guidance, available native installation, dismissal persistence, standalone suppression and applicable mobile/session/permission behavior. Do not force or fabricate a native installation event to declare this accepted.

The CSS implementation/release documentation can be closed while these items remain explicitly tracked. The stricter original all-wave acceptance gate is still qualified; this closeout does not silently waive it or authorize the Alpine follow-up.

## Release and validation

The major bump from `1.35.0` to `2.0.0` follows the user's release direction and marks the changed presentation/dependency contract. Custom templates relying on removed Bootstrap CSS, Crispy helpers or `base_bootstrap.html` need adaptation; `base.html` remains a Tailwind compatibility alias. This version/docs closeout introduces no schema, workflow, permission or route changes.

The existing release workflow verifies the version command and core/URL tests, then creates `v2.0.0` and a GitHub release when the VERSION change reaches `main`. A branch change does not itself publish the release; no tag or release is created manually here.

Closeout validation: version command equals VERSION; semantic-version tests; migration/renderer and URL guards; Django system checks; generated CSS consistency; static discovery/collection; Markdown local-link checks; and whitespace checks. Final executed results are recorded with the release change. Full app/browser results remain the earlier Wave 9 evidence rather than a new execution claim.

### Executed closeout results — 5 November 2026

- `app_version` stdout exactly matches VERSION: `2.0.0`. The remote had no `v2.0.0` tag when checked.
- Fresh test databases: `apps.core.tests.test_core` passed 120 tests (including semantic-version coverage), `apps.core.tests.test_url_consistency` passed 5, and `apps.core.tests.test_css_migration` passed 5. These match the release workflow's core/URL gate with the migration guards added.
- The initial preserved-database core run failed one existing settings test because a migration-seeded `DocumentNumberRule` row was absent. The fresh-database rerun reapplied migrations and passed; no application/test logic was changed to bypass the failure. Use a fresh database when reproducing this release gate rather than relying on preserved seed state.
- Django system checks, `css:check`, `findstatic css/app.tailwind.css`, `collectstatic --noinput --verbosity 0` and `git diff --check` passed.
- Local Markdown links in all 11 audited current/reference documents resolved. Three removed-file links in the historical baseline were corrected to immutable pre-cleanup source links.
- Source inventory rechecked: 118 templates, 133 `data-bs-*` attributes and seven Bootstrap API scripts, matching the recorded intentional remainder. No runtime source or generated CSS changed in this closeout.

Reproduce the fresh test gate from the repository root:

```powershell
.\scripts\run-django-test.ps1 -Target apps.core.tests.test_core,apps.core.tests.test_url_consistency,apps.core.tests.test_css_migration
.\venv\Scripts\python.exe backend/manage.py app_version
.\venv\Scripts\python.exe backend/manage.py check
bun run css:check
.\venv\Scripts\python.exe backend/manage.py findstatic css/app.tailwind.css --verbosity 0
.\venv\Scripts\python.exe backend/manage.py collectstatic --noinput --verbosity 0
git diff --check
```
