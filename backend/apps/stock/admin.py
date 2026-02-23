from django.contrib import admin
from .models import Stock, Transaction


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = (
        'item', 'location', 'batch_lot', 'expiry_date',
        'quantity', 'reserved', 'unit_price', 'sumber_dana',
    )
    list_filter = ('location', 'sumber_dana', 'item__kategori')
    search_fields = ('item__kode_barang', 'item__nama_barang', 'batch_lot')
    raw_id_fields = ('item', 'receiving_ref')
    list_per_page = 50
    date_hierarchy = 'expiry_date'


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        'transaction_type', 'item', 'batch_lot', 'quantity',
        'reference_type', 'user', 'created_at',
    )
    list_filter = ('transaction_type', 'reference_type', 'location')
    search_fields = ('item__kode_barang', 'item__nama_barang', 'batch_lot', 'notes')
    date_hierarchy = 'created_at'
    list_per_page = 50

    def has_change_permission(self, request, obj=None):
        return False  # Transactions are immutable

    def has_delete_permission(self, request, obj=None):
        return False  # Transactions are immutable
