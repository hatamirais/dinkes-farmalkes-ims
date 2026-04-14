"""
Audit logging signals for security events.
Logs authentication events (login, logout, lockout) as structured JSON to stdout.
"""

import logging

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

logger = logging.getLogger("security")


def _get_client_ip(request):
    """Extract client IP from request, respecting proxied headers."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


@receiver(user_logged_in)
def log_login(sender, request, user, **kwargs):
    logger.info(
        "login_success",
        extra={
            "event": "login_success",
            "username": user.username,
            "ip": _get_client_ip(request),
            "user_agent": request.META.get("HTTP_USER_AGENT", ""),
        },
    )


@receiver(user_logged_out)
def log_logout(sender, request, user, **kwargs):
    username = user.username if user else "anonymous"
    logger.info(
        "logout",
        extra={
            "event": "logout",
            "username": username,
            "ip": _get_client_ip(request),
        },
    )


@receiver(user_login_failed)
def log_login_failed(sender, credentials, request, **kwargs):
    username = credentials.get("username", "unknown")
    logger.warning(
        "login_failed",
        extra={
            "event": "login_failed",
            "username": username,
            "ip": _get_client_ip(request) if request else "unknown",
        },
    )
