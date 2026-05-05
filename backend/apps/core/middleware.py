from django.core.exceptions import PermissionDenied
from django.conf import settings

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
                    raise PermissionDenied("Akses Admin Panel hanya untuk Admin.")

        return self.get_response(request)


class CSPMiddleware:
    """Inject Content-Security-Policy header from SECURE_CSP setting."""

    def __init__(self, get_response):
        self.get_response = get_response
        csp_dict = getattr(settings, "SECURE_CSP", {})
        parts = []
        for directive, values in csp_dict.items():
            parts.append(f"{directive} {' '.join(values)}")
        self._header = "; ".join(parts) if parts else ""

    def __call__(self, request):
        response = self.get_response(request)
        if self._header:
            response["Content-Security-Policy"] = self._header
        return response
