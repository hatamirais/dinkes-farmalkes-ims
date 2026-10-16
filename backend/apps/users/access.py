from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.utils import timezone

from apps.items.models import Facility

from .models import (
    AuthorityDelegation,
    AuthorityExercise,
    ModuleAccess,
    User,
)


DELEGATE_ROLES = {User.Role.ADMIN_UMUM, User.Role.GUDANG}
FACILITY_BOUND_MODULES = {ModuleAccess.Module.PUSKESMAS, ModuleAccess.Module.LPLPO}


@dataclass(frozen=True)
class AuthorityDecision:
    allowed: bool
    basis: str | None = None
    delegation: AuthorityDelegation | None = None
    actor: User | None = None


ROLE_DEFAULT_SCOPES: Dict[str, Dict[str, int]] = {
    User.Role.ADMIN: {
        ModuleAccess.Module.USERS: ModuleAccess.Scope.MANAGE,
        ModuleAccess.Module.ITEMS: ModuleAccess.Scope.MANAGE,
        ModuleAccess.Module.STOCK: ModuleAccess.Scope.MANAGE,
        ModuleAccess.Module.RECEIVING: ModuleAccess.Scope.MANAGE,
        ModuleAccess.Module.PROCUREMENT: ModuleAccess.Scope.MANAGE,
        ModuleAccess.Module.DISTRIBUTION: ModuleAccess.Scope.MANAGE,
        ModuleAccess.Module.ALLOCATION: ModuleAccess.Scope.MANAGE,
        ModuleAccess.Module.RECALL: ModuleAccess.Scope.MANAGE,
        ModuleAccess.Module.EXPIRED: ModuleAccess.Scope.MANAGE,
        ModuleAccess.Module.STOCK_OPNAME: ModuleAccess.Scope.MANAGE,
        ModuleAccess.Module.REPORTS: ModuleAccess.Scope.MANAGE,
        ModuleAccess.Module.ADMIN_PANEL: ModuleAccess.Scope.MANAGE,
        ModuleAccess.Module.PUSKESMAS: ModuleAccess.Scope.MANAGE,
        ModuleAccess.Module.LPLPO: ModuleAccess.Scope.MANAGE,
    },
    User.Role.KEPALA: {
        ModuleAccess.Module.USERS: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.ITEMS: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.STOCK: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.RECEIVING: ModuleAccess.Scope.APPROVE,
        ModuleAccess.Module.PROCUREMENT: ModuleAccess.Scope.APPROVE,
        ModuleAccess.Module.DISTRIBUTION: ModuleAccess.Scope.APPROVE,
        ModuleAccess.Module.ALLOCATION: ModuleAccess.Scope.APPROVE,
        ModuleAccess.Module.RECALL: ModuleAccess.Scope.APPROVE,
        ModuleAccess.Module.EXPIRED: ModuleAccess.Scope.APPROVE,
        ModuleAccess.Module.STOCK_OPNAME: ModuleAccess.Scope.APPROVE,
        ModuleAccess.Module.REPORTS: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.ADMIN_PANEL: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.PUSKESMAS: ModuleAccess.Scope.APPROVE,
        ModuleAccess.Module.LPLPO: ModuleAccess.Scope.APPROVE,
    },
    User.Role.ADMIN_UMUM: {
        ModuleAccess.Module.USERS: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.ITEMS: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.STOCK: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.RECEIVING: ModuleAccess.Scope.OPERATE,
        ModuleAccess.Module.PROCUREMENT: ModuleAccess.Scope.OPERATE,
        ModuleAccess.Module.DISTRIBUTION: ModuleAccess.Scope.OPERATE,
        ModuleAccess.Module.ALLOCATION: ModuleAccess.Scope.OPERATE,
        ModuleAccess.Module.RECALL: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.EXPIRED: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.STOCK_OPNAME: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.REPORTS: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.ADMIN_PANEL: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.PUSKESMAS: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.LPLPO: ModuleAccess.Scope.VIEW,
    },
    User.Role.GUDANG: {
        ModuleAccess.Module.USERS: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.ITEMS: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.STOCK: ModuleAccess.Scope.OPERATE,
        ModuleAccess.Module.RECEIVING: ModuleAccess.Scope.OPERATE,
        ModuleAccess.Module.PROCUREMENT: ModuleAccess.Scope.OPERATE,
        ModuleAccess.Module.DISTRIBUTION: ModuleAccess.Scope.OPERATE,
        ModuleAccess.Module.ALLOCATION: ModuleAccess.Scope.OPERATE,
        ModuleAccess.Module.RECALL: ModuleAccess.Scope.OPERATE,
        ModuleAccess.Module.EXPIRED: ModuleAccess.Scope.OPERATE,
        ModuleAccess.Module.STOCK_OPNAME: ModuleAccess.Scope.OPERATE,
        ModuleAccess.Module.REPORTS: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.ADMIN_PANEL: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.PUSKESMAS: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.LPLPO: ModuleAccess.Scope.OPERATE,
    },
    User.Role.AUDITOR: {
        ModuleAccess.Module.USERS: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.ITEMS: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.STOCK: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.RECEIVING: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.PROCUREMENT: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.DISTRIBUTION: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.ALLOCATION: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.RECALL: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.EXPIRED: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.STOCK_OPNAME: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.REPORTS: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.ADMIN_PANEL: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.PUSKESMAS: ModuleAccess.Scope.VIEW,
        ModuleAccess.Module.LPLPO: ModuleAccess.Scope.VIEW,
    },
    User.Role.PUSKESMAS: {
        ModuleAccess.Module.USERS: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.ITEMS: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.STOCK: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.RECEIVING: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.PROCUREMENT: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.DISTRIBUTION: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.ALLOCATION: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.RECALL: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.EXPIRED: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.STOCK_OPNAME: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.REPORTS: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.ADMIN_PANEL: ModuleAccess.Scope.NONE,
        ModuleAccess.Module.PUSKESMAS: ModuleAccess.Scope.OPERATE,
        ModuleAccess.Module.LPLPO: ModuleAccess.Scope.OPERATE,
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
    return default_scope_for_role(getattr(user, "role", ""), module)


def is_super_admin(user: User) -> bool:
    return bool(getattr(user, "is_superuser", False)) or (
        getattr(user, "role", None) == User.Role.ADMIN
    )


def has_module_scope(user: User, module: str, min_scope: int) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return get_user_module_scope(user, module) >= min_scope


def can_manage_authority_delegations(user: User) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return is_super_admin(user) or getattr(user, "role", None) == User.Role.KEPALA


def can_delegate_module(user: User, module: str) -> bool:
    if not can_manage_authority_delegations(user):
        return False
    if is_super_admin(user):
        return True
    return has_module_scope(user, module, ModuleAccess.Scope.APPROVE)


def lock_authority_user_state(user: User, module: str) -> User | None:
    """Lock/reload an authority actor and module access inside an atomic block."""
    try:
        locked_user = User.objects.select_for_update().get(pk=user.pk)
    except User.DoesNotExist:
        return None
    list(
        ModuleAccess.objects.select_for_update()
        .filter(user=locked_user, module=module)
        .order_by("user_id", "module")
    )
    return locked_user


def _has_valid_delegate_facility(user: User, module: str, *, for_update: bool) -> bool:
    if module not in FACILITY_BOUND_MODULES:
        return True
    if not user.facility_id:
        return False
    facility = Facility.objects.filter(
        pk=user.facility_id,
        facility_type=Facility.FacilityType.PUSKESMAS,
        is_active=True,
    )
    if for_update:
        facility = facility.select_for_update()
    return facility.exists()


def _is_eligible_delegate(user: User, module: str, *, for_update: bool = False) -> bool:
    return bool(
        user.is_active
        and user.role in DELEGATE_ROLES
        and has_module_scope(user, module, ModuleAccess.Scope.VIEW)
        and _has_valid_delegate_facility(user, module, for_update=for_update)
    )


def _get_locked_active_authority_delegation(
    user: User,
    module: str,
    *,
    at: datetime | None = None,
) -> AuthorityDelegation | None:
    # User and ModuleAccess are already locked. Lock the facility before the
    # delegation so its eligibility cannot change during this checkpoint.
    if not _is_eligible_delegate(user, module, for_update=True):
        return None
    candidates = list(
        AuthorityDelegation.objects.select_related("delegate", "granted_by")
        .select_for_update(of=("self",))
        .filter(
            authority=AuthorityDelegation.Authority.KEPALA_APPROVAL,
            module=module,
            delegate=user,
            revoked_at__isnull=True,
        )
        .order_by("starts_at", "pk")
    )
    effective_at = at or timezone.now()
    return next(
        (
            delegation
            for delegation in candidates
            if delegation.starts_at <= effective_at
            and (delegation.ends_at is None or delegation.ends_at > effective_at)
        ),
        None,
    )


def get_active_authority_delegation(
    user: User,
    module: str,
    *,
    at: datetime | None = None,
    for_update: bool = False,
) -> AuthorityDelegation | None:
    if not getattr(user, "is_authenticated", False):
        return None

    if for_update:
        locked_user = lock_authority_user_state(user, module)
        if locked_user is None:
            return None
        return _get_locked_active_authority_delegation(
            locked_user,
            module,
            at=at,
        )

    if not _is_eligible_delegate(user, module):
        return None

    effective_at = at or timezone.now()
    queryset = AuthorityDelegation.objects.select_related("delegate", "granted_by")
    return (
        queryset.filter(
            authority=AuthorityDelegation.Authority.KEPALA_APPROVAL,
            module=module,
            delegate=user,
            delegate__is_active=True,
            revoked_at__isnull=True,
            starts_at__lte=effective_at,
        )
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=effective_at))
        .first()
    )


def resolve_approval_authority(
    user: User,
    module: str,
    *,
    role_gated: bool,
    at: datetime | None = None,
    for_update: bool = False,
) -> AuthorityDecision:
    if not getattr(user, "is_authenticated", False):
        return AuthorityDecision(False)

    if for_update:
        user = lock_authority_user_state(user, module)
        if user is None:
            return AuthorityDecision(False)

    if getattr(user, "is_superuser", False):
        return AuthorityDecision(True, "superuser", actor=user)

    has_approve_scope = has_module_scope(user, module, ModuleAccess.Scope.APPROVE)
    if has_approve_scope and (
        not role_gated
        or getattr(user, "role", None) in {User.Role.ADMIN, User.Role.KEPALA}
    ):
        return AuthorityDecision(True, "role", actor=user)

    if for_update:
        delegation = _get_locked_active_authority_delegation(
            user,
            module,
            at=at,
        )
    else:
        delegation = get_active_authority_delegation(
            user,
            module,
            at=at,
        )
    if delegation:
        return AuthorityDecision(
            True,
            "delegation",
            delegation,
            actor=user,
        )
    return AuthorityDecision(False, actor=user)


def can_approve_module(user: User, module: str) -> bool:
    """Allow the existing approve-scope path or an active Kepala delegation."""
    return resolve_approval_authority(user, module, role_gated=False).allowed


def can_approve_workflow(user: User, module: str) -> bool:
    """Return whether a user may perform a Kepala/Admin approval checkpoint."""
    return resolve_approval_authority(user, module, role_gated=True).allowed


def record_authority_exercise(
    decision: AuthorityDecision,
    *,
    actor: User,
    module: str,
    action: str,
    target,
    exercised_at: datetime | None = None,
) -> AuthorityExercise | None:
    if decision.basis != "delegation" or decision.delegation is None:
        return None

    actor = decision.actor or actor
    delegation = decision.delegation
    timestamp = exercised_at or timezone.now()
    return AuthorityExercise.objects.create(
        delegation=delegation,
        actor=actor,
        module=module,
        action=action,
        content_type=ContentType.objects.get_for_model(target, for_concrete_model=False),
        object_id=target.pk,
        exercised_at=timestamp,
        actor_name_snapshot=actor.full_name or actor.username,
        actor_nip_snapshot=actor.nip,
        authority_title_snapshot="Plh. Kepala Instalasi",
        delegation_starts_at_snapshot=delegation.starts_at,
        delegation_ends_at_snapshot=delegation.ends_at,
        grantor_name_snapshot=(
            delegation.granted_by.full_name or delegation.granted_by.username
        ),
        reason_snapshot=delegation.reason,
    )


def has_authority_exercise(target) -> bool:
    """Return whether delegated-authority audit history references ``target``."""
    if target.pk is None:
        return False
    content_type = ContentType.objects.get_for_model(
        target,
        for_concrete_model=False,
    )
    return AuthorityExercise.objects.filter(
        content_type=content_type,
        object_id=target.pk,
    ).exists()


def get_authority_exercise(target, *, action: str | None = None):
    content_type = ContentType.objects.get_for_model(
        target,
        for_concrete_model=False,
    )
    queryset = AuthorityExercise.objects.filter(
        content_type=content_type,
        object_id=target.pk,
    ).select_related("actor", "delegation")
    if action:
        queryset = queryset.filter(action=action)
    return queryset.order_by("-exercised_at", "-pk").first()


def get_delegated_signature(
    target,
    *,
    action: str,
    actor: User | None,
    exercised_at: datetime | None,
):
    if actor is None or exercised_at is None:
        return None

    content_type = ContentType.objects.get_for_model(
        target,
        for_concrete_model=False,
    )
    exercise = (
        AuthorityExercise.objects.filter(
            content_type=content_type,
            object_id=target.pk,
            action=action,
            actor=actor,
            exercised_at=exercised_at,
        )
        .order_by("-pk")
        .first()
    )
    if exercise is None:
        return None
    return {
        "name": exercise.actor_name_snapshot,
        "nip": exercise.actor_nip_snapshot,
        "title": exercise.authority_title_snapshot,
        "exercised_at": exercise.exercised_at,
    }


def can_view_mobile_stock(user: User) -> bool:
    """Match the stock view decorator's Django-permission/module-scope access."""
    return bool(getattr(user, "is_authenticated", False)) and (
        user.has_perm("stock.view_stock")
        or has_module_permission(user, "stock.view_stock")
    )


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
