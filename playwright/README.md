Local Playwright workspace for browser-based verification and focused UI regressions.

Use the root npm scripts and files under `scripts/playwright/` to bootstrap auth and open role windows for manual multi-role checking.

Committed specs under `playwright/` are reserved for targeted browser regressions that are hard to cover with Django tests alone, such as frontend-derived wizard state.

Useful commands from repo root:

- `npm run playwright:bootstrap`
- `npm run playwright:open`
- `npm run playwright:test`

Current default launcher set: PUSKESMAS, GUDANG, KEPALA, ADMIN_UMUM, AUDITOR, ADMIN.

