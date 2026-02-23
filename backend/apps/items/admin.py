from django.contrib import admin
from .models import Unit, Category, FundingSource, Location, Supplier, Facility, Item


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'description')
    search_fields = ('code', 'name')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'is_controlled', 'sort_order')
    list_filter = ('is_controlled',)
    search_fields = ('code', 'name')
    list_editable = ('sort_order',)


@admin.register(FundingSource)
class FundingSourceAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('code', 'name')


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('code', 'name')


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'phone', 'email', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('code', 'name', 'email')


@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'facility_type', 'phone', 'is_active')
    list_filter = ('facility_type', 'is_active')
    search_fields = ('code', 'name')


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = (
        'kode_barang', 'nama_barang', 'satuan', 'kategori',
        'is_program_item', 'program_name', 'minimum_stock', 'is_active',
    )
    list_filter = ('kategori', 'is_program_item', 'is_active', 'satuan')
    search_fields = ('kode_barang', 'nama_barang', 'program_name')
    list_per_page = 50
