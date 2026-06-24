from django.conf import settings
from django_ratelimit.decorators import ratelimit

DEFAULT_USER_BULK_ACTION_RATE_LIMIT = "10/m"
DEFAULT_USER_MUTATION_RATE_LIMIT = "20/m"
DEFAULT_ITEM_MUTATION_RATE_LIMIT = "20/m"
DEFAULT_USER_PASSWORD_RESET_RATE_LIMIT = "5/m"
DEFAULT_PASSWORD_CHANGE_RATE_LIMIT = "5/m"
DEFAULT_PUSKESMAS_RECEIPT_CONFIRMATION_MUTATION_RATE_LIMIT = "20/m"
DEFAULT_PUSKESMAS_CONSUMPTION_MUTATION_RATE_LIMIT = "20/m"
DEFAULT_LPLPO_IMPORT_RATE_LIMIT = "5/h"
DEFAULT_STOCK_OPNAME_MUTATION_RATE_LIMIT = "20/m"
DEFAULT_STOCK_OPNAME_FORM_RATE_LIMIT = DEFAULT_STOCK_OPNAME_MUTATION_RATE_LIMIT
DEFAULT_STOCK_OPNAME_INPUT_RATE_LIMIT = "60/m"
DEFAULT_STOCK_OPNAME_WORKFLOW_RATE_LIMIT = "20/m"


def _setting_rate(name, default):
    def _rate(group, request):
        return getattr(settings, name, default)

    return _rate


def _fallback_setting_rate(name, fallback_name, default):
    def _rate(group, request):
        return getattr(
            settings,
            name,
            getattr(settings, fallback_name, default),
        )

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

# Backward-compatible alias for older imports while the receipt-confirmation
# naming propagates through the codebase and deployment config.
puskesmas_sbbk_mutation_ratelimit = (
    puskesmas_receipt_confirmation_mutation_ratelimit
)

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

stock_opname_form_mutation_ratelimit = ratelimit(
    key="user_or_ip",
    method="POST",
    rate=_fallback_setting_rate(
        "STOCK_OPNAME_FORM_RATE_LIMIT",
        "STOCK_OPNAME_MUTATION_RATE_LIMIT",
        DEFAULT_STOCK_OPNAME_FORM_RATE_LIMIT,
    ),
    block=True,
    group="stock_opname.form_mutation",
)

stock_opname_input_mutation_ratelimit = ratelimit(
    key="user_or_ip",
    method="POST",
    rate=_fallback_setting_rate(
        "STOCK_OPNAME_INPUT_RATE_LIMIT",
        "STOCK_OPNAME_MUTATION_RATE_LIMIT",
        DEFAULT_STOCK_OPNAME_INPUT_RATE_LIMIT,
    ),
    block=True,
    group="stock_opname.input_mutation",
)

stock_opname_workflow_mutation_ratelimit = ratelimit(
    key="user_or_ip",
    method="POST",
    rate=_fallback_setting_rate(
        "STOCK_OPNAME_WORKFLOW_RATE_LIMIT",
        "STOCK_OPNAME_MUTATION_RATE_LIMIT",
        DEFAULT_STOCK_OPNAME_WORKFLOW_RATE_LIMIT,
    ),
    block=True,
    group="stock_opname.workflow_mutation",
)
