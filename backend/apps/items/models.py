from django.db import models
from apps.core.models import TimeStampedModel


class Unit(TimeStampedModel):
    """Measurement unit lookup table (TAB, BTL, AMP, etc.)."""
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    class Meta:
        db_table = 'units'
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.name}"


class Category(TimeStampedModel):
    """Item category lookup table (TABLET, INJEKSI, VAKSIN, etc.)."""
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = 'categories'
        ordering = ['sort_order', 'code']
        verbose_name_plural = 'Categories'

    def __str__(self):
        return f"{self.code} - {self.name}"


class FundingSource(TimeStampedModel):
    """Funding source lookup table (DAK, DAU, APBD, HIBAH, etc.)."""
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'funding_sources'
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.name}"


class Location(TimeStampedModel):
    """Storage location lookup table."""
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'locations'
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.name}"


class Supplier(TimeStampedModel):
    """Vendor/supplier for procurement tracking."""
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=255)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'suppliers'
        ordering = ['name']

    def __str__(self):
        return self.name


class Facility(TimeStampedModel):
    """Distribution destination (Puskesmas, RS, Clinic)."""

    class FacilityType(models.TextChoices):
        PUSKESMAS = 'PUSKESMAS', 'Puskesmas'
        RS = 'RS', 'Rumah Sakit'
        CLINIC = 'CLINIC', 'Klinik'

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=255)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    facility_type = models.CharField(
        max_length=20,
        choices=FacilityType.choices,
        default=FacilityType.PUSKESMAS,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'facilities'
        ordering = ['code']
        verbose_name_plural = 'Facilities'

    def __str__(self):
        return f"{self.code} - {self.name}"


class Item(TimeStampedModel):
    """Central item registry (Master Barang)."""
    kode_barang = models.CharField(max_length=50, unique=True)
    nama_barang = models.CharField(max_length=255)
    satuan = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        related_name='items',
    )
    kategori = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='items',
    )
    is_program_item = models.BooleanField(
        default=False,
        help_text='Designated program item [P]',
    )
    program_name = models.CharField(
        max_length=100,
        blank=True,
        help_text='Program name (TB, HIV, Kusta, etc.)',
    )
    minimum_stock = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text='Threshold for low stock alerts',
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'items'
        ordering = ['kode_barang']
        indexes = [
            models.Index(fields=['kategori', 'is_program_item'], name='idx_item_category_program'),
        ]

    def __str__(self):
        return f"{self.kode_barang} - {self.nama_barang}"
