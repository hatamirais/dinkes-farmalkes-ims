from django.contrib import admin
from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import ForeignKeyWidget

from .models import Stock, Transaction
from apps.items.models import Item, Location, FundingSource


# ── Resources ──────────────────────────────────────────────


class StockResource(resources.ModelResource):
    item = fields.Field(
        column_name='item_code',
        attribute='item',
        widget=ForeignKeyWidget(Item, field='kode_barang'),
    )
    location = fields.Field(
        column_name='location_code',
        attribute='location',
        widget=ForeignKeyWidget(Location, field='code'),
    )
    sumber_dana = fields.Field(
        column_name='sumber_dana_code',
        attribute='sumber_dana',
        widget=ForeignKeyWidget(FundingSource, field='code'),
    )

    class Meta:
        model = Stock
        fields = (
            'id', 'item', 'location', 'batch_lot', 'expiry_date',
            'quantity', 'reserved', 'unit_price', 'sumber_dana',
        )
        import_id_fields = ('item', 'location', 'batch_lot')
        skip_unchanged = True
        report_skipped = False


# ── Admin ──────────────────────────────────────────────────


@admin.register(Stock)
class StockAdmin(ImportExportModelAdmin):
    resource_classes = [StockResource]
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
    """Transactions are immutable — no import/export."""
    list_display = (
        'transaction_type', 'item', 'batch_lot', 'quantity',
        'reference_type', 'user', 'created_at',
    )
    list_filter = ('transaction_type', 'reference_type', 'location')
    search_fields = ('item__kode_barang', 'item__nama_barang', 'batch_lot', 'notes')
    date_hierarchy = 'created_at'
    list_per_page = 50

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
