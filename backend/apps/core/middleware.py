from django.http import HttpResponseForbidden

from apps.users.access import has_module_scope
from apps.users.models import ModuleAccess


class AdminPanelAccessMiddleware:
    """Restrict /admin access to users with admin_panel manage scope."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/admin/"):
            user = getattr(request, "user", None)
            if user and user.is_authenticated:
                allowed = has_module_scope(
                    user,
                    ModuleAccess.Module.ADMIN_PANEL,
                    ModuleAccess.Scope.MANAGE,
                )
                if not allowed:
                    return HttpResponseForbidden(
                        "<h1>403 Forbidden</h1><p>Akses Admin Panel hanya untuk Admin.</p>"
                    )

        return self.get_response(request)
