from django.contrib import admin

from .models import (
    ProcurementAmendment,
    ProcurementAmendmentLine,
    ProcurementContract,
    ProcurementContractLine,
)


class ProcurementContractLineInline(admin.TabularInline):
    model = ProcurementContractLine
    extra = 0

    def has_add_permission(self, request, obj=None):
        return super().has_add_permission(request, obj) and (
            obj is None or obj.status == ProcurementContract.Status.DRAFT
        )

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (
            obj is None or obj.status == ProcurementContract.Status.DRAFT
        )

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (
            obj is None or obj.status == ProcurementContract.Status.DRAFT
        )


class ProcurementAmendmentLineInline(admin.TabularInline):
    model = ProcurementAmendmentLine
    extra = 0

    def has_add_permission(self, request, obj=None):
        return super().has_add_permission(request, obj) and (
            obj is None or obj.status == ProcurementAmendment.Status.DRAFT
        )

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (
            obj is None or obj.status == ProcurementAmendment.Status.DRAFT
        )

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (
            obj is None or obj.status == ProcurementAmendment.Status.DRAFT
        )


@admin.register(ProcurementContract)
class ProcurementContractAdmin(admin.ModelAdmin):
    list_display = (
        "document_number",
        "external_document_number",
        "contract_date",
        "supplier",
        "sumber_dana",
        "status",
    )
    list_filter = ("status", "contract_date")
    search_fields = (
        "document_number",
        "external_document_number",
        "supplier__name",
    )
    inlines = [ProcurementContractLineInline]
    readonly_fields = (
        "document_number",
        "status",
        "submitted_by",
        "submitted_at",
        "approved_by",
        "approved_at",
        "closed_by",
        "closed_at",
        "cancelled_by",
        "cancelled_at",
        "cancel_reason",
    )


@admin.register(ProcurementAmendment)
class ProcurementAmendmentAdmin(admin.ModelAdmin):
    list_display = (
        "document_number",
        "contract",
        "amendment_date",
        "status",
    )
    list_filter = ("status", "amendment_date")
    search_fields = ("document_number", "contract__document_number")
    inlines = [ProcurementAmendmentLineInline]
    readonly_fields = (
        "document_number",
        "status",
        "submitted_by",
        "submitted_at",
        "approved_by",
        "approved_at",
    )
