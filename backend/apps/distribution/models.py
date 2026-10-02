from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from apps.core.models import TimeStampedModel
from apps.core.decimal_validation import (
    PRICE_DECIMAL_PLACES,
    PRICE_MAX_DIGITS,
    multiply_decimals,
)

class Distribution(TimeStampedModel):
    """Outbound stock requests and allocations."""

    class DistributionType(models.TextChoices):
        LPLPO = "LPLPO", "LPLPO"
        SPECIAL_REQUEST = "SPECIAL_REQUEST", "Permintaan Khusus"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Diajukan"
        VERIFIED = "VERIFIED", "Terverifikasi"
        PREPARED = "PREPARED", "Disiapkan"
        DISTRIBUTED = "DISTRIBUTED", "Terdistribusi"
        REJECTED = "REJECTED", "Ditolak"

    distribution_type = models.CharField(
        max_length=20, choices=DistributionType.choices
    )
    document_number = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Diterbitkan otomatis pada checkpoint workflow.",
    )
    request_date = models.DateField()
    facility = models.ForeignKey(
        "items.Facility",
        on_delete=models.PROTECT,
        related_name="distributions",
    )
    program = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_distributions",
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="verified_distributions",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_distributions",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    distributed_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    ocr_text = models.TextField(
        blank=True,
        help_text="Extracted text from uploaded proof document (Special Request)",
    )
    allocation = models.ForeignKey(
        "allocation.Allocation",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="distributions",
        help_text="Parent allocation that auto-generated this distribution",
    )

    class Meta:
        db_table = "distributions"
        ordering = ["-request_date"]
        indexes = [
            models.Index(
                fields=["status", "request_date"], name="idx_dist_status_date"
            ),
            models.Index(
                fields=["facility", "request_date"], name="idx_dist_facility_date"
            ),
        ]

    def __str__(self):
        return f"{self.document_number or 'Belum diterbitkan'} → {self.facility}"

    @property
    def is_generated_lplpo_distribution(self):
        if self.distribution_type != self.DistributionType.LPLPO:
            return False
        try:
            self.lplpo_source
        except ObjectDoesNotExist:
            return False
        return True

class DistributionStaffAssignment(TimeStampedModel):
    """Staff members involved in a distribution workflow."""

    distribution = models.ForeignKey(
        Distribution,
        on_delete=models.CASCADE,
        related_name="staff_assignments",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="distribution_staff_assignments",
    )

    class Meta:
        db_table = "distribution_staff_assignments"
        unique_together = ("distribution", "user")
        ordering = ["user__full_name", "user__username"]

    def __str__(self):
        return f"{self.distribution.document_number} - {self.user}"


class DistributionItem(models.Model):
    """Line items for distribution requests."""

    distribution = models.ForeignKey(
        Distribution,
        on_delete=models.CASCADE,
        related_name="items",
    )
    item = models.ForeignKey(
        "items.Item",
        on_delete=models.PROTECT,
        related_name="distribution_items",
    )
    quantity_requested = models.DecimalField(max_digits=12, decimal_places=2)
    quantity_approved = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    stock = models.ForeignKey(
        "stock.Stock",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="distribution_items",
        help_text="Specific batch allocated (FEFO selection)",
    )
    issued_batch_lot = models.CharField(max_length=100, blank=True)
    issued_expiry_date = models.DateField(null=True, blank=True)
    issued_unit_price = models.DecimalField(
        max_digits=PRICE_MAX_DIGITS,
        decimal_places=PRICE_DECIMAL_PLACES,
        null=True,
        blank=True,
    )
    issued_sumber_dana = models.ForeignKey(
        "items.FundingSource",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="issued_distribution_items",
    )
    reserved_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Jumlah stok yang sedang dibooking untuk dokumen ini.",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()

    class Meta:
        db_table = "distribution_items"

    def __str__(self):
        return f"{self.item} × {self.quantity_requested}"

    @property
    def settled_quantity(self):
        from django.db.models import DecimalField, Sum, Value
        from django.db.models.functions import Coalesce

        return self.settlement_receipts.aggregate(
            total=Coalesce(
                Sum("quantity"),
                Value(0, output_field=DecimalField(max_digits=12, decimal_places=2)),
            )
        )["total"]

    @property
    def outstanding_quantity(self):
        approved_quantity = self.quantity_approved or self.quantity_requested or 0
        outstanding = approved_quantity - self.settled_quantity
        return outstanding if outstanding > 0 else 0

    @property
    def outstanding_value(self):
        if self.issued_unit_price is None:
            return 0
        return multiply_decimals(self.outstanding_quantity, self.issued_unit_price)
