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
