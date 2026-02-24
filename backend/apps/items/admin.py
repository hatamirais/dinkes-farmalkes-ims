from django.contrib import admin
from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import ForeignKeyWidget

from .models import Unit, Category, FundingSource, Location, Supplier, Facility, Item


# ── Resources ──────────────────────────────────────────────


class UnitResource(resources.ModelResource):
    class Meta:
        model = Unit
        fields = ('id', 'code', 'name', 'description')
        import_id_fields = ('code',)
        skip_unchanged = True
        report_skipped = False


class CategoryResource(resources.ModelResource):
    class Meta:
        model = Category
        fields = ('id', 'code', 'name', 'sort_order')
        import_id_fields = ('code',)
        skip_unchanged = True
        report_skipped = False


class FundingSourceResource(resources.ModelResource):
    class Meta:
        model = FundingSource
        fields = ('id', 'code', 'name', 'description', 'is_active')
        import_id_fields = ('code',)
        skip_unchanged = True
        report_skipped = False


class LocationResource(resources.ModelResource):
    class Meta:
        model = Location
        fields = ('id', 'code', 'name', 'description', 'is_active')
        import_id_fields = ('code',)
        skip_unchanged = True
        report_skipped = False


class SupplierResource(resources.ModelResource):
    class Meta:
        model = Supplier
        fields = ('id', 'code', 'name', 'address', 'phone', 'email', 'notes', 'is_active')
        import_id_fields = ('code',)
        skip_unchanged = True
        report_skipped = False


class FacilityResource(resources.ModelResource):
    class Meta:
        model = Facility
        fields = ('id', 'code', 'name', 'address', 'phone', 'facility_type', 'is_active')
        import_id_fields = ('code',)
        skip_unchanged = True
        report_skipped = False


class ItemResource(resources.ModelResource):
    satuan = fields.Field(
        column_name='satuan',
        attribute='satuan',
        widget=ForeignKeyWidget(Unit, field='code'),
    )
    kategori = fields.Field(
        column_name='kategori',
        attribute='kategori',
        widget=ForeignKeyWidget(Category, field='code'),
    )

    class Meta:
        model = Item
        fields = (
            'id', 'kode_barang', 'nama_barang', 'satuan', 'kategori',
            'is_program_item', 'program_name', 'minimum_stock',
            'description', 'is_active',
        )
        import_id_fields = ('kode_barang',)
        skip_unchanged = True
        report_skipped = False


# ── Admin ──────────────────────────────────────────────────


@admin.register(Unit)
class UnitAdmin(ImportExportModelAdmin):
    resource_classes = [UnitResource]
    list_display = ('code', 'name', 'description')
    search_fields = ('code', 'name')


@admin.register(Category)
class CategoryAdmin(ImportExportModelAdmin):
    resource_classes = [CategoryResource]
    list_display = ('code', 'name', 'sort_order')
    search_fields = ('code', 'name')
    list_editable = ('sort_order',)


@admin.register(FundingSource)
class FundingSourceAdmin(ImportExportModelAdmin):
    resource_classes = [FundingSourceResource]
    list_display = ('code', 'name', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('code', 'name')


@admin.register(Location)
class LocationAdmin(ImportExportModelAdmin):
    resource_classes = [LocationResource]
    list_display = ('code', 'name', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('code', 'name')


@admin.register(Supplier)
class SupplierAdmin(ImportExportModelAdmin):
    resource_classes = [SupplierResource]
    list_display = ('code', 'name', 'phone', 'email', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('code', 'name', 'email')


@admin.register(Facility)
class FacilityAdmin(ImportExportModelAdmin):
    resource_classes = [FacilityResource]
    list_display = ('code', 'name', 'facility_type', 'phone', 'is_active')
    list_filter = ('facility_type', 'is_active')
    search_fields = ('code', 'name')


@admin.register(Item)
class ItemAdmin(ImportExportModelAdmin):
    resource_classes = [ItemResource]
    list_display = (
        'kode_barang', 'nama_barang', 'satuan', 'kategori',
        'is_program_item', 'program_name', 'minimum_stock', 'is_active',
    )
    list_filter = ('kategori', 'is_program_item', 'is_active', 'satuan')
    search_fields = ('kode_barang', 'nama_barang', 'program_name')
    list_per_page = 50
