from django.db import models
from django.conf import settings
from django.utils import timezone
from apps.core.models import TimeStampedModel


class StockOpname(TimeStampedModel):
    """Header document for a physical inventory count session."""

    class PeriodType(models.TextChoices):
        MONTHLY = 'MONTHLY', 'Bulanan'
        QUARTERLY = 'QUARTERLY', 'Triwulan'
        SEMESTER = 'SEMESTER', 'Semester'
        YEARLY = 'YEARLY', 'Tahunan'

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        IN_PROGRESS = 'IN_PROGRESS', 'Sedang Berjalan'
        COMPLETED = 'COMPLETED', 'Selesai'

    document_number = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        help_text='Kosongkan untuk auto-generate (SO-YYYYMM-XXXXX)',
    )
    period_type = models.CharField(
        max_length=20,
        choices=PeriodType.choices,
    )
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_stock_opnames',
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    categories = models.ManyToManyField(
        'items.Category',
        related_name='stock_opnames',
        help_text='Kategori barang yang akan dihitung',
    )
    assigned_to = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='assigned_stock_opnames',
        help_text='Petugas yang ditugaskan untuk menghitung',
    )

    class Meta:
        db_table = 'stock_opnames'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.document_number} ({self.get_period_type_display()})"

    def save(self, *args, **kwargs):
        if not self.document_number:
            prefix = f"SO-{timezone.now().strftime('%Y%m')}-"
            last = (
                StockOpname.objects
                .filter(document_number__startswith=prefix)
                .order_by('-document_number')
                .first()
            )
            if last:
                last_num = int(last.document_number.split('-')[-1])
                new_num = last_num + 1
            else:
                new_num = 1
            self.document_number = f"{prefix}{str(new_num).zfill(5)}"
        super().save(*args, **kwargs)

    @property
    def total_items(self):
        return self.items.count()

    @property
    def counted_items(self):
        return self.items.filter(actual_quantity__isnull=False).count()

    @property
    def discrepancy_items(self):
        return self.items.exclude(actual_quantity=models.F('system_quantity')).filter(actual_quantity__isnull=False)

    @property
    def discrepancy_count(self):
        return self.discrepancy_items.count()

    @property
    def progress_percentage(self):
        total = self.total_items
        if total == 0:
            return 0
        return int((self.counted_items / total) * 100)


class StockOpnameItem(models.Model):
    """Individual item row for a stock opname session."""

    stock_opname = models.ForeignKey(
        StockOpname,
        on_delete=models.CASCADE,
        related_name='items',
    )
    stock = models.ForeignKey(
        'stock.Stock',
        on_delete=models.PROTECT,
        related_name='opname_items',
    )
    system_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text='Snapshot of stock quantity at time of opname creation',
    )
    actual_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Actual counted quantity by staff',
    )
    notes = models.TextField(blank=True, help_text='Catatan jika ada selisih')

    class Meta:
        db_table = 'stock_opname_items'
        unique_together = ['stock_opname', 'stock']
        ordering = ['stock__item__nama_barang', 'stock__location__code']

    def __str__(self):
        return f"{self.stock.item} | Sistem: {self.system_quantity} | Aktual: {self.actual_quantity}"

    @property
    def difference(self):
        if self.actual_quantity is None:
            return None
        return self.actual_quantity - self.system_quantity

    @property
    def has_discrepancy(self):
        if self.actual_quantity is None:
            return False
        return self.actual_quantity != self.system_quantity
