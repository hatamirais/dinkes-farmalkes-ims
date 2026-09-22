import string
import unicodedata

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base model with created_at and updated_at timestamps."""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SystemSettings(TimeStampedModel):
    """
    Singleton model to hold dynamic system settings (facility name, logo, etc.).
    """
    platform_label = models.CharField(
        max_length=255,
        default="Healthcare Inventory Platform",
        help_text="Label singkat untuk branding aplikasi, misalnya badge di halaman login.",
    )
    facility_name = models.CharField(max_length=255, default="Healthcare Inventory Management System")
    facility_address = models.TextField(blank=True)
    facility_phone = models.CharField(max_length=50, blank=True)
    header_title = models.CharField(max_length=255, default="KEMENTERIAN KESEHATAN REPUBLIK INDONESIA")
    logo = models.ImageField(upload_to="settings/", blank=True, null=True, help_text="Biarkan kosong jika tidak ada logo khusus. Gunakan gambar transparan (PNG) untuk hasil terbaik.")

    class Meta:
        verbose_name = "System Settings"
        verbose_name_plural = "System Settings"

    @classmethod
    def get_settings(cls):
        obj, created = cls.objects.get_or_create(id=1)
        return obj

    def save(self, *args, **kwargs):
        self.id = 1  # Force id to 1 for singleton
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Settings for {self.facility_name}"


class DocumentNumberRule(TimeStampedModel):
    """User-configurable formatting for one system-owned document family."""

    class Key(models.TextChoices):
        ALLOCATION = "ALLOCATION", "Alokasi"
        DISTRIBUTION_LPLPO = "DISTRIBUTION_LPLPO", "Distribusi LPLPO"
        DISTRIBUTION_SPECIAL_REQUEST = (
            "DISTRIBUTION_SPECIAL_REQUEST",
            "Permintaan Khusus",
        )
        PROCUREMENT_CONTRACT = "PROCUREMENT_CONTRACT", "SPJ / Kontrak"
        PROCUREMENT_AMENDMENT = "PROCUREMENT_AMENDMENT", "Amandemen SPJ"
        RECEIVING = "RECEIVING", "Penerimaan"
        RECALL = "RECALL", "Recall"
        EXPIRED = "EXPIRED", "Kedaluwarsa"
        STOCK_TRANSFER = "STOCK_TRANSFER", "Mutasi Lokasi"
        STOCK_OPNAME = "STOCK_OPNAME", "Stock Opname"

    class ResetPeriod(models.TextChoices):
        NEVER = "NEVER", "Tidak pernah"
        YEARLY = "YEARLY", "Tahunan"
        MONTHLY = "MONTHLY", "Bulanan"

    key = models.CharField(max_length=64, choices=Key.choices, unique=True)
    label = models.CharField(max_length=100)
    template = models.CharField(max_length=255)
    reset_period = models.CharField(
        max_length=10,
        choices=ResetPeriod.choices,
        default=ResetPeriod.YEARLY,
    )
    padding = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
        help_text="Jumlah minimum digit nomor urut.",
    )

    class Meta:
        db_table = "document_number_rules"
        ordering = ["label", "key"]

    def __str__(self):
        return self.label

    @property
    def allowed_tokens(self):
        return {"seq", "year", "month"}

    def clean(self):
        super().clean()
        template = unicodedata.normalize("NFC", (self.template or "").strip())
        if not template:
            raise ValidationError({"template": "Template nomor dokumen wajib diisi."})
        if "\x00" in template:
            raise ValidationError({"template": "Template tidak boleh memuat karakter null."})

        try:
            parsed = list(string.Formatter().parse(template))
        except ValueError as exc:
            raise ValidationError({"template": "Kurung kurawal pada template tidak valid."}) from exc

        fields = []
        for _literal, field_name, format_spec, conversion in parsed:
            if field_name is None:
                continue
            if format_spec or conversion:
                raise ValidationError(
                    {"template": "Format dan konversi placeholder tidak didukung."}
                )
            fields.append(field_name)

        unknown = sorted(set(fields) - self.allowed_tokens)
        if unknown:
            raise ValidationError(
                {"template": f"Placeholder tidak didukung: {', '.join(unknown)}."}
            )
        if fields.count("seq") != 1:
            raise ValidationError(
                {"template": "Template harus memuat {seq} tepat satu kali."}
            )
        if self.reset_period == self.ResetPeriod.YEARLY and fields.count("year") != 1:
            raise ValidationError(
                {"template": "Rule tahunan harus memuat {year} tepat satu kali."}
            )
        if self.reset_period == self.ResetPeriod.MONTHLY and (
            fields.count("year") != 1 or fields.count("month") != 1
        ):
            raise ValidationError(
                {
                    "template": (
                        "Rule bulanan harus memuat {year} dan {month}, "
                        "masing-masing tepat satu kali."
                    )
                }
            )
        sample_values = {
            "seq": "9" * self.padding,
            "year": "2026",
            "month": "09",
        }
        try:
            sample = template.format(**sample_values)
        except (KeyError, ValueError) as exc:
            raise ValidationError({"template": "Template nomor dokumen tidak valid."}) from exc
        max_length = 100
        if len(sample) > max_length:
            raise ValidationError(
                {
                    "template": (
                        f"Hasil template contoh melebihi batas {max_length} karakter."
                    )
                }
            )

        self.template = template
        self.label = unicodedata.normalize("NFC", (self.label or "").strip())


class DocumentNumberSequence(models.Model):
    """Internal counter; users configure rules, never counter values."""

    rule = models.ForeignKey(
        DocumentNumberRule,
        on_delete=models.PROTECT,
        related_name="sequences",
    )
    period_key = models.CharField(max_length=6, blank=True)
    scope_key = models.CharField(max_length=191, blank=True)
    last_value = models.PositiveBigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "document_number_sequences"
        constraints = [
            models.UniqueConstraint(
                fields=["rule", "period_key", "scope_key"],
                name="uq_doc_number_sequence_scope",
            )
        ]

    def __str__(self):
        return f"{self.rule.key}:{self.period_key}:{self.scope_key}={self.last_value}"


class DocumentNumberIssue(TimeStampedModel):
    """Immutable issuance identity plus explicit void state for official numbers."""

    class Status(models.TextChoices):
        ISSUED = "ISSUED", "Diterbitkan"
        VOID = "VOID", "Dibatalkan"

    rule = models.ForeignKey(
        DocumentNumberRule,
        on_delete=models.PROTECT,
        related_name="issues",
    )
    document_number = models.CharField(max_length=100)
    sequence_value = models.PositiveBigIntegerField()
    period_key = models.CharField(max_length=6, blank=True)
    scope_key = models.CharField(max_length=191, blank=True)
    business_date = models.DateField()
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ISSUED,
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.PositiveBigIntegerField()
    target = GenericForeignKey("content_type", "object_id")
    target_label = models.CharField(max_length=255, blank=True)
    rule_label_snapshot = models.CharField(max_length=100)
    template_snapshot = models.CharField(max_length=255)
    reset_period_snapshot = models.CharField(max_length=10)
    padding_snapshot = models.PositiveSmallIntegerField()
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="document_numbers_issued",
    )
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="document_numbers_voided",
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.TextField(blank=True)

    class Meta:
        db_table = "document_number_issues"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["rule", "document_number"],
                name="uq_doc_number_issue_rule_number",
            ),
            models.UniqueConstraint(
                fields=["content_type", "object_id"],
                name="uq_doc_number_issue_target",
            ),
        ]
        indexes = [
            models.Index(
                fields=["business_date", "status"],
                name="idx_doc_issue_date_status",
            ),
            models.Index(
                fields=["content_type", "object_id"],
                name="idx_doc_issue_target",
            ),
        ]

    def __str__(self):
        return self.document_number
