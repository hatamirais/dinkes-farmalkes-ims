from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q

from .models import Stock, Transaction
from apps.items.models import Category, Location, FundingSource


@login_required
def stock_list(request):
    queryset = (
        Stock.objects.select_related('item', 'location', 'sumber_dana')
        .filter(quantity__gt=0)
        .order_by('item__nama_barang', 'expiry_date')
    )

    search = request.GET.get('q', '').strip()
    if search:
        queryset = queryset.filter(
            Q(item__kode_barang__icontains=search) |
            Q(item__nama_barang__icontains=search) |
            Q(batch_lot__icontains=search)
        )

    location = request.GET.get('location')
    if location:
        queryset = queryset.filter(location_id=location)

    sumber_dana = request.GET.get('sumber_dana')
    if sumber_dana:
        queryset = queryset.filter(sumber_dana_id=sumber_dana)

    paginator = Paginator(queryset, 25)
    stocks = paginator.get_page(request.GET.get('page'))

    # Build filter lists with selected state
    locations = []
    for loc in Location.objects.filter(is_active=True):
        locations.append({
            'id': loc.id,
            'name': loc.name,
            'selected': 'selected' if location == str(loc.id) else '',
        })

    funding_sources = []
    for sd in FundingSource.objects.filter(is_active=True):
        funding_sources.append({
            'id': sd.id,
            'name': sd.name,
            'selected': 'selected' if sumber_dana == str(sd.id) else '',
        })

    return render(request, 'stock/stock_list.html', {
        'stocks': stocks,
        'locations': locations,
        'funding_sources': funding_sources,
        'search': search,
        'selected_location': location or '',
        'selected_sumber_dana': sumber_dana or '',
    })


@login_required
def transaction_list(request):
    queryset = (
        Transaction.objects.select_related('item', 'user', 'location')
        .order_by('-created_at')
    )

    search = request.GET.get('q', '').strip()
    if search:
        queryset = queryset.filter(
            Q(item__kode_barang__icontains=search) |
            Q(item__nama_barang__icontains=search) |
            Q(batch_lot__icontains=search) |
            Q(notes__icontains=search)
        )

    tx_type = request.GET.get('type')
    if tx_type:
        queryset = queryset.filter(transaction_type=tx_type)

    paginator = Paginator(queryset, 25)
    transactions = paginator.get_page(request.GET.get('page'))

    return render(request, 'stock/transaction_list.html', {
        'transactions': transactions,
        'search': search,
        'selected_type': tx_type or '',
        'type_in': 'selected' if tx_type == 'IN' else '',
        'type_out': 'selected' if tx_type == 'OUT' else '',
        'type_adjust': 'selected' if tx_type == 'ADJUST' else '',
        'type_return': 'selected' if tx_type == 'RETURN' else '',
    })
