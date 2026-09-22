from django.db import models
from django.conf import settings
from apps.core.models import TimeStampedModel
from django.utils import timezone


class Recall(TimeStampedModel):
    """Document for returning items to supplier."""

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        SUBMITTED = 'SUBMITTED', 'Diajukan'
        VERIFIED = 'VERIFIED', 'Terverifikasi'
        COMPLETED = 'COMPLETED', 'Selesai'

    document_number = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        null=True,
        help_text='Diterbitkan otomatis saat recall diajukan.'
    )
    recall_date = models.DateField(default=timezone.now)
    supplier = models.ForeignKey(
        'items.Supplier',
        on_delete=models.PROTECT,
        related_name='recalls',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_recalls',
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='verified_recalls',
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='completed_recalls',
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'recalls'
        ordering = ['-recall_date']

    def __str__(self):
        return f"{self.document_number} - {self.supplier}"

class RecallItem(models.Model):
    """Line items for each recall document."""
    recall = models.ForeignKey(
        Recall,
        on_delete=models.CASCADE,
        related_name='items',
    )
    item = models.ForeignKey(
        'items.Item',
        on_delete=models.PROTECT,
        related_name='recall_items',
    )
    stock = models.ForeignKey(
        'stock.Stock',
        on_delete=models.PROTECT,
        related_name='recall_items',
        help_text='Specific batch being recalled',
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    notes = models.TextField(blank=True, help_text='Alasan recall')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'recall_items'

    def __str__(self):
        return f"{self.item} × {self.quantity}"
