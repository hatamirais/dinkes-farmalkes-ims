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

    from apps.users.access import has_module_scope
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

    if has_module_scope(user, ModuleAccess.Module.RECEIVING, ModuleAccess.Scope.VIEW):
        from apps.receiving.models import Receiving

        count = Receiving.objects.filter(
            status__in=[
                Receiving.Status.SUBMITTED,
                Receiving.Status.APPROVED,
                Receiving.Status.PARTIAL,
            ]
        ).count()
        add_notification_item(
            "Penerimaan",
            count,
            reverse("receiving:receiving_list"),
            "bi-inbox-fill",
        )

    if has_module_scope(
        user, ModuleAccess.Module.DISTRIBUTION, ModuleAccess.Scope.VIEW
    ):
        from apps.distribution.models import Distribution

        base_qs = Distribution.objects.filter(
            status__in=[
                Distribution.Status.SUBMITTED,
                Distribution.Status.VERIFIED,
                Distribution.Status.PREPARED,
            ]
        )
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

    if has_module_scope(user, ModuleAccess.Module.RECALL, ModuleAccess.Scope.VIEW):
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

    if has_module_scope(user, ModuleAccess.Module.EXPIRED, ModuleAccess.Scope.VIEW):
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

    if has_module_scope(
        user, ModuleAccess.Module.STOCK_OPNAME, ModuleAccess.Scope.VIEW
    ):
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

    if has_module_scope(user, ModuleAccess.Module.PUSKESMAS, ModuleAccess.Scope.VIEW):
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

    if has_module_scope(user, ModuleAccess.Module.LPLPO, ModuleAccess.Scope.VIEW):
        from apps.lplpo.models import LPLPO

        count = LPLPO.objects.filter(
            status__in=[LPLPO.Status.SUBMITTED, LPLPO.Status.REVIEWED]
        ).count()
        add_notification_item(
            "LPLPO",
            count,
            reverse("lplpo:lplpo_list"),
            "bi-file-earmark-medical",
        )

    total = sum(item["count"] for item in notification_items)
    return {
        "nav_notification_count": total,
        "nav_notification_items": notification_items,
    }
