from django.contrib import admin

from .models import (
    Allocation,
    AllocationFacility,
    AllocationItem,
    AllocationItemFacility,
    AllocationStaffAssignment,
)


class DraftAllocationInlineMixin:
    def _parent_is_draft(self, obj):
        return obj is None or obj.status == Allocation.Status.DRAFT

    def has_add_permission(self, request, obj=None):
        return super().has_add_permission(request, obj) and self._parent_is_draft(obj)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and self._parent_is_draft(obj)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and self._parent_is_draft(obj)


class AllocationFacilityInline(DraftAllocationInlineMixin, admin.TabularInline):
    model = AllocationFacility
    extra = 1
    raw_id_fields = ("facility",)


class AllocationItemFacilityInline(admin.TabularInline):
    model = AllocationItemFacility
    extra = 1
    raw_id_fields = ("facility",)

    def _parent_is_draft(self, obj):
        return obj is None or obj.allocation.status == Allocation.Status.DRAFT

    def has_add_permission(self, request, obj=None):
        return super().has_add_permission(request, obj) and self._parent_is_draft(obj)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and self._parent_is_draft(obj)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and self._parent_is_draft(obj)


class AllocationItemInline(DraftAllocationInlineMixin, admin.TabularInline):
    model = AllocationItem
    extra = 1
    raw_id_fields = ("item", "stock")


class AllocationStaffAssignmentInline(DraftAllocationInlineMixin, admin.TabularInline):
    model = AllocationStaffAssignment
    extra = 1
    raw_id_fields = ("user",)


@admin.register(Allocation)
class AllocationAdmin(admin.ModelAdmin):
    list_display = (
        "document_number",
        "title",
        "allocation_date",
        "status",
        "created_by",
    )
    list_filter = ("status", "allocation_date")
    search_fields = (
        "document_number",
        "title",
        "referensi",
        "notes",
        "created_by__username",
        "created_by__full_name",
    )
    date_hierarchy = "allocation_date"
    raw_id_fields = ("created_by",)
    readonly_fields = (
        "document_number",
        "status",
        "submitted_by",
        "submitted_at",
        "approved_by",
        "approved_at",
        "rejection_reason",
    )
    inlines = [
        AllocationStaffAssignmentInline,
        AllocationFacilityInline,
        AllocationItemInline,
    ]

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.status != Allocation.Status.DRAFT:
            return False
        return super().has_change_permission(request, obj)


@admin.register(AllocationItem)
class AllocationItemAdmin(admin.ModelAdmin):
    list_display = ("allocation", "item", "total_qty_available")
    raw_id_fields = ("item", "stock")
    readonly_fields = ("allocation",)
    inlines = [AllocationItemFacilityInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.allocation.status != Allocation.Status.DRAFT:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.allocation.status != Allocation.Status.DRAFT:
            return False
        return super().has_delete_permission(request, obj)
