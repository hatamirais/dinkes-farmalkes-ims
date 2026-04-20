from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Sum, Q, F, DecimalField, ExpressionWrapper, Value
from django.db.models.functions import Coalesce

from apps.items.models import Item
from apps.lplpo.models import LPLPO
from apps.puskesmas.models import PuskesmasRequest
from apps.stock.models import Stock, Transaction
from apps.users.models import User
from django.urls import reverse_lazy
from django.views.generic.edit import UpdateView
from django.contrib.auth.mixins import UserPassesTestMixin
from django.contrib import messages
from apps.core.models import SystemSettings
from apps.core.forms import SystemSettingsForm

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
        lplpo_counts = lplpo_queryset.aggregate(
            draft_lplpo_count=Count("pk", filter=Q(status=LPLPO.Status.DRAFT)),
            submitted_lplpo_count=Count(
                "pk", filter=Q(status=LPLPO.Status.SUBMITTED)
            ),
            reviewed_lplpo_count=Count("pk", filter=Q(status=LPLPO.Status.REVIEWED)),
        )

        latest_lplpo = lplpo_queryset.order_by("-tahun", "-bulan", "-created_at").first()
        recent_lplpos = lplpo_queryset.order_by("-tahun", "-bulan", "-created_at")[:5]
        recent_requests = request_queryset.order_by("-request_date", "-created_at")[:5]

        return render(
            request,
            "dashboard_puskesmas.html",
            {
                "facility": facility,
                **lplpo_counts,
                "recent_lplpos": recent_lplpos,
                "recent_requests": recent_requests,
                "latest_lplpo": latest_lplpo,
            },
        )

    today = timezone.now().date()
    three_months_later = today + timedelta(days=90)
    thirty_days_ago = today - timedelta(days=29)
    zero_decimal = Value(Decimal("0"), output_field=DecimalField(max_digits=18, decimal_places=2))
    stock_queryset = Stock.objects.filter(quantity__gt=0)
    stock_totals = stock_queryset.aggregate(
        total_stock_entries=Count("pk"),
        total_stock_quantity=Coalesce(Sum("quantity"), zero_decimal),
        total_stock_value=Coalesce(
            Sum(
                ExpressionWrapper(
                    F("quantity") * F("unit_price"),
                    output_field=DecimalField(max_digits=18, decimal_places=2),
                )
            ),
            zero_decimal,
        ),
    )

    # Stats
    total_items = Item.objects.filter(is_active=True).count()
    total_stock_entries = stock_totals["total_stock_entries"]
    total_stock_quantity = stock_totals["total_stock_quantity"]
    total_stock_value = stock_totals["total_stock_value"]

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
    expiring_soon_queryset = stock_queryset.filter(expiry_date__lte=three_months_later)
    expiring_soon = expiring_soon_queryset.select_related("item").order_by(
        "expiry_date"
    )[:10]
    expiring_soon_count = expiring_soon_queryset.count()

    today_transaction_count = Transaction.objects.filter(created_at__date=today).count()
    tx_last_30_days = Transaction.objects.filter(created_at__date__gte=thirty_days_ago)
    tx_summary = tx_last_30_days.aggregate(
        inbound_30_days=Coalesce(
            Sum(
                "quantity",
                filter=Q(transaction_type=Transaction.TransactionType.IN),
            ),
            zero_decimal,
        ),
        outbound_30_days=Coalesce(
            Sum(
                "quantity",
                filter=Q(transaction_type=Transaction.TransactionType.OUT),
            ),
            zero_decimal,
        ),
    )
    inbound_30_days = tx_summary["inbound_30_days"]
    outbound_30_days = tx_summary["outbound_30_days"]
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
        },
    )


class SystemSettingsUpdateView(UserPassesTestMixin, UpdateView):
    model = SystemSettings
    form_class = SystemSettingsForm
    template_name = "core/settings_form.html"
    success_url = reverse_lazy('dashboard')

    def test_func(self):
        return self.request.user.role == User.Role.ADMIN

    def get_object(self, queryset=None):
        return SystemSettings.get_settings()

    def form_valid(self, form):
        messages.success(self.request, "Pengaturan sistem berhasil diperbarui.")
        return super().form_valid(form)
