"""Shared read-side scope rules; mutations still recheck locked authority."""

from django.core.exceptions import PermissionDenied
from django.db.models import Q

from apps.users.access import (
    can_approve_module,
    get_active_authority_delegation,
    has_module_permission,
    has_module_scope,
    is_super_admin,
)
from apps.users.models import ModuleAccess, User

from .models import LPLPO


def can_access_lplpo_cross_facility(user, *, route_kind, status):
    role = getattr(user, "role", None)

    if role == User.Role.GUDANG:
        if route_kind == "queue":
            return True
        if route_kind in {"detail", "print"}:
            return status in {
                LPLPO.Status.SUBMITTED,
                LPLPO.Status.PIC_VERIFIED,
                LPLPO.Status.REJECTED_PIC,
                LPLPO.Status.APPROVED,
                LPLPO.Status.CLOSED,
            }
        if route_kind == "instalasi_verify":
            return status == LPLPO.Status.SUBMITTED
        if route_kind == "instalasi_review":
            return status in {
                LPLPO.Status.PIC_VERIFIED,
                LPLPO.Status.REJECTED_PIC,
            }
        if route_kind == "instalasi_reject":
            return status == LPLPO.Status.SUBMITTED
        return False

    if role == User.Role.KEPALA:
        if route_kind == "queue":
            return True
        if route_kind in {"detail", "print"}:
            return status in {
                LPLPO.Status.REVIEWED,
                LPLPO.Status.APPROVED,
                LPLPO.Status.CLOSED,
            }
        if route_kind == "instalasi_finalize":
            return status == LPLPO.Status.REVIEWED
        if route_kind == "instalasi_reject":
            return status == LPLPO.Status.REVIEWED
        return False

    return False


def get_cross_facility_queue_statuses(user):
    role = getattr(user, "role", None)
    if role == User.Role.GUDANG:
        return {
            LPLPO.Status.SUBMITTED,
            LPLPO.Status.PIC_VERIFIED,
            LPLPO.Status.REJECTED_PIC,
            LPLPO.Status.APPROVED,
            LPLPO.Status.CLOSED,
        }
    if role == User.Role.KEPALA:
        return {
            LPLPO.Status.REVIEWED,
            LPLPO.Status.APPROVED,
            LPLPO.Status.CLOSED,
        }
    return set()


def scope_lplpo_queue(queryset, user):
    """Apply the existing queue facility/stage boundary."""
    if is_super_admin(user):
        return queryset
    if can_access_lplpo_cross_facility(user, route_kind="queue", status=None):
        access_filter = Q(status__in=get_cross_facility_queue_statuses(user))
        if (
            user.role == User.Role.GUDANG
            and user.facility_id
            and get_active_authority_delegation(user, ModuleAccess.Module.LPLPO)
        ):
            access_filter |= Q(status=LPLPO.Status.REVIEWED, facility_id=user.facility_id)
        return queryset.filter(access_filter)
    if not user.facility_id:
        raise PermissionDenied("Akun Anda belum terhubung ke fasilitas.")
    return queryset.filter(facility_id=user.facility_id)


def _route_filter(user, route_kind, statuses):
    if is_super_admin(user):
        return Q(status__in=statuses)
    access_filter = Q(
        status__in=[
            status for status in statuses
            if can_access_lplpo_cross_facility(user, route_kind=route_kind, status=status)
        ]
    )
    if user.facility_id:
        access_filter |= Q(status__in=statuses, facility_id=user.facility_id)
    return access_filter


def pending_lplpo_queryset(user):
    """Pending work reachable through both the normal queue and detail page."""
    queryset = LPLPO.objects.all()
    if user.role == User.Role.PUSKESMAS or not (
        user.has_perm("lplpo.view_lplpo")
        or has_module_permission(user, "lplpo.view_lplpo")
    ):
        return queryset.none()
    can_operate = has_module_scope(
        user, ModuleAccess.Module.LPLPO, ModuleAccess.Scope.OPERATE
    )
    can_approve = can_approve_module(user, ModuleAccess.Module.LPLPO)
    if not can_operate and not can_approve:
        return queryset.none()
    if (
        not is_super_admin(user)
        and user.role not in {User.Role.GUDANG, User.Role.KEPALA}
        and not user.facility_id
    ):
        return queryset.none()
    queryset = scope_lplpo_queue(queryset, user)
    if not is_super_admin(user):
        queryset = queryset.filter(submitted_at__isnull=False)
    work_filter = Q(pk__in=[])
    if can_operate:
        work_filter |= _route_filter(user, "instalasi_verify", [LPLPO.Status.SUBMITTED])
        work_filter |= _route_filter(
            user, "instalasi_review", [LPLPO.Status.PIC_VERIFIED, LPLPO.Status.REJECTED_PIC]
        )
    if can_approve:
        work_filter |= _route_filter(user, "instalasi_finalize", [LPLPO.Status.REVIEWED])
    pending_statuses = [
        LPLPO.Status.SUBMITTED,
        LPLPO.Status.PIC_VERIFIED,
        LPLPO.Status.REJECTED_PIC,
        LPLPO.Status.REVIEWED,
    ]
    return queryset.filter(work_filter).filter(_route_filter(user, "detail", pending_statuses))
