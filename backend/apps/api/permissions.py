from django.conf import settings
from rest_framework.permissions import BasePermission


class ReportingApiEnabled(BasePermission):
    message = "Reporting API is disabled."

    def has_permission(self, request, view):
        return bool(getattr(settings, "REPORTING_API_ENABLED", False))
