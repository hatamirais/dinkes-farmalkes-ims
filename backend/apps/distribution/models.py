from django.db import models
from django.conf import settings
from apps.core.models import TimeStampedModel


class Distribution(TimeStampedModel):
    """Outbound stock requests and allocations."""

    class DistributionType(models.TextChoices):
        LPLPO = 'LPLPO', 'LPLPO'
        ALLOCATION = 'ALLOCATION', 'Alokasi'
        SPECIAL_REQUEST = 'SPECIAL_REQUEST', 'Permintaan Khusus'

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        SUBMITTED = 'SUBMITTED', 'Diajukan'
        VERIFIED = 'VERIFIED', 'Terverifikasi'
        PREPARED = 'PREPARED', 'Disiapkan'
        DISTRIBUTED = 'DISTRIBUTED', 'Terdistribusi'
        REJECTED = 'REJECTED', 'Ditolak'

    distribution_type = models.CharField(max_length=20, choices=DistributionType.choices)
    document_number = models.CharField(max_length=100, unique=True)
    request_date = models.DateField()
    facility = models.ForeignKey(
        'items.Facility',
        on_delete=models.PROTECT,
        related_name='distributions',
    )
    program = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SUBMITTED,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_distributions',
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='verified_distributions',
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='approved_distributions',
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    distributed_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    ocr_text = models.TextField(
        blank=True,
        help_text='Extracted text from uploaded proof document (Special Request)',
    )

    class Meta:
        db_table = 'distributions'
        ordering = ['-request_date']
        indexes = [
            models.Index(fields=['status', 'request_date'], name='idx_dist_status_date'),
            models.Index(fields=['facility', 'request_date'], name='idx_dist_facility_date'),
        ]

    def __str__(self):
        return f"{self.document_number} → {self.facility}"


class DistributionItem(models.Model):
    """Line items for distribution requests."""
    distribution = models.ForeignKey(
        Distribution,
        on_delete=models.CASCADE,
        related_name='items',
    )
    item = models.ForeignKey(
        'items.Item',
        on_delete=models.PROTECT,
        related_name='distribution_items',
    )
    quantity_requested = models.DecimalField(max_digits=12, decimal_places=2)
    quantity_approved = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    stock = models.ForeignKey(
        'stock.Stock',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='distribution_items',
        help_text='Specific batch allocated (FEFO selection)',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'distribution_items'

    def __str__(self):
        return f"{self.item} × {self.quantity_requested}"
