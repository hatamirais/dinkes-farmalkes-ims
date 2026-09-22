from django.contrib import admin
from .models import Recall, RecallItem


class RecallItemInline(admin.TabularInline):
    model = RecallItem
    extra = 1
    autocomplete_fields = ['item', 'stock']


@admin.register(Recall)
class RecallAdmin(admin.ModelAdmin):
    list_display = ('document_number', 'recall_date', 'supplier', 'status', 'created_by')
    list_filter = ('status', 'recall_date', 'supplier')
    search_fields = ('document_number', 'supplier__name')
    readonly_fields = ('document_number', 'created_at', 'updated_at', 'verified_at', 'completed_at')
    inlines = [RecallItemInline]
    autocomplete_fields = ['supplier', 'created_by', 'verified_by']
    actions = ['mark_completed']

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

    @admin.action(description='Tandai Selesai (hanya status Terverifikasi)')
    def mark_completed(self, request, queryset):
        verified_qs = queryset.filter(status=Recall.Status.VERIFIED)
        skipped = queryset.count() - verified_qs.count()
        updated = verified_qs.update(status=Recall.Status.COMPLETED)

        if updated:
            self.message_user(request, f'{updated} dokumen recall ditandai selesai.')
        if skipped:
            self.message_user(
                request,
                f'{skipped} dokumen dilewati karena bukan status Terverifikasi.',
                level='warning',
            )
