from django.contrib import admin
from .models import LPLPO, LPLPOItem


class LPLPOItemInline(admin.TabularInline):
    model = LPLPOItem
    extra = 0
    readonly_fields = (
        "persediaan",
        "stock_keseluruhan",
        "stock_optimum",
        "jumlah_kebutuhan",
    )


@admin.register(LPLPO)
class LPLPOAdmin(admin.ModelAdmin):
    list_display = (
        "document_number",
        "facility",
        "bulan",
        "tahun",
        "status",
        "created_by",
    )
    list_filter = ("status", "tahun", "bulan")
    search_fields = ("document_number", "facility__name")
    readonly_fields = (
        "document_number",
        "created_by",
        "verified_by",
        "verified_at",
        "reviewed_by",
        "reviewed_at",
        "approved_by",
        "approved_at",
        "submitted_at",
        "distribution",
    )
    inlines = [LPLPOItemInline]
