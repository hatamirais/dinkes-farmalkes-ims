from django.core.exceptions import ValidationError
from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

from apps.core.decimal_validation import (
    PRICE_DECIMAL_PLACES,
    PRICE_MAX_DIGITS,
    multiply_decimals,
    validate_finite_decimal,
)
from apps.core.models import TimeStampedModel


def format_decimal_label(value):
    label = format(value, "f")
    if "." in label:
        label = label.rstrip("0").rstrip(".")
    return label or "0"


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
    source_document_number = models.CharField(
        max_length=100,
        default="LEGACY",
        help_text="Original source document that created this stock valuation layer.",
    )
    expiry_date = models.DateField(null=True, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    reserved = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Stock allocated for pending distributions",
    )
    unit_price = models.DecimalField(
        max_digits=PRICE_MAX_DIGITS,
        decimal_places=PRICE_DECIMAL_PLACES,
        default=0,
    )
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
                fields=[
                    "item",
                    "location",
                    "batch_lot",
                    "sumber_dana",
                    "source_document_number",
                ],
                name="uq_stock_batch",
            ),
        ]
        indexes = [
            models.Index(
                fields=["item", "location", "expiry_date"], name="idx_stock_fefo"
            ),
            models.Index(
                fields=["source_document_number"], name="idx_stock_source_doc"
            ),
            models.Index(fields=["expiry_date"], name="idx_stock_expiry"),
            models.Index(fields=["item", "location"], name="idx_stock_item_loc"),
        ]
        ordering = ["item", "expiry_date"]

    def __str__(self):
        return (
            f"{self.item} | {self.batch_lot} | "
            f"{self.source_document_number} | Qty: {self.quantity}"
        )

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
    def picker_label(self):
        funding_code = self.sumber_dana.code if self.sumber_dana_id else "-"
        return (
            f"{self.batch_lot} | "
            f"Tersedia: {format_decimal_label(self.available_quantity)} | "
            f"Exp: {self.expiry_date_display} | Dokumen: {self.source_document_number} | "
            f"Dana: {funding_code} | Harga: {format_decimal_label(self.unit_price)}"
        )

    @property
    def total_value(self):
        """Total value = quantity × unit_price."""
        return multiply_decimals(self.quantity, self.unit_price)

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
    source_document_number = models.CharField(
        max_length=100,
        default="LEGACY",
        help_text="Original source document for the stock valuation layer moved by this transaction.",
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    unit_price = models.DecimalField(
        max_digits=PRICE_MAX_DIGITS,
        decimal_places=PRICE_DECIMAL_PLACES,
        null=True,
        blank=True,
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
            models.Index(
                fields=["source_document_number"], name="idx_trans_source_doc"
            ),
            models.Index(fields=["created_at"], name="idx_trans_created"),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.transaction_type} | {self.item} | {self.quantity} | {self.created_at}"


class OpeningBalanceImport(TimeStampedModel):
    """Admin-only opening stock import batch."""

    document_number = models.CharField(max_length=100, unique=True)
    effective_date = models.DateField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_opening_balance_imports",
    )
    posted_at = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "opening_balance_imports"
        ordering = ["-effective_date", "-created_at"]
        indexes = [
            models.Index(
                fields=["effective_date"], name="idx_opening_balance_date"
            ),
        ]

    def __str__(self):
        return f"{self.document_number} ({self.effective_date:%Y-%m-%d})"


class SourceDocumentNumberClaim(TimeStampedModel):
    """Shared uniqueness registry for stock source document numbers."""

    class SourceType(models.TextChoices):
        RECEIVING = "RECEIVING", "Penerimaan"
        OPENING_BALANCE = "OPENING_BALANCE", "Saldo Awal"

    document_number = models.CharField(max_length=100, unique=True)
    source_type = models.CharField(max_length=30, choices=SourceType.choices)
    source_id = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "source_document_number_claims"
        indexes = [
            models.Index(
                fields=["source_type", "source_id"],
                name="idx_source_doc_claim_source",
            ),
        ]

    def __str__(self):
        return f"{self.document_number} ({self.source_type})"


class OpeningBalanceImportItem(models.Model):
    """Line item posted by an opening stock import batch."""

    opening_balance = models.ForeignKey(
        OpeningBalanceImport,
        on_delete=models.CASCADE,
        related_name="items",
    )
    item = models.ForeignKey(
        "items.Item",
        on_delete=models.PROTECT,
        related_name="opening_balance_import_items",
    )
    location = models.ForeignKey(
        "items.Location",
        on_delete=models.PROTECT,
        related_name="opening_balance_import_items",
    )
    sumber_dana = models.ForeignKey(
        "items.FundingSource",
        on_delete=models.PROTECT,
        related_name="opening_balance_import_items",
    )
    batch_lot = models.CharField(max_length=100)
    expiry_date = models.DateField(null=True, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    unit_price = models.DecimalField(
        max_digits=PRICE_MAX_DIGITS,
        decimal_places=PRICE_DECIMAL_PLACES,
        default=0,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "opening_balance_import_items"
        ordering = ["item", "expiry_date", "batch_lot"]
        indexes = [
            models.Index(
                fields=["item", "location", "batch_lot"],
                name="idx_opening_balance_item_batch",
            ),
        ]

    def __str__(self):
        return f"{self.item} | {self.batch_lot} | {self.quantity}"


class StockTransfer(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        COMPLETED = "COMPLETED", "Selesai"

    document_number = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        null=True,
        help_text="Diterbitkan otomatis saat mutasi diselesaikan.",
    )
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

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.source_location_id and self.destination_location_id:
            if self.source_location_id == self.destination_location_id:
                raise ValidationError(
                    {
                        "destination_location": "Lokasi tujuan harus berbeda dari lokasi asal."
                    }
                )

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
