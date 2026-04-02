from django.conf import settings


def app_version(_request):
    return {"app_version": settings.APP_VERSION}


def nav_notifications(request):
    """
    Provides a global pending-document count for the navbar notification bell.
    Runs on every authenticated request; uses COUNT-only queries for efficiency.
    Returns zero counts for unauthenticated and PUSKESMAS users.
    """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"nav_notification_count": 0}

    from apps.users.access import has_module_scope
    from apps.users.models import ModuleAccess, User

    if user.role == User.Role.PUSKESMAS:
        return {"nav_notification_count": 0}

    total = 0

    if has_module_scope(user, ModuleAccess.Module.RECEIVING, ModuleAccess.Scope.VIEW):
        from apps.receiving.models import Receiving

        total += Receiving.objects.filter(
            status__in=[
                Receiving.Status.SUBMITTED,
                Receiving.Status.APPROVED,
                Receiving.Status.PARTIAL,
            ]
        ).count()

    if has_module_scope(
        user, ModuleAccess.Module.DISTRIBUTION, ModuleAccess.Scope.VIEW
    ):
        from apps.distribution.models import Distribution

        total += Distribution.objects.filter(
            status__in=[
                Distribution.Status.SUBMITTED,
                Distribution.Status.VERIFIED,
                Distribution.Status.PREPARED,
            ]
        ).count()

    if has_module_scope(user, ModuleAccess.Module.RECALL, ModuleAccess.Scope.VIEW):
        from apps.recall.models import Recall

        total += Recall.objects.filter(
            status__in=[Recall.Status.SUBMITTED, Recall.Status.VERIFIED]
        ).count()

    if has_module_scope(user, ModuleAccess.Module.EXPIRED, ModuleAccess.Scope.VIEW):
        from apps.expired.models import Expired

        total += Expired.objects.filter(
            status__in=[Expired.Status.SUBMITTED, Expired.Status.VERIFIED]
        ).count()

    if has_module_scope(
        user, ModuleAccess.Module.STOCK_OPNAME, ModuleAccess.Scope.VIEW
    ):
        from apps.stock_opname.models import StockOpname

        total += StockOpname.objects.filter(
            status=StockOpname.Status.IN_PROGRESS
        ).count()

    if has_module_scope(user, ModuleAccess.Module.PUSKESMAS, ModuleAccess.Scope.VIEW):
        from apps.puskesmas.models import PuskesmasRequest

        total += PuskesmasRequest.objects.filter(
            status=PuskesmasRequest.Status.SUBMITTED
        ).count()

    if has_module_scope(user, ModuleAccess.Module.LPLPO, ModuleAccess.Scope.VIEW):
        from apps.lplpo.models import LPLPO

        total += LPLPO.objects.filter(
            status__in=[LPLPO.Status.SUBMITTED, LPLPO.Status.REVIEWED]
        ).count()

    return {"nav_notification_count": total}
