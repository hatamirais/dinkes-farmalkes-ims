from django.contrib import admin
from .models import Recall, RecallItem


class RecallItemInline(admin.TabularInline):
    model = RecallItem
    extra = 1
    autocomplete_fields = ['item', 'stock']

    def _parent_is_draft(self, obj):
        return obj is None or obj.status == Recall.Status.DRAFT

    def has_add_permission(self, request, obj=None):
        return super().has_add_permission(request, obj) and self._parent_is_draft(obj)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and self._parent_is_draft(obj)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and self._parent_is_draft(obj)


@admin.register(Recall)
class RecallAdmin(admin.ModelAdmin):
    list_display = ('document_number', 'recall_date', 'supplier', 'status', 'created_by')
    list_filter = ('status', 'recall_date', 'supplier')
    search_fields = ('document_number', 'supplier__name')
    readonly_fields = (
        'document_number', 'status', 'created_at', 'updated_at',
        'verified_by', 'verified_at', 'completed_by', 'completed_at',
    )
    inlines = [RecallItemInline]
    autocomplete_fields = ['supplier', 'created_by']
    actions = []

    fieldsets = (
        ('Informasi Recall', {
            'fields': (
                'document_number',
                'recall_date',
                'supplier',
                'status'
            )
        }),
        ('Otorisasi & Catatan', {
            'fields': (
                'notes',
                'created_by',
                'verified_by',
                'verified_at',
                'completed_by',
                'completed_at',
            )
        }),
        ('Audit Trail', {
            'classes': ('collapse',),
            'fields': ('created_at', 'updated_at'),
        }),
    )

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.status != Recall.Status.DRAFT:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status != Recall.Status.DRAFT:
            return False
        return super().has_delete_permission(request, obj)
