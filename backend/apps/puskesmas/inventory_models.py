"""Facility inventory foundation. Quantities are incomplete until consumption posts."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from apps.core.decimal_validation import PRICE_DECIMAL_PLACES, PRICE_MAX_DIGITS


class ImmutableQuerySet(models.QuerySet):
    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Gunakan layanan posting inventaris untuk membuat catatan.")

    def update(self, **kwargs):
        raise ValidationError("Catatan inventaris yang diposting tidak dapat diubah.")

    def delete(self):
        raise ValidationError("Catatan inventaris tidak dapat dihapus.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Catatan inventaris tidak dapat diubah.")


class ImmutableRecord(models.Model):
    objects = ImmutableQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding or (self.pk is not None and type(self).objects.filter(pk=self.pk).exists()):
            raise ValidationError("Catatan inventaris tidak dapat diubah.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Catatan inventaris tidak dapat dihapus.")


class PuskesmasInventoryAccount(ImmutableRecord):
    facility = models.OneToOneField("items.Facility", on_delete=models.PROTECT)
    effective_date = models.DateField()
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    @property
    def readiness(self):
        return "FOUNDATION_INCOMPLETE"


class PuskesmasOpeningVerification(models.Model):
    objects = ImmutableQuerySet.as_manager()
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Pratinjau"
        SUBMITTED = "SUBMITTED", "Menunggu verifikasi"
        REJECTED = "REJECTED", "Ditolak"
        POSTED = "POSTED", "Diposting"
        CANCELLED = "CANCELLED", "Dibatalkan"

    facility = models.ForeignKey("items.Facility", on_delete=models.PROTECT)
    year = models.PositiveIntegerField()
    reference = models.CharField(max_length=100)
    notes = models.TextField(blank=True, max_length=1000)
    zero_stock = models.BooleanField(default=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    digest = models.CharField(max_length=64)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="inventory_openings_prepared")
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    expires_at = models.DateTimeField()
    submitted_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="inventory_openings_cancelled",
    )
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="inventory_openings_reviewed")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=1000, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(year__gte=1000, year__lte=9999), name="pkopening_valid_year"),
            models.UniqueConstraint(fields=["facility"], condition=models.Q(status="POSTED"), name="pkopening_one_initial"),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            with transaction.atomic():
                original = type(self).objects.select_for_update().get(pk=self.pk)
                if original.status != "DRAFT":
                    raise ValidationError("Versi saldo awal yang diajukan tidak dapat diubah langsung.")
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Dokumen saldo awal harus dipertahankan.")


class PuskesmasOpeningVerificationLine(ImmutableRecord):
    def save(self, *args, **kwargs):
        with transaction.atomic():
            parent = PuskesmasOpeningVerification.objects.select_for_update().get(pk=self.opening_id)
            if parent.status != "DRAFT":
                raise ValidationError("Rincian pengajuan saldo awal sudah dikunci.")
            return super().save(*args, **kwargs)

    opening = models.ForeignKey(PuskesmasOpeningVerification, on_delete=models.PROTECT, related_name="lines")
    source_distribution_item = models.ForeignKey(
        "distribution.DistributionItem", on_delete=models.PROTECT, null=True, blank=True,
        related_name="opening_verification_lines",
    )
    source_stock = models.ForeignKey(
        "stock.Stock", on_delete=models.PROTECT, null=True, blank=True,
        related_name="puskesmas_opening_candidate_lines",
        help_text="Warehouse identity reference only; not evidence of delivery or a stock transfer.",
    )
    line_key = models.CharField(max_length=100)
    item = models.ForeignKey("items.Item", on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    unit_price = models.DecimalField(max_digits=PRICE_MAX_DIGITS, decimal_places=PRICE_DECIMAL_PLACES, null=True, blank=True)
    batch_lot = models.CharField(max_length=100, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    sumber_dana = models.ForeignKey("items.FundingSource", on_delete=models.PROTECT, null=True, blank=True)
    source_document_number = models.CharField(max_length=100, blank=True)
    provenance_note = models.CharField(max_length=1000, blank=True)

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(fields=["opening", "line_key"], name="pkopening_line_key"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="pkopening_line_positive"),
            models.CheckConstraint(condition=models.Q(unit_price__gte=0) | models.Q(unit_price__isnull=True), name="pkopening_line_price"),
        ]


class PuskesmasInventoryPosting(ImmutableRecord):
    facility = models.ForeignKey("items.Facility", on_delete=models.PROTECT)
    opening = models.OneToOneField(PuskesmasOpeningVerification, on_delete=models.PROTECT, null=True, blank=True, related_name="posting")
    receipt = models.OneToOneField("puskesmas.PuskesmasReceiptConfirmation", on_delete=models.PROTECT, null=True, blank=True, related_name="inventory_posting")
    consumption_revision = models.OneToOneField("puskesmas.PuskesmasConsumptionRevision", on_delete=models.PROTECT, null=True, blank=True, related_name="posting")
    reversal_of = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversal")
    effective_date = models.DateField()
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    digest = models.CharField(max_length=64)

    class Meta:
        constraints = [models.CheckConstraint(
            condition=(
                models.Q(opening__isnull=False, receipt__isnull=True, consumption_revision__isnull=True, reversal_of__isnull=True)
                | models.Q(opening__isnull=True, receipt__isnull=False, consumption_revision__isnull=True, reversal_of__isnull=True)
                | models.Q(opening__isnull=True, receipt__isnull=True, consumption_revision__isnull=False, reversal_of__isnull=True)
                | models.Q(opening__isnull=True, receipt__isnull=True, consumption_revision__isnull=True, reversal_of__isnull=False)
            ),
            name="pkinvposting_one_source",
        )]


class PuskesmasInventoryLayer(ImmutableRecord):
    posting = models.ForeignKey(PuskesmasInventoryPosting, on_delete=models.PROTECT, related_name="layers")
    opening_line = models.OneToOneField(PuskesmasOpeningVerificationLine, on_delete=models.PROTECT, null=True, blank=True)
    receipt_line = models.OneToOneField("puskesmas.PuskesmasReceiptConfirmationItem", on_delete=models.PROTECT, null=True, blank=True)
    item = models.ForeignKey("items.Item", on_delete=models.PROTECT)
    batch_lot = models.CharField(max_length=100, blank=True, help_text="Kosong berarti tidak diketahui.")
    expiry_date = models.DateField(null=True, blank=True, help_text="Kosong hanya untuk barang tanpa kewajiban kedaluwarsa.")
    unit_price = models.DecimalField(max_digits=PRICE_MAX_DIGITS, decimal_places=PRICE_DECIMAL_PLACES)
    sumber_dana = models.ForeignKey("items.FundingSource", on_delete=models.PROTECT, null=True, blank=True)
    source_document_number = models.CharField(max_length=100, blank=True)
    provenance_note = models.CharField(max_length=1000, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(unit_price__gte=0), name="pkinvlayer_price"),
            models.CheckConstraint(condition=(models.Q(opening_line__isnull=False, receipt_line__isnull=True) | models.Q(opening_line__isnull=True, receipt_line__isnull=False)), name="pkinvlayer_one_origin"),
        ]
        indexes = [models.Index(fields=["item", "expiry_date", "id"], name="pkinvlayer_fefo")]


class PuskesmasInventoryBalance(ImmutableRecord):
    """Initial projection only; future consumption services must extend this contract."""
    layer = models.OneToOneField(PuskesmasInventoryLayer, on_delete=models.PROTECT, related_name="balance")
    quantity = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gte=0), name="pkinvbalance_nonnegative")]


class PuskesmasInventoryMovement(ImmutableRecord):
    posting = models.ForeignKey(PuskesmasInventoryPosting, on_delete=models.PROTECT, related_name="movements")
    layer = models.ForeignKey(PuskesmasInventoryLayer, on_delete=models.PROTECT, related_name="movements")
    quantity_delta = models.DecimalField(max_digits=12, decimal_places=2)
    unit_price = models.DecimalField(max_digits=PRICE_MAX_DIGITS, decimal_places=PRICE_DECIMAL_PLACES)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=~models.Q(quantity_delta=0), name="pkinvmovement_nonzero"),
            models.CheckConstraint(condition=models.Q(unit_price__gte=0), name="pkinvmovement_price"),
            models.UniqueConstraint(fields=["posting", "layer"], name="pkinvmovement_event_layer"),
        ]


class PuskesmasConsumptionRevision(ImmutableRecord):
    """Retained input snapshot; replacement never edits the previous revision."""
    consumption = models.ForeignKey("puskesmas.PuskesmasConsumption", on_delete=models.PROTECT, related_name="inventory_revisions")
    number = models.PositiveIntegerField()
    effective_date = models.DateField()
    digest = models.CharField(max_length=64)
    snapshot = models.JSONField()
    reason = models.CharField(max_length=1000, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(fields=["consumption", "number"], name="pkconsrevision_number"),
            models.CheckConstraint(condition=models.Q(number__gte=1), name="pkconsrevision_positive"),
        ]


class PuskesmasConsumptionAllocation(ImmutableRecord):
    revision = models.ForeignKey(PuskesmasConsumptionRevision, on_delete=models.PROTECT, related_name="allocations")
    layer = models.ForeignKey(PuskesmasInventoryLayer, on_delete=models.PROTECT, related_name="consumption_allocations")
    subunit = models.ForeignKey("puskesmas.PuskesmasSubunit", on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=PRICE_MAX_DIGITS, decimal_places=PRICE_DECIMAL_PLACES)

    @property
    def cost(self):
        from apps.core.decimal_validation import multiply_decimals
        return multiply_decimals(self.quantity, self.unit_price)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["revision", "layer", "subunit"], name="pkconsallocation_source"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="pkconsallocation_positive"),
            models.CheckConstraint(condition=models.Q(unit_price__gte=0), name="pkconsallocation_price"),
        ]


class PuskesmasConsumptionAudit(ImmutableRecord):
    """Durable before/after trail, including drafts; independent of signal logging."""
    facility = models.ForeignKey("items.Facility", on_delete=models.PROTECT)
    consumption_id_snapshot = models.PositiveBigIntegerField()
    event = models.CharField(max_length=24)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)


class PuskesmasLPLPOInventoryBinding(ImmutableRecord):
    """Explicit opt-in, retaining the manual document values being replaced."""
    lplpo = models.OneToOneField("lplpo.LPLPO", on_delete=models.PROTECT, related_name="inventory_binding")
    opening = models.ForeignKey(PuskesmasOpeningVerification, on_delete=models.PROTECT)
    previous_values = models.JSONField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)
