from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.decorators import perm_required
from apps.stock.models import Stock, Transaction

from .forms import ExpiredForm, ExpiredItemFormSet
from .models import Expired


@login_required
def expired_list(request):
    queryset = Expired.objects.select_related('created_by').order_by('-report_date')

    search = request.GET.get('q', '').strip()
    if search:
        queryset = queryset.filter(document_number__icontains=search)

    status = request.GET.get('status')
    if status:
        queryset = queryset.filter(status=status)

    paginator = Paginator(queryset, 25)
    items = paginator.get_page(request.GET.get('page'))

    return render(request, 'expired/expired_list.html', {
        'expired_items': items,
        'search': search,
        'selected_status': status or '',
        'status_draft': 'selected' if status == Expired.Status.DRAFT else '',
        'status_submitted': 'selected' if status == Expired.Status.SUBMITTED else '',
        'status_verified': 'selected' if status == Expired.Status.VERIFIED else '',
        'status_disposed': 'selected' if status == Expired.Status.DISPOSED else '',
    })


@login_required
@perm_required('expired.add_expired')
def expired_create(request):
    if request.method == 'POST':
        form = ExpiredForm(request.POST)
        formset = ExpiredItemFormSet(request.POST, prefix='items')

        if form.is_valid() and formset.is_valid():
            expired_doc = form.save(commit=False)
            expired_doc.created_by = request.user
            expired_doc.status = Expired.Status.DRAFT
            expired_doc.save()

            formset.instance = expired_doc
            formset.save()

            messages.success(request, f'Dokumen expired {expired_doc.document_number} berhasil dibuat.')
            return redirect('expired:expired_detail', pk=expired_doc.pk)
    else:
        form = ExpiredForm()
        formset = ExpiredItemFormSet(prefix='items')

    return render(request, 'expired/expired_form.html', {
        'form': form,
        'formset': formset,
        'title': 'Buat Dokumen Expired',
        'is_edit': False,
    })


@login_required
@perm_required('expired.change_expired')
def expired_edit(request, pk):
    expired_doc = get_object_or_404(Expired, pk=pk)
    if expired_doc.status not in (Expired.Status.DRAFT, Expired.Status.SUBMITTED):
        messages.error(request, 'Hanya dokumen Draft/Diajukan yang dapat diubah.')
        return redirect('expired:expired_detail', pk=expired_doc.pk)

    if request.method == 'POST':
        form = ExpiredForm(request.POST, instance=expired_doc)
        formset = ExpiredItemFormSet(request.POST, instance=expired_doc, prefix='items')

        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, f'Dokumen {expired_doc.document_number} berhasil diperbarui.')
            return redirect('expired:expired_detail', pk=expired_doc.pk)
    else:
        form = ExpiredForm(instance=expired_doc)
        formset = ExpiredItemFormSet(instance=expired_doc, prefix='items')

    return render(request, 'expired/expired_form.html', {
        'form': form,
        'formset': formset,
        'title': f'Edit Dokumen {expired_doc.document_number}',
        'is_edit': True,
        'expired_doc': expired_doc,
    })


@login_required
def expired_detail(request, pk):
    expired_doc = get_object_or_404(
        Expired.objects.select_related('created_by', 'verified_by', 'disposed_by'),
        pk=pk,
    )
    items = expired_doc.items.select_related(
        'item',
        'item__satuan',
        'stock',
        'stock__location',
        'stock__sumber_dana',
    )

    return render(request, 'expired/expired_detail.html', {
        'expired_doc': expired_doc,
        'items': items,
    })


@login_required
@perm_required('expired.change_expired')
def expired_submit(request, pk):
    expired_doc = get_object_or_404(Expired, pk=pk)
    if request.method != 'POST':
        return redirect('expired:expired_detail', pk=pk)

    if expired_doc.status != Expired.Status.DRAFT:
        messages.error(request, 'Hanya dokumen Draft yang dapat diajukan.')
        return redirect('expired:expired_detail', pk=pk)

    if not expired_doc.items.exists():
        messages.error(request, 'Tambahkan minimal 1 item sebelum mengajukan dokumen.')
        return redirect('expired:expired_detail', pk=pk)

    expired_doc.status = Expired.Status.SUBMITTED
    expired_doc.save(update_fields=['status', 'updated_at'])
    messages.success(request, f'Dokumen {expired_doc.document_number} berhasil diajukan.')
    return redirect('expired:expired_detail', pk=pk)


@login_required
@perm_required('expired.change_expired')
def expired_verify(request, pk):
    expired_doc = get_object_or_404(Expired, pk=pk)
    if request.method != 'POST':
        return redirect('expired:expired_detail', pk=pk)

    if expired_doc.status != Expired.Status.SUBMITTED:
        messages.error(request, 'Hanya dokumen berstatus Diajukan yang dapat diverifikasi.')
        return redirect('expired:expired_detail', pk=pk)

    expired_items = list(expired_doc.items.select_related('item', 'stock'))
    if not expired_items:
        messages.error(request, 'Dokumen tidak memiliki item untuk diverifikasi.')
        return redirect('expired:expired_detail', pk=pk)

    try:
        with transaction.atomic():
            for expired_item in expired_items:
                stock = Stock.objects.select_for_update().get(pk=expired_item.stock_id)

                if stock.item_id != expired_item.item_id:
                    raise ValueError(f'Batch stok tidak sesuai untuk item {expired_item.item.nama_barang}.')

                if expired_item.quantity > stock.available_quantity:
                    raise ValueError(
                        f'Stok tidak cukup untuk {expired_item.item.nama_barang}. '
                        f'Tersedia {stock.available_quantity}, diminta {expired_item.quantity}.'
                    )

                stock.quantity = stock.quantity - expired_item.quantity
                stock.save(update_fields=['quantity', 'updated_at'])

                Transaction.objects.create(
                    transaction_type=Transaction.TransactionType.OUT,
                    item=expired_item.item,
                    location=stock.location,
                    batch_lot=stock.batch_lot,
                    quantity=expired_item.quantity,
                    unit_price=stock.unit_price,
                    sumber_dana=stock.sumber_dana,
                    reference_type=Transaction.ReferenceType.EXPIRED,
                    reference_id=expired_doc.id,
                    user=request.user,
                    notes=f'Expired {expired_doc.document_number}: {expired_item.notes}'.strip(),
                )

            expired_doc.status = Expired.Status.VERIFIED
            expired_doc.verified_by = request.user
            expired_doc.verified_at = timezone.now()
            expired_doc.save(update_fields=['status', 'verified_by', 'verified_at', 'updated_at'])

    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('expired:expired_detail', pk=pk)

    messages.success(request, f'Dokumen {expired_doc.document_number} berhasil diverifikasi dan stok diperbarui.')
    return redirect('expired:expired_detail', pk=pk)


@login_required
@perm_required('expired.change_expired')
def expired_dispose(request, pk):
    expired_doc = get_object_or_404(Expired, pk=pk)
    if request.method != 'POST':
        return redirect('expired:expired_detail', pk=pk)

    if expired_doc.status != Expired.Status.VERIFIED:
        messages.error(request, 'Hanya dokumen terverifikasi yang dapat ditandai dimusnahkan.')
        return redirect('expired:expired_detail', pk=pk)

    expired_doc.status = Expired.Status.DISPOSED
    expired_doc.disposed_by = request.user
    expired_doc.disposed_at = timezone.now()
    expired_doc.save(update_fields=['status', 'disposed_by', 'disposed_at', 'updated_at'])
    messages.success(request, f'Dokumen {expired_doc.document_number} ditandai dimusnahkan.')
    return redirect('expired:expired_detail', pk=pk)


@login_required
@perm_required('expired.delete_expired')
def expired_delete(request, pk):
    expired_doc = get_object_or_404(Expired, pk=pk)
    if request.method != 'POST':
        return redirect('expired:expired_detail', pk=pk)

    if expired_doc.status != Expired.Status.DRAFT:
        messages.error(request, 'Hanya dokumen Draft yang dapat dihapus.')
        return redirect('expired:expired_detail', pk=pk)

    doc_number = expired_doc.document_number
    expired_doc.delete()
    messages.success(request, f'Dokumen {doc_number} berhasil dihapus.')
    return redirect('expired:expired_list')
