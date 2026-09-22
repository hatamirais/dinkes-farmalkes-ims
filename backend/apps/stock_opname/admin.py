from django.contrib import admin
from .models import StockOpname, StockOpnameItem


class StockOpnameItemInline(admin.TabularInline):
    model = StockOpnameItem
    extra = 0
    readonly_fields = (
        'stock',
        'system_quantity',
        'completion_stock_quantity',
        'actual_quantity',
        'notes',
    )


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
    workflow_readonly_fields = (
        'document_number',
        'status',
        'created_by',
        'completed_by',
        'completed_at',
    )

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

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        readonly_fields.extend(self.workflow_readonly_fields)
        return tuple(dict.fromkeys(readonly_fields))

    def save_model(self, request, obj, form, change):
        if not change:
            obj.status = StockOpname.Status.DRAFT
            obj.created_by = request.user
            obj.completed_by = None
            obj.completed_at = None
        super().save_model(request, obj, form, change)

