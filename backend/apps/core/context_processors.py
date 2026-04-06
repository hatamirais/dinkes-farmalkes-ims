from django.conf import settings
from django.urls import reverse


def app_version(_request):
    return {"app_version": settings.APP_VERSION}


def nav_notifications(request):
    """
    Provides notification summary data for the navbar bell dropdown.
    Runs on every authenticated request and only includes actionable items.
    """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"nav_notification_count": 0, "nav_notification_items": []}

    from apps.users.access import get_user_module_scope
    from apps.users.models import ModuleAccess, User

    if user.role == User.Role.PUSKESMAS:
        return {"nav_notification_count": 0, "nav_notification_items": []}

    notification_items = []

    def add_notification_item(label, count, url, icon):
        if count > 0:
            notification_items.append(
                {
                    "label": label,
                    "count": count,
                    "url": url,
                    "icon": icon,
                }
            )

    receiving_scope = get_user_module_scope(user, ModuleAccess.Module.RECEIVING)
    distribution_scope = get_user_module_scope(user, ModuleAccess.Module.DISTRIBUTION)
    recall_scope = get_user_module_scope(user, ModuleAccess.Module.RECALL)
    expired_scope = get_user_module_scope(user, ModuleAccess.Module.EXPIRED)
    stock_opname_scope = get_user_module_scope(user, ModuleAccess.Module.STOCK_OPNAME)
    puskesmas_scope = get_user_module_scope(user, ModuleAccess.Module.PUSKESMAS)
    lplpo_scope = get_user_module_scope(user, ModuleAccess.Module.LPLPO)

    if receiving_scope >= ModuleAccess.Scope.OPERATE:
        from apps.receiving.models import Receiving

        receiving_statuses = []
        if receiving_scope >= ModuleAccess.Scope.APPROVE:
            receiving_statuses.append(Receiving.Status.SUBMITTED)
        if receiving_scope in (ModuleAccess.Scope.OPERATE, ModuleAccess.Scope.MANAGE):
            receiving_statuses.extend(
                [Receiving.Status.APPROVED, Receiving.Status.PARTIAL]
            )

        if receiving_statuses:
            planned_count = Receiving.objects.filter(
                is_planned=True,
                status__in=receiving_statuses,
            ).count()
            add_notification_item(
                "Rencana Penerimaan",
                planned_count,
                reverse("receiving:receiving_plan_list"),
                "bi-clipboard-check",
            )

            regular_count = Receiving.objects.filter(
                is_planned=False,
                status__in=receiving_statuses,
            ).count()
            add_notification_item(
                "Penerimaan",
                regular_count,
                reverse("receiving:receiving_list"),
                "bi-inbox-fill",
            )

    if distribution_scope >= ModuleAccess.Scope.OPERATE:
        from apps.distribution.models import Distribution

        distribution_statuses = []
        if distribution_scope >= ModuleAccess.Scope.APPROVE:
            distribution_statuses.append(Distribution.Status.SUBMITTED)
        if distribution_scope in (ModuleAccess.Scope.OPERATE, ModuleAccess.Scope.MANAGE):
            distribution_statuses.extend(
                [Distribution.Status.VERIFIED, Distribution.Status.PREPARED]
            )

        base_qs = Distribution.objects.filter(status__in=distribution_statuses)
        add_notification_item(
            "Distribusi dari LPLPO",
            base_qs.filter(
                distribution_type=Distribution.DistributionType.LPLPO
            ).count(),
            reverse("distribution:distribution_list"),
            "bi-truck",
        )
        add_notification_item(
            "Distribusi Permintaan Khusus",
            base_qs.filter(
                distribution_type=Distribution.DistributionType.SPECIAL_REQUEST
            ).count(),
            reverse("distribution:distribution_list"),
            "bi-send",
        )
        add_notification_item(
            "Alokasi",
            base_qs.filter(
                distribution_type=Distribution.DistributionType.ALLOCATION
            ).count(),
            reverse("distribution:distribution_list"),
            "bi-box-arrow-up-right",
        )

    if recall_scope >= ModuleAccess.Scope.APPROVE:
        from apps.recall.models import Recall

        count = Recall.objects.filter(
            status__in=[Recall.Status.SUBMITTED, Recall.Status.VERIFIED]
        ).count()
        add_notification_item(
            "Recall / Retur",
            count,
            reverse("recall:recall_list"),
            "bi-arrow-return-left",
        )

    if expired_scope >= ModuleAccess.Scope.APPROVE:
        from apps.expired.models import Expired

        count = Expired.objects.filter(
            status__in=[Expired.Status.SUBMITTED, Expired.Status.VERIFIED]
        ).count()
        add_notification_item(
            "Kadaluarsa",
            count,
            reverse("expired:expired_list"),
            "bi-trash",
        )

    if stock_opname_scope >= ModuleAccess.Scope.OPERATE:
        from apps.stock_opname.models import StockOpname

        count = StockOpname.objects.filter(
            status=StockOpname.Status.IN_PROGRESS
        ).count()
        add_notification_item(
            "Stock Opname",
            count,
            reverse("stock_opname:opname_list"),
            "bi-clipboard-check",
        )

    if puskesmas_scope >= ModuleAccess.Scope.VIEW:
        from apps.puskesmas.models import PuskesmasRequest

        count = PuskesmasRequest.objects.filter(
            status=PuskesmasRequest.Status.SUBMITTED
        ).count()
        add_notification_item(
            "Permintaan Puskesmas",
            count,
            reverse("puskesmas:request_list"),
            "bi-file-earmark-arrow-up",
        )

    if lplpo_scope >= ModuleAccess.Scope.OPERATE:
        from apps.lplpo.models import LPLPO

        lplpo_statuses = []
        if lplpo_scope in (ModuleAccess.Scope.OPERATE, ModuleAccess.Scope.MANAGE):
            lplpo_statuses.append(LPLPO.Status.SUBMITTED)
        if lplpo_scope >= ModuleAccess.Scope.APPROVE:
            lplpo_statuses.append(LPLPO.Status.REVIEWED)

        count = LPLPO.objects.filter(status__in=lplpo_statuses).count() if lplpo_statuses else 0
        add_notification_item("LPLPO", count, reverse("lplpo:lplpo_list"), "bi-file-earmark-medical")

    total = sum(item["count"] for item in notification_items)
    return {
        "nav_notification_count": total,
        "nav_notification_items": notification_items,
    }
