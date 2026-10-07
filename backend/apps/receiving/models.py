import hashlib
import unicodedata

from django.db import IntegrityError, models, transaction
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import F
from django.utils import timezone
from apps.core.decimal_validation import (
    PRICE_DECIMAL_PLACES,
    PRICE_MAX_DIGITS,
    multiply_decimals,
)
from apps.core.models import TimeStampedModel
from .storage import ReceivingDocumentStorage


class ReceivingTypeOption(TimeStampedModel):
    """Receiving type lookup rows, including system-defined options."""

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    is_system = models.BooleanField(default=False)
    requires_supplier = models.BooleanField(default=False)
    sort_order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        db_table = "receiving_type_options"
        ordering = ["sort_order", "name"]

    def __str__(self):
        return f"{self.code} - {self.name}"

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().upper()
        self.name = (self.name or "").strip()
        super().save(*args, **kwargs)


def get_reserved_receiving_type_codes():
    return {"RETURN_RS", *(choice[0] for choice in Receiving.ReceivingType.choices)}


def normalize_receiving_type_code(value):
    normalized = unicodedata.normalize("NFC", (value or "").strip())
    if "\x00" in normalized:
        raise ValidationError(
            {"receiving_type": "Tipe penerimaan mengandung karakter tidak valid."}
        )
    return normalized.upper()


def validate_receiving_type_code(value):
    receiving_type = normalize_receiving_type_code(value)
    if not receiving_type:
        return receiving_type
    if len(receiving_type) > 20:
        raise ValidationError({"receiving_type": "Tipe penerimaan terlalu panjang."})

    if receiving_type in get_reserved_receiving_type_codes():
        system_codes = {choice[0] for choice in Receiving.ReceivingType.choices}
        if receiving_type not in system_codes:
            raise ValidationError({"receiving_type": "Masukkan pilihan yang valid."})
        active_system_exists = ReceivingTypeOption.objects.filter(
            code=receiving_type,
            is_active=True,
            is_system=True,
        ).exists()
        if active_system_exists:
            return receiving_type
        raise ValidationError({"receiving_type": "Masukkan pilihan yang valid."})

    custom_exists = ReceivingTypeOption.objects.filter(
        code=receiving_type,
        is_active=True,
    ).exists()
    if custom_exists:
        return receiving_type

    raise ValidationError({"receiving_type": "Masukkan pilihan yang valid."})


def receiving_type_requires_supplier(value):
    receiving_type = normalize_receiving_type_code(value)
    if not receiving_type:
        return False
    return ReceivingTypeOption.objects.filter(
        code=receiving_type,
        requires_supplier=True,
    ).exists()


def _create_receiving_stock_row(
    *,
    item,
    location,
    batch_lot,
    sumber_dana,
    expiry_date,
    quantity,
    unit_price,
    receiving_ref,
    source_document_number,
):
    from apps.stock.models import Stock

    return Stock.objects.create(
        item=item,
        location=location,
        batch_lot=batch_lot,
        source_document_number=source_document_number,
        sumber_dana=sumber_dana,
        expiry_date=expiry_date,
        quantity=quantity,
        unit_price=unit_price,
        receiving_ref=receiving_ref,
    )


def _rewrite_zero_receiving_stock_metadata(
    *,
    stock_pk,
    expiry_date,
    unit_price,
    receiving_ref,
):
    from apps.stock.models import Stock

    stock = Stock.objects.select_for_update().get(pk=stock_pk)
    if stock.quantity != 0 or stock.reserved != 0:
        return {
            "pk": stock.pk,
            "expiry_date": stock.expiry_date,
            "quantity": stock.quantity,
            "reserved": stock.reserved,
            "unit_price": stock.unit_price,
        }

    stock.expiry_date = expiry_date
    stock.unit_price = unit_price
    stock.receiving_ref = receiving_ref
    stock.updated_at = timezone.now()
    stock.save(
        update_fields=[
            "expiry_date",
            "unit_price",
            "receiving_ref",
            "updated_at",
        ]
    )
    return {
        "pk": stock.pk,
        "expiry_date": stock.expiry_date,
        "quantity": stock.quantity,
        "reserved": stock.reserved,
        "unit_price": stock.unit_price,
    }


def increment_receiving_stock(
    *,
    item,
    location,
    batch_lot,
    sumber_dana,
    expiry_date,
    quantity,
    unit_price,
    receiving_ref,
    source_document_number,
    allow_zero_layer_metadata_update=False,
):
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("increment_receiving_stock harus dipanggil dalam transaksi.")

    from apps.stock.models import Stock

    stock_filters = {
        "item": item,
        "location": location,
        "batch_lot": batch_lot,
        "sumber_dana": sumber_dana,
        "source_document_number": source_document_number,
    }
    updated_at = timezone.now()
    existing_stock = (
        Stock.objects.filter(**stock_filters)
        .values("pk", "expiry_date", "quantity", "reserved", "unit_price")
        .first()
    )
    if (
        existing_stock
        and (
            existing_stock["expiry_date"] != expiry_date
            or existing_stock["unit_price"] != unit_price
        )
        and existing_stock["quantity"] == 0
        and existing_stock["reserved"] == 0
        and allow_zero_layer_metadata_update
    ):
        existing_stock = _rewrite_zero_receiving_stock_metadata(
            stock_pk=existing_stock["pk"],
            expiry_date=expiry_date,
            unit_price=unit_price,
            receiving_ref=receiving_ref,
        )
    if existing_stock and existing_stock["expiry_date"] != expiry_date:
        raise ValueError(
            "Batch stok yang sama tidak boleh memiliki tanggal kedaluwarsa berbeda."
        )
    if existing_stock and existing_stock["unit_price"] != unit_price:
        raise ValueError(
            "Batch stok yang sama dalam dokumen sumber yang sama tidak boleh memiliki harga satuan berbeda."
        )

    update_filters = {
        **stock_filters,
        "expiry_date": expiry_date,
        "unit_price": unit_price,
    }
    updated = Stock.objects.filter(**update_filters).update(
        quantity=F("quantity") + quantity,
        updated_at=updated_at,
    )
    if updated:
        return

    try:
        with transaction.atomic():
            _create_receiving_stock_row(
                item=item,
                location=location,
                batch_lot=batch_lot,
                sumber_dana=sumber_dana,
                expiry_date=expiry_date,
                quantity=quantity,
                unit_price=unit_price,
                receiving_ref=receiving_ref,
                source_document_number=source_document_number,
            )
    except IntegrityError:
        existing_stock = (
            Stock.objects.filter(**stock_filters)
            .values("pk", "expiry_date", "quantity", "reserved", "unit_price")
            .first()
        )
        if (
            existing_stock
            and (
                existing_stock["expiry_date"] != expiry_date
                or existing_stock["unit_price"] != unit_price
            )
            and existing_stock["quantity"] == 0
            and existing_stock["reserved"] == 0
            and allow_zero_layer_metadata_update
        ):
            existing_stock = _rewrite_zero_receiving_stock_metadata(
                stock_pk=existing_stock["pk"],
                expiry_date=expiry_date,
                unit_price=unit_price,
                receiving_ref=receiving_ref,
            )
        if existing_stock and existing_stock["expiry_date"] != expiry_date:
            raise ValueError(
                "Batch stok yang sama tidak boleh memiliki tanggal kedaluwarsa berbeda."
            )
        if existing_stock and existing_stock["unit_price"] != unit_price:
            raise ValueError(
                "Batch stok yang sama dalam dokumen sumber yang sama tidak boleh memiliki harga satuan berbeda."
            )
        updated = Stock.objects.filter(**update_filters).update(
            quantity=F("quantity") + quantity,
            updated_at=updated_at,
        )
        if updated:
            return
        raise


def resolve_receiving_source_document_number(
    receiving,
    item=None,
    location=None,
    batch_lot=None,
    sumber_dana=None,
):
    if not receiving.pk:
        return receiving.document_number

    from apps.stock.models import Stock, Transaction

    stock_filters = {"receiving_ref": receiving}
    if item is not None:
        stock_filters["item"] = item
    if location is not None:
        stock_filters["location"] = location
    if batch_lot is not None:
        stock_filters["batch_lot"] = batch_lot
    if sumber_dana is not None:
        stock_filters["sumber_dana"] = sumber_dana

    existing_sources = list(
        Stock.objects.filter(**stock_filters)
        .exclude(source_document_number="")
        .values_list("source_document_number", flat=True)
        .distinct()
        .order_by("source_document_number")
    )
    non_header_sources = [
        source
        for source in existing_sources
        if source != receiving.document_number
    ]
    if len(non_header_sources) == 1:
        return non_header_sources[0]
    if len(existing_sources) == 1:
        return existing_sources[0]

    transaction_filters = {
        "reference_type": Transaction.ReferenceType.RECEIVING,
        "reference_id": receiving.pk,
    }
    if item is not None:
        transaction_filters["item"] = item
    if location is not None:
        transaction_filters["location"] = location
    if batch_lot is not None:
        transaction_filters["batch_lot"] = batch_lot
    if sumber_dana is not None:
        transaction_filters["sumber_dana"] = sumber_dana

    transaction_sources = list(
        Transaction.objects.filter(**transaction_filters)
        .exclude(source_document_number="")
        .values_list("source_document_number", flat=True)
        .distinct()
        .order_by("source_document_number")
    )
    non_header_transaction_sources = [
        source
        for source in transaction_sources
        if source != receiving.document_number
    ]
    if len(non_header_transaction_sources) == 1:
        return non_header_transaction_sources[0]
    if len(transaction_sources) == 1:
        return transaction_sources[0]
    collision_alias = _receiving_collision_source_document_number(receiving)
    if collision_alias:
        document_sources = set(
            Stock.objects.filter(receiving_ref=receiving)
            .exclude(source_document_number="")
            .values_list("source_document_number", flat=True)
        )
        document_sources.update(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.RECEIVING,
                reference_id=receiving.pk,
            )
            .exclude(source_document_number="")
            .values_list("source_document_number", flat=True)
        )
        non_header_document_sources = {
            source
            for source in document_sources
            if source != receiving.document_number
        }
        if non_header_document_sources == {collision_alias}:
            return collision_alias
    return receiving.document_number


def _receiving_collision_source_document_number(receiving):
    from apps.stock.models import OpeningBalanceImport

    if not receiving.document_number:
        return ""
    if not OpeningBalanceImport.objects.filter(
        document_number=receiving.document_number
    ).exists():
        return ""

    digest = hashlib.sha1(
        f"RECEIVING:{receiving.document_number}".encode("utf-8")
    ).hexdigest()[:8]
    suffix_length = 100 - len("RCV") - len(digest) - 2
    return f"RCV-{digest}-{receiving.document_number[:suffix_length]}"


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
        CANCELLED = "CANCELLED", "Dibatalkan"

    receiving_type = models.CharField(max_length=20)
    document_number = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        null=True,
        help_text="Diterbitkan otomatis pada checkpoint workflow.",
    )
    receiving_date = models.DateField()
    import_group = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        help_text="Identitas grup dari import CSV; bukan nomor dokumen resmi.",
    )
    is_planned = models.BooleanField(default=False)
    contract = models.ForeignKey(
        "procurement.ProcurementContract",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="receivings",
    )
    supplier = models.ForeignKey(
        "items.Supplier",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="receivings",
        help_text="Required for PROCUREMENT type",
    )
    facility = models.ForeignKey(
        "items.Facility",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="receivings",
        help_text="Optional facility reference for receiving documents.",
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
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cancelled_receivings",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "receivings"
        ordering = ["-receiving_date"]
        indexes = [
            models.Index(
                fields=["status", "receiving_date"], name="idx_recv_status_date"
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["contract"],
                condition=models.Q(contract__isnull=False, is_planned=True),
                name="uniq_planned_receiving_contract",
            ),
        ]

    def __str__(self):
        return f"{self.document_number or 'Belum diterbitkan'} ({self.receiving_type_label})"

    @property
    def receiving_type_label(self):
        type_name = (
            ReceivingTypeOption.objects.filter(code=self.receiving_type, is_active=True)
            .values_list("name", flat=True)
            .first()
        )
        if type_name:
            return type_name

        builtin_map = dict(self.ReceivingType.choices)
        return builtin_map.get(self.receiving_type, self.receiving_type)

    def clean(self):
        super().clean()
        normalized_receiving_type = normalize_receiving_type_code(self.receiving_type)
        try:
            self.receiving_type = validate_receiving_type_code(normalized_receiving_type)
        except ValidationError:
            existing_receiving_type = None
            if self.pk:
                existing_receiving_type = (
                    Receiving.objects.filter(pk=self.pk)
                    .values_list("receiving_type", flat=True)
                    .first()
                )
            if (
                existing_receiving_type
                and normalized_receiving_type == existing_receiving_type
                and ReceivingTypeOption.objects.filter(
                    code=normalized_receiving_type
                ).exists()
            ):
                self.receiving_type = normalized_receiving_type
            else:
                raise
        self._validate_document_number_not_opening_balance_collision()
        self._validate_document_number_immutable_after_movements()
        if receiving_type_requires_supplier(self.receiving_type) and not self.supplier_id:
            raise ValidationError(
                {"supplier": "Supplier wajib diisi untuk tipe penerimaan ini."}
            )
        if self.contract_id:
            if not self.is_planned:
                raise ValidationError({"contract": "Kontrak hanya boleh ditautkan ke rencana penerimaan."})
            if self.receiving_type != self.ReceivingType.PROCUREMENT:
                raise ValidationError({"receiving_type": "Rencana dari kontrak harus bertipe Pengadaan."})
            duplicate_qs = Receiving.objects.filter(contract_id=self.contract_id, is_planned=True)
            if self.pk:
                duplicate_qs = duplicate_qs.exclude(pk=self.pk)
            if duplicate_qs.exists():
                raise ValidationError({"contract": "Setiap kontrak SPJ hanya boleh memiliki satu rencana penerimaan."})

    def _validate_document_number_not_opening_balance_collision(self):
        if not self.document_number:
            return

        from apps.stock.models import OpeningBalanceImport, SourceDocumentNumberClaim

        if OpeningBalanceImport.objects.filter(
            document_number=self.document_number
        ).exists() and not self._document_number_is_unchanged():
            raise ValidationError(
                {
                    "document_number": (
                        f"Nomor dokumen '{self.document_number}' sudah digunakan "
                        "oleh dokumen saldo awal. Gunakan nomor penerimaan yang berbeda."
                    )
                }
            )

        claimed_numbers = SourceDocumentNumberClaim.objects.filter(
            document_number=self.document_number
        )
        if self.pk:
            claimed_numbers = claimed_numbers.exclude(
                source_type=SourceDocumentNumberClaim.SourceType.RECEIVING,
                source_id=self.pk,
            )
        if claimed_numbers.exists() and not self._document_number_is_unchanged():
            raise ValidationError(
                {
                    "document_number": (
                        f"Nomor dokumen '{self.document_number}' sudah diklaim "
                        "oleh dokumen sumber stok lain."
                    )
                }
            )

    def _document_number_is_unchanged(self):
        if not self.pk or not self.document_number:
            return False
        return Receiving.objects.filter(
            pk=self.pk,
            document_number=self.document_number,
        ).exists()

    def _claim_document_number(self, old_document_number=None):
        if not self.document_number or old_document_number == self.document_number:
            return None

        from apps.stock.models import SourceDocumentNumberClaim

        try:
            return SourceDocumentNumberClaim.objects.create(
                document_number=self.document_number,
                source_type=SourceDocumentNumberClaim.SourceType.RECEIVING,
                source_id=self.pk,
            )
        except IntegrityError as exc:
            raise ValidationError(
                {
                    "document_number": (
                        f"Nomor dokumen '{self.document_number}' sudah diklaim "
                        "oleh dokumen sumber stok lain."
                    )
                }
            ) from exc

    def _release_old_document_number_claim(self, old_document_number):
        if not old_document_number or old_document_number == self.document_number:
            return

        from apps.stock.models import SourceDocumentNumberClaim

        SourceDocumentNumberClaim.objects.filter(
            document_number=old_document_number,
            source_type=SourceDocumentNumberClaim.SourceType.RECEIVING,
            source_id=self.pk,
        ).delete()

    def has_posted_stock_movements(self):
        if not self.pk:
            return False

        from apps.stock.models import Stock, Transaction

        return (
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.RECEIVING,
                reference_id=self.pk,
            ).exists()
            or Stock.objects.filter(receiving_ref_id=self.pk).exists()
        )

    def _validate_document_number_immutable_after_movements(self):
        if not self.pk:
            return

        old_document_number = (
            Receiving.objects.filter(pk=self.pk)
            .values_list("document_number", flat=True)
            .first()
        )
        if old_document_number and old_document_number != self.document_number:
            raise ValidationError(
                {
                    "document_number": (
                        "Nomor dokumen penerimaan yang sudah diterbitkan tidak dapat diubah."
                    )
                }
            )

    def save(self, *args, **kwargs):
        old_document_number = None
        if self.pk:
            old_document_number = (
                Receiving.objects.filter(pk=self.pk)
                .values_list("document_number", flat=True)
                .first()
            )

        self._validate_document_number_not_opening_balance_collision()
        self._validate_document_number_immutable_after_movements()

        with transaction.atomic():
            claim = self._claim_document_number(old_document_number)
            super().save(*args, **kwargs)
            if claim and claim.source_id != self.pk:
                claim.source_id = self.pk
                claim.save(update_fields=["source_id", "updated_at"])
            self._release_old_document_number_claim(old_document_number)


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
    settlement_distribution_item = models.ForeignKey(
        "distribution.DistributionItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="settlement_receipts",
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    batch_lot = models.CharField(max_length=100)
    expiry_date = models.DateField(null=True, blank=True)
    unit_price = models.DecimalField(
        max_digits=PRICE_MAX_DIGITS,
        decimal_places=PRICE_DECIMAL_PLACES,
    )
    location = models.ForeignKey(
        "items.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="receiving_items",
    )
    posted_sumber_dana = models.ForeignKey(
        "items.FundingSource",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="posted_receiving_items",
        help_text="Actual funding source layer posted to stock for this item.",
    )
    posted_source_document_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="Actual stock source document layer posted for this item.",
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
    def total_price(self):
        return multiply_decimals(self.quantity, self.unit_price)


class ReceivingDocument(models.Model):
    """Supporting documents for receiving (eKatalog files, grant letters)."""

    receiving = models.ForeignKey(
        Receiving,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    file = models.FileField(
        upload_to="receiving/%Y/%m/",
        storage=ReceivingDocumentStorage(),
    )
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
    contract_line = models.ForeignKey(
        "procurement.ProcurementContractLine",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="receiving_order_items",
    )
    planned_quantity = models.DecimalField(max_digits=12, decimal_places=2)
    received_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit_price = models.DecimalField(
        max_digits=PRICE_MAX_DIGITS,
        decimal_places=PRICE_DECIMAL_PLACES,
        default=0,
    )
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
