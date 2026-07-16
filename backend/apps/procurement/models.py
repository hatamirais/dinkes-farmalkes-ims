import unicodedata

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.decimal_validation import validate_finite_decimal
from apps.core.models import TimeStampedModel


def _normalize_text(value, *, field_label, max_length=None, allow_blank=True):
    if value is None:
        return "" if allow_blank else value

    normalized = unicodedata.normalize("NFC", str(value))
    if "\x00" in normalized:
        raise ValidationError(f"{field_label} mengandung karakter yang tidak valid.")
    normalized = " ".join(normalized.strip().split())
    if not normalized and not allow_blank:
        raise ValidationError(f"{field_label} wajib diisi.")
    if max_length is not None and len(normalized) > max_length:
        raise ValidationError(
            f"{field_label} tidak boleh lebih dari {max_length} karakter."
        )
    return normalized


def _validate_date_year(value, *, field_label):
    if value is None:
        return
    if value.year < 1000 or value.year > 9999:
        raise ValidationError(f"{field_label} harus berada pada rentang tahun 1000-9999.")


class ProcurementWorkflowError(ValueError):
    """Raised when a procurement workflow action violates business rules."""


def _next_prefixed_sequence(model, prefix):
    sequence = 0
    for document_number in model.objects.filter(document_number__startswith=prefix).values_list(
        "document_number", flat=True
    ):
        suffix = (document_number or "").removeprefix(prefix)
        if suffix.isdigit():
            sequence = max(sequence, int(suffix))
    return sequence + 1


class ProcurementContract(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Diajukan"
        APPROVED = "APPROVED", "Disetujui"
        CLOSED = "CLOSED", "Ditutup"

    document_number = models.CharField(max_length=100, unique=True, blank=True)
    contract_date = models.DateField()
    supplier = models.ForeignKey(
        "items.Supplier",
        on_delete=models.PROTECT,
        related_name="procurement_contracts",
    )
    sumber_dana = models.ForeignKey(
        "items.FundingSource",
        on_delete=models.PROTECT,
        related_name="procurement_contracts",
    )
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_procurement_contracts",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="submitted_procurement_contracts",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_procurement_contracts",
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="closed_procurement_contracts",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "procurement_contracts"
        ordering = ["-contract_date", "-created_at"]
        indexes = [
            models.Index(fields=["status", "contract_date"], name="idx_proc_contract_status_date"),
        ]

    def __str__(self):
        return self.document_number or "SPJ baru"

    def clean(self):
        super().clean()
        _validate_date_year(self.contract_date, field_label="Tanggal kontrak")
        self.document_number = _normalize_text(
            self.document_number,
            field_label="Nomor dokumen",
            max_length=100,
        )
        self.notes = _normalize_text(self.notes, field_label="Catatan")
        if self.supplier_id and not self.supplier.is_active:
            raise ValidationError({"supplier": "Supplier harus aktif."})
        if self.sumber_dana_id and not self.sumber_dana.is_active:
            raise ValidationError({"sumber_dana": "Sumber dana harus aktif."})

    @staticmethod
    def generate_document_number():
        year = timezone.now().year
        prefix = f"SPJ-{year}-"
        sequence = _next_prefixed_sequence(ProcurementContract, prefix)
        return f"{prefix}{sequence:05d}"

    def save(self, *args, **kwargs):
        if not self.document_number:
            self.document_number = self.generate_document_number()
        super().save(*args, **kwargs)


class ProcurementContractLine(TimeStampedModel):
    contract = models.ForeignKey(
        ProcurementContract,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    item = models.ForeignKey(
        "items.Item",
        on_delete=models.PROTECT,
        related_name="procurement_contract_lines",
    )
    original_quantity = models.DecimalField(max_digits=12, decimal_places=2)
    original_unit_price = models.DecimalField(max_digits=15, decimal_places=2)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "procurement_contract_lines"
        ordering = ["item__nama_barang", "pk"]
        unique_together = ("contract", "item")

    def __str__(self):
        return f"{self.contract} - {self.item}"

    @property
    def latest_approved_amendment_line(self):
        return (
            self.amendment_lines.select_related("amendment")
            .filter(amendment__status=ProcurementAmendment.Status.APPROVED)
            .order_by("-amendment__approved_at", "-amendment_id")
            .first()
        )

    @property
    def current_quantity(self):
        amendment_line = self.latest_approved_amendment_line
        return amendment_line.revised_quantity if amendment_line else self.original_quantity

    @property
    def current_unit_price(self):
        amendment_line = self.latest_approved_amendment_line
        return amendment_line.revised_unit_price if amendment_line else self.original_unit_price

    def clean(self):
        super().clean()
        errors = {}
        try:
            self.original_quantity = validate_finite_decimal(
                self.original_quantity,
                field_label="Jumlah kontrak awal",
            )
        except ValidationError as exc:
            errors["original_quantity"] = exc.messages
            self.original_quantity = None

        try:
            self.original_unit_price = validate_finite_decimal(
                self.original_unit_price,
                field_label="Harga satuan awal",
            )
        except ValidationError as exc:
            errors["original_unit_price"] = exc.messages
            self.original_unit_price = None

        if self.original_quantity is not None and self.original_quantity <= 0:
            errors["original_quantity"] = "Jumlah kontrak awal harus lebih dari 0."
        if self.original_unit_price is not None and self.original_unit_price <= 0:
            errors["original_unit_price"] = "Harga satuan awal harus lebih dari 0."
        self.notes = _normalize_text(self.notes, field_label="Catatan")
        if self.item_id and not self.item.is_active:
            errors["item"] = "Barang harus aktif."
        if errors:
            raise ValidationError(errors)


class ProcurementAmendment(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Diajukan"
        APPROVED = "APPROVED", "Disetujui"

    contract = models.ForeignKey(
        ProcurementContract,
        on_delete=models.PROTECT,
        related_name="amendments",
    )
    document_number = models.CharField(max_length=100, unique=True, blank=True)
    amendment_date = models.DateField()
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_procurement_amendments",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="submitted_procurement_amendments",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_procurement_amendments",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "procurement_amendments"
        ordering = ["-amendment_date", "-created_at"]
        indexes = [
            models.Index(fields=["status", "amendment_date"], name="idx_proc_amend_status_date"),
        ]

    def __str__(self):
        return self.document_number or "Amandemen baru"

    def clean(self):
        super().clean()
        _validate_date_year(self.amendment_date, field_label="Tanggal amandemen")
        self.document_number = _normalize_text(
            self.document_number,
            field_label="Nomor amandemen",
            max_length=100,
        )
        self.notes = _normalize_text(self.notes, field_label="Catatan")
        if self.contract_id and self.contract.status == ProcurementContract.Status.CLOSED:
            raise ValidationError({"contract": "Kontrak yang sudah ditutup tidak dapat diamandemen."})

    def generate_document_number(self):
        if not self.contract_id:
            raise ValidationError({"contract": "Kontrak wajib diisi sebelum nomor amandemen dibuat."})
        prefix = f"{self.contract.document_number}-A"
        sequence = _next_prefixed_sequence(ProcurementAmendment, prefix)
        document_number = f"{prefix}{sequence}"
        max_length = self._meta.get_field("document_number").max_length
        if len(document_number) > max_length:
            raise ValidationError(
                {
                    "document_number": (
                        "Nomor amandemen otomatis melebihi batas "
                        f"{max_length} karakter. Pendekkan nomor SPJ induk."
                    )
                }
            )
        return document_number

    def save(self, *args, **kwargs):
        if not self.document_number:
            self.document_number = self.generate_document_number()
        super().save(*args, **kwargs)


class ProcurementAmendmentLine(TimeStampedModel):
    amendment = models.ForeignKey(
        ProcurementAmendment,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    contract_line = models.ForeignKey(
        ProcurementContractLine,
        on_delete=models.PROTECT,
        related_name="amendment_lines",
    )
    revised_quantity = models.DecimalField(max_digits=12, decimal_places=2)
    revised_unit_price = models.DecimalField(max_digits=15, decimal_places=2)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "procurement_amendment_lines"
        ordering = ["contract_line__item__nama_barang", "pk"]
        unique_together = ("amendment", "contract_line")

    def __str__(self):
        return f"{self.amendment} - {self.contract_line.item}"

    def clean(self):
        super().clean()
        errors = {}
        try:
            self.revised_quantity = validate_finite_decimal(
                self.revised_quantity,
                field_label="Jumlah revisi",
            )
        except ValidationError as exc:
            errors["revised_quantity"] = exc.messages
            self.revised_quantity = None

        try:
            self.revised_unit_price = validate_finite_decimal(
                self.revised_unit_price,
                field_label="Harga satuan revisi",
            )
        except ValidationError as exc:
            errors["revised_unit_price"] = exc.messages
            self.revised_unit_price = None

        if self.revised_quantity is not None and self.revised_quantity <= 0:
            errors["revised_quantity"] = "Jumlah revisi harus lebih dari 0."
        if self.revised_unit_price is not None and self.revised_unit_price <= 0:
            errors["revised_unit_price"] = "Harga satuan revisi harus lebih dari 0."
        self.notes = _normalize_text(self.notes, field_label="Catatan")
        if self.contract_line_id and self.amendment_id:
            if self.contract_line.contract_id != self.amendment.contract_id:
                errors["contract_line"] = "Baris kontrak tidak sesuai dengan kontrak amandemen."
        if errors:
            raise ValidationError(errors)
