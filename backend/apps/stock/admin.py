from django.contrib import admin
from django.core.exceptions import ValidationError
from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import ForeignKeyWidget, DateWidget

from apps.core.admin_mixins import ImportGuideMixin
from .models import Stock, Transaction, StockTransfer, StockTransferItem
from apps.items.models import Item, Location, FundingSource


# ── Resources ──────────────────────────────────────────────


class StockResource(resources.ModelResource):
    item = fields.Field(
        column_name="item_code",
        attribute="item",
        widget=ForeignKeyWidget(Item, field="kode_barang"),
    )

    @staticmethod
    def _row_value(row, key):
        value = row.get(key, "")
        if value is None:
            return ""
        return str(value).strip()

    def before_import_row(self, row, **kwargs):
        item_code = self._row_value(row, "item_code")
        expiry_value = self._row_value(row, "expiry_date")
        if not item_code or expiry_value:
            return super().before_import_row(row, **kwargs)

        item = Item.objects.filter(kode_barang=item_code).only("requires_expiry_date").first()
        if item and item.requires_expiry_date:
            raise ValidationError(
                {"expiry_date": "Tanggal kedaluwarsa wajib diisi untuk item ini."}
            )

        return super().before_import_row(row, **kwargs)
    location = fields.Field(
        column_name="location_code",
        attribute="location",
        widget=ForeignKeyWidget(Location, field="code"),
    )
    sumber_dana = fields.Field(
        column_name="sumber_dana_code",
        attribute="sumber_dana",
        widget=ForeignKeyWidget(FundingSource, field="code"),
    )
    expiry_date = fields.Field(
        column_name="expiry_date",
        attribute="expiry_date",
        widget=DateWidget(format="%d/%m/%Y"),
    )

    class Meta:
        model = Stock
        fields = (
            "id",
            "item",
            "location",
            "batch_lot",
            "expiry_date",
            "quantity",
            "reserved",
            "unit_price",
            "sumber_dana",
        )
        import_id_fields = ("item", "location", "batch_lot")
        skip_unchanged = True
        report_skipped = False


# ── Admin ──────────────────────────────────────────────────


@admin.register(Stock)
class StockAdmin(ImportGuideMixin, ImportExportModelAdmin):
    resource_classes = [StockResource]
    list_display = (
        "item",
        "location",
        "batch_lot",
        "expiry_date",
        "quantity",
        "reserved",
        "unit_price",
        "sumber_dana",
    )
    list_filter = ("location", "sumber_dana", "item__kategori")
    search_fields = ("item__kode_barang", "item__nama_barang", "batch_lot")
    raw_id_fields = ("item", "receiving_ref")
    list_per_page = 50
    date_hierarchy = "expiry_date"
    import_guide = {
        "title": "Stok Barang",
        "description": "Identifier unik: item_code + location_code + batch_lot",
        "columns": [
            {
                "name": "item_code",
                "required": True,
                "description": "Kode barang (kode_barang) dari tabel Items",
            },
            {
                "name": "location_code",
                "required": True,
                "description": "Kode lokasi dari tabel Locations",
            },
            {"name": "batch_lot", "required": True, "description": "Nomor batch/lot"},
            {
                "name": "expiry_date",
                "required": False,
                "description": "Format: DD/MM/YYYY. Kosongkan hanya untuk item tanpa kedaluwarsa.",
            },
            {
                "name": "quantity",
                "required": False,
                "description": "Jumlah stok (default: 0)",
            },
            {
                "name": "reserved",
                "required": False,
                "description": "Stok dialokasikan (default: 0)",
            },
            {
                "name": "unit_price",
                "required": False,
                "description": "Harga satuan (default: 0)",
            },
            {
                "name": "sumber_dana_code",
                "required": True,
                "description": "Kode sumber dana dari tabel Funding Sources",
            },
        ],
    }


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    """Transactions are immutable — no import/export."""

    list_display = (
        "transaction_type",
        "item",
        "batch_lot",
        "quantity",
        "reference_type",
        "user",
        "created_at",
    )
    list_filter = ("transaction_type", "reference_type", "location")
    search_fields = ("item__kode_barang", "item__nama_barang", "batch_lot", "notes")
    date_hierarchy = "created_at"
    list_per_page = 50

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class StockTransferItemInline(admin.TabularInline):
    model = StockTransferItem
    extra = 0
    autocomplete_fields = ("stock", "item")


@admin.register(StockTransfer)
class StockTransferAdmin(admin.ModelAdmin):
    list_display = (
        "document_number",
        "transfer_date",
        "source_location",
        "destination_location",
        "status",
        "created_by",
    )
    list_filter = ("status", "source_location", "destination_location")
    search_fields = (
        "document_number",
        "source_location__name",
        "destination_location__name",
    )
    inlines = [StockTransferItemInline]
