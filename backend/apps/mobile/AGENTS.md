# mobile AGENTS.md

App-specific guidance for the server-rendered mobile/PWA surface.

## Surface And Entry Policy

- Mobile is Django templates and existing session authentication, not a standalone React frontend or public REST API.
- Desktop and installed-PWA entry points use `/mobile/`.
- Users with stock-view access land on mobile stock; approval-only users land on the approval inbox; users with neither receive `403`.

## Approval Inbox

- The inbox mirrors the owning workflow's role and module-scope rules; mobile access never broadens approval authority.
- Distribution and expired approvals require superuser or role `ADMIN` / `KEPALA` with the relevant module scope at least `APPROVE`, unless the owning workflow accepts a currently valid module-specific Acting Kepala delegation.
- Allocation-generated child distributions are excluded because their actions belong to the parent Allocation workflow.
- Permission failures raise `PermissionDenied` and use centralized error rendering.

## Tailwind presentation

The server-rendered mobile/PWA shell and all five routed child templates load generated Tailwind CSS through `mobile/base.html`, with scoped source in `backend/static_src/css/mobile.css`. Bootstrap CSS and the unused Bootstrap bundle are absent from mobile pages; Bootstrap Icons and the unchanged `mobile.js` remain. The historical `backend/static/mobile/css/mobile.css` was removed during Wave 9. Manifest/service-worker behavior and routes are unchanged.

Keep all `data-mobile-*`, `data-pwa-*`, stock-result IDs, native confirmation forms, and session/CSRF contracts. Use the approved shared tokens and at least 44px touch targets. Dynamic stock-service `text-bg-*` values are adapted only under `.mobile-shell .mobile-stock-badge`; do not change the shared stock service for presentation. Device-only PWA checks and current route evidence are recorded in `docs/css-refactoring/MIGRATION_LEDGER.md`.
