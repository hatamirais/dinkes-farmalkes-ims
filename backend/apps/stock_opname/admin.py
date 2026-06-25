from django.contrib import admin
from .models import StockOpname, StockOpnameItem


class StockOpnameItemInline(admin.TabularInline):
    model = StockOpnameItem
    extra = 0
    readonly_fields = ('stock', 'system_quantity', 'actual_quantity', 'notes')


@admin.register(StockOpname)
class StockOpnameAdmin(admin.ModelAdmin):
    list_display = (
        'document_number', 'period_type', 'period_start', 'period_end',
        'status', 'created_by', 'get_assigned_to', 'created_at',
    )
    list_filter = ('status', 'period_type', 'categories')
    search_fields = ('document_number',)
    filter_horizontal = ('categories', 'assigned_to')
    inlines = [StockOpnameItemInline]
    date_hierarchy = 'created_at'
    list_per_page = 25

    @admin.display(description='Ditugaskan Kepada')
    def get_assigned_to(self, obj):
        return ', '.join(
            u.full_name or u.username for u in obj.assigned_to.all()
        ) or '-'

    # F15: pre-fetch M2M and FK so get_assigned_to does not fire N+1 queries.
    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related('created_by')
            .prefetch_related('assigned_to')
        )

