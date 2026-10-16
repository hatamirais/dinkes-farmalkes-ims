from django.apps import AppConfig
from django.db.models.signals import pre_delete


AUTHORITY_EXERCISE_TARGET_MODELS = (
    "receiving.Receiving",
    "procurement.ProcurementContract",
    "procurement.ProcurementAmendment",
    "distribution.Distribution",
    "allocation.Allocation",
    "recall.Recall",
    "expired.Expired",
    "stock_opname.StockOpname",
    "puskesmas.PuskesmasRequest",
    "lplpo.LPLPO",
)


class UsersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.users'
    verbose_name = 'Users'

    def ready(self):
        from apps.users import signals

        for model_label in AUTHORITY_EXERCISE_TARGET_MODELS:
            model = self.apps.get_model(model_label)
            pre_delete.connect(
                signals.protect_authority_exercise_target,
                sender=model,
                dispatch_uid=f"users.protect_authority_exercise_target.{model_label}",
            )
