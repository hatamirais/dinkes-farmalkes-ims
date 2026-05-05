from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel


class LPLPO(TimeStampedModel):
    """Header document for monthly Puskesmas stock report and request."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Diajukan"
        REVIEWED = "REVIEWED", "Ditinjau"
        DISTRIBUTED = "DISTRIBUTED", "Didistribusikan"
        CLOSED = "CLOSED", "Ditutup"

    facility = models.ForeignKey(
        "items.Facility",
        on_delete=models.PROTECT,
        related_name="lplpos",
        limit_choices_to={"facility_type": "PUSKESMAS", "is_active": True},
    )
    bulan = models.PositiveSmallIntegerField(
        help_text="Bulan periode LPLPO (1-12)",
    )
    tahun = models.PositiveIntegerField(
        help_text="Tahun periode LPLPO",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    document_number = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        help_text="Auto-generated: LPLPO-YYYYMM-XXXXX",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_lplpos",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_lplpos",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    distribution = models.OneToOneField(
        "distribution.Distribution",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lplpo_source",
        help_text="Distribution document generated from this LPLPO",
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "lplpos"
        ordering = ["-tahun", "-bulan", "facility__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["facility", "bulan", "tahun"],
                name="uq_lplpo_facility_period",
            )
        ]
        indexes = [
            models.Index(
                fields=["facility", "tahun", "bulan"],
                name="idx_lplpo_facility_period",
            ),
            models.Index(fields=["status"], name="idx_lplpo_status"),
        ]

    def __str__(self):
        return f"{self.document_number} – {self.facility} ({self.bulan}/{self.tahun})"

    @property
    def period_display(self):
        """Human-friendly period label, e.g. 'Januari 2026'."""
        import calendar

        return f"{calendar.month_name[self.bulan]} {self.tahun}"

    def save(self, *args, **kwargs):
        if not self.document_number:
            prefix = f"LPLPO-{self.tahun}{str(self.bulan).zfill(2)}-"
            last = (
                LPLPO.objects.filter(document_number__startswith=prefix)
                .order_by("-document_number")
                .first()
            )
            if last:
                try:
                    num = int(last.document_number.split("-")[-1]) + 1
                except (ValueError, IndexError):
                    num = 1
            else:
                num = 1
            self.document_number = f"{prefix}{str(num).zfill(5)}"
        super().save(*args, **kwargs)


class LPLPOItem(models.Model):
    """Line item for each drug/supply in an LPLPO document."""

    lplpo = models.ForeignKey(
        LPLPO,
        on_delete=models.CASCADE,
        related_name="items",
    )
    item = models.ForeignKey(
        "items.Item",
        on_delete=models.PROTECT,
        related_name="lplpo_items",
    )

    # === Filled by Puskesmas ===
    stock_awal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Manual on first LPLPO, auto-filled from previous month Stock Keseluruhan",
    )
    penerimaan = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Auto-filled from Distribution records, confirmable by Puskesmas",
    )

    class ProcurementSource(models.TextChoices):
        BLUD = "BLUD", "BLUD"
        APBD = "APBD", "APBD"
        BHP = "BHP", "BHP"
        HIBAH = "HIBAH", "Hibah"
        LAINNYA = "LAINNYA", "Lainnya"

    procurement_source = models.CharField(
        max_length=20,
        choices=ProcurementSource.choices,
        blank=True,
        default="",
        help_text="Sumber pengadaan untuk item ini",
    )
    pemakaian = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Filled by Puskesmas operator",
    )
    stock_gudang_puskesmas = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Physical count of Puskesmas warehouse stock",
    )
    waktu_kosong = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0,
        help_text="Stockout days in the reporting period",
    )
    permintaan_jumlah = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Requested quantity by Puskesmas",
    )
    permintaan_alasan = models.TextField(
        blank=True,
        help_text="Reason for request",
    )

    # === Computed Fields (auto-calculated, stored) ===
    persediaan = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="stock_awal + penerimaan",
    )
    stock_keseluruhan = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="persediaan - pemakaian",
    )
    stock_optimum = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="stock_keseluruhan * 1.2",
    )
    jumlah_kebutuhan = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="(stock_keseluruhan * 0.2) + waktu_kosong",
    )

    # === Filled by Instalasi Farmasi ===
    pemberian_jumlah = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Actual quantity given, system-suggested = jumlah_kebutuhan",
    )
    pemberian_alasan = models.TextField(
        blank=True,
        help_text="Reason if pemberian differs from permintaan",
    )

    # === Audit ===
    penerimaan_auto_filled = models.BooleanField(
        default=False,
        help_text="True if penerimaan was auto-filled from Distribution records",
    )

    class Meta:
        db_table = "lplpo_items"
        unique_together = [("lplpo", "item")]
        ordering = ["item__kategori__sort_order", "item__nama_barang"]

    def __str__(self):
        return f"{self.item} – {self.lplpo.document_number}"

    def compute_fields(self):
        """Recalculate all derived fields. Called automatically before save."""

        def safe(val):
            return val if val is not None else Decimal("0")

        self.persediaan = safe(self.stock_awal) + safe(self.penerimaan)
        self.stock_keseluruhan = self.persediaan - safe(self.pemakaian)
        self.stock_optimum = self.stock_keseluruhan * Decimal("1.2")
        self.jumlah_kebutuhan = (
            self.stock_keseluruhan * Decimal("0.2")
        ) + safe(self.waktu_kosong)

    def save(self, *args, **kwargs):
        self.compute_fields()
        super().save(*args, **kwargs)


# ──────────────── Helper functions ────────────────────


def get_penerimaan_for_facility_period(facility, bulan, tahun):
    """
    Returns dict: {item_id: total_quantity} for all distributions
    sent to this facility in the given month/year.
    """
    from django.db.models import Sum

    from apps.distribution.models import Distribution, DistributionItem

    distributions = Distribution.objects.filter(
        facility=facility,
        status=Distribution.Status.DISTRIBUTED,
        distributed_date__year=tahun,
        distributed_date__month=bulan,
    )
    result = {}
    items = (
        DistributionItem.objects.filter(distribution__in=distributions)
        .values("item_id")
        .annotate(total=Sum("quantity_approved"))
    )
    for row in items:
        result[row["item_id"]] = row["total"] or Decimal("0")
    return result


def get_previous_lplpo(facility, bulan, tahun):
    """Return the previous month's CLOSED LPLPO for stock_awal auto-fill."""
    prev_bulan = bulan - 1
    prev_tahun = tahun
    if prev_bulan < 1:
        prev_bulan = 12
        prev_tahun -= 1

    return (
        LPLPO.objects.filter(
            facility=facility,
            bulan=prev_bulan,
            tahun=prev_tahun,
            status=LPLPO.Status.CLOSED,
        )
        .first()
    )
