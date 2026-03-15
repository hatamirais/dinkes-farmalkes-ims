from .access import has_module_scope
from .models import ModuleAccess


def access_flags(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {
            "can_view_user_management": False,
            "can_open_admin_panel": False,
        }

    return {
        "can_view_user_management": has_module_scope(
            user, ModuleAccess.Module.USERS, ModuleAccess.Scope.VIEW
        ),
        "can_open_admin_panel": has_module_scope(
            user, ModuleAccess.Module.ADMIN_PANEL, ModuleAccess.Scope.MANAGE
        ),
    }
