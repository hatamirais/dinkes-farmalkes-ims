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


class ProcurementAmendmentLineInline(admin.TabularInline):
    model = ProcurementAmendmentLine
    extra = 0


@admin.register(ProcurementContract)
class ProcurementContractAdmin(admin.ModelAdmin):
    list_display = (
        "document_number",
        "contract_date",
        "supplier",
        "sumber_dana",
        "status",
    )
    list_filter = ("status", "contract_date")
    search_fields = ("document_number", "supplier__name")
    inlines = [ProcurementContractLineInline]


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
