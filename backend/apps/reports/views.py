from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from apps.core.decorators import perm_required
from django.db import models
from django.db.models import Sum, Q, F, Case, When, OuterRef, Subquery, Count, Exists
from django.db.models.functions import Coalesce, TruncDate
from django.urls import reverse

from apps.core.decimal_validation import multiply_decimals, sum_decimals
from apps.core.models import DocumentNumberIssue
from .forms import InventoryReportFilterForm, NumberingHistoryFilterForm
from .exports import (
    export_numbering_history_excel,
    export_rincian_excel,
    export_rekap_excel,
)
from apps.stock.models import OpeningBalanceImportItem, Transaction, Stock
from apps.distribution.models import Distribution


_PENGELUARAN_REPORT_TAB_URL_NAMES = {
    '': 'reports:pengeluaran',
    Distribution.DistributionType.SPECIAL_REQUEST: 'reports:pengeluaran',
    'ALLOCATION': 'reports:pengeluaran',
    Distribution.DistributionType.LPLPO: 'reports:pengeluaran',
}


@login_required
@perm_required('reports.view_reports')
def reports_index(request):
    form = InventoryReportFilterForm(request.GET or InventoryReportFilterForm.get_default_initial())
    
    report_data = []
    
    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        initial_import_as_opening_balance = (
            Q(reference_type='INITIAL_IMPORT')
            & Q(transaction_type='IN')
            & (
                Q(has_effective_opening_balance_item=True)
                | (
                    Q(created_at__date__lte=start_date)
                    & Q(has_any_opening_balance_item=False)
                )
            )
        )
        initial_import_as_period_receiving = (
            Q(reference_type='INITIAL_IMPORT')
            & Q(transaction_type='IN')
            & (
                Q(has_in_period_opening_balance_item=True)
                | (
                    Q(created_at__date__gt=start_date)
                    & Q(created_at__date__lte=end_date)
                    & Q(has_any_opening_balance_item=False)
                )
            )
        )

        # Subquery to get expiry_date from Stock
        # A specific batch of an item from a specific funding source usually has a consistent expiry_date.
        expiry_sq = Stock.objects.filter(
            item=OuterRef('item'),
            location=OuterRef('location'),
            batch_lot=OuterRef('batch_lot'),
            sumber_dana=OuterRef('sumber_dana'),
            source_document_number=OuterRef('source_document_number'),
        ).values('expiry_date')[:1]

        # First level query to annotate initial balances and period flows
        qs = Transaction.objects.annotate(
            has_effective_opening_balance_item=Exists(
                OpeningBalanceImportItem.objects.filter(
                    opening_balance_id=OuterRef('reference_id'),
                    opening_balance__created_at__lte=OuterRef('created_at'),
                    opening_balance__effective_date__lte=start_date,
                    item=OuterRef('item'),
                    location=OuterRef('location'),
                    batch_lot=OuterRef('batch_lot'),
                    sumber_dana=OuterRef('sumber_dana'),
                    quantity=OuterRef('quantity'),
                    unit_price=OuterRef('unit_price'),
                )
            ),
            has_any_opening_balance_item=Exists(
                OpeningBalanceImportItem.objects.filter(
                    opening_balance_id=OuterRef('reference_id'),
                    opening_balance__created_at__lte=OuterRef('created_at'),
                    item=OuterRef('item'),
                    location=OuterRef('location'),
                    batch_lot=OuterRef('batch_lot'),
                    sumber_dana=OuterRef('sumber_dana'),
                    quantity=OuterRef('quantity'),
                    unit_price=OuterRef('unit_price'),
                )
            ),
            has_in_period_opening_balance_item=Exists(
                OpeningBalanceImportItem.objects.filter(
                    opening_balance_id=OuterRef('reference_id'),
                    opening_balance__created_at__lte=OuterRef('created_at'),
                    opening_balance__effective_date__gt=start_date,
                    opening_balance__effective_date__lte=end_date,
                    item=OuterRef('item'),
                    location=OuterRef('location'),
                    batch_lot=OuterRef('batch_lot'),
                    sumber_dana=OuterRef('sumber_dana'),
                    quantity=OuterRef('quantity'),
                    unit_price=OuterRef('unit_price'),
                )
            ),
        ).values(
            'item__kategori__name',
            'item__kategori__sort_order',
            'item__nama_barang',
            'item__satuan__name',
            'location_id',
            'location__code',
            'location__name',
            'batch_lot',
            'source_document_number',
            'sumber_dana__name',
            'unit_price'
        ).annotate(
            expiry_date=Subquery(expiry_sq),
            initial_stock=Coalesce(
                Sum(
                    Case(
                        When(
                            initial_import_as_opening_balance,
                            then=F('quantity'),
                        ),
                        When(
                            Q(created_at__date__lt=start_date)
                            & Q(transaction_type='IN')
                            & ~Q(reference_type='INITIAL_IMPORT'),
                            then=F('quantity'),
                        ),
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
                            reference_type='RECEIVING',
                            transaction_type='IN',
                            then=F('quantity')
                        ),
                        When(
                            created_at__date__range=[start_date, end_date],
                            reference_type='RECEIVING',
                            transaction_type='OUT',
                            then=-F('quantity')
                        ),
                        When(
                            initial_import_as_period_receiving,
                            then=F('quantity')
                        ),
                        default=0,
                        output_field=models.DecimalField()
                    )
                ),
                0, output_field=models.DecimalField()
            ),
            transfer_in=Coalesce(
                Sum(
                    Case(
                        When(
                            created_at__date__range=[start_date, end_date],
                            reference_type='TRANSFER',
                            transaction_type='IN',
                            then=F('quantity'),
                        ),
                        default=0,
                        output_field=models.DecimalField(),
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
            transfer_out=Coalesce(
                Sum(
                    Case(
                        When(
                            created_at__date__range=[start_date, end_date],
                            reference_type='TRANSFER',
                            transaction_type='OUT',
                            then=F('quantity'),
                        ),
                        default=0,
                        output_field=models.DecimalField(),
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
        ).order_by(
            'item__kategori__sort_order',
            'item__kategori__name',
            'item__nama_barang',
            'location__code',
            'location__name',
            'batch_lot',
        )
        
        # We need a second annotate step (or list comprehension) to properly add ending_stock safely.
        # F-expressions mapped over coalesced outputs in annotate chaining sometimes act up on PostgreSQL.
        for row in qs:
            row['location_label'] = (
                f"{row['location__code']} - {row['location__name']}"
                if row.get('location__code')
                else row.get('location__name', '')
            )
            row['ending_stock'] = (
                row['initial_stock'] 
                + row['received'] 
                + row['transfer_in']
                - row['distributed'] 
                - row['transfer_out']
                - row['expired']
            )
            # Only include rows that have actual movement or stock
            if (row['initial_stock'] != 0 or 
                row['received'] != 0 or 
                row['transfer_in'] != 0 or
                row['distributed'] != 0 or 
                row['transfer_out'] != 0 or
                row['expired'] != 0):
                report_data.append(row)

    # Excel export path
    if request.GET.get('format') == 'excel' and report_data:
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        return export_rincian_excel(report_data, start_date, end_date)

    context = {
        'form': form,
        'report_data': report_data
    }
    return render(request, 'reports/index.html', context)


def _numbering_status_badge(status):
    return (
        'bg-danger-subtle text-danger-emphasis'
        if status == DocumentNumberIssue.Status.VOID
        else 'bg-success-subtle text-success-emphasis'
    )


def _numbering_workflow_url(target):
    if target is None:
        return ''
    route_by_label = {
        'allocation.Allocation': 'allocation:allocation_detail',
        'distribution.Distribution': 'distribution:distribution_detail',
        'procurement.ProcurementContract': 'procurement:contract_detail',
        'procurement.ProcurementAmendment': 'procurement:amendment_detail',
        'recall.Recall': 'recall:recall_detail',
        'expired.Expired': 'expired:expired_detail',
        'stock.StockTransfer': 'stock:transfer_detail',
        'stock_opname.StockOpname': 'stock_opname:opname_detail',
    }
    if target._meta.label == 'receiving.Receiving':
        route_name = (
            'receiving:receiving_plan_detail'
            if target.is_planned
            else 'receiving:receiving_detail'
        )
    else:
        route_name = route_by_label.get(target._meta.label)
    return reverse(route_name, args=[target.pk]) if route_name else ''


@login_required
@perm_required('reports.view_reports')
def reports_numbering_history(request):
    form = NumberingHistoryFilterForm(
        request.GET or NumberingHistoryFilterForm.get_default_initial()
    )
    history_rows = []
    selected_rule_label = ''

    if form.is_valid():
        rule_key = form.cleaned_data.get('rule_key')
        year = form.cleaned_data.get('year')
        selected_rule_label = dict(form.fields['rule_key'].choices).get(
            rule_key,
            '',
        )

        qs = (
            DocumentNumberIssue.objects.select_related(
                'rule', 'content_type', 'issued_by', 'voided_by'
            )
            .filter(business_date__year=year)
            .order_by(
                '-business_date',
                F('issued_at').desc(nulls_last=True),
                '-id',
            )
        )

        if rule_key:
            qs = qs.filter(rule__key=rule_key)

        issues = list(qs)
        targets_by_key = {}
        ids_by_content_type = {}
        for issue in issues:
            ids_by_content_type.setdefault(issue.content_type_id, []).append(issue.object_id)
        for issue in issues:
            content_type_id = issue.content_type_id
            if any(key[0] == content_type_id for key in targets_by_key):
                continue
            model_class = issue.content_type.model_class()
            if model_class is None:
                continue
            for object_id, target in model_class.objects.in_bulk(
                ids_by_content_type[content_type_id]
            ).items():
                targets_by_key[(content_type_id, object_id)] = target

        for issue in issues:
            target = targets_by_key.get((issue.content_type_id, issue.object_id))
            actor = issue.issued_by
            actor_name = '-'
            if actor is not None:
                actor_name = actor.full_name or actor.username
            target_status = '-'
            if target is not None and hasattr(target, 'get_status_display'):
                target_status = target.get_status_display()

            history_rows.append(
                {
                    'document_number': issue.document_number,
                    'rule_label': issue.rule_label_snapshot,
                    'issue_status': issue.get_status_display(),
                    'status_badge_class': _numbering_status_badge(issue.status),
                    'target_status': target_status,
                    'business_date': issue.business_date,
                    'period_key': issue.period_key or '-',
                    'sequence_value': issue.sequence_value,
                    'issued_at': issue.issued_at,
                    'issued_by': actor_name,
                    'voided_at': issue.voided_at,
                    'void_reason': issue.void_reason or '-',
                    'target_label': issue.target_label,
                    'workflow_url': _numbering_workflow_url(target),
                }
            )

        if request.GET.get('format') == 'excel' and history_rows:
            return export_numbering_history_excel(
                history_rows,
                year,
                selected_rule_label,
            )

    context = {
        'form': form,
        'history_rows': history_rows,
        'selected_rule_label': selected_rule_label,
    }
    return render(request, 'reports/numbering_history.html', context)

@login_required
@perm_required('reports.view_reports')
def reports_rekap(request):
    from apps.items.models import FundingSource
    from decimal import Decimal

    form = InventoryReportFilterForm(request.GET or InventoryReportFilterForm.get_default_initial())

    all_sumber_dana = FundingSource.objects.filter(is_active=True).order_by('code')

    # Get selected sumber_dana IDs from GET params
    selected_sd_ids = request.GET.getlist('sumber_dana')
    selected_sd_ids = [int(x) for x in selected_sd_ids if x.isdigit()]

    rekap_data = []
    grand_totals = {
        'saldo_awal': Decimal('0'),
        'nilai_terima': Decimal('0'),
        'nilai_distribusi': Decimal('0'),
        'nilai_ed': Decimal('0'),
        'saldo_akhir': Decimal('0'),
    }

    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        initial_import_as_opening_balance = (
            Q(reference_type='INITIAL_IMPORT')
            & Q(transaction_type='IN')
            & (
                Q(has_effective_opening_balance_item=True)
                | (
                    Q(created_at__date__lte=start_date)
                    & Q(has_any_opening_balance_item=False)
                )
            )
        )
        initial_import_as_period_receiving = (
            Q(reference_type='INITIAL_IMPORT')
            & Q(transaction_type='IN')
            & (
                Q(has_in_period_opening_balance_item=True)
                | (
                    Q(created_at__date__gt=start_date)
                    & Q(created_at__date__lte=end_date)
                    & Q(has_any_opening_balance_item=False)
                )
            )
        )

        # Base queryset: filter by sumber_dana if selected
        base_qs = Transaction.objects.all()
        if selected_sd_ids:
            base_qs = base_qs.filter(sumber_dana_id__in=selected_sd_ids)
        money_field = models.DecimalField(max_digits=38, decimal_places=12)

        # Aggregate by sumber_dana + kategori
        qs = base_qs.annotate(
            has_effective_opening_balance_item=Exists(
                OpeningBalanceImportItem.objects.filter(
                    opening_balance_id=OuterRef('reference_id'),
                    opening_balance__created_at__lte=OuterRef('created_at'),
                    opening_balance__effective_date__lte=start_date,
                    item=OuterRef('item'),
                    location=OuterRef('location'),
                    batch_lot=OuterRef('batch_lot'),
                    sumber_dana=OuterRef('sumber_dana'),
                    quantity=OuterRef('quantity'),
                    unit_price=OuterRef('unit_price'),
                )
            ),
            has_any_opening_balance_item=Exists(
                OpeningBalanceImportItem.objects.filter(
                    opening_balance_id=OuterRef('reference_id'),
                    opening_balance__created_at__lte=OuterRef('created_at'),
                    item=OuterRef('item'),
                    location=OuterRef('location'),
                    batch_lot=OuterRef('batch_lot'),
                    sumber_dana=OuterRef('sumber_dana'),
                    quantity=OuterRef('quantity'),
                    unit_price=OuterRef('unit_price'),
                )
            ),
            has_in_period_opening_balance_item=Exists(
                OpeningBalanceImportItem.objects.filter(
                    opening_balance_id=OuterRef('reference_id'),
                    opening_balance__created_at__lte=OuterRef('created_at'),
                    opening_balance__effective_date__gt=start_date,
                    opening_balance__effective_date__lte=end_date,
                    item=OuterRef('item'),
                    location=OuterRef('location'),
                    batch_lot=OuterRef('batch_lot'),
                    sumber_dana=OuterRef('sumber_dana'),
                    quantity=OuterRef('quantity'),
                    unit_price=OuterRef('unit_price'),
                )
            ),
        ).values(
            'sumber_dana__id',
            'sumber_dana__name',
            'item__kategori__name',
            'item__kategori__sort_order',
        ).annotate(
            saldo_awal=Coalesce(
                Sum(
                    Case(
                        When(
                            initial_import_as_opening_balance,
                            then=F('quantity') * F('unit_price')
                        ),
                        When(
                            Q(created_at__date__lt=start_date)
                            & Q(transaction_type='IN')
                            & ~Q(reference_type='INITIAL_IMPORT'),
                            then=F('quantity') * F('unit_price')
                        ),
                        When(created_at__date__lt=start_date, transaction_type='OUT',
                             then=-F('quantity') * F('unit_price')),
                        default=0,
                        output_field=money_field
                    )
                ),
                0, output_field=money_field
            ),
            nilai_terima=Coalesce(
                Sum(
                    Case(
                        When(
                            created_at__date__range=[start_date, end_date],
                            reference_type='RECEIVING',
                            transaction_type='IN',
                            then=F('quantity') * F('unit_price')
                        ),
                        When(
                            created_at__date__range=[start_date, end_date],
                            reference_type='RECEIVING',
                            transaction_type='OUT',
                            then=-F('quantity') * F('unit_price')
                        ),
                        When(
                            initial_import_as_period_receiving,
                            then=F('quantity') * F('unit_price')
                        ),
                        default=0,
                        output_field=money_field
                    )
                ),
                0, output_field=money_field
            ),
            nilai_distribusi=Coalesce(
                Sum(
                    Case(
                        When(
                            created_at__date__range=[start_date, end_date],
                            reference_type__in=['DISTRIBUTION', 'RECALL'],
                            transaction_type='OUT',
                            then=F('quantity') * F('unit_price')
                        ),
                        default=0,
                        output_field=money_field
                    )
                ),
                0, output_field=money_field
            ),
            nilai_ed=Coalesce(
                Sum(
                    Case(
                        When(
                            created_at__date__range=[start_date, end_date],
                            reference_type='EXPIRED',
                            transaction_type='OUT',
                            then=F('quantity') * F('unit_price')
                        ),
                        default=0,
                        output_field=money_field
                    )
                ),
                0, output_field=money_field
            ),
        ).order_by('sumber_dana__name', 'item__kategori__sort_order', 'item__kategori__name')

        # Group data by sumber_dana for template rendering
        sd_groups = {}
        for row in qs:
            sd_name = row['sumber_dana__name'] or 'TIDAK DIKETAHUI'
            sd_id = row['sumber_dana__id']
            if sd_name not in sd_groups:
                sd_groups[sd_name] = {
                    'sd_id': sd_id,
                    'sd_name': sd_name,
                    'categories': [],
                    'subtotal_saldo_awal': Decimal('0'),
                    'subtotal_nilai_terima': Decimal('0'),
                    'subtotal_nilai_distribusi': Decimal('0'),
                    'subtotal_nilai_ed': Decimal('0'),
                    'subtotal_saldo_akhir': Decimal('0'),
                }

            saldo_awal = row['saldo_awal'] or Decimal('0')
            nilai_terima = row['nilai_terima'] or Decimal('0')
            nilai_distribusi = row['nilai_distribusi'] or Decimal('0')
            nilai_ed = row['nilai_ed'] or Decimal('0')
            negative_nilai_distribusi = multiply_decimals(
                nilai_distribusi, Decimal("-1")
            )
            negative_nilai_ed = multiply_decimals(nilai_ed, Decimal("-1"))
            saldo_akhir = sum_decimals(
                [saldo_awal, nilai_terima, negative_nilai_distribusi, negative_nilai_ed]
            )

            # Skip zero rows
            if saldo_awal == 0 and nilai_terima == 0 and nilai_distribusi == 0 and nilai_ed == 0:
                continue

            category_row = {
                'kategori': row['item__kategori__name'] or 'Lainnya',
                'saldo_awal': saldo_awal,
                'nilai_terima': nilai_terima,
                'nilai_distribusi': nilai_distribusi,
                'nilai_ed': nilai_ed,
                'saldo_akhir': saldo_akhir,
            }
            sd_groups[sd_name]['categories'].append(category_row)

            # Accumulate subtotals
            sd_groups[sd_name]['subtotal_saldo_awal'] = sum_decimals(
                [sd_groups[sd_name]['subtotal_saldo_awal'], saldo_awal]
            )
            sd_groups[sd_name]['subtotal_nilai_terima'] = sum_decimals(
                [sd_groups[sd_name]['subtotal_nilai_terima'], nilai_terima]
            )
            sd_groups[sd_name]['subtotal_nilai_distribusi'] = sum_decimals(
                [sd_groups[sd_name]['subtotal_nilai_distribusi'], nilai_distribusi]
            )
            sd_groups[sd_name]['subtotal_nilai_ed'] = sum_decimals(
                [sd_groups[sd_name]['subtotal_nilai_ed'], nilai_ed]
            )
            sd_groups[sd_name]['subtotal_saldo_akhir'] = sum_decimals(
                [sd_groups[sd_name]['subtotal_saldo_akhir'], saldo_akhir]
            )

        # Build final list and grand totals
        for sd_name, group in sd_groups.items():
            if group['categories']:
                rekap_data.append(group)
                grand_totals['saldo_awal'] = sum_decimals(
                    [grand_totals['saldo_awal'], group['subtotal_saldo_awal']]
                )
                grand_totals['nilai_terima'] = sum_decimals(
                    [grand_totals['nilai_terima'], group['subtotal_nilai_terima']]
                )
                grand_totals['nilai_distribusi'] = sum_decimals(
                    [grand_totals['nilai_distribusi'], group['subtotal_nilai_distribusi']]
                )
                grand_totals['nilai_ed'] = sum_decimals(
                    [grand_totals['nilai_ed'], group['subtotal_nilai_ed']]
                )
                grand_totals['saldo_akhir'] = sum_decimals(
                    [grand_totals['saldo_akhir'], group['subtotal_saldo_akhir']]
                )

    # Excel export path
    if request.GET.get('format') == 'excel' and rekap_data:
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        return export_rekap_excel(rekap_data, grand_totals, start_date, end_date)

    context = {
        'form': form,
        'rekap_data': rekap_data,
        'grand_totals': grand_totals,
        'all_sumber_dana': all_sumber_dana,
        'selected_sd_ids': selected_sd_ids,
    }
    return render(request, 'reports/rekap.html', context)

@login_required
@perm_required('reports.view_reports')
def reports_penerimaan_hibah(request):
    from apps.receiving.models import ReceivingItem
    from .exports import export_penerimaan_hibah_excel

    form = InventoryReportFilterForm(request.GET or InventoryReportFilterForm.get_default_initial())
    report_data = []

    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')

        completed_statuses = ['RECEIVED', 'CLOSED', 'VERIFIED']

        qs = ReceivingItem.objects.filter(
            receiving__receiving_type='GRANT',
            receiving__receiving_date__range=[start_date, end_date],
            receiving__status__in=completed_statuses,
        ).select_related(
            'receiving', 'receiving__sumber_dana', 'item', 'item__satuan',
        ).order_by(
            'receiving__receiving_date', 'receiving__document_number', 'item__nama_barang',
        )

        for ri in qs:
            report_data.append({
                'document_number': ri.receiving.document_number,
                'receiving_date': ri.receiving.receiving_date,
                'grant_origin': ri.receiving.grant_origin,
                'sumber_dana': ri.receiving.sumber_dana.name if ri.receiving.sumber_dana else '-',
                'nama_barang': ri.item.nama_barang,
                'satuan': ri.item.satuan.name if ri.item.satuan else '-',
                'batch_lot': ri.batch_lot,
                'expiry_date': ri.expiry_date,
                'unit_price': ri.unit_price,
                'quantity': ri.quantity,
                'total_price': multiply_decimals(ri.quantity, ri.unit_price),
            })

        if request.GET.get('format') == 'excel' and report_data:
            return export_penerimaan_hibah_excel(report_data, start_date, end_date)

    total_quantity = sum(r['quantity'] for r in report_data)
    total_value = sum_decimals(r['total_price'] for r in report_data)

    context = {
        'form': form,
        'report_data': report_data,
        'total_quantity': total_quantity,
        'total_value': total_value,
    }
    return render(request, 'reports/penerimaan_hibah.html', context)

@login_required
@perm_required('reports.view_reports')
def reports_pengadaan(request):
    from apps.receiving.models import ReceivingItem
    from .exports import export_pengadaan_excel

    form = InventoryReportFilterForm(request.GET or InventoryReportFilterForm.get_default_initial())
    report_data = []

    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')

        completed_statuses = ['PARTIAL', 'RECEIVED', 'CLOSED', 'VERIFIED']

        qs = ReceivingItem.objects.annotate(
            actual_receiving_date=Coalesce(
                TruncDate('received_at'),
                F('receiving__receiving_date'),
            )
        ).filter(
            receiving__receiving_type='PROCUREMENT',
            actual_receiving_date__range=[start_date, end_date],
            receiving__status__in=completed_statuses,
        ).select_related(
            'receiving', 'receiving__supplier', 'receiving__sumber_dana', 'receiving__contract',
            'item', 'item__satuan',
        ).order_by(
            'actual_receiving_date', 'receiving__document_number', 'item__nama_barang',
        )

        for ri in qs:
            report_data.append({
                'document_number': ri.receiving.document_number,
                'receiving_date': ri.actual_receiving_date,
                'supplier': ri.receiving.supplier.name if ri.receiving.supplier else '-',
                'contract_document_number': ri.receiving.contract.document_number if getattr(ri.receiving, 'contract', None) else '-',
                'sumber_dana': ri.receiving.sumber_dana.name if ri.receiving.sumber_dana else '-',
                'nama_barang': ri.item.nama_barang,
                'satuan': ri.item.satuan.name if ri.item.satuan else '-',
                'batch_lot': ri.batch_lot,
                'expiry_date': ri.expiry_date,
                'unit_price': ri.unit_price,
                'quantity': ri.quantity,
                'total_price': multiply_decimals(ri.quantity, ri.unit_price),
            })

        if request.GET.get('format') == 'excel' and report_data:
            return export_pengadaan_excel(report_data, start_date, end_date)

    total_quantity = sum(r['quantity'] for r in report_data)
    total_value = sum_decimals(r['total_price'] for r in report_data)

    context = {
        'form': form,
        'report_data': report_data,
        'total_quantity': total_quantity,
        'total_value': total_value,
    }
    return render(request, 'reports/pengadaan.html', context)

@login_required
@perm_required('reports.view_reports')
def reports_kadaluarsa(request):
    from apps.expired.models import ExpiredItem
    from .exports import export_kadaluarsa_excel

    form = InventoryReportFilterForm(request.GET or InventoryReportFilterForm.get_default_initial())
    report_data = []

    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')

        qs = ExpiredItem.objects.filter(
            expired__report_date__range=[start_date, end_date],
            expired__status='DISPOSED',
        ).select_related(
            'expired', 'item', 'item__satuan', 'stock', 'stock__sumber_dana',
        ).order_by(
            'expired__report_date', 'expired__document_number', 'item__nama_barang',
        )

        for ei in qs:
            unit_price = ei.stock.unit_price if ei.stock else 0
            report_data.append({
                'document_number': ei.expired.document_number,
                'report_date': ei.expired.report_date,
                'nama_barang': ei.item.nama_barang,
                'satuan': ei.item.satuan.name if ei.item.satuan else '-',
                'batch_lot': ei.stock.batch_lot if ei.stock else '-',
                'expiry_date': ei.stock.expiry_date if ei.stock else None,
                'sumber_dana': ei.stock.sumber_dana.name if ei.stock and ei.stock.sumber_dana else '-',
                'unit_price': unit_price,
                'quantity': ei.quantity,
                'total_price': multiply_decimals(ei.quantity, unit_price),
                'notes': ei.notes,
            })

        if request.GET.get('format') == 'excel' and report_data:
            return export_kadaluarsa_excel(report_data, start_date, end_date)

    total_quantity = sum(r['quantity'] for r in report_data)
    total_value = sum_decimals(r['total_price'] for r in report_data)

    context = {
        'form': form,
        'report_data': report_data,
        'total_quantity': total_quantity,
        'total_value': total_value,
    }
    return render(request, 'reports/kadaluarsa.html', context)

@login_required
@perm_required('reports.view_reports')
def reports_pengeluaran(request):
    return render_pengeluaran_report(request)


def render_pengeluaran_report(
    request,
    *,
    forced_distribution_type='',
    base_report_url_name='reports:pengeluaran',
    tab_url_names=None,
):
    from apps.distribution.models import DistributionItem
    from .forms import PengeluaranReportFilterForm
    from .exports import export_pengeluaran_excel

    initial_data = PengeluaranReportFilterForm.get_default_initial()
    effective_querydict = request.GET.copy()
    for key, value in initial_data.items():
        if not effective_querydict.get(key):
            effective_querydict[key] = value
    if forced_distribution_type:
        effective_querydict['distribution_type'] = forced_distribution_type

    form = PengeluaranReportFilterForm(effective_querydict)
    report_data = []
    active_distribution_type = forced_distribution_type or effective_querydict.get('distribution_type', '') or ''
    selected_distribution_type_label = dict(
        PengeluaranReportFilterForm.base_fields['distribution_type'].choices
    ).get(active_distribution_type, 'Semua Distribusi')
    selected_facility_name = 'Semua Fasilitas'

    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        distribution_type = forced_distribution_type or form.cleaned_data.get('distribution_type')
        facility = form.cleaned_data.get('facility')
        selected_facility_name = facility.name if facility else 'Semua Fasilitas'
        active_distribution_type = distribution_type or ''
        selected_distribution_type_label = dict(form.fields['distribution_type'].choices).get(
            active_distribution_type,
            'Semua Distribusi',
        )

        qs = DistributionItem.objects.filter(
            distribution__status='DISTRIBUTED',
            distribution__request_date__range=[start_date, end_date],
        ).select_related(
            'distribution', 'distribution__facility',
            'item', 'item__satuan', 'stock', 'stock__sumber_dana',
        ).order_by(
            'distribution__request_date', 'distribution__document_number', 'item__nama_barang',
        )

        if facility:
            qs = qs.filter(distribution__facility=facility)

        if distribution_type == 'ALLOCATION':
            qs = qs.filter(distribution__allocation__isnull=False)
        elif distribution_type:
            qs = qs.filter(distribution__distribution_type=distribution_type)

        for di in qs:
            qty = di.quantity_approved if di.quantity_approved is not None else di.quantity_requested
            unit_price = di.stock.unit_price if di.stock else 0
            report_data.append({
                'document_number': di.distribution.document_number,
                'request_date': di.distribution.request_date,
                'facility_name': di.distribution.facility.name if di.distribution.facility else '-',
                'nama_barang': di.item.nama_barang,
                'satuan': di.item.satuan.name if di.item.satuan else '-',
                'batch_lot': di.stock.batch_lot if di.stock else '-',
                'expiry_date': di.stock.expiry_date if di.stock else None,
                'sumber_dana': di.stock.sumber_dana.name if di.stock and di.stock.sumber_dana else '-',
                'unit_price': unit_price,
                'quantity': qty,
                'total_price': multiply_decimals(qty, unit_price),
            })

        if request.GET.get('format') == 'excel' and report_data:
            return export_pengeluaran_excel(
                report_data,
                start_date,
                end_date,
                selected_facility_name,
                selected_distribution_type_label,
            )

    if tab_url_names is None:
        tab_url_names = _PENGELUARAN_REPORT_TAB_URL_NAMES

    tab_choices = PengeluaranReportFilterForm.base_fields['distribution_type'].choices
    tab_base_params = effective_querydict.copy()
    tab_base_params.pop('format', None)
    tab_base_params.pop('distribution_type', None)
    tabs = []
    for value, label in tab_choices:
        tab_params = tab_base_params.copy()
        if value:
            tab_params['distribution_type'] = value
        tab_url = reverse(tab_url_names.get(value, base_report_url_name))
        encoded_params = tab_params.urlencode()
        if encoded_params:
            tab_url = f'{tab_url}?{encoded_params}'
        tabs.append(
            {
                'value': value,
                'label': label,
                'url': tab_url,
                'active': value == active_distribution_type,
            }
        )

    total_quantity = sum(r['quantity'] for r in report_data)
    total_value = sum_decimals(r['total_price'] for r in report_data)

    context = {
        'form': form,
        'report_data': report_data,
        'total_quantity': total_quantity,
        'total_value': total_value,
        'tabs': tabs,
        'active_distribution_type': active_distribution_type,
        'selected_distribution_type_label': selected_distribution_type_label,
        'selected_facility_name': selected_facility_name,
        'base_report_url_name': base_report_url_name,
    }
    return render(request, 'reports/pengeluaran.html', context)
