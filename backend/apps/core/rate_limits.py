from django.conf import settings
from django_ratelimit.decorators import ratelimit

DEFAULT_USER_BULK_ACTION_RATE_LIMIT = "10/m"
DEFAULT_USER_MUTATION_RATE_LIMIT = "20/m"
DEFAULT_USER_PASSWORD_RESET_RATE_LIMIT = "5/m"
DEFAULT_PASSWORD_CHANGE_RATE_LIMIT = "5/m"
DEFAULT_PUSKESMAS_SBBK_MUTATION_RATE_LIMIT = "20/m"


def _setting_rate(name, default):
    def _rate(group, request):
        return getattr(settings, name, default)

    return _rate


user_bulk_action_ratelimit = ratelimit(
    key="user_or_ip",
    method="POST",
    rate=_setting_rate(
        "USER_BULK_ACTION_RATE_LIMIT",
        DEFAULT_USER_BULK_ACTION_RATE_LIMIT,
    ),
    block=True,
    group="users.bulk_action",
)

user_mutation_ratelimit = ratelimit(
    key="user_or_ip",
    method="POST",
    rate=_setting_rate(
        "USER_MUTATION_RATE_LIMIT",
        DEFAULT_USER_MUTATION_RATE_LIMIT,
    ),
    block=True,
    group="users.mutation",
)

user_password_reset_ratelimit = ratelimit(
    key="user_or_ip",
    method="POST",
    rate=_setting_rate(
        "USER_PASSWORD_RESET_RATE_LIMIT",
        DEFAULT_USER_PASSWORD_RESET_RATE_LIMIT,
    ),
    block=True,
    group="users.password_reset",
)

password_change_ratelimit = ratelimit(
    key="user_or_ip",
    method="POST",
    rate=_setting_rate(
        "PASSWORD_CHANGE_RATE_LIMIT",
        DEFAULT_PASSWORD_CHANGE_RATE_LIMIT,
    ),
    block=True,
    group="auth.password_change",
)

puskesmas_sbbk_mutation_ratelimit = ratelimit(
    key="user_or_ip",
    method="POST",
    rate=_setting_rate(
        "PUSKESMAS_SBBK_MUTATION_RATE_LIMIT",
        DEFAULT_PUSKESMAS_SBBK_MUTATION_RATE_LIMIT,
    ),
    block=True,
    group="puskesmas.sbbk_mutation",
)
