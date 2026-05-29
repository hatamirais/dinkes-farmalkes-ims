from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.core.csv_exports import SanitizedCSV
from apps.items.admin import ItemAdmin, ItemResource
from apps.items.forms import ItemForm
from apps.items.models import Item, Unit, Category, Program
from apps.users.models import User


class ItemAdminCsvExportSecurityTest(TestCase):
	def setUp(self):
		self.unit = Unit.objects.create(code='TAB', name='Tablet')
		self.category = Category.objects.create(code='OBAT', name='Obat')

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
		unit = Unit.objects.create(code=' tab ', name=' Tablet   Oral ')
		self.assertEqual(unit.code, 'TAB')
		self.assertEqual(unit.name, 'Tablet Oral')

	def test_category_duplicate_name_case_insensitive_blocked(self):
		Category.objects.create(code='TABLET', name='Tablet')
		duplicate = Category(code='TABLET2', name='tablet')
		with self.assertRaises(ValidationError):
			duplicate.save()

	def test_program_duplicate_name_case_insensitive_blocked(self):
		Program.objects.create(code='HIV', name='Human Immunodeficiency Virus')
		duplicate = Program(code='HIV2', name='human immunodeficiency virus')
		with self.assertRaises(ValidationError):
			duplicate.save()


class ItemEssentialTagTests(TestCase):
	def setUp(self):
		self.unit = Unit.objects.create(code='TAB', name='Tablet')
		self.category = Category.objects.create(code='OBAT', name='Obat')

	def test_item_form_exposes_essential_flag(self):
		form = ItemForm()
		self.assertIn('is_essential', form.fields)

	def test_item_defaults_to_not_essential(self):
		item = Item.objects.create(
			nama_barang='Paracetamol',
			satuan=self.unit,
			kategori=self.category,
		)
		self.assertFalse(item.is_essential)

	def test_item_list_shows_essential_badge(self):
		user = User.objects.create_superuser(
			username='admin',
			email='admin@example.com',
			password='password12345',
		)
		self.client.force_login(user)
		Item.objects.create(
			nama_barang='Amoxicillin',
			satuan=self.unit,
			kategori=self.category,
			is_essential=True,
		)

		response = self.client.get(reverse('items:item_list'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, '[E] Esensial')

	def test_picker_label_strips_program_and_essential_suffixes(self):
		item = Item.objects.create(
			nama_barang='Isoniazid (H) 300 mg Tablet [P] [E]',
			satuan=self.unit,
			kategori=self.category,
		)

		self.assertEqual(item.picker_label, 'Isoniazid (H) 300 mg Tablet')
