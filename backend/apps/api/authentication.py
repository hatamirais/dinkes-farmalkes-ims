import hmac

from django.conf import settings
from rest_framework import authentication, exceptions


class ReportingApiPrincipal:
    is_authenticated = True

    def __str__(self):
        return "reporting-api-client"


class ReportingApiAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request)
        if not header:
            raise exceptions.AuthenticationFailed("Missing bearer token.")

        parts = header.split()
        expected_keyword = self.keyword.lower().encode("ascii")
        if len(parts) != 2 or parts[0].lower() != expected_keyword:
            raise exceptions.AuthenticationFailed("Invalid bearer token.")

        configured_secret = getattr(settings, "REPORTING_API_SHARED_SECRET", "")
        if not configured_secret:
            raise exceptions.AuthenticationFailed("Reporting API secret is not configured.")

        try:
            configured_secret_bytes = configured_secret.encode("ascii")
        except UnicodeEncodeError as exc:
            raise exceptions.AuthenticationFailed(
                "Reporting API secret must contain ASCII characters only."
            ) from exc

        if not hmac.compare_digest(parts[1], configured_secret_bytes):
            raise exceptions.AuthenticationFailed("Invalid bearer token.")

        return ReportingApiPrincipal(), parts[1].decode("ascii")

    def authenticate_header(self, request):
        return self.keyword
