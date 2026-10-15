# users AGENTS.md

App-specific guidance for accounts, roles, module scopes, Acting Kepala authority, and user audit behavior.

## Permissions And Roles

- `apps.users.User` is the configured auth model.
- `ModuleAccess` supplements Django permissions. Scopes are `NONE`, `VIEW`, `OPERATE`, `APPROVE`, and `MANAGE`; default role scopes live in `apps.users.access`.
- Elevated module scope alone does not turn a user into an approver where the owning workflow also requires role `ADMIN` / `KEPALA`.
- `AUDITOR` keeps read-only scopes for directly authorized pages. Its sidebar is report-only, and its dashboard must not link into operational menu pages.
- User-management denials raise `PermissionDenied` and use centralized error rendering.

## Acting Kepala

- Temporary authority uses `AuthorityDelegation`; never change `User.role` to model an acting appointment.
- Only superusers, `ADMIN`, and `KEPALA` manage delegations under `/users/acting-authority/`.
- Delegates must be active `ADMIN_UMUM` or `GUDANG` users with existing access to the delegated module.
- `ADMIN_UMUM` and `GUDANG` may have an optional active Puskesmas facility link for Puskesmas/LPLPO delegation. Other facility types are not valid delegate links. `PUSKESMAS` still requires a Puskesmas facility but is never an eligible delegate.
- Delegations are module-specific and either finite with timezone-aware bounds or open-ended (`ends_at=NULL`, `Sampai dicabut`). Non-revoked delegations cannot overlap for one module.
- Creation locks and reloads the grantor, delegate, and their relevant module-access rows, then revalidates all eligibility rules before inserting any delegation rows.
- Revocation locks and reloads the actor plus relevant module access before locking the delegation, then rechecks both module authority and the current end time. A finite delegation at or past `ends_at` remains naturally `Berakhir` and must not receive revocation actor/time/reason metadata.
- The delegation create form uses the locally vendored Flatpickr 4.6.13 assets to guarantee Indonesian, 24-hour `DD/MM/YYYY HH:mm` controls while preserving the Django `YYYY-MM-DDTHH:mm` submission format; keep its no-JavaScript native `datetime-local` fallback valid.
- Delegation supplements, rather than replaces, the permanent Kepala.
- Approval workflows lock and reload the actor plus relevant module access before resolving permanent authority, then lock candidate delegations and recheck eligibility and current time before locking the workflow row.
- Transactional authority decisions expose that locked actor; facility-bound workflows must use it for their post-lock object-scope check, ownership fields, and delegated audit snapshot.
- Exercised authority creates append-only `AuthorityExercise` actor/title/grant snapshots so historical output continues to identify the real actor as `Plh. Kepala Instalasi` after expiry, revocation, or profile changes.
- Any workflow target referenced by `AuthorityExercise` is protected from instance, queryset/bulk, and cascading hard deletion so the generic audit reference cannot be orphaned.
- Render a delegated signature only when its `AuthorityExercise` actor and timestamp match the workflow object's current checkpoint actor and timestamp. Historical exercises remain append-only but must not override a later permanent or delegated action after step-back and reprocessing.
- Delegation never grants settings access, user management, Django Admin, facility bypass, or unrelated module access.

## Mutation Throttling And Audit

- `@user_mutation_ratelimit` covers user create, update, toggle-active, delete, delegation creation, and delegation revocation.
- Password-reset and password-change flows use their dedicated settings-backed limits.
- `django-auditlog` records database-backed create/update/delete history for selected critical models; its current UI is the `LogEntry` Django Admin at `/admin/`, not a custom IMS sidebar page.
- Auditlog is signal-driven and does not automatically cover `bulk_create`, `bulk_update`, or `QuerySet.update()`. Critical bulk paths need explicit workflow logs or tests where row-level history is required.
- User bulk activate/deactivate intentionally locks rows and calls per-row `save(update_fields=["is_active"])` so each status change emits an audit entry.
