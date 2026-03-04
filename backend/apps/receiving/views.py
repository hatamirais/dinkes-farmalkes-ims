from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from apps.core.decorators import role_required
from apps.items.models import Supplier, FundingSource
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
        'selected_status': status or '',
        'selected_type': r_type or '',
        'status_draft': 'selected' if status == 'DRAFT' else '',
        'status_submitted': 'selected' if status == 'SUBMITTED' else '',
        'status_verified': 'selected' if status == 'VERIFIED' else '',
        'type_procurement': 'selected' if r_type == 'PROCUREMENT' else '',
        'type_grant': 'selected' if r_type == 'GRANT' else '',
    })


@login_required
@role_required('ADMIN', 'GUDANG', 'KEPALA', 'ADMIN_UMUM')
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


# ── AJAX Quick-Create Views ────────────────────────────────


@login_required
@require_POST
def quick_create_supplier(request):
    """AJAX endpoint to create a new Supplier."""
    code = request.POST.get('code', '').strip()
    name = request.POST.get('name', '').strip()

    if not code or not name:
        return JsonResponse({'error': 'Kode dan Nama wajib diisi.'}, status=400)

    if Supplier.objects.filter(code=code).exists():
        return JsonResponse({'error': f'Supplier dengan kode "{code}" sudah ada.'}, status=400)

    supplier = Supplier.objects.create(
        code=code,
        name=name,
        address=request.POST.get('address', '').strip(),
        phone=request.POST.get('phone', '').strip(),
        email=request.POST.get('email', '').strip(),
        notes=request.POST.get('notes', '').strip(),
    )
    return JsonResponse({'id': supplier.pk, 'text': str(supplier)})


@login_required
@require_POST
def quick_create_funding_source(request):
    """AJAX endpoint to create a new FundingSource."""
    code = request.POST.get('code', '').strip()
    name = request.POST.get('name', '').strip()

    if not code or not name:
        return JsonResponse({'error': 'Kode dan Nama wajib diisi.'}, status=400)

    if FundingSource.objects.filter(code=code).exists():
        return JsonResponse({'error': f'Sumber dana dengan kode "{code}" sudah ada.'}, status=400)

    source = FundingSource.objects.create(
        code=code,
        name=name,
        description=request.POST.get('description', '').strip(),
    )
    return JsonResponse({'id': source.pk, 'text': str(source)})
