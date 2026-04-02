from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum, Q, F, DecimalField, ExpressionWrapper

from apps.distribution.models import Distribution
from apps.expired.models import Expired as ExpiredDoc
from apps.items.models import Item
from apps.lplpo.models import LPLPO
from apps.puskesmas.models import PuskesmasRequest
from apps.recall.models import Recall
from apps.receiving.models import Receiving
from apps.stock.models import Stock, Transaction
from apps.stock_opname.models import StockOpname
from apps.users.access import has_module_scope
from apps.users.models import ModuleAccess, User


@login_required
def dashboard(request):
    if request.user.role == User.Role.PUSKESMAS:
        facility = request.user.facility
        if not facility:
            return render(
                request,
                "dashboard_puskesmas.html",
                {
                    "facility": None,
                    "draft_lplpo_count": 0,
                    "submitted_lplpo_count": 0,
                    "reviewed_lplpo_count": 0,
                    "recent_lplpos": [],
                    "recent_requests": [],
                    "latest_lplpo": None,
                },
            )

        lplpo_queryset = LPLPO.objects.filter(facility=facility).select_related(
            "facility"
        )
        request_queryset = PuskesmasRequest.objects.filter(
            facility=facility
        ).select_related("program")

        latest_lplpo = lplpo_queryset.order_by("-tahun", "-bulan", "-created_at").first()
        draft_lplpo_count = lplpo_queryset.filter(status=LPLPO.Status.DRAFT).count()
        submitted_lplpo_count = lplpo_queryset.filter(
            status=LPLPO.Status.SUBMITTED
        ).count()
        reviewed_lplpo_count = lplpo_queryset.filter(
            status=LPLPO.Status.REVIEWED
        ).count()

        recent_lplpos = lplpo_queryset.order_by("-tahun", "-bulan", "-created_at")[:5]
        recent_requests = request_queryset.order_by("-request_date", "-created_at")[:5]

        return render(
            request,
            "dashboard_puskesmas.html",
            {
                "facility": facility,
                "draft_lplpo_count": draft_lplpo_count,
                "submitted_lplpo_count": submitted_lplpo_count,
                "reviewed_lplpo_count": reviewed_lplpo_count,
                "recent_lplpos": recent_lplpos,
                "recent_requests": recent_requests,
                "latest_lplpo": latest_lplpo,
            },
        )

    today = timezone.now().date()
    three_months_later = today + timedelta(days=90)
    thirty_days_ago = today - timedelta(days=29)

    # Stats
    total_items = Item.objects.filter(is_active=True).count()
    total_stock_entries = Stock.objects.filter(quantity__gt=0).count()
    total_stock_quantity = Stock.objects.filter(quantity__gt=0).aggregate(
        total=Sum("quantity")
    )["total"] or Decimal("0")
    total_stock_value = Stock.objects.filter(quantity__gt=0).aggregate(
        total=Sum(
            ExpressionWrapper(
                F("quantity") * F("unit_price"),
                output_field=DecimalField(max_digits=18, decimal_places=2),
            )
        )
    ).get("total") or Decimal("0")

    # Low stock: items where total stock quantity is below minimum_stock
    low_stock_items = (
        Item.objects.filter(is_active=True)
        .annotate(total_qty=Sum("stock_entries__quantity"))
        .filter(
            Q(total_qty__lt=F("minimum_stock")) | Q(total_qty__isnull=True),
            minimum_stock__gt=0,
        )
    )
    low_stock_count = low_stock_items.count()

    # Expiring soon: stock entries expiring within 3 months
    expiring_soon = (
        Stock.objects.filter(
            quantity__gt=0,
            expiry_date__lte=three_months_later,
        )
        .select_related("item")
        .order_by("expiry_date")[:10]
    )
    expiring_soon_count = Stock.objects.filter(
        quantity__gt=0,
        expiry_date__lte=three_months_later,
    ).count()

    today_transaction_count = Transaction.objects.filter(created_at__date=today).count()
    tx_last_30_days = Transaction.objects.filter(created_at__date__gte=thirty_days_ago)
    inbound_30_days = tx_last_30_days.filter(
        transaction_type=Transaction.TransactionType.IN
    ).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
    outbound_30_days = tx_last_30_days.filter(
        transaction_type=Transaction.TransactionType.OUT
    ).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
    movement_total_30_days = inbound_30_days + outbound_30_days
    if movement_total_30_days > 0:
        inbound_percent_30_days = int((inbound_30_days / movement_total_30_days) * 100)
        outbound_percent_30_days = 100 - inbound_percent_30_days
    else:
        inbound_percent_30_days = 0
        outbound_percent_30_days = 0

    # Recent transactions
    recent_transactions = Transaction.objects.select_related("item", "user").order_by(
        "-created_at"
    )[:10]

    # ── Notification Center ─────────────────────────────────────────────────
    notification_modules = []
    user = request.user

    def _recent_docs(qs, detail_url_name, limit=3):
        """Return a list of dicts suitable for the notification panel."""
        items = []
        for obj in qs[:limit]:
            items.append(
                {
                    "doc_number": obj.document_number,
                    "status_display": obj.get_status_display(),
                    "created_at": obj.created_at,
                    "url": reverse(detail_url_name, args=[obj.pk]),
                }
            )
        return items

    if has_module_scope(user, ModuleAccess.Module.RECEIVING, ModuleAccess.Scope.VIEW):
        pending_qs = Receiving.objects.filter(
            status__in=[
                Receiving.Status.SUBMITTED,
                Receiving.Status.APPROVED,
                Receiving.Status.PARTIAL,
            ]
        ).order_by("-created_at")
        count = pending_qs.count()
        notification_modules.append(
            {
                "label": "Penerimaan",
                "icon": "bi-inbox-fill",
                "color": "primary",
                "list_url": reverse("receiving:receiving_list"),
                "count": count,
                "recent": _recent_docs(pending_qs, "receiving:receiving_detail"),
            }
        )

    if has_module_scope(
        user, ModuleAccess.Module.DISTRIBUTION, ModuleAccess.Scope.VIEW
    ):
        pending_qs = Distribution.objects.filter(
            status__in=[
                Distribution.Status.SUBMITTED,
                Distribution.Status.VERIFIED,
                Distribution.Status.PREPARED,
            ]
        ).order_by("-created_at")
        count = pending_qs.count()
        notification_modules.append(
            {
                "label": "Distribusi",
                "icon": "bi-send",
                "color": "success",
                "list_url": reverse("distribution:distribution_list"),
                "count": count,
                "recent": _recent_docs(pending_qs, "distribution:distribution_detail"),
            }
        )

    if has_module_scope(user, ModuleAccess.Module.RECALL, ModuleAccess.Scope.VIEW):
        pending_qs = Recall.objects.filter(
            status__in=[Recall.Status.SUBMITTED, Recall.Status.VERIFIED]
        ).order_by("-created_at")
        count = pending_qs.count()
        notification_modules.append(
            {
                "label": "Recall / Retur",
                "icon": "bi-arrow-return-left",
                "color": "warning",
                "list_url": reverse("recall:recall_list"),
                "count": count,
                "recent": _recent_docs(pending_qs, "recall:recall_detail"),
            }
        )

    if has_module_scope(user, ModuleAccess.Module.EXPIRED, ModuleAccess.Scope.VIEW):
        pending_qs = ExpiredDoc.objects.filter(
            status__in=[ExpiredDoc.Status.SUBMITTED, ExpiredDoc.Status.VERIFIED]
        ).order_by("-created_at")
        count = pending_qs.count()
        notification_modules.append(
            {
                "label": "Kadaluarsa",
                "icon": "bi-trash",
                "color": "danger",
                "list_url": reverse("expired:expired_list"),
                "count": count,
                "recent": _recent_docs(pending_qs, "expired:expired_detail"),
            }
        )

    if has_module_scope(
        user, ModuleAccess.Module.STOCK_OPNAME, ModuleAccess.Scope.VIEW
    ):
        pending_qs = StockOpname.objects.filter(
            status=StockOpname.Status.IN_PROGRESS
        ).order_by("-created_at")
        count = pending_qs.count()
        notification_modules.append(
            {
                "label": "Stock Opname",
                "icon": "bi-clipboard-check",
                "color": "info",
                "list_url": reverse("stock_opname:opname_list"),
                "count": count,
                "recent": _recent_docs(pending_qs, "stock_opname:opname_detail"),
            }
        )

    if has_module_scope(user, ModuleAccess.Module.PUSKESMAS, ModuleAccess.Scope.VIEW):
        pending_qs = PuskesmasRequest.objects.filter(
            status=PuskesmasRequest.Status.SUBMITTED
        ).order_by("-created_at")
        count = pending_qs.count()
        notification_modules.append(
            {
                "label": "Permintaan Puskesmas",
                "icon": "bi-file-earmark-arrow-up",
                "color": "secondary",
                "list_url": reverse("puskesmas:request_list"),
                "count": count,
                "recent": _recent_docs(pending_qs, "puskesmas:request_detail"),
            }
        )

    if has_module_scope(user, ModuleAccess.Module.LPLPO, ModuleAccess.Scope.VIEW):
        pending_qs = LPLPO.objects.filter(
            status__in=[LPLPO.Status.SUBMITTED, LPLPO.Status.REVIEWED]
        ).order_by("-created_at")
        count = pending_qs.count()
        notification_modules.append(
            {
                "label": "LPLPO",
                "icon": "bi-file-earmark-medical",
                "color": "secondary",
                "list_url": reverse("lplpo:lplpo_list"),
                "count": count,
                "recent": _recent_docs(pending_qs, "lplpo:lplpo_detail"),
            }
        )

    total_pending = sum(m["count"] for m in notification_modules)
    active_notification_modules = [m for m in notification_modules if m["count"] > 0]

    return render(
        request,
        "dashboard.html",
        {
            "total_items": total_items,
            "total_stock_entries": total_stock_entries,
            "total_stock_quantity": total_stock_quantity,
            "total_stock_value": total_stock_value,
            "low_stock_count": low_stock_count,
            "expiring_soon_count": expiring_soon_count,
            "expiring_soon": expiring_soon,
            "today_transaction_count": today_transaction_count,
            "inbound_30_days": inbound_30_days,
            "outbound_30_days": outbound_30_days,
            "inbound_percent_30_days": inbound_percent_30_days,
            "outbound_percent_30_days": outbound_percent_30_days,
            "thirty_days_ago": thirty_days_ago,
            "today": today,
            "recent_transactions": recent_transactions,
            "notification_modules": notification_modules,
            "active_notification_modules": active_notification_modules,
            "total_pending": total_pending,
        },
    )
