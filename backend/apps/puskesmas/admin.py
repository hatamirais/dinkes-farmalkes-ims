from django.contrib import admin
from .expiry_models import PuskesmasExpiry, PuskesmasExpiryRevision, PuskesmasExpiryLine
from .inventory_models import (
    PuskesmasInventoryAccount, PuskesmasOpeningVerification,
    PuskesmasOpeningVerificationLine, PuskesmasInventoryPosting,
    PuskesmasInventoryLayer, PuskesmasInventoryBalance, PuskesmasInventoryMovement,
    PuskesmasConsumptionRevision, PuskesmasConsumptionAllocation,
    PuskesmasConsumptionAudit, PuskesmasLPLPOInventoryBinding,
)
from .models import (
    PuskesmasConsumption,
    PuskesmasConsumptionEntry,
    PuskesmasRequest,
    PuskesmasRequestItem,
    PuskesmasSubunit,
)
from .opname_models import (
    FacilityOpname, LPLPOOpnameLink, OpnameAction, OpnameActivation, OpnameAuthority,
    OpnameCaseNote, OpnameDecision, OpnameRevision,
)


class PuskesmasRequestItemInline(admin.TabularInline):
    model = PuskesmasRequestItem
    extra = 1
    readonly_fields = ["created_at"]


@admin.register(PuskesmasInventoryAccount, PuskesmasOpeningVerification,
                PuskesmasOpeningVerificationLine, PuskesmasInventoryPosting,
                PuskesmasInventoryLayer, PuskesmasInventoryBalance, PuskesmasInventoryMovement,
                PuskesmasConsumptionRevision, PuskesmasConsumptionAllocation,
                PuskesmasConsumptionAudit, PuskesmasLPLPOInventoryBinding,
                PuskesmasExpiry, PuskesmasExpiryRevision, PuskesmasExpiryLine)
class InventoryReadOnlyAdmin(admin.ModelAdmin):
    actions = None

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(
    [FacilityOpname, LPLPOOpnameLink, OpnameAction, OpnameActivation, OpnameCaseNote, OpnameDecision, OpnameRevision],
    InventoryReadOnlyAdmin,
)


@admin.register(OpnameAuthority)
class OpnameAuthorityAdmin(admin.ModelAdmin):
    actions = None
    list_display = ("facility", "user", "review_count", "approve_adjustment", "correct_receipt", "reopen_count")
    list_filter = ("review_count", "approve_adjustment", "correct_receipt", "reopen_count")
    search_fields = ("user__username", "facility__name")

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_readonly_fields(self, request, obj=None):
        return ("facility", "user") if obj else ()

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "facility":
            kwargs["queryset"] = db_field.remote_field.model.objects.filter(facility_type="PUSKESMAS", is_active=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        from .inventory import lock_facility, locked_actor
        locked_actor(obj.user)
        lock_facility(obj.facility_id)
        super().save_model(request, obj, form, change)

    def delete_model(self, request, obj):
        from .inventory import lock_facility, locked_actor
        locked_actor(obj.user)
        lock_facility(obj.facility_id)
        super().delete_model(request, obj)


class PuskesmasConsumptionEntryInline(admin.TabularInline):
    model = PuskesmasConsumptionEntry
    extra = 0


@admin.register(PuskesmasRequest)
class PuskesmasRequestAdmin(admin.ModelAdmin):
    list_display = [
        "document_number",
        "facility",
        "program",
        "status",
        "request_date",
        "created_by",
    ]
    list_filter = ["status", "facility", "program"]
    search_fields = ["document_number", "facility__name"]
    readonly_fields = ["document_number", "created_by", "approved_by", "approved_at", "distribution"]
    inlines = [PuskesmasRequestItemInline]


@admin.register(PuskesmasSubunit)
class PuskesmasSubunitAdmin(admin.ModelAdmin):
    list_display = ["name", "facility", "subunit_type", "sort_order", "is_active"]
    list_filter = ["facility", "subunit_type", "is_active"]
    search_fields = ["name", "facility__name"]


@admin.register(PuskesmasConsumption)
class PuskesmasConsumptionAdmin(admin.ModelAdmin):
    list_display = ["facility", "bulan", "tahun", "created_by", "updated_by"]
    list_filter = ["tahun", "bulan", "facility"]
    search_fields = ["facility__name"]
    readonly_fields = ["created_by", "updated_by"]
    inlines = [PuskesmasConsumptionEntryInline]
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
