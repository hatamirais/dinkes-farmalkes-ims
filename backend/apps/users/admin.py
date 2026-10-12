from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.core.exceptions import PermissionDenied

from .access import ensure_default_module_access
from .forms import UI_ROLE_CHOICES
from .models import AuthorityDelegation, AuthorityExercise, ModuleAccess, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "username",
        "full_name",
        "nip",
        "email",
        "role",
        "is_staff",
        "is_active",
    )
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("username", "full_name", "nip", "email")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Additional Info", {"fields": ("role", "full_name", "nip")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Additional Info", {"fields": ("role", "full_name", "nip")}),
    )

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # Restrict role choices unless editing an existing ADMIN user
        if "role" in form.base_fields:
            if not (obj and obj.pk and obj.role == User.Role.ADMIN):
                form.base_fields["role"].choices = UI_ROLE_CHOICES
        return form

    def save_model(self, request, obj, form, change):
        """
        After saving via Admin panel, seed ModuleAccess defaults so the user
        can access Dashboard features gated by ModuleAccess scopes.
        Blocks creating new ADMIN-role users through the Admin panel.
        """
        # Block creating or promoting to ADMIN via Admin panel
        if obj.role == User.Role.ADMIN:
            if not change or (change and obj.role != User.objects.get(pk=obj.pk).role):
                raise PermissionDenied(
                    "Role Admin hanya dapat dibuat melalui CLI server."
                )
        super().save_model(request, obj, form, change)
        ensure_default_module_access(obj)


@admin.register(ModuleAccess)
class ModuleAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "module", "scope", "updated_at")
    list_filter = ("module", "scope")
    search_fields = ("user__username", "user__full_name", "user__email")


class ReadOnlyAuditAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuthorityDelegation)
class AuthorityDelegationAdmin(ReadOnlyAuditAdmin):
    list_display = (
        "delegate",
        "module",
        "starts_at",
        "ends_at",
        "granted_by",
        "revoked_at",
    )
    list_filter = ("module", "authority", "revoked_at")
    search_fields = (
        "delegate__username",
        "delegate__full_name",
        "granted_by__username",
        "reason",
    )


@admin.register(AuthorityExercise)
class AuthorityExerciseAdmin(ReadOnlyAuditAdmin):
    list_display = ("actor", "module", "action", "exercised_at", "delegation")
    list_filter = ("module", "action")
    search_fields = (
        "actor__username",
        "actor_name_snapshot",
        "reason_snapshot",
    )
