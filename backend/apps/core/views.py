from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum, Q, F

from apps.items.models import Item
from apps.stock.models import Stock, Transaction


@login_required
def dashboard(request):
    today = timezone.now().date()
    three_months_later = today + timedelta(days=90)

    # Stats
    total_items = Item.objects.filter(is_active=True).count()
    total_stock_entries = Stock.objects.filter(quantity__gt=0).count()

    # Low stock: items where total stock quantity is below minimum_stock
    low_stock_items = (
        Item.objects.filter(is_active=True)
        .annotate(total_qty=Sum('stock_entries__quantity'))
        .filter(
            Q(total_qty__lt=F('minimum_stock')) | Q(total_qty__isnull=True),
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
        .select_related('item')
        .order_by('expiry_date')[:10]
    )
    expiring_soon_count = Stock.objects.filter(
        quantity__gt=0,
        expiry_date__lte=three_months_later,
    ).count()

    # Add is_expired flag for template
    for stock in expiring_soon:
        stock.is_expired = stock.expiry_date <= today

    # Recent transactions
    recent_transactions = (
        Transaction.objects.select_related('item', 'user')
        .order_by('-created_at')[:10]
    )

    return render(request, 'dashboard.html', {
        'total_items': total_items,
        'total_stock_entries': total_stock_entries,
        'low_stock_count': low_stock_count,
        'expiring_soon_count': expiring_soon_count,
        'expiring_soon': expiring_soon,
        'recent_transactions': recent_transactions,
    })
