from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q

from .models import Receiving, ReceivingItem
from .forms import ReceivingForm, ReceivingItemFormSet


@login_required
def receiving_list(request):
    queryset = (
        Receiving.objects.select_related('supplier', 'sumber_dana', 'created_by')
        .order_by('-receiving_date')
    )

    search = request.GET.get('q', '').strip()
    if search:
        queryset = queryset.filter(
            Q(document_number__icontains=search) |
            Q(supplier__name__icontains=search)
        )

    status = request.GET.get('status')
    if status:
        queryset = queryset.filter(status=status)

    r_type = request.GET.get('type')
    if r_type:
        queryset = queryset.filter(receiving_type=r_type)

    paginator = Paginator(queryset, 25)
    receivings = paginator.get_page(request.GET.get('page'))

    return render(request, 'receiving/receiving_list.html', {
        'receivings': receivings,
        'search': search,
        'selected_status': status,
        'selected_type': r_type,
    })


@login_required
def receiving_create(request):
    if request.method == 'POST':
        form = ReceivingForm(request.POST)
        formset = ReceivingItemFormSet(request.POST, prefix='items')

        if form.is_valid() and formset.is_valid():
            receiving = form.save(commit=False)
            receiving.created_by = request.user
            receiving.save()

            formset.instance = receiving
            formset.save()

            messages.success(request, f'Penerimaan {receiving.document_number} berhasil dibuat.')
            return redirect('receiving:receiving_list')
    else:
        form = ReceivingForm()
        formset = ReceivingItemFormSet(prefix='items')

    return render(request, 'receiving/receiving_form.html', {
        'form': form,
        'formset': formset,
        'title': 'Buat Penerimaan Baru',
    })


@login_required
def receiving_detail(request, pk):
    receiving = get_object_or_404(
        Receiving.objects.select_related('supplier', 'sumber_dana', 'created_by', 'verified_by'),
        pk=pk,
    )
    items = receiving.items.select_related('item', 'item__satuan')

    return render(request, 'receiving/receiving_detail.html', {
        'receiving': receiving,
        'items': items,
    })
