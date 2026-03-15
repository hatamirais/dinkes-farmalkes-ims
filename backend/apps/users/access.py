from __future__ import annotations

from typing import Dict

from .models import ModuleAccess, User


ROLE_DEFAULT_SCOPES: Dict[str, Dict[str, int]] = {
    User.Role.ADMIN: {
        ModuleAccess.Module.USERS: ModuleAccess.Scope.MANAGE,
        ModuleAccess.Module.ITEMS: ModuleAccess.Scope.MANAGE,
        ModuleAccess.Module.STOCK: ModuleAccess.Scope.MANAGE,
        ModuleAccess.Module.RECEIVING: ModuleAccess.Scope.MANAGE,
        ModuleAccess.Module.DISTRIBUTION: ModuleAccess.Scope.MANAGE,
        ModuleAccess.Module.RECALL: ModuleAccess.Scope.MANAGE,
        ModuleAccess.Module.EXPIRED: ModuleAccess.Scope.MANAGE,
        ModuleAccess.Module.STOCK_OPNAME: ModuleAccess.Scope.MANAGE,
        ModuleAccess.Module.REPORTS: ModuleAccess.Scope.MANAGE,
        ModuleAccess.Module.ADMIN_PANEL: ModuleAccess.Scope.MANAGE,
    },
    User.Role.KEPALA: {
        ModuleAccess.Module.USERS: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.ITEMS: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.STOCK: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.RECEIVING: ModuleAccess.Scope.APPROVE,
        ModuleAccess.Module.DISTRIBUTION: ModuleAccess.Scope.APPROVE,
        ModuleAccess.Module.RECALL: ModuleAccess.Scope.APPROVE,
        ModuleAccess.Module.EXPIRED: ModuleAccess.Scope.APPROVE,
        ModuleAccess.Module.STOCK_OPNAME: ModuleAccess.Scope.APPROVE,
        ModuleAccess.Module.REPORTS: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.ADMIN_PANEL: ModuleAccess.Scope.NONE,
    },
    User.Role.ADMIN_UMUM: {
        ModuleAccess.Module.USERS: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.ITEMS: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.STOCK: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.RECEIVING: ModuleAccess.Scope.OPERATE,
        ModuleAccess.Module.DISTRIBUTION: ModuleAccess.Scope.OPERATE,
        ModuleAccess.Module.RECALL: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.EXPIRED: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.STOCK_OPNAME: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.REPORTS: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.ADMIN_PANEL: ModuleAccess.Scope.NONE,
    },
    User.Role.GUDANG: {
        ModuleAccess.Module.USERS: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.ITEMS: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.STOCK: ModuleAccess.Scope.OPERATE,
        ModuleAccess.Module.RECEIVING: ModuleAccess.Scope.OPERATE,
        ModuleAccess.Module.DISTRIBUTION: ModuleAccess.Scope.OPERATE,
        ModuleAccess.Module.RECALL: ModuleAccess.Scope.OPERATE,
        ModuleAccess.Module.EXPIRED: ModuleAccess.Scope.OPERATE,
        ModuleAccess.Module.STOCK_OPNAME: ModuleAccess.Scope.OPERATE,
        ModuleAccess.Module.REPORTS: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.ADMIN_PANEL: ModuleAccess.Scope.NONE,
    },
    User.Role.AUDITOR: {
        ModuleAccess.Module.USERS: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.ITEMS: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.STOCK: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.RECEIVING: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.DISTRIBUTION: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.RECALL: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.EXPIRED: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.STOCK_OPNAME: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.REPORTS: ModuleAccess.Scope.MANAGE,
        ModuleAccess.Module.ADMIN_PANEL: ModuleAccess.Scope.NONE,
    },
}


def default_scope_for_role(role: str, module: str) -> int:
    return ROLE_DEFAULT_SCOPES.get(role, {}).get(module, ModuleAccess.Scope.NONE)


def get_user_module_scope(user: User, module: str) -> int:
    assignment = (
        ModuleAccess.objects.filter(user=user, module=module).only("scope").first()
    )
    if assignment:
        return assignment.scope
    return ModuleAccess.Scope.NONE


def has_module_scope(user: User, module: str, min_scope: int) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return get_user_module_scope(user, module) >= min_scope


def required_scope_for_perm(perm: str) -> int:
    _, codename = perm.split(".", 1)
    action = codename.split("_", 1)[0]

    if action == "view":
        return ModuleAccess.Scope.VIEW

    if action in {"add", "change", "delete"}:
        return ModuleAccess.Scope.OPERATE

    return ModuleAccess.Scope.OPERATE


def has_module_permission(user: User, perm: str) -> bool:
    if "." not in perm:
        return False

    app_label, _ = perm.split(".", 1)
    valid_modules = {choice[0] for choice in ModuleAccess.Module.choices}
    if app_label not in valid_modules:
        return False

    if app_label == ModuleAccess.Module.USERS:
        required = required_scope_for_perm(perm)
        if required == ModuleAccess.Scope.VIEW:
            return has_module_scope(user, app_label, ModuleAccess.Scope.VIEW)
        return has_module_scope(user, app_label, ModuleAccess.Scope.MANAGE)

    return has_module_scope(user, app_label, required_scope_for_perm(perm))


def ensure_default_module_access(user: User, overwrite: bool = False) -> int:
    defaults = ROLE_DEFAULT_SCOPES.get(user.role, {})
    created_or_updated = 0

    for module, scope in defaults.items():
        obj, created = ModuleAccess.objects.get_or_create(
            user=user,
            module=module,
            defaults={"scope": scope},
        )
        if created:
            created_or_updated += 1
            continue

        if overwrite and obj.scope != scope:
            obj.scope = scope
            obj.save(update_fields=["scope", "updated_at"])
            created_or_updated += 1

    return created_or_updated
