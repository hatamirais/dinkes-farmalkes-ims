from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import models
from django.core.exceptions import ValidationError
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.models import TimeStampedModel


def _safe_decimal(value, default="0"):
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


class PuskesmasSBBK(TimeStampedModel):
    """Independent Puskesmas receipt document used as LPLPO penerimaan truth."""

    document_number = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        help_text="Kosongkan untuk auto-generate (SBBK-YYYYMM-XXXXX)",
    )
    facility = models.ForeignKey(
        "items.Facility",
        on_delete=models.PROTECT,
        related_name="puskesmas_sbbks",
        limit_choices_to={"facility_type": "PUSKESMAS", "is_active": True},
    )
    received_date = models.DateField(default=timezone.now)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_puskesmas_sbbks",
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
        return f"{self.document_number} – {self.facility}"

    def _get_document_number_prefix(self):
        received_date = self.received_date or timezone.localdate()
        if isinstance(received_date, str):
            received_date = date.fromisoformat(received_date)
        return f"SBBK-{received_date.strftime('%Y%m')}"

    def _generate_next_document_number(self):
        prefix = self._get_document_number_prefix()
        prefix_with_dash = f"{prefix}-"
        last = (
            PuskesmasSBBK.objects.filter(document_number__startswith=prefix_with_dash)
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
            "Unable to generate a unique Puskesmas SBBK document number after retries."
        )


class PuskesmasSBBKItem(models.Model):
    """SBBK line item; duplicate items are allowed to preserve unit-price splits."""

    sbbk = models.ForeignKey(
        PuskesmasSBBK,
        on_delete=models.CASCADE,
        related_name="items",
    )
    item = models.ForeignKey(
        "items.Item",
        on_delete=models.PROTECT,
        related_name="puskesmas_sbbk_items",
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Jumlah diterima dalam satuan utuh",
    )
    unit_price = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        help_text="Harga satuan pada SBBK",
    )
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
                "Jumlah SBBK harus berupa bilangan bulat agar sinkron dengan LPLPO."
            )

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
