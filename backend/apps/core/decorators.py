"""
Permission-based access control decorators for Healthcare IMS.

perm_required: Checks Django permissions (managed via Groups in Admin panel).
role_required: DEPRECATED — kept for backward compatibility but new code
               should use perm_required.

Usage:
    @perm_required('receiving.add_receiving')
    def my_view(request):
        ...

    # Multiple permissions (user needs ANY one of them):
    @perm_required('recall.change_recall', 'recall.delete_recall')
    def my_view(request):
        ...
"""

from functools import wraps
from django.http import HttpResponseForbidden
from django.shortcuts import render

from apps.users.access import has_module_permission


def perm_required(*perms):
    """
    Decorator that restricts view access to users with specific Django permissions.

    Uses Django's permission framework — permissions are assigned via Groups
    in the Admin panel. No code changes needed to adjust access.

    Must be used AFTER @login_required to ensure request.user is authenticated.
    Returns 403 Forbidden if the user lacks ALL of the listed permissions.
    Superusers always pass the check (Django's has_perm returns True for superusers).

    Args:
        *perms: One or more permission strings (e.g., 'receiving.add_receiving').
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # Superusers bypass all permission checks
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)

            # User needs ANY one of the listed permissions
            if any(request.user.has_perm(p) for p in perms):
                return view_func(request, *args, **kwargs)

            # Fallback to module-role access model
            if any(has_module_permission(request.user, p) for p in perms):
                return view_func(request, *args, **kwargs)

            return HttpResponseForbidden(
                "<h1>403 Forbidden</h1>"
                "<p>Anda tidak memiliki izin untuk mengakses halaman ini.</p>"
            )

        return _wrapped_view

    return decorator


def role_required(*allowed_roles):
    """
    DEPRECATED: Use @perm_required instead for permission-based access control.

    This decorator checks the user.role field directly. New views should use
    @perm_required which checks Django group permissions manageable from Admin.
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            if request.user.role in allowed_roles:
                return view_func(request, *args, **kwargs)
            return HttpResponseForbidden(
                "<h1>403 Forbidden</h1>"
                "<p>Anda tidak memiliki izin untuk mengakses halaman ini.</p>"
            )

        return _wrapped_view

    return decorator
