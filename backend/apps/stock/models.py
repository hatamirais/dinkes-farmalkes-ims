from django.core.exceptions import ValidationError
from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

from apps.core.decimal_validation import validate_finite_decimal
from apps.core.models import TimeStampedModel


class Stock(TimeStampedModel):
    """Real-time inventory tracking by batch/location."""

    item = models.ForeignKey(
        "items.Item",
        on_delete=models.PROTECT,
        related_name="stock_entries",
    )
    location = models.ForeignKey(
        "items.Location",
        on_delete=models.PROTECT,
        related_name="stock_entries",
    )
    batch_lot = models.CharField(max_length=100)
    expiry_date = models.DateField(null=True, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    reserved = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Stock allocated for pending distributions",
    )
    unit_price = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    sumber_dana = models.ForeignKey(
        "items.FundingSource",
        on_delete=models.PROTECT,
        related_name="stock_entries",
    )
    receiving_ref = models.ForeignKey(
        "receiving.Receiving",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_entries",
    )

    class Meta:
        db_table = "stock"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=0),
                name="chk_stock_quantity",
            ),
            models.CheckConstraint(
                condition=models.Q(reserved__gte=0),
                name="chk_stock_reserved_gte_0",
            ),
            models.UniqueConstraint(
                fields=["item", "location", "batch_lot", "sumber_dana"],
                name="uq_stock_batch",
            ),
        ]
        indexes = [
            models.Index(
                fields=["item", "location", "expiry_date"], name="idx_stock_fefo"
            ),
            models.Index(fields=["expiry_date"], name="idx_stock_expiry"),
            models.Index(fields=["item", "location"], name="idx_stock_item_loc"),
        ]
        ordering = ["item", "expiry_date"]

    def __str__(self):
        return f"{self.item} | {self.batch_lot} | Qty: {self.quantity}"

    def clean(self):
        errors = {}

        if (
            self.item_id
            and getattr(self.item, "requires_expiry_date", True)
            and self.expiry_date is None
        ):
            errors["expiry_date"] = "Tanggal kedaluwarsa wajib diisi untuk item ini."

        if errors:
            raise ValidationError(errors)

    @property
    def available_quantity(self):
        """Available stock = quantity - reserved."""
        return self.quantity - self.reserved

    @property
    def total_value(self):
        """Total value = quantity × unit_price."""
        return self.quantity * self.unit_price

    @property
    def expiry_date_display(self):
        if self.expiry_date:
            return self.expiry_date.strftime("%d/%m/%Y")
        return "Tanpa kedaluwarsa"

    @property
    def is_expired(self):
        """Whether this stock batch has expired."""
        if self.expiry_date is None:
            return False
        return self.expiry_date <= timezone.now().date()

    @property
    def is_near_expiry(self):
        """Whether this stock batch expires within 90 days."""
        if self.expiry_date is None:
            return False
        return (
            not self.is_expired
            and self.expiry_date <= timezone.now().date() + timedelta(days=90)
        )


class Transaction(models.Model):
    """Immutable audit trail of all stock movements."""

    class TransactionType(models.TextChoices):
        IN = "IN", "Barang Masuk"
        OUT = "OUT", "Barang Keluar"
        ADJUST = "ADJUST", "Penyesuaian"
        RETURN = "RETURN", "Retur"

    class ReferenceType(models.TextChoices):
        RECEIVING = "RECEIVING", "Penerimaan"
        DISTRIBUTION = "DISTRIBUTION", "Distribusi"
        ALLOCATION = "ALLOCATION", "Alokasi"
        ADJUSTMENT = "ADJUSTMENT", "Penyesuaian"
        INITIAL_IMPORT = "INITIAL_IMPORT", "Import Awal"
        RECALL = "RECALL", "Recall"
        EXPIRED = "EXPIRED", "Kedaluwarsa"
        TRANSFER = "TRANSFER", "Mutasi Lokasi"

    transaction_type = models.CharField(max_length=10, choices=TransactionType.choices)
    item = models.ForeignKey(
        "items.Item",
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    location = models.ForeignKey(
        "items.Location",
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    batch_lot = models.CharField(max_length=100)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    unit_price = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True
    )
    sumber_dana = models.ForeignKey(
        "items.FundingSource",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="transactions",
    )
    reference_type = models.CharField(
        max_length=20,
        choices=ReferenceType.choices,
    )
    reference_id = models.PositiveIntegerField(
        default=0,
        help_text="Polymorphic reference to source document",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "transactions"
        indexes = [
            models.Index(fields=["item", "-created_at"], name="idx_trans_item_date"),
            models.Index(
                fields=["reference_type", "reference_id"], name="idx_trans_reference"
            ),
            models.Index(fields=["created_at"], name="idx_trans_created"),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.transaction_type} | {self.item} | {self.quantity} | {self.created_at}"


class StockTransfer(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        COMPLETED = "COMPLETED", "Selesai"

    document_number = models.CharField(max_length=50, unique=True)
    transfer_date = models.DateField(default=timezone.now)
    source_location = models.ForeignKey(
        "items.Location",
        on_delete=models.PROTECT,
        related_name="stock_transfers_from",
    )
    destination_location = models.ForeignKey(
        "items.Location",
        on_delete=models.PROTECT,
        related_name="stock_transfers_to",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_stock_transfers",
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="completed_stock_transfers",
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "stock_transfers"
        ordering = ["-transfer_date", "-created_at"]

    @staticmethod
    def generate_document_number():
        year = timezone.now().year
        prefix = f"TRF-{year}-"
        last = (
            StockTransfer.objects.filter(document_number__startswith=prefix)
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

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.source_location_id and self.destination_location_id:
            if self.source_location_id == self.destination_location_id:
                raise ValidationError(
                    {
                        "destination_location": "Lokasi tujuan harus berbeda dari lokasi asal."
                    }
                )

    def save(self, *args, **kwargs):
        from django.db import IntegrityError

        auto_generated_document_number = not self.document_number
        if auto_generated_document_number:
            self.document_number = self.generate_document_number()

        max_retries = 3
        for attempt in range(max_retries):
            try:
                super().save(*args, **kwargs)
                return
            except IntegrityError as exc:
                error_message = " ".join(str(arg) for arg in exc.args)
                constraint_name = (
                    getattr(getattr(exc.__cause__, "diag", None), "constraint_name", "")
                    or ""
                )
                if (
                    auto_generated_document_number
                    and attempt < max_retries - 1
                    and (
                        "document_number" in error_message
                        or "document_number" in constraint_name
                    )
                ):
                    # Regenerate and retry on duplicate document number
                    self.document_number = self.generate_document_number()
                else:
                    raise


class StockTransferItem(models.Model):
    transfer = models.ForeignKey(
        StockTransfer,
        on_delete=models.CASCADE,
        related_name="items",
    )
    stock = models.ForeignKey(
        Stock,
        on_delete=models.PROTECT,
        related_name="transfer_items",
    )
    item = models.ForeignKey(
        "items.Item",
        on_delete=models.PROTECT,
        related_name="stock_transfer_items",
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "stock_transfer_items"
        ordering = ["id"]

    def clean(self):
        from django.core.exceptions import ValidationError

        errors = {}

        try:
            self.quantity = validate_finite_decimal(
                self.quantity,
                field_label="Jumlah mutasi",
            )
        except ValidationError as exc:
            errors["quantity"] = exc.messages
            self.quantity = None

        if self.quantity is not None and self.quantity <= 0:
            errors["quantity"] = "Jumlah mutasi harus lebih dari 0."

        if self.stock_id and self.item_id and self.stock.item_id != self.item_id:
            errors["item"] = "Barang tidak sesuai dengan batch stok sumber."

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.transfer.document_number} | {self.item} | {self.quantity}"
