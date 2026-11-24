"""Protect finalized consumption against ordinary ORM/admin mutation."""
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import models, transaction


def assert_draft_write(consumption_id):
    if not consumption_id:
        return
    Consumption = apps.get_model("puskesmas", "PuskesmasConsumption")
    Revision = apps.get_model("puskesmas", "PuskesmasConsumptionRevision")
    Facility = apps.get_model("items", "Facility")
    facility_id = Consumption.objects.filter(pk=consumption_id).values_list("facility_id", flat=True).first()
    if facility_id:
        Facility.objects.select_for_update().get(pk=facility_id)
        Consumption.objects.select_for_update().get(pk=consumption_id)
    if Revision.objects.filter(consumption_id=consumption_id).exists():
        raise ValidationError("Pemakaian sudah diposting; gunakan koreksi beralasan dengan jejak revisi.")


class ConsumptionQuerySet(models.QuerySet):
    def _check(self, objects=None):
        header = self.model._meta.model_name == "puskesmasconsumption"
        ids = ([obj.pk if header else obj.consumption_id for obj in objects] if objects is not None
               else self.values_list("pk" if header else "consumption_id", flat=True))
        for pk in sorted({pk for pk in ids if pk}):
            assert_draft_write(pk)

    def update(self, **kwargs):
        with transaction.atomic():
            self._check()
            target = kwargs.get("consumption_id") or getattr(kwargs.get("consumption"), "pk", None)
            if target:
                assert_draft_write(target)
            return super().update(**kwargs)

    def delete(self):
        with transaction.atomic():
            self._check()
            return super().delete()

    def bulk_create(self, objs, **kwargs):
        if kwargs.get("update_conflicts"):
            raise ValidationError("Upsert pemakaian tidak diizinkan.")
        objs = list(objs)
        with transaction.atomic():
            self._check(objs)
            return super().bulk_create(objs, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        objs = list(objs)
        with transaction.atomic():
            self._check(objs)
            self.filter(pk__in=[obj.pk for obj in objs])._check()
            return super().bulk_update(objs, fields, **kwargs)
