from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from apps.core.models import TimeStampedModel


class Stock(TimeStampedModel):
    """Real-time inventory tracking by batch/location."""
    item = models.ForeignKey(
        'items.Item',
        on_delete=models.PROTECT,
        related_name='stock_entries',
    )
    location = models.ForeignKey(
        'items.Location',
        on_delete=models.PROTECT,
        related_name='stock_entries',
    )
    batch_lot = models.CharField(max_length=100)
    expiry_date = models.DateField()
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    reserved = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text='Stock allocated for pending distributions',
    )
    unit_price = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    sumber_dana = models.ForeignKey(
        'items.FundingSource',
        on_delete=models.PROTECT,
        related_name='stock_entries',
    )
    receiving_ref = models.ForeignKey(
        'receiving.Receiving',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='stock_entries',
    )

    class Meta:
        db_table = 'stock'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=0),
                name='chk_stock_quantity',
            ),
            models.CheckConstraint(
                condition=models.Q(reserved__gte=0),
                name='chk_stock_reserved_gte_0',
            ),
            models.UniqueConstraint(
                fields=['item', 'location', 'batch_lot', 'sumber_dana'],
                name='uq_stock_batch',
            ),
        ]
        indexes = [
            models.Index(fields=['item', 'location', 'expiry_date'], name='idx_stock_fefo'),
            models.Index(fields=['expiry_date'], name='idx_stock_expiry'),
            models.Index(fields=['item', 'location'], name='idx_stock_item_loc'),
        ]
        ordering = ['item', 'expiry_date']

    def __str__(self):
        return f"{self.item} | {self.batch_lot} | Qty: {self.quantity}"

    @property
    def available_quantity(self):
        """Available stock = quantity - reserved."""
        return self.quantity - self.reserved

    @property
    def total_value(self):
        """Total value = quantity × unit_price."""
        return self.quantity * self.unit_price

    @property
    def is_expired(self):
        """Whether this stock batch has expired."""
        return self.expiry_date <= timezone.now().date()

    @property
    def is_near_expiry(self):
        """Whether this stock batch expires within 90 days."""
        return not self.is_expired and self.expiry_date <= timezone.now().date() + timedelta(days=90)


class Transaction(models.Model):
    """Immutable audit trail of all stock movements."""

    class TransactionType(models.TextChoices):
        IN = 'IN', 'Barang Masuk'
        OUT = 'OUT', 'Barang Keluar'
        ADJUST = 'ADJUST', 'Penyesuaian'
        RETURN = 'RETURN', 'Retur'

    class ReferenceType(models.TextChoices):
        RECEIVING = 'RECEIVING', 'Penerimaan'
        DISTRIBUTION = 'DISTRIBUTION', 'Distribusi'
        ADJUSTMENT = 'ADJUSTMENT', 'Penyesuaian'
        INITIAL_IMPORT = 'INITIAL_IMPORT', 'Import Awal'

    transaction_type = models.CharField(max_length=10, choices=TransactionType.choices)
    item = models.ForeignKey(
        'items.Item',
        on_delete=models.PROTECT,
        related_name='transactions',
    )
    location = models.ForeignKey(
        'items.Location',
        on_delete=models.PROTECT,
        related_name='transactions',
    )
    batch_lot = models.CharField(max_length=100)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    unit_price = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    sumber_dana = models.ForeignKey(
        'items.FundingSource',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='transactions',
    )
    reference_type = models.CharField(
        max_length=20,
        choices=ReferenceType.choices,
    )
    reference_id = models.PositiveIntegerField(
        default=0,
        help_text='Polymorphic reference to source document',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='transactions',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'transactions'
        indexes = [
            models.Index(fields=['item', '-created_at'], name='idx_trans_item_date'),
            models.Index(fields=['reference_type', 'reference_id'], name='idx_trans_reference'),
            models.Index(fields=['created_at'], name='idx_trans_created'),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.transaction_type} | {self.item} | {self.quantity} | {self.created_at}"
