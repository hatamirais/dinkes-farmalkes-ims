from django.contrib import admin
from .models import Distribution, DistributionItem


class DistributionItemInline(admin.TabularInline):
    model = DistributionItem
    extra = 1
    fields = ('item', 'quantity_requested', 'quantity_approved', 'stock', 'notes')
    raw_id_fields = ('item', 'stock')

    def _parent_is_draft(self, obj):
        return obj is None or obj.status == Distribution.Status.DRAFT

    def has_add_permission(self, request, obj=None):
        return super().has_add_permission(request, obj) and self._parent_is_draft(obj)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and self._parent_is_draft(obj)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and self._parent_is_draft(obj)


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
    raw_id_fields = ('facility', 'created_by')
    readonly_fields = (
        'document_number',
        'status',
        'verified_by',
        'verified_at',
        'approved_by',
        'approved_at',
        'distributed_date',
    )
    list_per_page = 25

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        if obj is not None and obj.document_number:
            readonly_fields.append('request_date')
        return tuple(readonly_fields)

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.status != Distribution.Status.DRAFT:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        # Distribution deletion must use the application workflow so status,
        # assignment, reservation, and document-number safeguards all run.
        return False
