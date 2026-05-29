from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from apps.core.decorators import perm_required
from django.db import models
from django.db.models import Sum, Q, F, Case, When, OuterRef, Subquery, Count
from django.db.models.functions import Coalesce
from django.urls import reverse

from .forms import InventoryReportFilterForm, NumberingHistoryFilterForm
from .exports import (
    export_numbering_history_excel,
    export_rincian_excel,
    export_rekap_excel,
)
from apps.stock.models import Transaction, Stock
from apps.distribution.models import Distribution


_PENGELUARAN_REPORT_TAB_URL_NAMES = {
    '': 'reports:pengeluaran',
    Distribution.DistributionType.SPECIAL_REQUEST: 'reports:pengeluaran',
    Distribution.DistributionType.ALLOCATION: 'reports:pengeluaran',
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

        # Subquery to get expiry_date from Stock
        # A specific batch of an item from a specific funding source usually has a consistent expiry_date.
        expiry_sq = Stock.objects.filter(
            item=OuterRef('item'),
            batch_lot=OuterRef('batch_lot'),
            sumber_dana=OuterRef('sumber_dana')
        ).values('expiry_date')[:1]

        # First level query to annotate initial balances and period flows
        qs = Transaction.objects.values(
            'item__kategori__name',
            'item__kategori__sort_order',
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
        ).order_by('item__kategori__sort_order', 'item__kategori__name', 'item__nama_barang', 'batch_lot')
        
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
    return {
        Distribution.Status.DRAFT: 'bg-secondary-subtle text-secondary-emphasis',
        Distribution.Status.SUBMITTED: 'bg-warning-subtle text-warning-emphasis',
        Distribution.Status.VERIFIED: 'bg-info-subtle text-info-emphasis',
        Distribution.Status.GENERATED: 'bg-primary-subtle text-primary-emphasis',
        Distribution.Status.PREPARED: 'bg-primary-subtle text-primary-emphasis',
        Distribution.Status.DISTRIBUTED: 'bg-success-subtle text-success-emphasis',
        Distribution.Status.REJECTED: 'bg-danger-subtle text-danger-emphasis',
    }.get(status, 'bg-light text-dark')


@login_required
@perm_required('reports.view_reports')
def reports_numbering_history(request):
    form = NumberingHistoryFilterForm(
        request.GET or NumberingHistoryFilterForm.get_default_initial()
    )
    history_rows = []
    selected_distribution_type_label = ''

    if form.is_valid():
        distribution_type = form.cleaned_data.get('distribution_type')
        year = form.cleaned_data.get('year')
        selected_distribution_type_label = dict(form.fields['distribution_type'].choices).get(
            distribution_type,
            '',
        )

        qs = (
            Distribution.objects.filter(
                distribution_type__in=[
                    Distribution.DistributionType.LPLPO,
                    Distribution.DistributionType.SPECIAL_REQUEST,
                ]
            )
            .select_related('facility', 'created_by')
            .annotate(item_count=Count('items'))
            .order_by('-created_at', '-id')
        )

        if distribution_type:
            qs = qs.filter(distribution_type=distribution_type)
        if year:
            qs = qs.filter(created_at__year=year)

        for dist in qs:
            source_document_number = '-'
            source_label = '-'
            if dist.distribution_type == Distribution.DistributionType.LPLPO:
                source = getattr(dist, 'lplpo_source', None)
                if source is not None:
                    source_document_number = source.document_number
                    source_label = 'LPLPO'
            elif dist.distribution_type == Distribution.DistributionType.SPECIAL_REQUEST:
                source = getattr(dist, 'puskesmas_request', None)
                if source is not None:
                    source_document_number = source.document_number
                    source_label = 'Permintaan Khusus'

            creator_name = (
                dist.created_by.full_name
                if getattr(dist.created_by, 'full_name', '')
                else dist.created_by.username
            )

            history_rows.append(
                {
                    'pk': dist.pk,
                    'document_number': dist.document_number,
                    'distribution_type': dist.get_distribution_type_display(),
                    'status': dist.get_status_display(),
                    'status_badge_class': _numbering_status_badge(dist.status),
                    'facility_name': dist.facility.name,
                    'request_date': dist.request_date,
                    'created_at': dist.created_at,
                    'created_by': creator_name,
                    'item_count': dist.item_count,
                    'source_label': source_label,
                    'source_document_number': source_document_number,
                    'notes': dist.notes or '-',
                    'workflow_url': reverse('distribution:distribution_detail', args=[dist.pk]),
                }
            )

        if request.GET.get('format') == 'excel' and history_rows:
            return export_numbering_history_excel(
                history_rows,
                year,
                selected_distribution_type_label,
            )

    context = {
        'form': form,
        'history_rows': history_rows,
        'selected_distribution_type_label': selected_distribution_type_label,
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

        # Base queryset: filter by sumber_dana if selected
        base_qs = Transaction.objects.all()
        if selected_sd_ids:
            base_qs = base_qs.filter(sumber_dana_id__in=selected_sd_ids)

        # Aggregate by sumber_dana + kategori
        qs = base_qs.values(
            'sumber_dana__id',
            'sumber_dana__name',
            'item__kategori__name',
            'item__kategori__sort_order',
        ).annotate(
            saldo_awal=Coalesce(
                Sum(
                    Case(
                        When(created_at__date__lt=start_date, transaction_type='IN',
                             then=F('quantity') * F('unit_price')),
                        When(created_at__date__lt=start_date, transaction_type='OUT',
                             then=-F('quantity') * F('unit_price')),
                        default=0,
                        output_field=models.DecimalField()
                    )
                ),
                0, output_field=models.DecimalField()
            ),
            nilai_terima=Coalesce(
                Sum(
                    Case(
                        When(
                            created_at__date__range=[start_date, end_date],
                            reference_type__in=['RECEIVING', 'INITIAL_IMPORT'],
                            transaction_type='IN',
                            then=F('quantity') * F('unit_price')
                        ),
                        default=0,
                        output_field=models.DecimalField()
                    )
                ),
                0, output_field=models.DecimalField()
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
                        output_field=models.DecimalField()
                    )
                ),
                0, output_field=models.DecimalField()
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
                        output_field=models.DecimalField()
                    )
                ),
                0, output_field=models.DecimalField()
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
            saldo_akhir = saldo_awal + nilai_terima - nilai_distribusi - nilai_ed

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
            sd_groups[sd_name]['subtotal_saldo_awal'] += saldo_awal
            sd_groups[sd_name]['subtotal_nilai_terima'] += nilai_terima
            sd_groups[sd_name]['subtotal_nilai_distribusi'] += nilai_distribusi
            sd_groups[sd_name]['subtotal_nilai_ed'] += nilai_ed
            sd_groups[sd_name]['subtotal_saldo_akhir'] += saldo_akhir

        # Build final list and grand totals
        for sd_name, group in sd_groups.items():
            if group['categories']:
                rekap_data.append(group)
                grand_totals['saldo_awal'] += group['subtotal_saldo_awal']
                grand_totals['nilai_terima'] += group['subtotal_nilai_terima']
                grand_totals['nilai_distribusi'] += group['subtotal_nilai_distribusi']
                grand_totals['nilai_ed'] += group['subtotal_nilai_ed']
                grand_totals['saldo_akhir'] += group['subtotal_saldo_akhir']

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
                'total_price': ri.quantity * ri.unit_price,
            })

        if request.GET.get('format') == 'excel' and report_data:
            return export_penerimaan_hibah_excel(report_data, start_date, end_date)

    total_quantity = sum(r['quantity'] for r in report_data)
    total_value = sum(r['total_price'] for r in report_data)

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

        completed_statuses = ['RECEIVED', 'CLOSED', 'VERIFIED']

        qs = ReceivingItem.objects.filter(
            receiving__receiving_type='PROCUREMENT',
            receiving__receiving_date__range=[start_date, end_date],
            receiving__status__in=completed_statuses,
        ).select_related(
            'receiving', 'receiving__supplier', 'receiving__sumber_dana',
            'item', 'item__satuan',
        ).order_by(
            'receiving__receiving_date', 'receiving__document_number', 'item__nama_barang',
        )

        for ri in qs:
            report_data.append({
                'document_number': ri.receiving.document_number,
                'receiving_date': ri.receiving.receiving_date,
                'supplier': ri.receiving.supplier.name if ri.receiving.supplier else '-',
                'sumber_dana': ri.receiving.sumber_dana.name if ri.receiving.sumber_dana else '-',
                'nama_barang': ri.item.nama_barang,
                'satuan': ri.item.satuan.name if ri.item.satuan else '-',
                'batch_lot': ri.batch_lot,
                'expiry_date': ri.expiry_date,
                'unit_price': ri.unit_price,
                'quantity': ri.quantity,
                'total_price': ri.quantity * ri.unit_price,
            })

        if request.GET.get('format') == 'excel' and report_data:
            return export_pengadaan_excel(report_data, start_date, end_date)

    total_quantity = sum(r['quantity'] for r in report_data)
    total_value = sum(r['total_price'] for r in report_data)

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
                'total_price': ei.quantity * unit_price,
                'notes': ei.notes,
            })

        if request.GET.get('format') == 'excel' and report_data:
            return export_kadaluarsa_excel(report_data, start_date, end_date)

    total_quantity = sum(r['quantity'] for r in report_data)
    total_value = sum(r['total_price'] for r in report_data)

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

        if distribution_type:
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
                'total_price': qty * unit_price,
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
    total_value = sum(r['total_price'] for r in report_data)

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
