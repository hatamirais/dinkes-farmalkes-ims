from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .access import ensure_default_module_access
from .models import ModuleAccess, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "full_name", "email", "role", "is_staff", "is_active")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("username", "full_name", "email")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Additional Info", {"fields": ("role", "full_name")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Additional Info", {"fields": ("role", "full_name")}),
    )

    def save_model(self, request, obj, form, change):
        """
        After saving via Admin panel, seed ModuleAccess defaults so the user
        can access Dashboard features gated by ModuleAccess scopes.
        The is_staff sync is handled automatically by the post_save signal.
        """
        super().save_model(request, obj, form, change)
        ensure_default_module_access(obj)


@admin.register(ModuleAccess)
class ModuleAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "module", "scope", "updated_at")
    list_filter = ("module", "scope")
    search_fields = ("user__username", "user__full_name", "user__email")
