from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import models
from django.db.models import DecimalField, ExpressionWrapper, F, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.core.models import TimeStampedModel


INDONESIAN_MONTH_NAMES = {
    1: "Januari",
    2: "Februari",
    3: "Maret",
    4: "April",
    5: "Mei",
    6: "Juni",
    7: "Juli",
    8: "Agustus",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Desember",
}


def normalize_whole_number(value):
    if value in (None, ""):
        return 0
    if isinstance(value, int):
        return value
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(decimal_value.to_integral_value(rounding=ROUND_HALF_UP))


def get_active_lplpo_year(server_date=None):
    """Return the active server-calendar year for LPLPO creation rules."""
    return (server_date or timezone.localdate()).year


def get_indonesian_month_name(month):
    """Return the Indonesian month label for 1-12."""
    try:
        return INDONESIAN_MONTH_NAMES[month]
    except KeyError as exc:
        raise ValueError("Bulan harus berada pada rentang 1-12.") from exc


def format_lplpo_period_label(bulan, tahun):
    """Return a human-friendly period label for messages and help text."""
    return f"{get_indonesian_month_name(bulan)} {tahun}"


def get_next_required_lplpo_period(facility, *, server_date=None):
    """
    Return the next contiguous month that must be created for a facility.

    The sequence resets every active server-calendar year and always starts
    from January. Any existing LPLPO in that year counts toward continuity,
    regardless of workflow status.
    """
    active_year = get_active_lplpo_year(server_date)
    existing_months = set(
        LPLPO.objects.filter(facility=facility, tahun=active_year).values_list(
            "bulan", flat=True
        )
    )

    for month in range(1, 13):
        if month not in existing_months:
            return active_year, month
    return active_year, None


def is_january_bootstrap_period(bulan, tahun, *, server_date=None):
    """Return True when the period is a year's opening January LPLPO.

    The bootstrap status is stable and does not change after a server-year
    rollover — any January document remains the opening-balance baseline for
    its own year regardless of the current server date.
    """
    return bulan == 1


class LPLPO(TimeStampedModel):
    """Header document for monthly Puskesmas stock report and request."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Diajukan"
        PIC_VERIFIED = "PIC_VERIFIED", "Terverifikasi PIC"
        REJECTED_PUSKESMAS = "REJECTED_PUSKESMAS", "Ditolak ke Puskesmas"
        REVIEWED = "REVIEWED", "Ditinjau PIC"
        REJECTED_PIC = "REJECTED_PIC", "Revisi Tinjauan PIC"
        APPROVED = "APPROVED", "Siap Distribusi"
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
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="verified_lplpos",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_lplpos",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_lplpos",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
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
        return f"{get_indonesian_month_name(self.bulan)} {self.tahun}"

    @property
    def is_january_bootstrap(self):
        """True when this document is the active-year January opening baseline."""
        return is_january_bootstrap_period(self.bulan, self.tahun)

    @property
    def is_rejected_for_puskesmas(self):
        return self.status == self.Status.REJECTED_PUSKESMAS

    @property
    def is_rejected_for_pic(self):
        return self.status == self.Status.REJECTED_PIC

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
    stock_awal = models.IntegerField(
        default=0,
        help_text=(
            "Manual on first LPLPO, auto-filled from previous month Stock "
            "Keseluruhan and may be negative when the prior month closed below zero"
        ),
    )
    penerimaan = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Auto-suggested from same-month Puskesmas receipt confirmations "
            "when available, confirmable by Puskesmas"
        ),
    )
    harga_satuan = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0,
        help_text=(
            "January may be suggested from same-month confirmed receipt "
            "confirmations; later periods use same-month weighted-average receipt "
            "prices or carry forward the previous month's price"
        ),
    )
    pemakaian = models.PositiveIntegerField(
        default=0,
        help_text="Filled by Puskesmas operator",
    )
    stock_gudang_puskesmas = models.PositiveIntegerField(
        default=0,
        help_text="Physical count of Puskesmas warehouse stock",
    )
    waktu_kosong = models.PositiveSmallIntegerField(
        default=0,
        help_text="Stockout days in the reporting period",
    )
    permintaan_jumlah = models.PositiveIntegerField(
        default=0,
        help_text="Requested quantity by Puskesmas",
    )
    permintaan_alasan = models.TextField(
        blank=True,
        help_text="Reason for request",
    )

    # === Computed Fields (auto-calculated, stored) ===
    persediaan = models.IntegerField(
        default=0,
        help_text="stock_awal + penerimaan",
    )
    stock_keseluruhan = models.IntegerField(
        default=0,
        help_text="persediaan - pemakaian",
    )
    stock_optimum = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="pemakaian * 1.2",
    )
    jumlah_kebutuhan = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="max(stock_optimum - stock_keseluruhan, 0) + waktu_kosong",
    )

    # === Filled by Instalasi Farmasi ===
    pemberian_jumlah = models.PositiveIntegerField(
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
        help_text=(
            "True if penerimaan was auto-filled from same-month Puskesmas "
            "receipt confirmations"
        ),
    )

    class Meta:
        db_table = "lplpo_items"
        unique_together = [("lplpo", "item")]
        ordering = ["item__kategori__sort_order", "item__nama_barang"]

    def __str__(self):
        return f"{self.item} – {self.lplpo.document_number}"

    def compute_fields(self):
        """Recalculate all derived fields. Called automatically before save."""

        def safe_int(val):
            return normalize_whole_number(val)

        self.persediaan = (
            safe_int(self.stock_awal)
            + safe_int(self.penerimaan)
        )
        self.stock_keseluruhan = self.persediaan - safe_int(self.pemakaian)
        # Stok optimum follows the consumption method: monthly usage plus a
        # 20 percent buffer, independent from the ending stock position.
        replenishment_basis = Decimal(safe_int(self.pemakaian))
        self.stock_optimum = replenishment_basis * Decimal("1.20")
        required_replenishment = self.stock_optimum - Decimal(self.stock_keseluruhan)
        if required_replenishment < Decimal("0"):
            required_replenishment = Decimal("0")
        self.jumlah_kebutuhan = required_replenishment + Decimal(
            safe_int(self.waktu_kosong)
        )

    @property
    def nilai_stok_awal(self):
        return Decimal(self.stock_awal or 0) * (self.harga_satuan or Decimal("0"))

    @property
    def nilai_penerimaan(self):
        return Decimal(self.penerimaan or 0) * (self.harga_satuan or Decimal("0"))

    @property
    def nilai_pemakaian(self):
        return Decimal(self.pemakaian or 0) * (self.harga_satuan or Decimal("0"))

    @property
    def nilai_stock_keseluruhan(self):
        return Decimal(self.stock_keseluruhan or 0) * (
            self.harga_satuan or Decimal("0")
        )

    def save(self, *args, **kwargs):
        self.compute_fields()
        super().save(*args, **kwargs)


# ──────────────── Helper functions ────────────────────


def get_penerimaan_for_facility_period(facility, bulan, tahun):
    """
    Returns dict: {item_id: total_quantity} from Puskesmas receipt-confirmation rows
    for the given facility/month/year.
    """
    from apps.puskesmas.models import PuskesmasReceiptConfirmationItem

    result = {}
    items = (
        PuskesmasReceiptConfirmationItem.objects.filter(
            sbbk__facility=facility,
            sbbk__received_date__year=tahun,
            sbbk__received_date__month=bulan,
            sbbk__status="CONFIRMED",
        )
        .values("item_id")
        .annotate(total=Sum("quantity"))
    )
    for row in items:
        result[row["item_id"]] = normalize_whole_number(row["total"])
    return result


def get_penerimaan_unit_prices_for_facility_period(facility, bulan, tahun):
    """Return weighted-average incoming prices per item from receipt-confirmation rows."""
    from apps.puskesmas.models import PuskesmasReceiptConfirmationItem

    value_expression = ExpressionWrapper(
        Coalesce(F("quantity"), Value(0))
        * Coalesce(F("unit_price"), Value(0)),
        output_field=DecimalField(max_digits=18, decimal_places=2),
    )
    rows = (
        PuskesmasReceiptConfirmationItem.objects.filter(
            sbbk__facility=facility,
            sbbk__received_date__year=tahun,
            sbbk__received_date__month=bulan,
            sbbk__status="CONFIRMED",
        )
        .values("item_id")
        .annotate(
            total_quantity=Coalesce(
                Sum("quantity"),
                Value(0, output_field=DecimalField(max_digits=12, decimal_places=2)),
            ),
            total_value=Coalesce(
                Sum(value_expression),
                Value(0, output_field=DecimalField(max_digits=18, decimal_places=2)),
            ),
        )
    )

    result = {}
    for row in rows:
        total_quantity = row["total_quantity"] or Decimal("0")
        if total_quantity <= 0:
            continue
        result[row["item_id"]] = (
            (row["total_value"] or Decimal("0")) / total_quantity
        ).quantize(Decimal("0.01"))
    return result


def sync_receiving_to_editable_lplpo(*, facility, bulan, tahun):
    """Recompute draft/rejected LPLPO penerimaan and harga_satuan from receipt data."""
    lplpo = (
        LPLPO.objects.select_for_update()
        .filter(
            facility=facility,
            bulan=bulan,
            tahun=tahun,
            status__in=[LPLPO.Status.DRAFT, LPLPO.Status.REJECTED_PUSKESMAS],
        )
        .first()
    )
    if not lplpo:
        return None

    penerimaan_data = get_penerimaan_for_facility_period(facility, bulan, tahun)
    harga_satuan_data = get_penerimaan_unit_prices_for_facility_period(
        facility, bulan, tahun
    )

    prev_lplpo = get_previous_lplpo(facility, bulan, tahun)
    prev_unit_prices = {}
    if prev_lplpo and not is_january_bootstrap_period(bulan, tahun):
        for prev_item in prev_lplpo.items.only("item_id", "harga_satuan"):
            prev_unit_prices[prev_item.item_id] = prev_item.harga_satuan

    items_to_update = []
    for line in lplpo.items.all():
        line.penerimaan = penerimaan_data.get(line.item_id, 0)
        line.penerimaan_auto_filled = line.item_id in penerimaan_data
        line.harga_satuan = harga_satuan_data.get(
            line.item_id,
            prev_unit_prices.get(line.item_id, line.harga_satuan or Decimal("0")),
        )
        line.compute_fields()
        items_to_update.append(line)

    if items_to_update:
        LPLPOItem.objects.bulk_update(
            items_to_update,
            [
                "penerimaan",
                "penerimaan_auto_filled",
                "harga_satuan",
                "persediaan",
                "stock_keseluruhan",
                "stock_optimum",
                "jumlah_kebutuhan",
            ],
        )

    return lplpo


# Temporary compatibility alias while the Puskesmas module is migrated.
sync_sbbk_to_editable_lplpo = sync_receiving_to_editable_lplpo


def get_previous_lplpo(facility, bulan, tahun):
    """Return the previous month's usable LPLPO for stock_awal auto-fill."""
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
        )
        .exclude(status__in=[LPLPO.Status.REJECTED_PUSKESMAS, LPLPO.Status.REJECTED_PIC])
        .first()
    )
