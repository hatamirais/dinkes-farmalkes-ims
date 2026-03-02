from django.test import TestCase
from django.core.files.base import ContentFile
from django.contrib.admin.sites import site

from apps.items.admin import ItemResource
from apps.items.models import Program, Item, Unit, Category


class ItemImportTest(TestCase):
    def setUp(self):
        # create lookup records
        self.unit = Unit.objects.create(code="TAB", name="Tablet")
        self.cat = Category.objects.create(code="CAT1", name="General")
        # ensure no DEFAULT program exists
        Program.objects.filter(code__iexact="DEFAULT").delete()

    def test_import_assigns_default_program(self):
        csv = (
            "nama_barang,satuan,kategori,is_program_item,program,minimum_stock,description,is_active\n"
            "Test Item,TAB,CAT1,1,,0,desc,1\n"
        )
        res = ItemResource()
        dataset = res.get_import_data(ContentFile(csv))
        # before import, no program exists
        self.assertFalse(Program.objects.filter(code__iexact="DEFAULT").exists())

        # run import (use import_data which triggers before_import_row)
        result = res.import_data(dataset, dry_run=False, raise_errors=True)

        # after import, DEFAULT program should exist and item should be created
        default = Program.objects.filter(code__iexact="DEFAULT").first()
        self.assertIsNotNone(default)
        item = Item.objects.filter(nama_barang="Test Item").first()
        self.assertIsNotNone(item)
        self.assertEqual(item.program, default)
