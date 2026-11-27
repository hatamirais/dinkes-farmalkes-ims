"""Operator-recorded withdrawals; these records do not certify disposal."""
from django.conf import settings
from django.db import models
from django.utils import timezone
from apps.core.decimal_validation import SOURCE_PRICE_DECIMAL_PLACES, SOURCE_PRICE_MAX_DIGITS, multiply_decimals
from .inventory_models import ImmutableRecord


class PuskesmasExpiry(ImmutableRecord):
    facility = models.ForeignKey("items.Facility", on_delete=models.PROTECT)
    request_key = models.UUIDField(unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-pk"]


class PuskesmasExpiryRevision(ImmutableRecord):
    expiry = models.ForeignKey(PuskesmasExpiry, on_delete=models.PROTECT, related_name="revisions")
    number = models.PositiveIntegerField()
    effective_date = models.DateField()
    reference = models.CharField(max_length=100, blank=True)
    reason = models.CharField(max_length=1000)
    digest = models.CharField(max_length=64)
    void = models.BooleanField(default=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["number"]
        constraints = [models.UniqueConstraint(fields=["expiry", "number"], name="pkexpiry_revision_number"),
            models.CheckConstraint(condition=models.Q(number__gte=1), name="pkexpiry_revision_positive")]


class PuskesmasExpiryLine(ImmutableRecord):
    revision = models.ForeignKey(PuskesmasExpiryRevision, on_delete=models.PROTECT, related_name="lines")
    layer = models.ForeignKey("puskesmas.PuskesmasInventoryLayer", on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=SOURCE_PRICE_MAX_DIGITS, decimal_places=SOURCE_PRICE_DECIMAL_PLACES)

    @property
    def cost(self):
        return multiply_decimals(self.quantity, self.unit_price)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["revision", "layer"], name="pkexpiry_line_layer"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="pkexpiry_line_positive"),
            models.CheckConstraint(condition=models.Q(unit_price__gte=0), name="pkexpiry_line_price")]
