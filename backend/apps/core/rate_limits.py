from django.conf import settings
from django_ratelimit.decorators import ratelimit

DEFAULT_USER_BULK_ACTION_RATE_LIMIT = "10/m"
DEFAULT_USER_MUTATION_RATE_LIMIT = "20/m"
DEFAULT_ITEM_MUTATION_RATE_LIMIT = "20/m"
DEFAULT_USER_PASSWORD_RESET_RATE_LIMIT = "5/m"
DEFAULT_PASSWORD_CHANGE_RATE_LIMIT = "5/m"
DEFAULT_PUSKESMAS_RECEIPT_CONFIRMATION_MUTATION_RATE_LIMIT = "20/m"
DEFAULT_PUSKESMAS_CONSUMPTION_MUTATION_RATE_LIMIT = "20/m"
DEFAULT_PROCUREMENT_MUTATION_RATE_LIMIT = "20/m"
DEFAULT_LPLPO_IMPORT_RATE_LIMIT = "5/h"


def _setting_rate(name, default):
    def _rate(group, request):
        return getattr(settings, name, default)

    return _rate


def _receipt_confirmation_rate(group, request):
    return getattr(
        settings,
        "PUSKESMAS_RECEIPT_CONFIRMATION_MUTATION_RATE_LIMIT",
        getattr(
            settings,
            "PUSKESMAS_SBBK_MUTATION_RATE_LIMIT",
            DEFAULT_PUSKESMAS_RECEIPT_CONFIRMATION_MUTATION_RATE_LIMIT,
        ),
    )


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

item_mutation_ratelimit = ratelimit(
    key="user_or_ip",
    method="POST",
    rate=_setting_rate(
        "ITEM_MUTATION_RATE_LIMIT",
        DEFAULT_ITEM_MUTATION_RATE_LIMIT,
    ),
    block=True,
    group="items.mutation",
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

puskesmas_receipt_confirmation_mutation_ratelimit = ratelimit(
    key="user_or_ip",
    method="POST",
    rate=_receipt_confirmation_rate,
    block=True,
    group="puskesmas.receipt_confirmation_mutation",
)

puskesmas_sbbk_mutation_ratelimit = puskesmas_receipt_confirmation_mutation_ratelimit

puskesmas_consumption_mutation_ratelimit = ratelimit(
    key="user_or_ip",
    method="POST",
    rate=_setting_rate(
        "PUSKESMAS_CONSUMPTION_MUTATION_RATE_LIMIT",
        DEFAULT_PUSKESMAS_CONSUMPTION_MUTATION_RATE_LIMIT,
    ),
    block=True,
    group="puskesmas.consumption_mutation",
)

procurement_mutation_ratelimit = ratelimit(
    key="user_or_ip",
    method="POST",
    rate=_setting_rate(
        "PROCUREMENT_MUTATION_RATE_LIMIT",
        DEFAULT_PROCUREMENT_MUTATION_RATE_LIMIT,
    ),
    block=True,
    group="procurement.mutation",
)

lplpo_import_ratelimit = ratelimit(
    key="user_or_ip",
    method="POST",
    rate=_setting_rate(
        "LPLPO_IMPORT_RATE_LIMIT",
        DEFAULT_LPLPO_IMPORT_RATE_LIMIT,
    ),
    block=True,
    group="lplpo.import_mutation",
)
