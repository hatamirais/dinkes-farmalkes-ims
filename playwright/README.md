Local Playwright workspace for browser-based verification and focused UI regressions.

Use Bun 1.3.14 and the root scripts under `scripts/playwright/` to bootstrap auth and open role windows for manual multi-role checking. Run `bun ci` first. The browser helper processes use a local Node runtime because persistent Chromium launch hung under Bun 1.3.14 on Windows during migration; package installation and script entry use Bun.

Committed specs under `playwright/` are reserved for targeted browser regressions that are hard to cover with Django tests alone, such as frontend-derived wizard state.

Useful commands from repo root:

- `bun run playwright:bootstrap`
- `bun run playwright:open`
- `bun run playwright:test`

Current launcher set: PUSKESMAS, GUDANG, GUDANG2, KEPALA, ADMIN_UMUM, AUDITOR, ADMIN (seven profiles across six roles).

