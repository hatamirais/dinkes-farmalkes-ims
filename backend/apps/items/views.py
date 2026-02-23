from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q

from .models import Item, Unit, Category, FundingSource, Location, Supplier, Facility
from .forms import ItemForm


@login_required
def item_list(request):
    queryset = Item.objects.select_related('satuan', 'kategori').filter(is_active=True)

    # Search
    search = request.GET.get('q', '').strip()
    if search:
        queryset = queryset.filter(
            Q(kode_barang__icontains=search) |
            Q(nama_barang__icontains=search) |
            Q(program_name__icontains=search)
        )

    # Filters
    kategori = request.GET.get('kategori')
    if kategori:
        queryset = queryset.filter(kategori_id=kategori)

    program = request.GET.get('program')
    if program == '1':
        queryset = queryset.filter(is_program_item=True)
    elif program == '0':
        queryset = queryset.filter(is_program_item=False)

    paginator = Paginator(queryset, 25)
    page = request.GET.get('page')
    items = paginator.get_page(page)

    # Build category list with selected state
    categories = []
    for cat in Category.objects.all():
        categories.append({
            'id': cat.id,
            'name': cat.name,
            'selected': 'selected' if kategori == str(cat.id) else '',
        })

    return render(request, 'items/item_list.html', {
        'items': items,
        'categories': categories,
        'search': search,
        'selected_kategori': kategori or '',
        'selected_program': program or '',
        'program_1_selected': 'selected' if program == '1' else '',
        'program_0_selected': 'selected' if program == '0' else '',
    })


@login_required
def item_create(request):
    if request.method == 'POST':
        form = ItemForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Barang berhasil ditambahkan.')
            return redirect('items:item_list')
    else:
        form = ItemForm()

    return render(request, 'items/item_form.html', {'form': form, 'title': 'Tambah Barang'})


@login_required
def item_update(request, pk):
    item = get_object_or_404(Item, pk=pk)
    if request.method == 'POST':
        form = ItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, 'Barang berhasil diperbarui.')
            return redirect('items:item_list')
    else:
        form = ItemForm(instance=item)

    return render(request, 'items/item_form.html', {'form': form, 'title': 'Edit Barang', 'item': item})


@login_required
def item_delete(request, pk):
    item = get_object_or_404(Item, pk=pk)
    if request.method == 'POST':
        item.is_active = False
        item.save()
        messages.success(request, f'Barang "{item.nama_barang}" berhasil dihapus.')
        return redirect('items:item_list')
    return render(request, 'items/item_confirm_delete.html', {'item': item})
