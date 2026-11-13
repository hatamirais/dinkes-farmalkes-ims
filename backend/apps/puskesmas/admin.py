from django.contrib import admin
from .inventory_models import (
    PuskesmasInventoryAccount, PuskesmasOpeningVerification,
    PuskesmasOpeningVerificationLine, PuskesmasInventoryPosting,
    PuskesmasInventoryLayer, PuskesmasInventoryBalance, PuskesmasInventoryMovement,
)
from .models import (
    PuskesmasConsumption,
    PuskesmasConsumptionEntry,
    PuskesmasRequest,
    PuskesmasRequestItem,
    PuskesmasSubunit,
)


class PuskesmasRequestItemInline(admin.TabularInline):
    model = PuskesmasRequestItem
    extra = 1
    readonly_fields = ["created_at"]


@admin.register(PuskesmasInventoryAccount, PuskesmasOpeningVerification,
                PuskesmasOpeningVerificationLine, PuskesmasInventoryPosting,
                PuskesmasInventoryLayer, PuskesmasInventoryBalance, PuskesmasInventoryMovement)
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
