from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q

from .models import Distribution, DistributionItem
from .forms import DistributionForm, DistributionItemFormSet


@login_required
def distribution_list(request):
    queryset = (
        Distribution.objects.select_related('facility', 'created_by')
        .order_by('-request_date')
    )

    search = request.GET.get('q', '').strip()
    if search:
        queryset = queryset.filter(
            Q(document_number__icontains=search) |
            Q(facility__name__icontains=search)
        )

    status = request.GET.get('status')
    if status:
        queryset = queryset.filter(status=status)

    d_type = request.GET.get('type')
    if d_type:
        queryset = queryset.filter(distribution_type=d_type)

    paginator = Paginator(queryset, 25)
    distributions = paginator.get_page(request.GET.get('page'))

    return render(request, 'distribution/distribution_list.html', {
        'distributions': distributions,
        'search': search,
        'selected_status': status or '',
        'selected_type': d_type or '',
        'status_draft': 'selected' if status == 'DRAFT' else '',
        'status_submitted': 'selected' if status == 'SUBMITTED' else '',
        'status_verified': 'selected' if status == 'VERIFIED' else '',
        'status_prepared': 'selected' if status == 'PREPARED' else '',
        'status_distributed': 'selected' if status == 'DISTRIBUTED' else '',
        'type_lplpo': 'selected' if d_type == 'LPLPO' else '',
        'type_allocation': 'selected' if d_type == 'ALLOCATION' else '',
        'type_special': 'selected' if d_type == 'SPECIAL' else '',
    })


@login_required
def distribution_create(request):
    if request.method == 'POST':
        form = DistributionForm(request.POST)
        formset = DistributionItemFormSet(request.POST, prefix='items')

        if form.is_valid() and formset.is_valid():
            distribution = form.save(commit=False)
            distribution.created_by = request.user
            distribution.save()

            formset.instance = distribution
            formset.save()

            messages.success(request, f'Distribusi {distribution.document_number} berhasil dibuat.')
            return redirect('distribution:distribution_list')
    else:
        form = DistributionForm()
        formset = DistributionItemFormSet(prefix='items')

    return render(request, 'distribution/distribution_form.html', {
        'form': form,
        'formset': formset,
        'title': 'Buat Distribusi Baru',
    })


@login_required
def distribution_detail(request, pk):
    distribution = get_object_or_404(
        Distribution.objects.select_related('facility', 'created_by', 'verified_by', 'approved_by'),
        pk=pk,
    )
    items = distribution.items.select_related('item', 'item__satuan', 'stock')

    return render(request, 'distribution/distribution_detail.html', {
        'distribution': distribution,
        'items': items,
    })
