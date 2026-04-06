from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db import models
from django.db.models import Sum, Q, F, Case, When, OuterRef, Subquery
from django.db.models.functions import Coalesce

from .forms import InventoryReportFilterForm
from apps.stock.models import Transaction, Stock

@login_required
def reports_index(request):
    form = InventoryReportFilterForm(request.GET or InventoryReportFilterForm.get_default_initial())
    
    report_data = []
    
    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')

        # Subquery to get expiry_date from Stock
        # A specific batch of an item from a specific funding source usually has a consistent expiry_date.
        expiry_sq = Stock.objects.filter(
            item=OuterRef('item'),
            batch_lot=OuterRef('batch_lot'),
            sumber_dana=OuterRef('sumber_dana')
        ).values('expiry_date')[:1]

        # First level query to annotate initial balances and period flows
        qs = Transaction.objects.values(
            'item__nama_barang',
            'item__satuan__name',
            'batch_lot',
            'sumber_dana__name',
            'unit_price'
        ).annotate(
            expiry_date=Subquery(expiry_sq),
            initial_stock=Coalesce(
                Sum(
                    Case(
                        When(created_at__date__lt=start_date, transaction_type='IN', then=F('quantity')),
                        When(created_at__date__lt=start_date, transaction_type='OUT', then=-F('quantity')),
                        default=0,
                        output_field=models.DecimalField()
                    )
                ), 
                0, output_field=models.DecimalField()
            ),
            received=Coalesce(
                Sum(
                    Case(
                        When(
                            created_at__date__range=[start_date, end_date], 
                            reference_type__in=['RECEIVING', 'INITIAL_IMPORT'],
                            transaction_type='IN',
                            then=F('quantity')
                        ),
                        default=0,
                        output_field=models.DecimalField()
                    )
                ),
                0, output_field=models.DecimalField()
            ),
            distributed=Coalesce(
                Sum(
                    Case(
                        When(
                            created_at__date__range=[start_date, end_date], 
                            reference_type__in=['DISTRIBUTION', 'RECALL'],
                            transaction_type='OUT',
                            then=F('quantity')
                        ),
                        default=0,
                        output_field=models.DecimalField()
                    )
                ),
                0, output_field=models.DecimalField()
            ),
            expired=Coalesce(
                Sum(
                    Case(
                        When(
                            created_at__date__range=[start_date, end_date], 
                            reference_type='EXPIRED',
                            transaction_type='OUT',
                            then=F('quantity')
                        ),
                        default=0,
                        output_field=models.DecimalField()
                    )
                ),
                0, output_field=models.DecimalField()
            )
        ).order_by('item__nama_barang', 'batch_lot')
        
        # We need a second annotate step (or list comprehension) to properly add ending_stock safely.
        # F-expressions mapped over coalesced outputs in annotate chaining sometimes act up on PostgreSQL.
        for row in qs:
            row['ending_stock'] = (
                row['initial_stock'] 
                + row['received'] 
                - row['distributed'] 
                - row['expired']
            )
            # Only include rows that have actual movement or stock
            if (row['initial_stock'] != 0 or 
                row['received'] != 0 or 
                row['distributed'] != 0 or 
                row['expired'] != 0):
                report_data.append(row)

    context = {
        'form': form,
        'report_data': report_data
    }
    return render(request, 'reports/index.html', context)
