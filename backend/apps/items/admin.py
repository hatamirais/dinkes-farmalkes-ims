from django.contrib import admin
from import_export import fields, resources
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import ForeignKeyWidget, ManyToManyWidget

from apps.core.admin_mixins import ImportGuideMixin
from .models import (
    Category,
    Facility,
    FundingSource,
    Item,
    Location,
    Program,
    Supplier,
    TherapeuticClass,
    Unit,
)


def _normalize_code_token(value):
    token = str(value or "")
    if "\x00" in token:
        raise ValueError("Kode mengandung karakter yang tidak valid.")
    return token.strip().upper()


class StrictCodeManyToManyWidget(ManyToManyWidget):
    def clean(self, value, row=None, **kwargs):
        if not value:
            return self.model.objects.none()

        if isinstance(value, (float, int)):
            tokens = [str(int(value))]
        else:
            tokens = [_normalize_code_token(part) for part in str(value).split(self.separator)]
            tokens = [token for token in tokens if token]

        if not tokens:
            return self.model.objects.none()

        queryset = self.model.objects.filter(**{f"{self.field}__in": tokens})
        found_tokens = {
            _normalize_code_token(getattr(obj, self.field)) for obj in queryset
        }
        missing_tokens = [token for token in tokens if token not in found_tokens]
        if missing_tokens:
            raise ValueError(
                "Kode kelas terapi tidak ditemukan: " + ", ".join(missing_tokens)
            )
        return queryset


# -- Resources ---------------------------------------------------------------


class UnitResource(resources.ModelResource):
    class Meta:
        model = Unit
        fields = ("id", "code", "name", "description")
        import_id_fields = ("code",)
        skip_unchanged = True
        report_skipped = False


class CategoryResource(resources.ModelResource):
    class Meta:
        model = Category
        fields = ("id", "code", "name", "description", "sort_order")
        import_id_fields = ("code",)
        skip_unchanged = True
        report_skipped = False


class FundingSourceResource(resources.ModelResource):
    class Meta:
        model = FundingSource
        fields = ("id", "code", "name", "description", "is_active")
        import_id_fields = ("code",)
        skip_unchanged = True
        report_skipped = False


class LocationResource(resources.ModelResource):
    class Meta:
        model = Location
        fields = ("id", "code", "name", "description", "is_active")
        import_id_fields = ("code",)
        skip_unchanged = True
        report_skipped = False


class SupplierResource(resources.ModelResource):
    class Meta:
        model = Supplier
        fields = (
            "id",
            "code",
            "name",
            "address",
            "phone",
            "email",
            "notes",
            "is_active",
        )
        import_id_fields = ("code",)
        skip_unchanged = True
        report_skipped = False


class FacilityResource(resources.ModelResource):
    class Meta:
        model = Facility
        fields = (
            "id",
            "code",
            "name",
            "facility_type",
            "address",
            "phone",
            "is_active",
        )
        import_id_fields = ("code",)
        skip_unchanged = True
        report_skipped = False


class ProgramResource(resources.ModelResource):
    class Meta:
        model = Program
        fields = ("id", "code", "name", "description", "is_active")
        import_id_fields = ("code",)
        skip_unchanged = True
        report_skipped = False


class TherapeuticClassResource(resources.ModelResource):
    class Meta:
        model = TherapeuticClass
        fields = ("id", "code", "name", "description", "is_active")
        import_id_fields = ("code",)
        skip_unchanged = True
        report_skipped = False


class ItemResource(resources.ModelResource):
    satuan = fields.Field(
        column_name="satuan",
        attribute="satuan",
        widget=ForeignKeyWidget(Unit, field="code"),
    )
    kategori = fields.Field(
        column_name="kategori",
        attribute="kategori",
        widget=ForeignKeyWidget(Category, field="code"),
    )
    program = fields.Field(
        column_name="program",
        attribute="program",
        widget=ForeignKeyWidget(Program, field="code"),
    )
    therapeutic_classes = fields.Field(
        column_name="therapeutic_classes",
        attribute="therapeutic_classes",
        widget=StrictCodeManyToManyWidget(
            TherapeuticClass,
            field="code",
            separator="|",
        ),
    )

    class Meta:
        model = Item
        fields = (
            "id",
            "kode_barang",
            "nama_barang",
            "satuan",
            "kategori",
            "is_program_item",
            "is_essential",
            "program",
            "therapeutic_classes",
            "minimum_stock",
            "description",
            "is_active",
        )
        import_id_fields = ("nama_barang",)
        skip_unchanged = True
        report_skipped = False

    def before_import_row(self, row, **kwargs):
        """Ensure program column is populated for program items."""
        is_prog = str(row.get("is_program_item") or "").strip()
        prog_val = _normalize_code_token(row.get("program") or "")

        truthy = {"1", "true", "True", "TRUE", "yes", "Yes", "YES"}
        if is_prog in truthy and not prog_val:
            default = (
                Program.objects.filter(code__iexact="DEFAULT").first()
                or Program.objects.filter(name__iexact="DEFAULT").first()
            )
            if not default:
                default = Program.objects.create(
                    code="DEFAULT", name="DEFAULT", is_active=True
                )
            row["program"] = default.code


# -- Admin -------------------------------------------------------------------


@admin.register(Unit)
class UnitAdmin(ImportGuideMixin, ImportExportModelAdmin):
    resource_classes = [UnitResource]
    list_display = ("code", "name", "description")
    search_fields = ("code", "name")
    import_guide = {
        "title": "Satuan (Unit)",
        "columns": [
            {"name": "code", "required": True, "description": "Kode unik (maks 20 karakter)"},
            {"name": "name", "required": True, "description": "Nama satuan (misal: Tablet, Botol, Ampul)"},
            {"name": "description", "required": False, "description": "Keterangan"},
        ],
    }


@admin.register(Category)
class CategoryAdmin(ImportGuideMixin, ImportExportModelAdmin):
    resource_classes = [CategoryResource]
    list_display = ("code", "name", "sort_order")
    search_fields = ("code", "name")
    list_editable = ("sort_order",)
    import_guide = {
        "title": "Kategori Barang",
        "columns": [
            {"name": "code", "required": True, "description": "Kode unik (maks 20 karakter)"},
            {"name": "name", "required": True, "description": "Nama kategori (misal: Obat, Alkes, BHP)"},
            {"name": "description", "required": False, "description": "Keterangan"},
            {"name": "sort_order", "required": False, "description": "Urutan tampilan (default: 0)"},
        ],
    }


@admin.register(FundingSource)
class FundingSourceAdmin(ImportGuideMixin, ImportExportModelAdmin):
    resource_classes = [FundingSourceResource]
    list_display = ("code", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")
    import_guide = {
        "title": "Sumber Dana",
        "columns": [
            {"name": "code", "required": True, "description": "Kode unik (misal: DAK, APBD, HIBAH)"},
            {"name": "name", "required": True, "description": "Nama sumber dana"},
            {"name": "description", "required": False, "description": "Keterangan"},
            {"name": "is_active", "required": False, "description": "1 = aktif, 0 = nonaktif (default: 1)"},
        ],
    }


@admin.register(Location)
class LocationAdmin(ImportGuideMixin, ImportExportModelAdmin):
    resource_classes = [LocationResource]
    list_display = ("code", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")
    import_guide = {
        "title": "Lokasi Gudang",
        "columns": [
            {"name": "code", "required": True, "description": "Kode unik (misal: GUD-001)"},
            {"name": "name", "required": True, "description": "Nama lokasi gudang"},
            {"name": "description", "required": False, "description": "Keterangan"},
            {"name": "is_active", "required": False, "description": "1 = aktif, 0 = nonaktif (default: 1)"},
        ],
    }


@admin.register(Supplier)
class SupplierAdmin(ImportGuideMixin, ImportExportModelAdmin):
    resource_classes = [SupplierResource]
    list_display = ("code", "name", "phone", "email", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name", "email")
    import_guide = {
        "title": "Supplier / Pemasok",
        "columns": [
            {"name": "code", "required": True, "description": "Kode unik (misal: SUP-001)"},
            {"name": "name", "required": True, "description": "Nama supplier"},
            {"name": "address", "required": False, "description": "Alamat"},
            {"name": "phone", "required": False, "description": "Nomor telepon"},
            {"name": "email", "required": False, "description": "Alamat email"},
            {"name": "notes", "required": False, "description": "Catatan tambahan"},
            {"name": "is_active", "required": False, "description": "1 = aktif, 0 = nonaktif (default: 1)"},
        ],
    }


@admin.register(Facility)
class FacilityAdmin(ImportGuideMixin, ImportExportModelAdmin):
    resource_classes = [FacilityResource]
    list_display = ("code", "name", "facility_type", "phone", "is_active")
    list_filter = ("facility_type", "is_active")
    search_fields = ("code", "name")
    import_guide = {
        "title": "Faskes / Fasilitas Kesehatan",
        "columns": [
            {"name": "code", "required": True, "description": "Kode unik (misal: PKM-001)"},
            {"name": "name", "required": True, "description": "Nama faskes"},
            {"name": "facility_type", "required": True, "description": "PUSKESMAS / RUMAH_SAKIT / KLINIK / PUSTU / POLINDES"},
            {"name": "address", "required": False, "description": "Alamat"},
            {"name": "phone", "required": False, "description": "Nomor telepon"},
            {"name": "is_active", "required": False, "description": "1 = aktif, 0 = nonaktif (default: 1)"},
        ],
    }


@admin.register(Program)
class ProgramAdmin(ImportGuideMixin, ImportExportModelAdmin):
    resource_classes = [ProgramResource]
    list_display = ("code", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")
    import_guide = {
        "title": "Program Kesehatan",
        "columns": [
            {"name": "code", "required": True, "description": "Kode unik (misal: TB, HIV, MAL)"},
            {"name": "name", "required": True, "description": "Nama program"},
            {"name": "description", "required": False, "description": "Keterangan"},
            {"name": "is_active", "required": False, "description": "1 = aktif, 0 = nonaktif (default: 1)"},
        ],
    }


@admin.register(TherapeuticClass)
class TherapeuticClassAdmin(ImportGuideMixin, ImportExportModelAdmin):
    resource_classes = [TherapeuticClassResource]
    list_display = ("code", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")
    import_guide = {
        "title": "Terapi Obat",
        "columns": [
            {"name": "code", "required": True, "description": "Kode unik kelas terapi (misal: ABX, ANALGESIK)"},
            {"name": "name", "required": True, "description": "Nama kelas terapi obat"},
            {"name": "description", "required": False, "description": "Keterangan"},
            {"name": "is_active", "required": False, "description": "1 = aktif, 0 = nonaktif (default: 1)"},
        ],
    }


@admin.register(Item)
class ItemAdmin(ImportGuideMixin, ImportExportModelAdmin):
    resource_classes = [ItemResource]
    list_display = (
        "kode_barang",
        "nama_barang",
        "satuan",
        "kategori",
        "is_program_item",
        "is_essential",
        "program",
        "therapeutic_class_list",
        "minimum_stock",
        "is_active",
    )
    list_filter = (
        "kategori",
        "is_program_item",
        "is_essential",
        "is_active",
        "satuan",
        "program",
        "therapeutic_classes",
    )
    search_fields = (
        "kode_barang",
        "nama_barang",
        "program__code",
        "program__name",
        "therapeutic_classes__code",
        "therapeutic_classes__name",
    )
    list_per_page = 50
    import_guide = {
        "title": "Master Barang",
        "description": "Identifier unik: nama_barang. Re-import akan update data yg sudah ada.",
        "columns": [
            {"name": "nama_barang", "required": True, "description": "Nama barang (unik, dipakai sebagai ID import)"},
            {"name": "satuan", "required": True, "description": "Kode satuan dari tabel Units"},
            {"name": "kategori", "required": True, "description": "Kode kategori dari tabel Categories"},
            {"name": "is_program_item", "required": False, "description": "1 = item program, 0 = bukan (default: 0)"},
            {"name": "is_essential", "required": False, "description": "1 = item esensial, 0 = bukan (default: 0)"},
            {"name": "program", "required": False, "description": "Kode program dari tabel Programs (jika program item)"},
            {"name": "therapeutic_classes", "required": False, "description": "Daftar kode terapi obat, pisahkan dengan | (contoh: ABX|RESP)"},
            {"name": "minimum_stock", "required": False, "description": "Batas minimum stok (default: 0)"},
            {"name": "description", "required": False, "description": "Keterangan"},
            {"name": "is_active", "required": False, "description": "1 = aktif, 0 = nonaktif (default: 1)"},
        ],
    }

    @admin.display(description="Terapi Obat")
    def therapeutic_class_list(self, obj):
        return ", ".join(
            obj.therapeutic_classes.order_by("name").values_list("name", flat=True)
        ) or "-"
