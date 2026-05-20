from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender="distribution.Distribution")
def close_lplpo_on_distribution_complete(sender, instance, **kwargs):
    """When a Distribution linked to an LPLPO is DISTRIBUTED, close the LPLPO."""
    from apps.lplpo.models import LPLPO

    if instance.status != "DISTRIBUTED":
        return
    try:
        lplpo = instance.lplpo_source
        if lplpo.status in (
            LPLPO.Status.REVIEWED,
            LPLPO.Status.APPROVED,
            LPLPO.Status.DISTRIBUTED,
        ):
            lplpo.status = LPLPO.Status.CLOSED
            lplpo.save(update_fields=["status", "updated_at"])
    except LPLPO.DoesNotExist:
        pass
