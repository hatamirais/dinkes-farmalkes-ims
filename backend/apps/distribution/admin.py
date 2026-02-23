from django.contrib import admin
from .models import Distribution, DistributionItem


class DistributionItemInline(admin.TabularInline):
    model = DistributionItem
    extra = 1
    fields = ('item', 'quantity_requested', 'quantity_approved', 'stock', 'notes')
    raw_id_fields = ('item', 'stock')


@admin.register(Distribution)
class DistributionAdmin(admin.ModelAdmin):
    list_display = (
        'document_number', 'distribution_type', 'request_date',
        'facility', 'status', 'created_by',
    )
    list_filter = ('distribution_type', 'status', 'facility')
    search_fields = ('document_number', 'facility__name', 'facility__code')
    date_hierarchy = 'request_date'
    inlines = [DistributionItemInline]
    raw_id_fields = ('facility', 'created_by', 'verified_by', 'approved_by')
    readonly_fields = ('verified_at', 'approved_at')
    list_per_page = 25
