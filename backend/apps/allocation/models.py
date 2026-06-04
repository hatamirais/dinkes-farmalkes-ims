from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.decimal_validation import validate_finite_decimal
from apps.core.models import TimeStampedModel


class Allocation(TimeStampedModel):
    """Pre-distribution planning and orchestration document.

    Approval triggers atomic generation of one Distribution per facility.
    Stock is deducted at each child distribution's delivery confirmation,
    not on the Allocation itself.
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Diajukan"
        APPROVED = "APPROVED", "Disetujui"
        PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED", "Sebagian Terpenuhi"
        FULFILLED = "FULFILLED", "Terpenuhi"
        REJECTED = "REJECTED", "Ditolak"

    document_number = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        help_text="Leave blank to auto-generate (e.g., ALK-2025-0042)",
    )
    title = models.CharField(
        max_length=255,
        blank=True,
        help_text="Judul dokumen alokasi untuk header atau kebutuhan cetak.",
    )
    referensi = models.CharField(
        max_length=255,
        blank=True,
        help_text="Nomor referensi (BAST, SP, dll.)",
    )
    allocation_date = models.DateField()
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=25,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    rejection_reason = models.TextField(
        blank=True,
        help_text="Alasan penolakan dari Kepala Instalasi",
    )

    # Actor / audit fields
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_allocations",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="submitted_allocations",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_allocations",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "allocations"
        ordering = ["-allocation_date", "-created_at"]
        indexes = [
            models.Index(
                fields=["status", "allocation_date"],
                name="idx_alloc_status_date",
            ),
        ]

    def __str__(self):
        return self.document_number or "Alokasi baru"

    def save(self, *args, **kwargs):
        if not self.document_number:
            year = timezone.now().year
            prefix = f"ALK-{year}-"
            last = (
                Allocation.objects.filter(document_number__startswith=prefix)
                .order_by("-document_number")
                .first()
            )
            if last:
                last_number = int(last.document_number.split("-")[-1])
                next_number = last_number + 1
            else:
                next_number = 1
            self.document_number = f"{prefix}{str(next_number).zfill(4)}"
        super().save(*args, **kwargs)

    @property
    def generated_distributions(self):
        """QuerySet of distributions auto-generated from this allocation."""
        return self.distributions.all()

    @property
    def delivery_progress(self):
        """Tuple (delivered_count, total_count) for progress tracking."""
        from apps.distribution.models import Distribution

        distributions = self.distributions.all()
        total = distributions.count()
        delivered = distributions.filter(
            status=Distribution.Status.DISTRIBUTED
        ).count()
        return delivered, total


class AllocationStaffAssignment(TimeStampedModel):
    """Staff members involved in an allocation workflow."""

    allocation = models.ForeignKey(
        Allocation,
        on_delete=models.CASCADE,
        related_name="staff_assignments",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="allocation_staff_assignments",
    )

    class Meta:
        db_table = "allocation_staff_assignments"
        unique_together = ("allocation", "user")
        ordering = ["user__full_name", "user__username"]

    def __str__(self):
        return f"{self.allocation} - {self.user}"


class AllocationFacility(models.Model):
    """Header-level facility selection for the allocation matrix UI."""

    allocation = models.ForeignKey(
        Allocation,
        on_delete=models.CASCADE,
        related_name="selected_facilities",
    )
    facility = models.ForeignKey(
        "items.Facility",
        on_delete=models.PROTECT,
        related_name="allocation_selections",
    )

    class Meta:
        db_table = "allocation_facilities"
        unique_together = ("allocation", "facility")
        ordering = ["facility__name"]

    def __str__(self):
        return f"{self.allocation} - {self.facility}"


class AllocationItem(models.Model):
    """Item-level allocation record. Each row represents one item+batch
    that will be distributed across multiple facilities."""

    allocation = models.ForeignKey(
        Allocation,
        on_delete=models.CASCADE,
        related_name="items",
    )
    item = models.ForeignKey(
        "items.Item",
        on_delete=models.PROTECT,
        related_name="allocation_items",
    )
    stock = models.ForeignKey(
        "stock.Stock",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="allocation_items",
        help_text="Specific batch allocated (FEFO selection)",
    )
    total_qty_available = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Snapshot of available stock at draft time",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "allocation_items"
        ordering = ["item__nama_barang"]

    def __str__(self):
        return f"{self.item} (tersedia: {self.total_qty_available})"

    @property
    def total_qty_allocated(self):
        """Sum of all per-facility allocations for this item."""
        from django.db.models import DecimalField, Sum, Value
        from django.db.models.functions import Coalesce

        return self.facility_allocations.aggregate(
            total=Coalesce(
                Sum("qty_allocated"),
                Value(0, output_field=DecimalField(max_digits=12, decimal_places=2)),
            )
        )["total"]

    @property
    def is_over_allocated(self):
        """Whether total allocated exceeds available stock."""
        return self.total_qty_allocated > self.total_qty_available

    def clean(self):
        errors = {}

        if self.stock_id and self.item_id and self.stock.item_id != self.item_id:
            errors["stock"] = "Batch stok harus sesuai dengan barang yang dipilih."

        if errors:
            raise ValidationError(errors)


class AllocationItemFacility(models.Model):
    """Per-facility quantity allocation for a specific item.
    Quantities are locked after approval."""

    allocation_item = models.ForeignKey(
        AllocationItem,
        on_delete=models.CASCADE,
        related_name="facility_allocations",
    )
    facility = models.ForeignKey(
        "items.Facility",
        on_delete=models.PROTECT,
        related_name="allocation_item_facilities",
    )
    qty_allocated = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Quantity allocated to this facility (locked after approval)",
    )

    class Meta:
        db_table = "allocation_item_facilities"
        unique_together = ("allocation_item", "facility")
        ordering = ["facility__name"]

    def __str__(self):
        return f"{self.facility} × {self.qty_allocated}"

    def clean(self):
        errors = {}

        try:
            self.qty_allocated = validate_finite_decimal(
                self.qty_allocated,
                field_label="Jumlah alokasi",
            )
        except ValidationError as exc:
            errors["qty_allocated"] = exc.messages
            self.qty_allocated = None

        if self.qty_allocated is not None and self.qty_allocated <= 0:
            errors["qty_allocated"] = "Jumlah alokasi harus lebih dari 0."

        if self.facility_id and self.allocation_item_id:
            allocation = self.allocation_item.allocation
            selected_facility_ids = set(
                allocation.selected_facilities.values_list("facility_id", flat=True)
            )
            if self.facility_id not in selected_facility_ids:
                errors["facility"] = (
                    "Fasilitas harus dipilih pada header alokasi."
                )

        if errors:
            raise ValidationError(errors)
