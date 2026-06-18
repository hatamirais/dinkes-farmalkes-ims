import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import models
from django.core.exceptions import ValidationError
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.core.models import TimeStampedModel


def _safe_decimal(value, default="0"):
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _normalize_text_value(value):
    if value in (None, ""):
        return ""
    normalized = unicodedata.normalize("NFC", str(value)).strip()
    if "\x00" in normalized:
        raise ValidationError("Teks tidak boleh mengandung null byte.")
    return normalized


def get_distribution_item_source_quantity(distribution_item):
    if distribution_item is None:
        return None
    if distribution_item.quantity_approved is not None:
        return distribution_item.quantity_approved
    return distribution_item.quantity_requested


class PuskesmasReceiptConfirmation(TimeStampedModel):
    """Receiver-side confirmation for one delivered distribution event."""

    class ReceiptStatus(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        CONFIRMED = "CONFIRMED", "Terkonfirmasi"

    document_number = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        help_text="Kosongkan untuk auto-generate (RCVCONF-YYYYMM-XXXXX)",
    )
    facility = models.ForeignKey(
        "items.Facility",
        on_delete=models.PROTECT,
        related_name="puskesmas_receipt_confirmations",
        limit_choices_to={"facility_type": "PUSKESMAS", "is_active": True},
    )
    distribution = models.OneToOneField(
        "distribution.Distribution",
        on_delete=models.PROTECT,
        related_name="receipt_confirmation",
        null=True,
        blank=True,
        help_text="Dokumen distribusi yang dikonfirmasi diterima oleh Puskesmas.",
    )
    received_date = models.DateField(default=timezone.now)
    status = models.CharField(
        max_length=20,
        choices=ReceiptStatus.choices,
        default=ReceiptStatus.DRAFT,
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_puskesmas_receipt_confirmations",
    )

    class Meta:
        db_table = "puskesmas_sbbks"
        ordering = ["-received_date", "-created_at"]
        indexes = [
            models.Index(
                fields=["facility", "received_date"], name="idx_sbbk_facility_date"
            ),
        ]

    def __str__(self):
        distribution_number = (
            getattr(self.distribution, "document_number", "") if self.distribution_id else ""
        )
        if distribution_number:
            return f"{self.document_number} – {self.facility} / {distribution_number}"
        return f"{self.document_number} – {self.facility}"

    @property
    def distribution_line_count(self):
        if not self.distribution_id:
            return self.items.count()
        return self.distribution.items.count()

    @property
    def confirmed_line_count(self):
        return self.items.count()

    @property
    def is_complete(self):
        if self.status != self.ReceiptStatus.CONFIRMED:
            return False
        if not self.distribution_id:
            return True
        return self.confirmed_line_count >= self.distribution_line_count

    def _get_document_number_prefix(self):
        received_date = self.received_date or timezone.localdate()
        if isinstance(received_date, str):
            received_date = date.fromisoformat(received_date)
        return f"RCVCONF-{received_date.strftime('%Y%m')}"

    def _generate_next_document_number(self):
        prefix = self._get_document_number_prefix()
        prefix_with_dash = f"{prefix}-"
        last = (
            PuskesmasReceiptConfirmation.objects.filter(
                document_number__startswith=prefix_with_dash
            )
            .order_by("-document_number")
            .first()
        )
        if last:
            try:
                last_num = int(last.document_number.split("-")[-1])
            except (ValueError, IndexError):
                last_num = 0
            new_num = last_num + 1
        else:
            new_num = 1
        return f"{prefix_with_dash}{str(new_num).zfill(5)}"

    def save(self, *args, **kwargs):
        self.notes = _normalize_text_value(self.notes)
        if self.distribution_id and not self.received_date:
            self.received_date = self.distribution.distributed_date or timezone.localdate()
        if self.pk or self.document_number:
            return super().save(*args, **kwargs)

        for _attempt in range(5):
            self.document_number = self._generate_next_document_number()
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError:
                self.document_number = ""

        raise IntegrityError(
            "Unable to generate a unique Puskesmas receipt confirmation number after retries."
        )

    def clean(self):
        super().clean()

        errors = {}
        if self.facility_id and self.facility.facility_type != "PUSKESMAS":
            errors["facility"] = (
                "Konfirmasi penerimaan hanya boleh terhubung ke fasilitas Puskesmas."
            )

        if self.received_date and not (1000 <= self.received_date.year <= 9999):
            errors["received_date"] = "Tahun tanggal tidak valid."

        if self.distribution_id:
            if self.distribution.facility_id != self.facility_id:
                errors["distribution"] = (
                    "Distribusi harus ditujukan ke fasilitas yang sama."
                )
            if self.distribution.status != self.distribution.Status.DISTRIBUTED:
                errors["distribution"] = (
                    "Hanya distribusi berstatus terdistribusi yang dapat dikonfirmasi."
                )

        if self.status not in self.ReceiptStatus.values:
            errors["status"] = "Status konfirmasi penerimaan tidak valid."

        try:
            normalized_notes = _normalize_text_value(self.notes)
        except ValidationError as exc:
            errors["notes"] = exc.messages[0]
            normalized_notes = ""

        if normalized_notes and len(normalized_notes) > 1000:
            errors["notes"] = "Catatan tidak boleh lebih dari 1000 karakter."

        if errors:
            raise ValidationError(errors)


class PuskesmasReceiptConfirmationItem(models.Model):
    """Receiver-side confirmation row; duplicates preserve batch or price splits."""

    sbbk = models.ForeignKey(
        PuskesmasReceiptConfirmation,
        on_delete=models.CASCADE,
        related_name="items",
    )
    distribution_item = models.ForeignKey(
        "distribution.DistributionItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="receipt_confirmation_items",
    )
    item = models.ForeignKey(
        "items.Item",
        on_delete=models.PROTECT,
        related_name="puskesmas_receipt_confirmation_items",
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Jumlah diterima dalam satuan utuh",
    )
    unit_price = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        help_text="Harga satuan aktual yang diterima Puskesmas",
    )
    batch_lot = models.CharField(max_length=100, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "puskesmas_sbbk_items"
        ordering = ["id"]

    def __str__(self):
        return f"{self.item} × {self.quantity}"

    @property
    def total_price(self):
        return _safe_decimal(self.quantity) * _safe_decimal(self.unit_price)

    def clean(self):
        super().clean()

        errors = {}
        parent_distribution_id = None
        if getattr(self, "sbbk", None) is not None:
            parent_distribution_id = self.sbbk.distribution_id
        try:
            quantity = (
                self.quantity
                if isinstance(self.quantity, Decimal)
                else Decimal(str(self.quantity))
            )
        except (InvalidOperation, TypeError, ValueError):
            quantity = None

        if quantity is None or quantity <= 0:
            errors["quantity"] = "Jumlah harus lebih dari 0."
        elif quantity != quantity.to_integral_value():
            errors["quantity"] = (
                "Jumlah penerimaan harus berupa bilangan bulat agar sinkron dengan LPLPO."
            )

        if self.unit_price is None:
            errors["unit_price"] = "Harga satuan wajib diisi."
        else:
            unit_price = _safe_decimal(self.unit_price, default=None)
            if unit_price is None or unit_price < 0:
                errors["unit_price"] = "Harga satuan tidak boleh kurang dari 0."

        if self.expiry_date and not (1000 <= self.expiry_date.year <= 9999):
            errors["expiry_date"] = "Tahun tanggal kedaluwarsa tidak valid."

        try:
            normalized_notes = _normalize_text_value(self.notes)
        except ValidationError as exc:
            errors["notes"] = exc.messages[0]
            normalized_notes = ""

        if normalized_notes and len(normalized_notes) > 255:
            errors["notes"] = "Keterangan tidak boleh lebih dari 255 karakter."

        if self.distribution_item_id:
            if parent_distribution_id and (
                self.distribution_item.distribution_id != parent_distribution_id
            ):
                errors["distribution_item"] = (
                    "Baris distribusi harus berasal dari dokumen distribusi yang sama."
                )
            if self.distribution_item.item_id != self.item_id:
                errors["item"] = "Barang harus sama dengan baris distribusi yang dipilih."

        if self.distribution_item_id and quantity is not None:
            source_batch = self.distribution_item.issued_batch_lot or ""
            source_expiry = self.distribution_item.issued_expiry_date
            source_price = self.distribution_item.issued_unit_price
            source_quantity = get_distribution_item_source_quantity(
                self.distribution_item
            )
            if (
                _safe_decimal(source_quantity) != _safe_decimal(quantity)
                or source_batch != (self.batch_lot or "")
                or source_expiry != self.expiry_date
                or _safe_decimal(source_price) != _safe_decimal(self.unit_price)
            ) and not normalized_notes:
                errors["notes"] = (
                    "Isi keterangan penyesuaian bila detail penerimaan berbeda dari distribusi."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.batch_lot = _normalize_text_value(self.batch_lot)
        self.notes = _normalize_text_value(self.notes)
        super().save(*args, **kwargs)


# Temporary compatibility aliases while the surrounding forms/views/tests are updated.
PuskesmasSBBK = PuskesmasReceiptConfirmation
PuskesmasSBBKItem = PuskesmasReceiptConfirmationItem


class PuskesmasSubunit(TimeStampedModel):
    """Facility-specific treatment room or helper-site reporting bucket."""

    class SubunitType(models.TextChoices):
        TREATMENT_ROOM = "TREATMENT_ROOM", "Ruang Tindakan"
        HELPER_SITE = "HELPER_SITE", "Puskesmas Pembantu"

    facility = models.ForeignKey(
        "items.Facility",
        on_delete=models.PROTECT,
        related_name="puskesmas_subunits",
        limit_choices_to={"facility_type": "PUSKESMAS", "is_active": True},
    )
    name = models.CharField(max_length=120)
    subunit_type = models.CharField(
        max_length=20,
        choices=SubunitType.choices,
    )
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "puskesmas_subunits"
        ordering = ["facility__name", "sort_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["facility", "name"],
                name="uq_pksubunit_facility_name",
            ),
        ]
        indexes = [
            models.Index(
                fields=["facility", "is_active", "sort_order"],
                name="idx_pksubunit_facility_active",
            ),
        ]

    def __str__(self):
        return f"{self.facility} - {self.name}"

    def clean(self):
        super().clean()
        errors = {}

        if self.facility_id and self.facility.facility_type != "PUSKESMAS":
            errors["facility"] = "Subunit hanya boleh terhubung ke fasilitas Puskesmas."

        try:
            normalized_name = _normalize_text_value(self.name)
        except ValidationError as exc:
            errors["name"] = exc.messages[0]
            normalized_name = ""

        if normalized_name and len(normalized_name) > 120:
            errors["name"] = "Nama subunit tidak boleh lebih dari 120 karakter."

        duplicate_qs = PuskesmasSubunit.objects.filter(
            facility=self.facility,
            name__iexact=normalized_name,
        )
        if self.pk:
            duplicate_qs = duplicate_qs.exclude(pk=self.pk)
        if normalized_name and duplicate_qs.exists():
            errors["name"] = "Nama subunit sudah digunakan pada fasilitas ini."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.name = _normalize_text_value(self.name)
        super().save(*args, **kwargs)


class PuskesmasConsumption(TimeStampedModel):
    """Monthly detailed consumption header for one Puskesmas."""

    facility = models.ForeignKey(
        "items.Facility",
        on_delete=models.PROTECT,
        related_name="puskesmas_consumptions",
        limit_choices_to={"facility_type": "PUSKESMAS", "is_active": True},
    )
    bulan = models.PositiveSmallIntegerField()
    tahun = models.PositiveIntegerField()
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_puskesmas_consumptions",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_puskesmas_consumptions",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "puskesmas_consumptions"
        ordering = ["-tahun", "-bulan", "facility__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["facility", "bulan", "tahun"],
                name="uq_pkconsumption_facility_period",
            )
        ]
        indexes = [
            models.Index(
                fields=["facility", "tahun", "bulan"],
                name="idx_pkcons_fac_period",
            ),
        ]

    def __str__(self):
        return f"{self.facility} - {self.bulan:02d}/{self.tahun}"

    def clean(self):
        super().clean()
        errors = {}

        if self.facility_id and self.facility.facility_type != "PUSKESMAS":
            errors["facility"] = "Pemakaian hanya boleh terhubung ke fasilitas Puskesmas."
        if self.bulan and not 1 <= self.bulan <= 12:
            errors["bulan"] = "Bulan harus berada pada rentang 1-12."
        if self.tahun and not 1000 <= self.tahun <= 9999:
            errors["tahun"] = "Tahun harus berada pada rentang 1000-9999."
        try:
            normalized_notes = _normalize_text_value(self.notes)
        except ValidationError as exc:
            errors["notes"] = exc.messages[0]
            normalized_notes = ""
        if normalized_notes and len(normalized_notes) > 1000:
            errors["notes"] = "Catatan tidak boleh lebih dari 1000 karakter."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.notes = _normalize_text_value(self.notes)
        super().save(*args, **kwargs)

    @property
    def total_consumption(self):
        aggregated = self.entries.aggregate(
            total=Coalesce(Sum("quantity"), 0)
        )
        return int(aggregated["total"] or 0)


class PuskesmasConsumptionEntry(models.Model):
    """Normalized item-by-subunit monthly consumption row."""

    consumption = models.ForeignKey(
        PuskesmasConsumption,
        on_delete=models.CASCADE,
        related_name="entries",
    )
    item = models.ForeignKey(
        "items.Item",
        on_delete=models.PROTECT,
        related_name="puskesmas_consumption_entries",
    )
    subunit = models.ForeignKey(
        PuskesmasSubunit,
        on_delete=models.PROTECT,
        related_name="consumption_entries",
    )
    quantity = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "puskesmas_consumption_entries"
        ordering = ["item__kategori__sort_order", "item__nama_barang", "subunit__sort_order", "subunit__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["consumption", "item", "subunit"],
                name="uq_pkconsentry_doc_item_subunit",
            )
        ]

    def __str__(self):
        return f"{self.consumption} - {self.item} - {self.subunit}"

    def clean(self):
        super().clean()
        errors = {}

        quantity = self.quantity
        if isinstance(quantity, Decimal):
            if quantity != quantity.to_integral_value():
                errors["quantity"] = "Jumlah pemakaian harus berupa bilangan bulat."
            quantity = int(quantity)
        elif quantity is None:
            errors["quantity"] = "Jumlah pemakaian wajib diisi."

        if quantity is not None and int(quantity) < 0:
            errors["quantity"] = "Jumlah pemakaian tidak boleh negatif."

        if self.consumption_id and self.subunit_id:
            if self.subunit.facility_id != self.consumption.facility_id:
                errors["subunit"] = "Subunit harus berasal dari fasilitas yang sama."

        if errors:
            raise ValidationError(errors)


class PuskesmasRequest(TimeStampedModel):
    """Ad-hoc item request from a Puskesmas to the Dinas (mostly program items)."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Diajukan"
        APPROVED = "APPROVED", "Disetujui"
        REJECTED = "REJECTED", "Ditolak"

    document_number = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        help_text="Kosongkan untuk auto-generate (REQ-YYYYMM-XXXXX)",
    )
    facility = models.ForeignKey(
        "items.Facility",
        on_delete=models.PROTECT,
        related_name="puskesmas_requests",
        limit_choices_to={"facility_type": "PUSKESMAS", "is_active": True},
    )
    request_date = models.DateField(default=timezone.now)
    program = models.ForeignKey(
        "items.Program",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="puskesmas_requests",
        help_text="Program kesehatan terkait (opsional, e.g. TB, HIV, Malaria)",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_puskesmas_requests",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_puskesmas_requests",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    # Distribution generated on approval
    distribution = models.OneToOneField(
        "distribution.Distribution",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="puskesmas_request",
    )

    class Meta:
        db_table = "puskesmas_requests"
        ordering = ["-request_date", "-created_at"]
        indexes = [
            models.Index(
                fields=["status", "request_date"], name="idx_pkreq_status_date"
            ),
            models.Index(
                fields=["facility", "request_date"], name="idx_pkreq_facility_date"
            ),
        ]

    def __str__(self):
        return f"{self.document_number} – {self.facility}"

    def save(self, *args, **kwargs):
        if not self.document_number:
            prefix = f"REQ-{timezone.now().strftime('%Y%m')}-"
            last = (
                PuskesmasRequest.objects.filter(document_number__startswith=prefix)
                .order_by("-document_number")
                .first()
            )
            if last:
                try:
                    last_num = int(last.document_number.split("-")[-1])
                except (ValueError, IndexError):
                    last_num = 0
                new_num = last_num + 1
            else:
                new_num = 1
            self.document_number = f"{prefix}{str(new_num).zfill(5)}"
        super().save(*args, **kwargs)


class PuskesmasRequestItem(models.Model):
    """Line item for a Puskesmas item request."""

    request = models.ForeignKey(
        PuskesmasRequest,
        on_delete=models.CASCADE,
        related_name="items",
    )
    item = models.ForeignKey(
        "items.Item",
        on_delete=models.PROTECT,
        related_name="puskesmas_request_items",
    )
    quantity_requested = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Jumlah yang diminta",
    )
    quantity_approved = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Jumlah yang disetujui (diisi saat approval)",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "puskesmas_request_items"
        ordering = ["id"]

    def __str__(self):
        return f"{self.item} × {self.quantity_requested}"
