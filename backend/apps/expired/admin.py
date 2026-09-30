from django.contrib import admin
from .models import Expired, ExpiredItem


class ExpiredItemInline(admin.TabularInline):
    model = ExpiredItem
    extra = 1
    autocomplete_fields = ['item', 'stock']

    def _parent_is_draft(self, obj):
        return obj is None or obj.status == Expired.Status.DRAFT

    def has_add_permission(self, request, obj=None):
        return super().has_add_permission(request, obj) and self._parent_is_draft(obj)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and self._parent_is_draft(obj)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and self._parent_is_draft(obj)


@admin.register(Expired)
class ExpiredAdmin(admin.ModelAdmin):
    list_display = ('document_number', 'report_date', 'status', 'created_by')
    list_filter = ('status', 'report_date')
    search_fields = ('document_number',)
    readonly_fields = (
        'document_number', 'status', 'created_at', 'updated_at',
        'verified_by', 'verified_at', 'disposed_by', 'disposed_at',
    )
    inlines = [ExpiredItemInline]
    autocomplete_fields = ['created_by']
    actions = None

    fieldsets = (
        ('Informasi Expired', {
            'fields': (
                'document_number',
                'report_date',
                'status'
            )
        }),
        ('Otorisasi & Catatan', {
            'fields': (
                'notes',
                'created_by',
                'verified_by',
                'verified_at',
                'disposed_by',
                'disposed_at',
            )
        }),
        ('Audit Trail', {
            'classes': ('collapse',),
            'fields': ('created_at', 'updated_at'),
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        if obj is not None and obj.document_number:
            readonly_fields.append('report_date')
        return tuple(readonly_fields)

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.status != Expired.Status.DRAFT:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return False
