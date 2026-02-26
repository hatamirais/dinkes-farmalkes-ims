from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.items.models import Unit, Category, Program


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
