from django.contrib import admin
from .models import Receiving, ReceivingItem, ReceivingDocument


class ReceivingItemInline(admin.TabularInline):
    model = ReceivingItem
    extra = 1
    fields = ('item', 'quantity', 'batch_lot', 'expiry_date', 'unit_price')
    raw_id_fields = ('item',)


class ReceivingDocumentInline(admin.TabularInline):
    model = ReceivingDocument
    extra = 0
    fields = ('file', 'file_name', 'file_type')


@admin.register(Receiving)
class ReceivingAdmin(admin.ModelAdmin):
    list_display = (
        'document_number', 'receiving_type', 'receiving_date',
        'supplier', 'sumber_dana', 'status', 'created_by',
    )
    list_filter = ('receiving_type', 'status', 'sumber_dana')
    search_fields = ('document_number', 'supplier__name')
    date_hierarchy = 'receiving_date'
    inlines = [ReceivingItemInline, ReceivingDocumentInline]
    raw_id_fields = ('supplier', 'created_by', 'verified_by')
    readonly_fields = ('verified_at',)
    list_per_page = 25
