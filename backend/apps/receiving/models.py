from django.db import models
from django.conf import settings
from apps.core.models import TimeStampedModel


class Receiving(TimeStampedModel):
    """Document for incoming stock (procurement or grants)."""

    class ReceivingType(models.TextChoices):
        PROCUREMENT = 'PROCUREMENT', 'Pengadaan'
        GRANT = 'GRANT', 'Hibah'

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        SUBMITTED = 'SUBMITTED', 'Diajukan'
        VERIFIED = 'VERIFIED', 'Terverifikasi'

    receiving_type = models.CharField(max_length=20, choices=ReceivingType.choices)
    document_number = models.CharField(max_length=100, unique=True)
    receiving_date = models.DateField()
    supplier = models.ForeignKey(
        'items.Supplier',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='receivings',
        help_text='Required for PROCUREMENT type',
    )
    grant_origin = models.CharField(
        max_length=100,
        blank=True,
        help_text='Province, Ministry, Donation (for GRANT type)',
    )
    program = models.CharField(max_length=100, blank=True)
    sumber_dana = models.ForeignKey(
        'items.FundingSource',
        on_delete=models.PROTECT,
        related_name='receivings',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_receivings',
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='verified_receivings',
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'receivings'
        ordering = ['-receiving_date']
        indexes = [
            models.Index(fields=['status', 'receiving_date'], name='idx_recv_status_date'),
        ]

    def __str__(self):
        return f"{self.document_number} ({self.get_receiving_type_display()})"


class ReceivingItem(models.Model):
    """Line items for each receiving document."""
    receiving = models.ForeignKey(
        Receiving,
        on_delete=models.CASCADE,
        related_name='items',
    )
    item = models.ForeignKey(
        'items.Item',
        on_delete=models.PROTECT,
        related_name='receiving_items',
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    batch_lot = models.CharField(max_length=100)
    expiry_date = models.DateField()
    unit_price = models.DecimalField(max_digits=15, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'receiving_items'

    def __str__(self):
        return f"{self.item} × {self.quantity}"

    @property
    def total_price(self):
        return self.quantity * self.unit_price


class ReceivingDocument(models.Model):
    """Supporting documents for receiving (eKatalog files, grant letters)."""
    receiving = models.ForeignKey(
        Receiving,
        on_delete=models.CASCADE,
        related_name='documents',
    )
    file = models.FileField(upload_to='receiving/%Y/%m/')
    file_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=50, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'receiving_documents'

    def __str__(self):
        return self.file_name
