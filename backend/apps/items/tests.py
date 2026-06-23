from django.contrib.admin.sites import AdminSite
from tablib import Dataset
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.core.csv_exports import SanitizedCSV
from apps.items.admin import ItemAdmin, ItemResource
from apps.items.forms import ItemForm
from apps.items.models import Category, Item, Program, TherapeuticClass, Unit
from apps.users.models import User


class ItemAdminCsvExportSecurityTest(TestCase):
    def setUp(self):
        self.unit = Unit.objects.create(code="TAB", name="Tablet")
        self.category = Category.objects.create(code="OBAT", name="Obat")

    def test_item_admin_uses_sanitized_csv_format(self):
        admin = ItemAdmin(Item, AdminSite())

        self.assertIn(SanitizedCSV, admin.get_export_formats())

    def test_item_resource_csv_export_neutralizes_formula_prefixed_values(self):
        item = Item.objects.create(
            nama_barang='=HYPERLINK("http://example.com")',
            satuan=self.unit,
            kategori=self.category,
        )

        dataset = ItemResource().export(Item.objects.filter(pk=item.pk))
        csv_output = SanitizedCSV().export_data(dataset)

        self.assertIn("\"'=HYPERLINK", csv_output)
        self.assertIn(item.kode_barang, csv_output)


class LookupModelGuardrailTest(TestCase):
    def test_unit_save_normalizes_code_and_name(self):
        unit = Unit.objects.create(code=" tab ", name=" Tablet   Oral ")
        self.assertEqual(unit.code, "TAB")
        self.assertEqual(unit.name, "Tablet Oral")

    def test_category_duplicate_name_case_insensitive_blocked(self):
        Category.objects.create(code="TABLET", name="Tablet")
        duplicate = Category(code="TABLET2", name="tablet")
        with self.assertRaises(ValidationError):
            duplicate.save()

    def test_program_duplicate_name_case_insensitive_blocked(self):
        Program.objects.create(code="HIV", name="Human Immunodeficiency Virus")
        duplicate = Program(code="HIV2", name="human immunodeficiency virus")
        with self.assertRaises(ValidationError):
            duplicate.save()

    def test_therapeutic_class_duplicate_name_case_insensitive_blocked(self):
        TherapeuticClass.objects.create(code="ABX", name="Antibiotik")
        duplicate = TherapeuticClass(code="ABX2", name="antibiotik")
        with self.assertRaises(ValidationError):
            duplicate.save()


class ItemTherapeuticClassTests(TestCase):
    def setUp(self):
        self.unit = Unit.objects.create(code="TAB", name="Tablet")
        self.category = Category.objects.create(code="OBAT", name="Obat")
        self.therapy_antibiotic = TherapeuticClass.objects.create(
            code="ABX",
            name="Antibiotik",
        )
        self.therapy_respiratory = TherapeuticClass.objects.create(
            code="RESP",
            name="Respirasi",
        )

    def test_item_form_exposes_therapeutic_classes_field(self):
        form = ItemForm()
        self.assertIn("therapeutic_classes", form.fields)

    def test_item_can_store_multiple_therapeutic_classes(self):
        item = Item.objects.create(
            nama_barang="Amoxicillin",
            satuan=self.unit,
            kategori=self.category,
        )
        item.therapeutic_classes.set(
            [self.therapy_antibiotic, self.therapy_respiratory]
        )

        self.assertQuerySetEqual(
            item.therapeutic_classes.order_by("code").values_list("code", flat=True),
            ["ABX", "RESP"],
            transform=lambda value: value,
        )

    def test_item_resource_exports_pipe_separated_therapeutic_codes(self):
        item = Item.objects.create(
            nama_barang="Amoxicillin",
            satuan=self.unit,
            kategori=self.category,
        )
        item.therapeutic_classes.set(
            [self.therapy_antibiotic, self.therapy_respiratory]
        )

        dataset = ItemResource().export(Item.objects.filter(pk=item.pk))

        self.assertEqual(dataset.dict[0]["therapeutic_classes"], "ABX|RESP")

    def test_item_resource_imports_multiple_therapeutic_codes(self):
        csv = (
            "nama_barang,satuan,kategori,is_program_item,program,therapeutic_classes,minimum_stock,description,is_active\n"
            "Paracetamol,TAB,OBAT,0,,ABX|RESP,0,desc,1\n"
        )
        dataset = Dataset().load(csv, format="csv")

        result = ItemResource().import_data(dataset, dry_run=False, raise_errors=True)

        self.assertFalse(result.has_errors())
        item = Item.objects.get(nama_barang="Paracetamol")
        self.assertQuerySetEqual(
            item.therapeutic_classes.order_by("code").values_list("code", flat=True),
            ["ABX", "RESP"],
            transform=lambda value: value,
        )

    def test_item_resource_rejects_unknown_therapeutic_code(self):
        csv = (
            "nama_barang,satuan,kategori,is_program_item,program,therapeutic_classes,minimum_stock,description,is_active\n"
            "Paracetamol,TAB,OBAT,0,,UNKNOWN,0,desc,1\n"
        )
        dataset = Dataset().load(csv, format="csv")

        with self.assertRaises(Exception) as exc:
            ItemResource().import_data(dataset, dry_run=False, raise_errors=True)

        self.assertIn("Kode kelas terapi tidak ditemukan", str(exc.exception))


class ItemEssentialTagTests(TestCase):
    def setUp(self):
        self.unit = Unit.objects.create(code="TAB", name="Tablet")
        self.category = Category.objects.create(code="OBAT", name="Obat")
        self.therapeutic_class = TherapeuticClass.objects.create(
            code="ANLG",
            name="Analgesik",
        )

    def test_item_defaults_to_not_essential(self):
        item = Item.objects.create(
            nama_barang="Paracetamol",
            satuan=self.unit,
            kategori=self.category,
        )
        self.assertFalse(item.is_essential)

    def test_item_list_shows_essential_badge_and_therapeutic_class(self):
        user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="password12345",
        )
        self.client.force_login(user)
        item = Item.objects.create(
            nama_barang="Amoxicillin",
            satuan=self.unit,
            kategori=self.category,
            is_essential=True,
        )
        item.therapeutic_classes.add(self.therapeutic_class)

        response = self.client.get(reverse("items:item_list"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "[E] Esensial")
        self.assertContains(response, "Analgesik")

    def test_item_list_filters_by_therapeutic_class(self):
        user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="password12345",
        )
        self.client.force_login(user)

        item = Item.objects.create(
            nama_barang="Amoxicillin",
            satuan=self.unit,
            kategori=self.category,
        )
        item.therapeutic_classes.add(self.therapeutic_class)
        other = Item.objects.create(
            nama_barang="Vitamin C",
            satuan=self.unit,
            kategori=self.category,
        )

        response = self.client.get(
            reverse("items:item_list"),
            {"therapeutic_class": self.therapeutic_class.pk},
            secure=True,
        )

        self.assertContains(response, item.nama_barang)
        self.assertNotContains(response, other.nama_barang)

    def test_picker_label_strips_program_and_essential_suffixes(self):
        item = Item.objects.create(
            nama_barang="Isoniazid (H) 300 mg Tablet [P] [E]",
            satuan=self.unit,
            kategori=self.category,
        )

        self.assertEqual(item.picker_label, "Isoniazid (H) 300 mg Tablet")


class TherapeuticClassQuickCreateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="password12345",
        )
        self.client.force_login(self.user)

    def test_quick_create_therapeutic_class_creates_lookup(self):
        response = self.client.post(
            reverse("items:quick_create_therapeutic_class"),
            {
                "code": "ABX",
                "name": "Antibiotik",
                "description": "Terapi infeksi",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(TherapeuticClass.objects.filter(code="ABX").exists())

    def test_quick_create_therapeutic_class_rejects_duplicate_name(self):
        TherapeuticClass.objects.create(code="ABX", name="Antibiotik")

        response = self.client.post(
            reverse("items:quick_create_therapeutic_class"),
            {
                "code": "ABX2",
                "name": "antibiotik",
                "description": "Duplikat",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Nama sudah digunakan", response.json()["error"])
