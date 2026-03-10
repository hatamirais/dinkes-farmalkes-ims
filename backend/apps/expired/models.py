from django.db import models
from django.conf import settings
from apps.core.models import TimeStampedModel
from django.utils import timezone


class Expired(TimeStampedModel):
    """Document for expired items disposal."""

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        SUBMITTED = 'SUBMITTED', 'Diajukan'
        VERIFIED = 'VERIFIED', 'Terverifikasi'
        DISPOSED = 'DISPOSED', 'Keluar dari Stock'

    document_number = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        help_text='Leave blank to auto-generate (e.g., EXP-YYYYMM-XXXXX)'
    )
    report_date = models.DateField(default=timezone.now)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_expired_docs',
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='verified_expired_docs',
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    disposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='disposed_expired_docs',
    )
    disposed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'expired_docs'
        ordering = ['-report_date']

    def __str__(self):
        return self.document_number

    def save(self, *args, **kwargs):
        if not self.document_number:
            prefix = f"EXP-{timezone.now().strftime('%Y%m')}-"
            last_doc = Expired.objects.filter(document_number__startswith=prefix).order_by('-document_number').first()
            if last_doc:
                last_number = int(last_doc.document_number.split('-')[-1])
                new_number = last_number + 1
            else:
                new_number = 1
            self.document_number = f"{prefix}{str(new_number).zfill(5)}"
        super().save(*args, **kwargs)


class ExpiredItem(models.Model):
    """Line items for each expired document."""
    expired = models.ForeignKey(
        Expired,
        on_delete=models.CASCADE,
        related_name='items',
    )
    item = models.ForeignKey(
        'items.Item',
        on_delete=models.PROTECT,
        related_name='expired_items',
    )
    stock = models.ForeignKey(
        'stock.Stock',
        on_delete=models.PROTECT,
        related_name='expired_items',
        help_text='Specific batch that expired',
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    notes = models.TextField(blank=True, help_text='Detail pemusnahan')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'expired_items'

    def __str__(self):
        return f"{self.item} × {self.quantity}"
