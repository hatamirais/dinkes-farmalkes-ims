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
- Delegations are module-specific and either finite with timezone-aware bounds or open-ended (`ends_at=NULL`, `Sampai dicabut`). Non-revoked delegations cannot overlap for one module.
- Delegation supplements, rather than replaces, the permanent Kepala.
- Approval workflows re-resolve and lock the delegation inside their transaction.
- Exercised authority creates append-only `AuthorityExercise` actor/title/grant snapshots so historical output continues to identify the real actor as `Plh. Kepala Instalasi` after expiry, revocation, or profile changes.
- Delegation never grants settings access, user management, Django Admin, facility bypass, or unrelated module access.

## Mutation Throttling And Audit

- `@user_mutation_ratelimit` covers user create, update, toggle-active, delete, delegation creation, and delegation revocation.
- Password-reset and password-change flows use their dedicated settings-backed limits.
- `django-auditlog` records database-backed create/update/delete history for selected critical models; its current UI is the `LogEntry` Django Admin at `/admin/`, not a custom IMS sidebar page.
- Auditlog is signal-driven and does not automatically cover `bulk_create`, `bulk_update`, or `QuerySet.update()`. Critical bulk paths need explicit workflow logs or tests where row-level history is required.
- User bulk activate/deactivate intentionally locks rows and calls per-row `save(update_fields=["is_active"])` so each status change emits an audit entry.
