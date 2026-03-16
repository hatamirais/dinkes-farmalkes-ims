from django.db import models
from django.conf import settings
from django.utils import timezone
from apps.core.models import TimeStampedModel


class ReceivingTypeOption(TimeStampedModel):
    """Custom receiving type options managed from form quick-create."""

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "receiving_type_options"
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} - {self.name}"

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().upper()
        self.name = (self.name or "").strip()
        super().save(*args, **kwargs)


class Receiving(TimeStampedModel):
    """Document for incoming stock (procurement or grants)."""

    class ReceivingType(models.TextChoices):
        PROCUREMENT = "PROCUREMENT", "Pengadaan"
        GRANT = "GRANT", "Hibah"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Diajukan"
        APPROVED = "APPROVED", "Disetujui"
        PARTIAL = "PARTIAL", "Diterima Sebagian"
        RECEIVED = "RECEIVED", "Diterima Lengkap"
        CLOSED = "CLOSED", "Ditutup"
        VERIFIED = "VERIFIED", "Terverifikasi"

    receiving_type = models.CharField(max_length=20, choices=ReceivingType.choices)
    document_number = models.CharField(max_length=100, unique=True, blank=True)
    receiving_date = models.DateField()
    is_planned = models.BooleanField(default=False)
    supplier = models.ForeignKey(
        "items.Supplier",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="receivings",
        help_text="Required for PROCUREMENT type",
    )
    grant_origin = models.CharField(
        max_length=100,
        blank=True,
        help_text="Province, Ministry, Donation (for GRANT type)",
    )
    program = models.CharField(max_length=100, blank=True)
    sumber_dana = models.ForeignKey(
        "items.FundingSource",
        on_delete=models.PROTECT,
        related_name="receivings",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_receivings",
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="verified_receivings",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_receivings",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="closed_receivings",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "receivings"
        ordering = ["-receiving_date"]
        indexes = [
            models.Index(
                fields=["status", "receiving_date"], name="idx_recv_status_date"
            ),
        ]

    def __str__(self):
        return f"{self.document_number} ({self.get_receiving_type_display()})"

    @property
    def receiving_type_label(self):
        builtin_map = dict(self.ReceivingType.choices)
        if self.receiving_type in builtin_map:
            return builtin_map[self.receiving_type]

        custom_label = (
            ReceivingTypeOption.objects.filter(code=self.receiving_type, is_active=True)
            .values_list("name", flat=True)
            .first()
        )
        return custom_label or self.receiving_type

    @staticmethod
    def generate_document_number():
        year = timezone.now().year
        prefix = f"RCV-{year}-"
        last = (
            Receiving.objects.filter(document_number__startswith=prefix)
            .order_by("-document_number")
            .values_list("document_number", flat=True)
            .first()
        )
        if last:
            try:
                num = int(last.split("-")[-1]) + 1
            except (ValueError, IndexError):
                num = 1
        else:
            num = 1
        return f"{prefix}{num:05d}"

    def save(self, *args, **kwargs):
        if not self.document_number:
            self.document_number = self.generate_document_number()
        super().save(*args, **kwargs)


class ReceivingItem(models.Model):
    """Line items for each receiving document."""

    receiving = models.ForeignKey(
        Receiving,
        on_delete=models.CASCADE,
        related_name="items",
    )
    order_item = models.ForeignKey(
        "receiving.ReceivingOrderItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="receipt_items",
    )
    item = models.ForeignKey(
        "items.Item",
        on_delete=models.PROTECT,
        related_name="receiving_items",
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    batch_lot = models.CharField(max_length=100)
    expiry_date = models.DateField()
    unit_price = models.DecimalField(max_digits=15, decimal_places=2)
    location = models.ForeignKey(
        "items.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="receiving_items",
    )
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="received_items",
    )
    received_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "receiving_items"

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
        related_name="documents",
    )
    file = models.FileField(upload_to="receiving/%Y/%m/")
    file_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=50, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "receiving_documents"

    def __str__(self):
        return self.file_name


class ReceivingOrderItem(TimeStampedModel):
    """Planned order line items (target quantities)."""

    receiving = models.ForeignKey(
        Receiving,
        on_delete=models.CASCADE,
        related_name="order_items",
    )
    item = models.ForeignKey(
        "items.Item",
        on_delete=models.PROTECT,
        related_name="receiving_order_items",
    )
    planned_quantity = models.DecimalField(max_digits=12, decimal_places=2)
    received_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit_price = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    is_cancelled = models.BooleanField(default=False)
    cancel_reason = models.TextField(blank=True)

    class Meta:
        db_table = "receiving_order_items"

    def __str__(self):
        return f"{self.item} × {self.planned_quantity}"

    @property
    def remaining_quantity(self):
        if self.is_cancelled:
            return 0
        remaining = self.planned_quantity - self.received_quantity
        return remaining if remaining > 0 else 0
