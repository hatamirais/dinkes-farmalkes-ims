# Tailwind migration ledger

Updated 20 October 2026. Visual direction and root `DESIGN.md` are approved. The Bun/Tailwind toolchain and unused foundation CSS exist; all rendered surfaces below remain on their current Bootstrap or project CSS. This ledger tracks future shell and template migrations; it is not a claim that the concepts have been implemented.

| Surface | Source template | Base / CSS dependency | Interaction or form contract | Existing verification | Status |
| --- | --- | --- | --- | --- | --- |
| Desktop shell | `backend/templates/base.html` | Bootstrap CSS, Bootstrap Icons, `style.css` | Sidebar collapse, dropdown, notifications; role and module-scope navigation | Browser review; core tests | Legacy; shared-shell task |
| Dashboard | `backend/templates/dashboard.html` and role-specific dashboard variants | Desktop base | Server-computed quick links, transactions, expiry list | Browser review; core tests | Legacy |
| Dense item list | `backend/templates/items/item_list.html` | Desktop base | Filters, XLSX export, edit actions | Browser review; items tests | Legacy |
| Item form and quick-create modal | `backend/templates/items/item_form.html` | Desktop base; Bootstrap modal `data-bs-*` | Item form classes, lookup POST validation, native checkbox/toggle semantics | Browser review; items tests | Legacy |
| Distribution workflow detail | `backend/templates/distribution/distribution_detail.html` | Desktop base; Bootstrap collapse/modal `data-bs-*` | Server-authorized actions, `confirm-actions.js` print hook, SBBK print sheet | Browser review; distribution tests | Legacy |
| Login and lockout | `backend/templates/registration/login.html`, `lockout.html` | Desktop base public content; crispy Bootstrap authentication form | Existing login, lockout, errors, axes | Browser review; core auth tests | Legacy |
| Centralized errors | `backend/templates/errors/status.html` | Direct Bootstrap CSS link | Centralized status actions and error handling | Browser review; core error tests | Legacy |
| Mobile stock and approval | `backend/templates/mobile/base.html`, `stock_list.html`, `approval_inbox.html` | Mobile Bootstrap CSS/JS and `mobile.css` | Session/CSRF, bottom navigation, stock filters, approval access | Browser review; mobile tests | Legacy; mobile wave |
| SBBK print | Print section of `backend/templates/distribution/distribution_detail.html` | Existing `@media print` and Bootstrap table rules | Seven-column table, conditional metadata, two signature blocks | Print-media browser capture; distribution tests | Legacy; print wave |

## Foundation status

- `backend/static_src/css/app.css` contains approved tokens and reusable buttons, fields, tables, badges, alerts, pagination, focus, disabled, and print foundations.
- `backend/static/css/app.tailwind.css` is committed generated output. `bun run css:check` verifies it; CI runs this check on relevant source and configuration changes.
- No Tailwind class or component above is loaded by a production template yet. No base template, form renderer, route, schema, permission, or workflow was changed by this foundation stage.
- Bootstrap CSS and JavaScript remain intentionally present. Alpine.js is deferred. `style-src 'unsafe-inline'` remains while inline styles exist.
