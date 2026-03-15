from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import ModuleAccess, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "full_name", "email", "role", "is_active")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("username", "full_name", "email")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Additional Info", {"fields": ("role", "full_name")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Additional Info", {"fields": ("role", "full_name")}),
    )


@admin.register(ModuleAccess)
class ModuleAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "module", "scope", "updated_at")
    list_filter = ("module", "scope")
    search_fields = ("user__username", "user__full_name", "user__email")
