from django.contrib import admin
from django.core.exceptions import ValidationError

from apps.puskesmas.opname_lplpo import is_gated
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

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (
            obj is None or not is_gated(obj.facility_id, obj.tahun, obj.bulan)
        )

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (
            obj is None or not is_gated(obj.facility_id, obj.tahun, obj.bulan)
        )

    def get_form(self, request, obj=None, **kwargs):
        base_form = super().get_form(request, obj, **kwargs)

        class LPLPOAdminForm(base_form):
            def clean(self):
                cleaned = super().clean()
                facility = cleaned.get("facility")
                year = cleaned.get("tahun")
                month = cleaned.get("bulan")
                if facility and year and month and 1000 <= year <= 9999 and 1 <= month <= 12:
                    from apps.puskesmas.inventory import lock_facility, locked_actor
                    # Django Admin wraps POST change forms in atomic().
                    locked_actor(request.user)
                    if facility.facility_type == "PUSKESMAS" and facility.is_active:
                        lock_facility(facility.pk)
                    if is_gated(facility.pk, year, month):
                        raise ValidationError("Gunakan alur LPLPO untuk bulan Stock Opname.")
                return cleaned

        return LPLPOAdminForm
