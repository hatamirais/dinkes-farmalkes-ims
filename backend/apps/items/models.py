from django.db import models
from django.core.exceptions import ValidationError
from apps.core.models import TimeStampedModel


def _normalize_spaces(value: str) -> str:
    return ' '.join(value.split())


def _validate_case_insensitive_name_uniqueness(instance, model_class, field_name='name'):
    value = getattr(instance, field_name, '')
    if not value:
        return

    queryset = model_class.objects.filter(**{f'{field_name}__iexact': value})
    if instance.pk:
        queryset = queryset.exclude(pk=instance.pk)
    if queryset.exists():
        raise ValidationError({field_name: 'Nama sudah digunakan. Gunakan nama lain.'})


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

    def save(self, *args, **kwargs):
        self.code = (self.code or '').strip().upper()
        self.name = _normalize_spaces((self.name or '').strip())
        _validate_case_insensitive_name_uniqueness(self, Unit)
        super().save(*args, **kwargs)


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

    def save(self, *args, **kwargs):
        self.code = (self.code or '').strip().upper()
        self.name = _normalize_spaces((self.name or '').strip())
        _validate_case_insensitive_name_uniqueness(self, Category)
        super().save(*args, **kwargs)


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


class Program(TimeStampedModel):
    """Health program lookup table (TB, HIV, MALARIA, etc.)."""
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'programs'
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.name}"

    def save(self, *args, **kwargs):
        self.code = (self.code or '').strip().upper()
        self.name = _normalize_spaces((self.name or '').strip())
        _validate_case_insensitive_name_uniqueness(self, Program)
        super().save(*args, **kwargs)


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
    kode_barang = models.CharField(max_length=50, unique=True, blank=True)
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
    program = models.ForeignKey(
        Program,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='items',
        help_text='Health program (TB, HIV, Malaria, etc.)',
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

    @staticmethod
    def generate_kode_barang():
        """Generate next sequential code: ITM-00001, ITM-00002, etc."""
        last = (
            Item.objects.filter(kode_barang__startswith='ITM-')
            .order_by('-kode_barang')
            .values_list('kode_barang', flat=True)
            .first()
        )
        if last:
            try:
                num = int(last.split('-')[-1]) + 1
            except (ValueError, IndexError):
                num = Item.objects.count() + 1
        else:
            num = 1
        return f"ITM-{num:05d}"

    def save(self, *args, **kwargs):
        if not self.kode_barang:
            self.kode_barang = self.generate_kode_barang()
        super().save(*args, **kwargs)

