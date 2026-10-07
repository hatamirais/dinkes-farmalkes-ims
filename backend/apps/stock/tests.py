from decimal import Decimal
from datetime import datetime
from datetime import timedelta
from datetime import date
import threading
from unittest.mock import patch
import importlib

from tablib import Dataset

from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, connections
from django.test import Client
from django.test import SimpleTestCase
from django.test import RequestFactory, TestCase
from django.test import TransactionTestCase
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.core.csv_exports import SanitizedCSV
from apps.users.models import ModuleAccess, User
from apps.stock.admin import (
    StockAdmin,
    StockResource,
    StockTransferAdmin,
    StockTransferItemInline,
)
from apps.items.models import Category, Facility, FundingSource, Item, Location, Supplier, Unit
from apps.receiving.models import Receiving, ReceivingItem
from apps.stock import views as stock_views
from apps.stock.models import (
    OpeningBalanceImport,
    OpeningBalanceImportItem,
    SourceDocumentNumberClaim,
    Stock,
    StockTransfer,
    StockTransferItem,
    Transaction,
)
from apps.expired.models import Expired, ExpiredItem
from apps.recall.models import Recall, RecallItem
from apps.stock_opname.models import StockOpname, StockOpnameItem
from apps.core.models import DocumentNumberRule, SystemSettings
from apps.allocation.models import Allocation, AllocationItem
from apps.distribution.models import Distribution, DistributionItem
from apps.puskesmas.models import PuskesmasReceiptConfirmation, PuskesmasReceiptConfirmationItem


class StockPickerLabelTests(TestCase):
    def test_total_value_uses_widened_decimal_precision(self):
        unit = Unit.objects.create(code="VAL-UNT", name="Value Unit")
        category = Category.objects.create(code="VAL-CAT", name="Value Category")
        item = Item.objects.create(
            kode_barang="VAL-ITEM",
            nama_barang="Value Item",
            satuan=unit,
            kategori=category,
        )
        location = Location.objects.create(code="VAL-LOC", name="Value Location")
        funding = FundingSource.objects.create(code="VAL-FUND", name="Value Funding")
        stock = Stock.objects.create(
            item=item,
            location=location,
            batch_lot="BATCH-VALUE",
            source_document_number="RCV-VALUE-001",
            expiry_date=date(2030, 1, 31),
            quantity=Decimal("9999999999.99"),
            unit_price=Decimal("9999999999999.1234567891"),
            sumber_dana=funding,
        )

        self.assertEqual(
            stock.total_value,
            Decimal("99999999999891234567891.008765432109"),
        )

    def test_picker_label_includes_source_layer_context(self):
        unit = Unit.objects.create(code="LBL-UNT", name="Label Unit")
        category = Category.objects.create(code="LBL-CAT", name="Label Category")
        item = Item.objects.create(
            kode_barang="LBL-ITEM",
            nama_barang="Label Item",
            satuan=unit,
            kategori=category,
        )
        location = Location.objects.create(code="LBL-LOC", name="Label Location")
        funding = FundingSource.objects.create(code="LBL-FUND", name="Label Funding")
        stock = Stock.objects.create(
            item=item,
            location=location,
            batch_lot="BATCH-LABEL",
            source_document_number="RCV-LAYER-001",
            expiry_date=date(2030, 1, 31),
            quantity=Decimal("12"),
            reserved=Decimal("2"),
            unit_price=Decimal("3456.78"),
            sumber_dana=funding,
        )

        self.assertEqual(
            stock.picker_label,
            (
                "BATCH-LABEL | Tersedia: 10 | Exp: 31/01/2030 | "
                "Dokumen: RCV-LAYER-001 | Dana: LBL-FUND | Harga: 3456.78"
            ),
        )


class StockAdminCsvExportSecurityTest(TestCase):
    def setUp(self):
        self.unit = Unit.objects.create(code='TAB', name='Tablet')
        self.category = Category.objects.create(code='OBAT', name='Obat', sort_order=1)
        self.item = Item.objects.create(
            nama_barang='Paracetamol 500mg',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
        )
        self.location = Location.objects.create(code='GUDANG', name='Gudang Utama')
        self.funding = FundingSource.objects.create(code='APBD', name='APBD')
        self.other_funding = FundingSource.objects.create(code='DAK', name='DAK')

    def test_stock_admin_uses_sanitized_csv_format(self):
        admin = StockAdmin(Stock, AdminSite())

        self.assertIn(SanitizedCSV, admin.get_export_formats())

    def test_stock_resource_csv_export_neutralizes_formula_prefixed_values(self):
        stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='@BATCH-01',
            expiry_date=date(2027, 1, 1),
            quantity=Decimal('25'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            source_document_number='SRC-DOC-TRF',
        )

        dataset = StockResource().export(Stock.objects.filter(pk=stock.pk))
        csv_output = SanitizedCSV().export_data(dataset)

        self.assertIn("'@BATCH-01", csv_output)
        self.assertIn(self.item.kode_barang, csv_output)

    def test_stock_resource_import_rejects_blank_expiry_for_expiring_item(self):
        dataset = Dataset(
            headers=[
                'item_code',
                'location_code',
                'batch_lot',
                'expiry_date',
                'quantity',
                'reserved',
                'unit_price',
                'sumber_dana_code',
            ]
        )
        dataset.append([
            self.item.kode_barang,
            self.location.code,
            'BATCH-EXP-01',
            '',
            '10',
            '0',
            '1000',
            self.funding.code,
        ])

        result = StockResource().import_data(dataset, dry_run=True, raise_errors=False)

        self.assertEqual(len(result.invalid_rows), 1)
        self.assertIn('Tanggal kedaluwarsa wajib diisi untuk item ini.', str(result.invalid_rows[0].error))

    def test_stock_resource_import_allows_blank_expiry_for_non_expiring_item(self):
        self.item.requires_expiry_date = False
        self.item.save(update_fields=['requires_expiry_date', 'updated_at'])
        dataset = Dataset(
            headers=[
                'item_code',
                'location_code',
                'batch_lot',
                'expiry_date',
                'quantity',
                'reserved',
                'unit_price',
                'sumber_dana_code',
            ]
        )
        dataset.append([
            self.item.kode_barang,
            self.location.code,
            'BATCH-NOEXP-01',
            '',
            '12',
            '0',
            '500',
            self.funding.code,
        ])

        result = StockResource().import_data(dataset, dry_run=True, raise_errors=False)

        self.assertFalse(result.has_errors())
        self.assertFalse(result.has_validation_errors())
        self.assertEqual(len(result.invalid_rows), 0)

    def test_stock_resource_import_keeps_distinct_rows_per_funding_source(self):
        dataset = Dataset(
            headers=[
                'item_code',
                'location_code',
                'batch_lot',
                'expiry_date',
                'quantity',
                'reserved',
                'unit_price',
                'sumber_dana_code',
            ]
        )
        dataset.append([
            self.item.kode_barang,
            self.location.code,
            'BATCH-FUND-01',
            '01/01/2030',
            '10',
            '0',
            '1000',
            self.funding.code,
        ])
        dataset.append([
            self.item.kode_barang,
            self.location.code,
            'BATCH-FUND-01',
            '01/01/2030',
            '7',
            '0',
            '1250',
            self.other_funding.code,
        ])

        result = StockResource().import_data(dataset, dry_run=False, raise_errors=False)

        self.assertFalse(result.has_errors())
        self.assertFalse(result.has_validation_errors())
        self.assertEqual(len(result.invalid_rows), 0)
        self.assertEqual(
            Stock.objects.filter(
                item=self.item,
                location=self.location,
                batch_lot='BATCH-FUND-01',
            ).count(),
            2,
        )
        self.assertEqual(
            Stock.objects.get(
                item=self.item,
                location=self.location,
                batch_lot='BATCH-FUND-01',
                sumber_dana=self.funding,
            ).quantity,
            Decimal('10'),
        )
        self.assertEqual(
            Stock.objects.get(
                item=self.item,
                location=self.location,
                batch_lot='BATCH-FUND-01',
                sumber_dana=self.other_funding,
            ).quantity,
            Decimal('7'),
        )


@override_settings(SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class OpeningBalanceImportAdminTests(TestCase):
    def setUp(self):
        self.unit = Unit.objects.create(code="OBI-TAB", name="Tablet")
        self.category = Category.objects.create(code="OBI-CAT", name="Obat")
        self.item = Item.objects.create(
            kode_barang="OBI-ITEM-001",
            nama_barang="Opening Balance Item",
            satuan=self.unit,
            kategori=self.category,
        )
        self.location = Location.objects.create(code="OBI-LOC", name="Gudang Saldo")
        self.funding = FundingSource.objects.create(code="OBI-FUND", name="Dana Saldo")
        self.admin_user = User.objects.create_superuser(
            username="opening-admin",
            password="secret12345",
        )
        self.staff_user = User.objects.create_user(
            username="opening-staff",
            password="secret12345",
            is_staff=True,
            role=User.Role.GUDANG,
        )

    def _csv_upload(self, content):
        return SimpleUploadedFile(
            "opening_balance.csv",
            content.encode("utf-8"),
            content_type="text/csv",
        )

    def test_opening_balance_import_posts_stock_and_initial_import_transaction(self):
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,BATCH-001,01/01/2028,2500\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CONFIRM IMPORT")
        preview_token = response.context["preview_token"]
        self.assertFalse(OpeningBalanceImport.objects.exists())
        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"action": "confirm", "preview_token": preview_token},
        )

        self.assertEqual(response.status_code, 302)
        opening_balance = OpeningBalanceImport.objects.get(
            document_number="SALDO-AWAL-2026"
        )
        claim = SourceDocumentNumberClaim.objects.get(
            document_number="SALDO-AWAL-2026"
        )
        self.assertEqual(opening_balance.effective_date, date(2026, 1, 1))
        self.assertEqual(
            claim.source_type,
            SourceDocumentNumberClaim.SourceType.OPENING_BALANCE,
        )
        self.assertEqual(claim.source_id, opening_balance.pk)
        self.assertEqual(OpeningBalanceImportItem.objects.count(), 1)
        stock = Stock.objects.get(
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            sumber_dana=self.funding,
            source_document_number="SALDO-AWAL-2026",
        )
        self.assertEqual(stock.quantity, Decimal("10"))
        self.assertEqual(stock.source_document_number, "SALDO-AWAL-2026")
        self.assertIsNone(stock.receiving_ref)
        tx = Transaction.objects.get(reference_type=Transaction.ReferenceType.INITIAL_IMPORT)
        self.assertEqual(tx.reference_id, opening_balance.pk)
        self.assertEqual(tx.quantity, Decimal("10"))

    def test_opening_balance_import_rejects_claimed_source_document_number(self):
        SourceDocumentNumberClaim.objects.create(
            document_number="SALDO-AWAL-CLAIMED",
            source_type=SourceDocumentNumberClaim.SourceType.RECEIVING,
        )
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-CLAIMED,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,BATCH-001,01/01/2028,2500\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "sudah diklaim oleh dokumen sumber stok lain",
        )
        self.assertFalse(OpeningBalanceImport.objects.exists())

    def test_opening_balance_import_rejects_orphan_opening_balance_claim(self):
        SourceDocumentNumberClaim.objects.create(
            document_number="SALDO-AWAL-ORPHAN",
            source_type=SourceDocumentNumberClaim.SourceType.OPENING_BALANCE,
            source_id=None,
        )
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-ORPHAN,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,BATCH-001,01/01/2028,2500\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "sudah diklaim oleh dokumen sumber stok lain",
        )
        self.assertFalse(OpeningBalanceImport.objects.exists())

    def test_opening_balance_import_clears_existing_receiving_reference(self):
        receiving = Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.GRANT,
            document_number="REC-OB-001",
            receiving_date=date(2026, 1, 1),
            sumber_dana=self.funding,
            created_by=self.admin_user,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            expiry_date=date(2028, 1, 1),
            quantity=Decimal("5"),
            unit_price=Decimal("2500"),
            sumber_dana=self.funding,
            receiving_ref=receiving,
            source_document_number="SALDO-AWAL-2026",
        )
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,BATCH-001,01/01/2028,2500\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CONFIRM IMPORT")
        preview_token = response.context["preview_token"]
        self.assertFalse(OpeningBalanceImport.objects.exists())
        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"action": "confirm", "preview_token": preview_token},
        )

        self.assertEqual(response.status_code, 302)
        stock = Stock.objects.get(
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            sumber_dana=self.funding,
            source_document_number="SALDO-AWAL-2026",
        )
        self.assertEqual(stock.quantity, Decimal("15"))
        self.assertIsNone(stock.receiving_ref)

    def test_opening_balance_reimport_skips_existing_rows_and_imports_new_rows(self):
        opening_balance = OpeningBalanceImport.objects.create(
            document_number="SALDO-AWAL-2026",
            effective_date=date(2026, 1, 1),
            created_by=self.admin_user,
            posted_at=timezone.now(),
        )
        SourceDocumentNumberClaim.objects.create(
            document_number="SALDO-AWAL-2026",
            source_type=SourceDocumentNumberClaim.SourceType.OPENING_BALANCE,
            source_id=opening_balance.pk,
        )
        OpeningBalanceImportItem.objects.create(
            opening_balance=opening_balance,
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            expiry_date=date(2028, 1, 1),
            quantity=Decimal("10"),
            unit_price=Decimal("2500"),
            sumber_dana=self.funding,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            expiry_date=date(2028, 1, 1),
            quantity=Decimal("10"),
            unit_price=Decimal("2500"),
            sumber_dana=self.funding,
            source_document_number="SALDO-AWAL-2026",
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            quantity=Decimal("10"),
            unit_price=Decimal("2500"),
            source_document_number="SALDO-AWAL-2026",
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.INITIAL_IMPORT,
            reference_id=opening_balance.pk,
            user=self.admin_user,
        )
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,BATCH-001,01/01/2028,2500\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},5,BATCH-002,01/01/2028,2500\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Skipped")
        self.assertContains(response, "New")
        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"action": "confirm", "preview_token": response.context["preview_token"]},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(OpeningBalanceImport.objects.count(), 1)
        self.assertEqual(SourceDocumentNumberClaim.objects.count(), 1)
        self.assertEqual(OpeningBalanceImportItem.objects.count(), 2)
        self.assertEqual(
            Stock.objects.get(batch_lot="BATCH-001").quantity,
            Decimal("10"),
        )
        self.assertEqual(
            Stock.objects.get(batch_lot="BATCH-002").quantity,
            Decimal("5"),
        )
        self.assertEqual(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.INITIAL_IMPORT
            ).count(),
            2,
        )

    def test_opening_balance_reimport_posts_delta_for_existing_stock_layer(self):
        opening_balance = OpeningBalanceImport.objects.create(
            document_number="SALDO-AWAL-2026",
            effective_date=date(2026, 1, 1),
            created_by=self.admin_user,
            posted_at=timezone.now(),
        )
        SourceDocumentNumberClaim.objects.create(
            document_number="SALDO-AWAL-2026",
            source_type=SourceDocumentNumberClaim.SourceType.OPENING_BALANCE,
            source_id=opening_balance.pk,
        )
        OpeningBalanceImportItem.objects.create(
            opening_balance=opening_balance,
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            expiry_date=date(2028, 1, 1),
            quantity=Decimal("10"),
            unit_price=Decimal("2500"),
            sumber_dana=self.funding,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            expiry_date=date(2028, 1, 1),
            quantity=Decimal("10"),
            unit_price=Decimal("2500"),
            sumber_dana=self.funding,
            source_document_number="SALDO-AWAL-2026",
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            quantity=Decimal("10"),
            unit_price=Decimal("2500"),
            source_document_number="SALDO-AWAL-2026",
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.INITIAL_IMPORT,
            reference_id=opening_balance.pk,
            user=self.admin_user,
        )
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},15,BATCH-001,01/01/2028,2500\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Delta")
        self.assertContains(response, "Qty Added")
        self.assertContains(response, "Requested Total")
        self.assertContains(response, "5")
        self.assertContains(response, "15")
        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"action": "confirm", "preview_token": response.context["preview_token"]},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(OpeningBalanceImportItem.objects.count(), 2)
        self.assertEqual(Stock.objects.get(batch_lot="BATCH-001").quantity, Decimal("15"))
        self.assertEqual(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.INITIAL_IMPORT
            ).count(),
            2,
        )
        self.assertEqual(
            Transaction.objects.order_by("-id").first().quantity,
            Decimal("5"),
        )

    def test_opening_balance_reimport_rejects_lower_existing_stock_layer_total(self):
        opening_balance = OpeningBalanceImport.objects.create(
            document_number="SALDO-AWAL-2026",
            effective_date=date(2026, 1, 1),
            created_by=self.admin_user,
            posted_at=timezone.now(),
        )
        SourceDocumentNumberClaim.objects.create(
            document_number="SALDO-AWAL-2026",
            source_type=SourceDocumentNumberClaim.SourceType.OPENING_BALANCE,
            source_id=opening_balance.pk,
        )
        OpeningBalanceImportItem.objects.create(
            opening_balance=opening_balance,
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            expiry_date=date(2028, 1, 1),
            quantity=Decimal("10"),
            unit_price=Decimal("2500"),
            sumber_dana=self.funding,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            expiry_date=date(2028, 1, 1),
            quantity=Decimal("10"),
            unit_price=Decimal("2500"),
            sumber_dana=self.funding,
            source_document_number="SALDO-AWAL-2026",
        )
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},7,BATCH-001,01/01/2028,2500\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Validasi gagal")
        self.assertContains(response, "Quantity reimport tidak boleh lebih kecil")
        self.assertEqual(OpeningBalanceImportItem.objects.count(), 1)
        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(Stock.objects.get(batch_lot="BATCH-001").quantity, Decimal("10"))

    def test_opening_balance_reimport_uses_migrated_collision_source_layer(self):
        document_number = "SRC-COLLIDE"
        source_document_number = StockAdmin._opening_balance_source_document_number(
            document_number,
            True,
        )
        receiving = Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.GRANT,
            document_number=document_number,
            receiving_date=date(2026, 1, 1),
            sumber_dana=self.funding,
            created_by=self.admin_user,
        )
        opening_balance = OpeningBalanceImport.objects.create(
            document_number=document_number,
            effective_date=date(2026, 1, 1),
            created_by=self.admin_user,
            posted_at=timezone.now(),
        )
        SourceDocumentNumberClaim.objects.update_or_create(
            document_number=document_number,
            defaults={
                "source_type": SourceDocumentNumberClaim.SourceType.RECEIVING,
                "source_id": receiving.pk,
            },
        )
        SourceDocumentNumberClaim.objects.update_or_create(
            document_number=source_document_number,
            defaults={
                "source_type": SourceDocumentNumberClaim.SourceType.OPENING_BALANCE,
                "source_id": None,
            },
        )
        OpeningBalanceImportItem.objects.create(
            opening_balance=opening_balance,
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            expiry_date=date(2028, 1, 1),
            quantity=Decimal("10"),
            unit_price=Decimal("2500"),
            sumber_dana=self.funding,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            expiry_date=date(2028, 1, 1),
            quantity=Decimal("10"),
            unit_price=Decimal("2500"),
            sumber_dana=self.funding,
            source_document_number=source_document_number,
        )
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"{document_number},01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,BATCH-001,01/01/2028,2500\n"
            f"{document_number},01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},5,BATCH-002,01/01/2028,2500\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Skipped")
        self.assertContains(response, "New")
        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"action": "confirm", "preview_token": response.context["preview_token"]},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(OpeningBalanceImport.objects.count(), 1)
        self.assertEqual(OpeningBalanceImportItem.objects.count(), 2)
        self.assertEqual(
            Stock.objects.get(batch_lot="BATCH-002").source_document_number,
            source_document_number,
        )
        self.assertEqual(
            Transaction.objects.get(batch_lot="BATCH-002").source_document_number,
            source_document_number,
        )

    def test_opening_balance_reimport_uses_retained_migrated_collision_claim(self):
        document_number = "SRC-DELETED-RECEIVING"
        source_document_number = StockAdmin._opening_balance_source_document_number(
            document_number,
            True,
        )
        receiving = Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.GRANT,
            document_number=document_number,
            receiving_date=date(2026, 1, 1),
            sumber_dana=self.funding,
            created_by=self.admin_user,
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot="RECEIVING-BATCH",
            quantity=Decimal("1"),
            unit_price=Decimal("2500"),
            source_document_number=document_number,
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=receiving.pk,
            user=self.admin_user,
        )
        opening_balance = OpeningBalanceImport.objects.create(
            document_number=document_number,
            effective_date=date(2026, 1, 1),
            created_by=self.admin_user,
            posted_at=timezone.now(),
        )
        SourceDocumentNumberClaim.objects.update_or_create(
            document_number=source_document_number,
            defaults={
                "source_type": SourceDocumentNumberClaim.SourceType.OPENING_BALANCE,
                "source_id": None,
            },
        )
        OpeningBalanceImportItem.objects.create(
            opening_balance=opening_balance,
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            expiry_date=date(2028, 1, 1),
            quantity=Decimal("10"),
            unit_price=Decimal("2500"),
            sumber_dana=self.funding,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            expiry_date=date(2028, 1, 1),
            quantity=Decimal("10"),
            unit_price=Decimal("2500"),
            sumber_dana=self.funding,
            source_document_number=source_document_number,
        )
        receiving.delete()
        self.assertTrue(
            SourceDocumentNumberClaim.objects.filter(
                document_number=document_number,
                source_type=SourceDocumentNumberClaim.SourceType.RECEIVING,
            ).exists()
        )
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"{document_number},01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,BATCH-001,01/01/2028,2500\n"
            f"{document_number},01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},5,BATCH-002,01/01/2028,2500\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Skipped")
        self.assertContains(response, "New")
        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"action": "confirm", "preview_token": response.context["preview_token"]},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            Stock.objects.get(batch_lot="BATCH-002").source_document_number,
            source_document_number,
        )
        self.assertEqual(
            Transaction.objects.get(
                batch_lot="BATCH-002",
                reference_type=Transaction.ReferenceType.INITIAL_IMPORT,
            ).source_document_number,
            source_document_number,
        )

    def test_opening_balance_reimport_ignores_unrelated_synthetic_claim(self):
        document_number = "SALDO-AWAL-2026"
        unrelated_document_number = StockAdmin._opening_balance_source_document_number(
            document_number,
            True,
        )
        opening_balance = OpeningBalanceImport.objects.create(
            document_number=document_number,
            effective_date=date(2026, 1, 1),
            created_by=self.admin_user,
            posted_at=timezone.now(),
        )
        unrelated_opening_balance = OpeningBalanceImport.objects.create(
            document_number=unrelated_document_number,
            effective_date=date(2026, 1, 1),
            created_by=self.admin_user,
            posted_at=timezone.now(),
        )
        SourceDocumentNumberClaim.objects.create(
            document_number=document_number,
            source_type=SourceDocumentNumberClaim.SourceType.OPENING_BALANCE,
            source_id=opening_balance.pk,
        )
        SourceDocumentNumberClaim.objects.create(
            document_number=unrelated_document_number,
            source_type=SourceDocumentNumberClaim.SourceType.OPENING_BALANCE,
            source_id=unrelated_opening_balance.pk,
        )
        OpeningBalanceImportItem.objects.create(
            opening_balance=opening_balance,
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            expiry_date=date(2028, 1, 1),
            quantity=Decimal("10"),
            unit_price=Decimal("2500"),
            sumber_dana=self.funding,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            expiry_date=date(2028, 1, 1),
            quantity=Decimal("10"),
            unit_price=Decimal("2500"),
            sumber_dana=self.funding,
            source_document_number=document_number,
        )
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"{document_number},01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,BATCH-001,01/01/2028,2500\n"
            f"{document_number},01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},5,BATCH-002,01/01/2028,2500\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Skipped")
        self.assertContains(response, "New")
        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"action": "confirm", "preview_token": response.context["preview_token"]},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            Stock.objects.get(batch_lot="BATCH-002").source_document_number,
            document_number,
        )
        self.assertFalse(
            Stock.objects.filter(
                batch_lot="BATCH-002",
                source_document_number=unrelated_document_number,
            ).exists()
        )

    def test_opening_balance_reimport_all_existing_rows_succeeds_without_new_ledger(self):
        opening_balance = OpeningBalanceImport.objects.create(
            document_number="SALDO-AWAL-2026",
            effective_date=date(2026, 1, 1),
            created_by=self.admin_user,
            posted_at=timezone.now(),
        )
        SourceDocumentNumberClaim.objects.create(
            document_number="SALDO-AWAL-2026",
            source_type=SourceDocumentNumberClaim.SourceType.OPENING_BALANCE,
            source_id=opening_balance.pk,
        )
        OpeningBalanceImportItem.objects.create(
            opening_balance=opening_balance,
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            expiry_date=date(2028, 1, 1),
            quantity=Decimal("10"),
            unit_price=Decimal("2500"),
            sumber_dana=self.funding,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            expiry_date=date(2028, 1, 1),
            quantity=Decimal("10"),
            unit_price=Decimal("2500"),
            sumber_dana=self.funding,
            source_document_number="SALDO-AWAL-2026",
        )
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,BATCH-001,01/01/2028,2500\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Skipped")
        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"action": "confirm", "preview_token": response.context["preview_token"]},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(OpeningBalanceImport.objects.count(), 1)
        self.assertEqual(OpeningBalanceImportItem.objects.count(), 1)
        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(Stock.objects.get().quantity, Decimal("10"))

    def test_opening_balance_reimport_rejects_blank_batch_lot(self):
        opening_balance = OpeningBalanceImport.objects.create(
            document_number="SALDO-AWAL-2026",
            effective_date=date(2026, 1, 1),
            created_by=self.admin_user,
            posted_at=timezone.now(),
        )
        SourceDocumentNumberClaim.objects.create(
            document_number="SALDO-AWAL-2026",
            source_type=SourceDocumentNumberClaim.SourceType.OPENING_BALANCE,
            source_id=opening_balance.pk,
        )
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,,01/01/2028,2500\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "batch_lot wajib diisi saat reimport")
        self.assertFalse(Stock.objects.exists())

    def test_opening_balance_confirm_rechecks_existing_stock_after_preview(self):
        opening_balance = OpeningBalanceImport.objects.create(
            document_number="SALDO-AWAL-2026",
            effective_date=date(2026, 1, 1),
            created_by=self.admin_user,
            posted_at=timezone.now(),
        )
        SourceDocumentNumberClaim.objects.create(
            document_number="SALDO-AWAL-2026",
            source_type=SourceDocumentNumberClaim.SourceType.OPENING_BALANCE,
            source_id=opening_balance.pk,
        )
        OpeningBalanceImportItem.objects.create(
            opening_balance=opening_balance,
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            expiry_date=date(2028, 1, 1),
            quantity=Decimal("10"),
            unit_price=Decimal("2500"),
            sumber_dana=self.funding,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            expiry_date=date(2028, 1, 1),
            quantity=Decimal("10"),
            unit_price=Decimal("2500"),
            sumber_dana=self.funding,
            source_document_number="SALDO-AWAL-2026",
        )
        stock_admin = StockAdmin(Stock, AdminSite())
        stale_preview = {
            "documents": [
                {
                    "document_number": "SALDO-AWAL-2026",
                    "effective_date": date(2026, 1, 1),
                    "rows": [
                        {
                            "item": self.item,
                            "location": self.location,
                            "funding": self.funding,
                            "batch_lot": "BATCH-001",
                            "expiry_date": date(2028, 1, 1),
                            "quantity": Decimal("10"),
                            "unit_price": Decimal("2500"),
                            "is_existing": False,
                        }
                    ],
                }
            ]
        }

        with (
            patch.object(
                stock_admin,
                "_preflight_opening_balance_csv",
                return_value={"errors": []},
            ),
            patch.object(
                stock_admin,
                "_parse_opening_balance_csv",
                return_value=stale_preview,
            ),
        ):
            result = stock_admin._process_opening_balance_csv("ignored", self.admin_user)

        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["items"], 0)
        self.assertEqual(result["transactions"], 0)
        self.assertEqual(OpeningBalanceImportItem.objects.count(), 1)
        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(Stock.objects.get().quantity, Decimal("10"))

    def test_opening_balance_confirm_rejects_stale_generated_batch_reimport(self):
        opening_balance = OpeningBalanceImport.objects.create(
            document_number="SALDO-AWAL-2026",
            effective_date=date(2026, 1, 1),
            created_by=self.admin_user,
            posted_at=timezone.now(),
        )
        SourceDocumentNumberClaim.objects.create(
            document_number="SALDO-AWAL-2026",
            source_type=SourceDocumentNumberClaim.SourceType.OPENING_BALANCE,
            source_id=opening_balance.pk,
        )
        stock_admin = StockAdmin(Stock, AdminSite())
        stale_preview = {
            "documents": [
                {
                    "document_number": "SALDO-AWAL-2026",
                    "effective_date": date(2026, 1, 1),
                    "rows": [
                        {
                            "row_num": 2,
                            "item": self.item,
                            "location": self.location,
                            "funding": self.funding,
                            "batch_lot": "SALDO-AWAL-2026-000002",
                            "batch_lot_was_supplied": False,
                            "expiry_date": date(2028, 1, 1),
                            "quantity": Decimal("10"),
                            "unit_price": Decimal("2500"),
                            "is_existing": False,
                        }
                    ],
                }
            ]
        }

        with (
            patch.object(
                stock_admin,
                "_preflight_opening_balance_csv",
                return_value={"errors": []},
            ),
            patch.object(
                stock_admin,
                "_parse_opening_balance_csv",
                return_value=stale_preview,
            ),
        ):
            with self.assertRaisesMessage(ValueError, "batch_lot wajib diisi"):
                stock_admin._process_opening_balance_csv("ignored", self.admin_user)

        self.assertFalse(OpeningBalanceImportItem.objects.exists())
        self.assertFalse(Stock.objects.exists())
        self.assertFalse(Transaction.objects.exists())

    def test_opening_balance_reimport_imports_transfer_created_stock_layer(self):
        opening_balance = OpeningBalanceImport.objects.create(
            document_number="SALDO-AWAL-2026",
            effective_date=date(2026, 1, 1),
            created_by=self.admin_user,
            posted_at=timezone.now(),
        )
        SourceDocumentNumberClaim.objects.create(
            document_number="SALDO-AWAL-2026",
            source_type=SourceDocumentNumberClaim.SourceType.OPENING_BALANCE,
            source_id=opening_balance.pk,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="BATCH-TRANSFER",
            expiry_date=date(2028, 1, 1),
            quantity=Decimal("3"),
            unit_price=Decimal("2500"),
            sumber_dana=self.funding,
            source_document_number="SALDO-AWAL-2026",
        )
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,BATCH-TRANSFER,01/01/2028,2500\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "New")
        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"action": "confirm", "preview_token": response.context["preview_token"]},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(OpeningBalanceImportItem.objects.count(), 1)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(
            Stock.objects.get(batch_lot="BATCH-TRANSFER").quantity,
            Decimal("13"),
        )

    def test_opening_balance_reimport_rejects_duplicate_new_rows(self):
        opening_balance = OpeningBalanceImport.objects.create(
            document_number="SALDO-AWAL-2026",
            effective_date=date(2026, 1, 1),
            created_by=self.admin_user,
            posted_at=timezone.now(),
        )
        SourceDocumentNumberClaim.objects.create(
            document_number="SALDO-AWAL-2026",
            source_type=SourceDocumentNumberClaim.SourceType.OPENING_BALANCE,
            source_id=opening_balance.pk,
        )
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},5,BATCH-NEW,01/01/2028,2500\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},7,BATCH-NEW,01/01/2028,2500\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Validasi gagal")
        self.assertContains(
            response,
            "Batch stok duplikat dalam CSV saldo awal",
        )
        self.assertEqual(OpeningBalanceImport.objects.count(), 1)
        self.assertFalse(OpeningBalanceImportItem.objects.exists())
        self.assertFalse(Transaction.objects.exists())
        self.assertFalse(Stock.objects.filter(batch_lot="BATCH-NEW").exists())

    def test_opening_balance_existing_header_locks_use_document_number_order(self):
        first = OpeningBalanceImport.objects.create(
            document_number="SALDO-AWAL-A",
            effective_date=date(2026, 1, 1),
            created_by=self.admin_user,
            posted_at=timezone.now(),
        )
        second = OpeningBalanceImport.objects.create(
            document_number="SALDO-AWAL-B",
            effective_date=date(2026, 1, 1),
            created_by=self.admin_user,
            posted_at=timezone.now(),
        )
        documents = [
            {"document_number": second.document_number},
            {"document_number": first.document_number},
        ]

        locked = StockAdmin._lock_existing_opening_balance_imports(documents)

        self.assertEqual(
            list(locked),
            ["SALDO-AWAL-A", "SALDO-AWAL-B"],
        )

    def test_opening_balance_new_claims_use_document_number_order(self):
        documents = [
            {"document_number": "SALDO-AWAL-B"},
            {"document_number": "SALDO-AWAL-A"},
        ]

        claims = StockAdmin._claim_new_opening_balance_document_numbers(documents, {})

        self.assertEqual(
            list(claims),
            ["SALDO-AWAL-A", "SALDO-AWAL-B"],
        )
        self.assertEqual(
            list(
                SourceDocumentNumberClaim.objects.order_by("id").values_list(
                    "document_number",
                    flat=True,
                )
            ),
            ["SALDO-AWAL-A", "SALDO-AWAL-B"],
        )

    def test_opening_balance_reimport_rejects_existing_document_date_mismatch(self):
        OpeningBalanceImport.objects.create(
            document_number="SALDO-AWAL-2026",
            effective_date=date(2026, 1, 1),
            created_by=self.admin_user,
            posted_at=timezone.now(),
        )
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-2026,02/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,BATCH-001,01/01/2028,2500\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "effective_date harus sama")
        self.assertFalse(Stock.objects.exists())

    def test_opening_balance_import_rejects_receiving_document_number_collision(self):
        Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.GRANT,
            document_number="SALDO-AWAL-2026",
            receiving_date=date(2026, 1, 1),
            sumber_dana=self.funding,
            created_by=self.admin_user,
        )
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,BATCH-001,01/01/2028,2500\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "sudah digunakan oleh dokumen penerimaan")
        self.assertFalse(OpeningBalanceImport.objects.exists())
        self.assertFalse(Stock.objects.exists())

    def test_opening_balance_import_accepts_semicolon_csv_with_decimal_comma(self):
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number;effective_date;sumber_dana_code;location_code;item_code;"
            "quantity;batch_lot;expiry_date;unit_price\n"
            f"SALDO-AWAL-2026;01/01/2026;{self.funding.code};{self.location.code};"
            f"{self.item.kode_barang};10;BATCH-001;01/01/2028;8893,31985\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CONFIRM IMPORT")
        self.assertContains(response, "CSV semicolon")
        self.assertContains(response, "8.893,31985")
        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"action": "confirm", "preview_token": response.context["preview_token"]},
        )

        self.assertEqual(response.status_code, 302)
        import_item = OpeningBalanceImportItem.objects.get()
        self.assertEqual(import_item.unit_price, Decimal("8893.31985"))
        stock = Stock.objects.get(source_document_number="SALDO-AWAL-2026")
        self.assertEqual(stock.unit_price, Decimal("8893.31985"))
        transaction = Transaction.objects.get(
            reference_type=Transaction.ReferenceType.INITIAL_IMPORT,
            reference_id=OpeningBalanceImport.objects.get().pk,
        )
        self.assertEqual(transaction.unit_price, Decimal("8893.31985"))

    def test_opening_balance_import_reports_multiple_preflight_errors(self):
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},0,BATCH-001,01/01/2028,-1\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"UNKNOWN,1,BATCH-002,01/01/2028,100\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Validasi gagal")
        self.assertContains(response, "quantity harus lebih dari 0")
        self.assertContains(response, "unit_price tidak boleh negatif")
        self.assertContains(response, "item_code &#x27;UNKNOWN&#x27; tidak ditemukan")
        self.assertFalse(OpeningBalanceImport.objects.exists())
        self.assertFalse(Stock.objects.exists())

    def test_opening_balance_import_changelist_shows_import_actions(self):
        self.client.force_login(self.admin_user)

        response = self.client.get(reverse("admin:stock_openingbalanceimport_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("admin:stock_opening_balance_import_csv"))
        self.assertContains(response, reverse("admin:stock_opening_balance_export_csv_template"))

    def test_stock_admin_generic_import_is_disabled(self):
        self.client.force_login(self.admin_user)

        response = self.client.get(reverse("admin:stock_stock_import"))

        self.assertEqual(response.status_code, 403)

    def test_stock_admin_direct_add_is_disabled(self):
        self.client.force_login(self.admin_user)

        response = self.client.get(reverse("admin:stock_stock_add"))

        self.assertEqual(response.status_code, 403)

    def test_stock_admin_direct_change_post_is_disabled(self):
        stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            expiry_date=date(2028, 1, 1),
            quantity=Decimal("5"),
            unit_price=Decimal("100"),
            sumber_dana=self.funding,
            source_document_number="SALDO-AWAL-2026",
        )
        self.client.force_login(self.admin_user)

        response = self.client.post(
            reverse("admin:stock_stock_change", args=[stock.pk]),
            {
                "item": self.item.pk,
                "location": self.location.pk,
                "batch_lot": "BATCH-001",
                "expiry_date": "2028-01-01",
                "quantity": "99",
                "reserved": "0",
                "unit_price": "100",
                "sumber_dana": self.funding.pk,
                "receiving_ref": "",
            },
        )

        self.assertEqual(response.status_code, 403)
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, Decimal("5"))

    def test_stock_admin_direct_delete_is_disabled(self):
        stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            expiry_date=date(2028, 1, 1),
            quantity=Decimal("5"),
            unit_price=Decimal("100"),
            sumber_dana=self.funding,
            source_document_number="SALDO-AWAL-2026",
        )
        self.client.force_login(self.admin_user)

        response = self.client.get(reverse("admin:stock_stock_delete", args=[stock.pk]))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Stock.objects.filter(pk=stock.pk).exists())

    def test_stock_admin_changelist_hides_direct_add_action(self):
        self.client.force_login(self.admin_user)

        response = self.client.get(reverse("admin:stock_stock_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("admin:stock_stock_add"))

    def test_opening_balance_import_rejects_receiving_columns_with_values(self):
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,receiving_type,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-2026,01/01/2026,GRANT,,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,BATCH-001,01/01/2028,2500\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(OpeningBalanceImport.objects.exists())
        self.assertFalse(Transaction.objects.filter(reference_type=Transaction.ReferenceType.INITIAL_IMPORT).exists())

    def test_opening_balance_import_rejects_header_only_csv(self):
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "tidak memiliki baris data")
        self.assertFalse(OpeningBalanceImport.objects.exists())
        self.assertFalse(Stock.objects.exists())

    def test_opening_balance_import_rejects_row_with_more_values_than_header(self):
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,BATCH-001,01/01/2028,2500,50\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "kolom melebihi header CSV")
        self.assertFalse(OpeningBalanceImport.objects.exists())
        self.assertFalse(Stock.objects.exists())

    def test_opening_balance_import_rejects_mismatched_effective_date_in_document(self):
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,BATCH-001,01/01/2028,2500\n"
            f"SALDO-AWAL-2026,02/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},5,BATCH-002,01/01/2028,2500\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "effective_date harus sama")
        self.assertFalse(OpeningBalanceImport.objects.exists())

    def test_opening_balance_import_rejects_future_effective_date(self):
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-2026,02/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,BATCH-001,01/01/2028,2500\n"
        )

        with patch("apps.stock.admin.timezone.localdate", return_value=date(2026, 1, 1)):
            response = self.client.post(
                reverse("admin:stock_opening_balance_import_csv"),
                {"csv_file": self._csv_upload(csv_content)},
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "effective_date tidak boleh melebihi tanggal posting")
        self.assertFalse(OpeningBalanceImport.objects.exists())
        self.assertFalse(Stock.objects.exists())

    def test_opening_balance_import_rejects_negative_unit_price(self):
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,BATCH-001,01/01/2028,-1\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "unit_price tidak boleh negatif")
        self.assertFalse(OpeningBalanceImport.objects.exists())

    def test_opening_balance_import_rejects_quantity_precision_overflow(self):
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},0.001,BATCH-001,01/01/2028,2500\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "quantity maksimal 12 digit dan 2 angka desimal")
        self.assertFalse(OpeningBalanceImport.objects.exists())

    def test_opening_balance_import_rejects_quantity_integer_digit_overflow(self):
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10000000000.00,BATCH-001,01/01/2028,2500\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "quantity maksimal 12 digit dan 2 angka desimal")
        self.assertFalse(OpeningBalanceImport.objects.exists())

    def test_opening_balance_import_rejects_unit_price_integer_digit_overflow(self):
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,BATCH-001,01/01/2028,10000000000000.00\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "unit_price maksimal 23 digit dan 10 angka desimal")
        self.assertFalse(OpeningBalanceImport.objects.exists())

    def test_opening_balance_import_rejects_existing_stock_unit_price_mismatch(self):
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            expiry_date=date(2028, 1, 1),
            quantity=Decimal("5"),
            unit_price=Decimal("100"),
            sumber_dana=self.funding,
            source_document_number="SALDO-AWAL-2026",
        )
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,BATCH-001,01/01/2028,200\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "harga satuan berbeda")
        self.assertFalse(OpeningBalanceImport.objects.exists())

    def test_opening_balance_preflight_preloads_existing_stock_layers(self):
        row_count = 25
        for index in range(row_count):
            Stock.objects.create(
                item=self.item,
                location=self.location,
                batch_lot=f"BATCH-QRY-{index:03d}",
                expiry_date=date(2028, 1, 1),
                quantity=Decimal("5"),
                unit_price=Decimal("100"),
                sumber_dana=self.funding,
                source_document_number="SALDO-AWAL-2026",
            )
        csv_rows = [
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price"
        ]
        csv_rows.extend(
            (
                f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},"
                f"{self.location.code},{self.item.kode_barang},1,"
                f"BATCH-QRY-{index:03d},01/01/2028,100"
            )
            for index in range(row_count)
        )
        stock_admin = StockAdmin(Stock, AdminSite())

        with CaptureQueriesContext(connection) as captured_queries:
            report = stock_admin._preflight_opening_balance_csv("\n".join(csv_rows))

        self.assertEqual(report["errors"], [])
        self.assertLessEqual(len(captured_queries), 8)

    def test_opening_balance_preview_rejects_duplicate_stock_key_rows(self):
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,BATCH-001,01/01/2028,100\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},5,BATCH-001,01/01/2028,200\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Batch stok duplikat dalam CSV saldo awal")
        self.assertFalse(OpeningBalanceImport.objects.exists())
        self.assertFalse(Stock.objects.exists())

    def test_opening_balance_preview_rejects_duplicate_stock_key_rows_before_price_conflict(self):
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,BATCH-001,01/01/2028,1000.1234567890\n"
            f"SALDO-AWAL-2026,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},5,BATCH-001,01/01/2028,1000.1234567891\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Batch stok duplikat dalam CSV saldo awal")
        self.assertFalse(OpeningBalanceImport.objects.exists())
        self.assertFalse(Stock.objects.exists())

    def test_opening_balance_import_allows_same_batch_price_layers_with_different_documents(self):
        self.client.force_login(self.admin_user)
        csv_content = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-2026-A,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,BATCH-001,01/01/2028,100\n"
            f"SALDO-AWAL-2026-B,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},5,BATCH-001,01/01/2028,200\n"
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CONFIRM IMPORT")
        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"action": "confirm", "preview_token": response.context["preview_token"]},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Stock.objects.count(), 2)
        self.assertTrue(
            Stock.objects.filter(
                batch_lot="BATCH-001",
                source_document_number="SALDO-AWAL-2026-A",
                unit_price=Decimal("100"),
            ).exists()
        )
        self.assertTrue(
            Stock.objects.filter(
                batch_lot="BATCH-001",
                source_document_number="SALDO-AWAL-2026-B",
                unit_price=Decimal("200"),
            ).exists()
        )

    def test_opening_balance_confirm_uses_preview_token_from_same_upload(self):
        self.client.force_login(self.admin_user)
        first_csv = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-FIRST,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,BATCH-FIRST,01/01/2028,2500\n"
        )
        second_csv = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-SECOND,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},20,BATCH-SECOND,01/01/2028,2500\n"
        )
        first_response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(first_csv)},
        )
        first_token = first_response.context["preview_token"]
        self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(second_csv)},
        )

        response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"action": "confirm", "preview_token": first_token},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            OpeningBalanceImport.objects.filter(document_number="SALDO-AWAL-FIRST").exists()
        )
        self.assertFalse(
            OpeningBalanceImport.objects.filter(document_number="SALDO-AWAL-SECOND").exists()
        )

    def test_opening_balance_blank_batch_generation_includes_document_identity(self):
        self.client.force_login(self.admin_user)
        first_csv = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-FIRST,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},10,,01/01/2028,2500\n"
        )
        second_csv = (
            "document_number,effective_date,sumber_dana_code,location_code,item_code,"
            "quantity,batch_lot,expiry_date,unit_price\n"
            f"SALDO-AWAL-SECOND,01/01/2026,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},20,,01/01/2028,2500\n"
        )
        first_response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(first_csv)},
        )
        self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"action": "confirm", "preview_token": first_response.context["preview_token"]},
        )
        second_response = self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"csv_file": self._csv_upload(second_csv)},
        )
        self.client.post(
            reverse("admin:stock_opening_balance_import_csv"),
            {"action": "confirm", "preview_token": second_response.context["preview_token"]},
        )

        batches = set(Stock.objects.values_list("batch_lot", flat=True))
        self.assertEqual(Stock.objects.count(), 2)
        self.assertEqual(len(batches), 2)

    def test_opening_balance_import_denies_non_admin_staff(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(reverse("admin:stock_opening_balance_import_csv"))

        self.assertEqual(response.status_code, 403)

    def test_opening_balance_import_admin_model_denies_non_admin_staff(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(reverse("admin:stock_openingbalanceimport_changelist"))

        self.assertEqual(response.status_code, 403)


class StockModelExpiryValidationTests(TestCase):
    def setUp(self):
        self.unit = Unit.objects.create(code='BTL', name='Bottle')
        self.category = Category.objects.create(code='MAT', name='Material', sort_order=1)
        self.location = Location.objects.create(code='MODEL', name='Gudang Model')
        self.funding = FundingSource.objects.create(code='DAK', name='Dana Alokasi Khusus')

    def test_full_clean_rejects_blank_expiry_for_expiring_item(self):
        item = Item.objects.create(
            kode_barang='ITM-MODEL-EXP',
            nama_barang='Model Expiring Item',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
            requires_expiry_date=True,
        )
        stock = Stock(
            item=item,
            location=self.location,
            batch_lot='MODEL-EXP-01',
            expiry_date=None,
            quantity=Decimal('3'),
            reserved=Decimal('0'),
            unit_price=Decimal('1500'),
            sumber_dana=self.funding,
        )

        with self.assertRaises(ValidationError) as exc:
            stock.full_clean()

        self.assertEqual(
            exc.exception.message_dict['expiry_date'],
            ['Tanggal kedaluwarsa wajib diisi untuk item ini.'],
        )

    def test_full_clean_allows_blank_expiry_for_non_expiring_item(self):
        item = Item.objects.create(
            kode_barang='ITM-MODEL-NOEXP',
            nama_barang='Model Non Expiring Item',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
            requires_expiry_date=False,
        )
        stock = Stock(
            item=item,
            location=self.location,
            batch_lot='MODEL-NOEXP-01',
            expiry_date=None,
            quantity=Decimal('4'),
            reserved=Decimal('0'),
            unit_price=Decimal('900'),
            sumber_dana=self.funding,
        )

        stock.full_clean()


class LegacyNoExpiryItemBackfillMigrationTests(TestCase):
    def setUp(self):
        self.unit = Unit.objects.create(code='PCS', name='Pieces')
        self.category = Category.objects.create(code='ALKES', name='Alkes', sort_order=1)
        self.location = Location.objects.create(code='LEGACY', name='Gudang Legacy')
        self.funding = FundingSource.objects.create(code='BTT', name='Belanja Tidak Terduga')

    def test_backfill_marks_items_with_null_expiry_history_as_non_expiring(self):
        migration_module = importlib.import_module(
            'apps.items.migrations.0009_backfill_non_expiring_items'
        )

        stock_item = Item.objects.create(
            kode_barang='ITM-LEGACY-STK',
            nama_barang='Legacy Stock Null Expiry',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
        )
        receiving_item = Item.objects.create(
            kode_barang='ITM-LEGACY-RCV',
            nama_barang='Legacy Receiving Null Expiry',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
        )
        unaffected_item = Item.objects.create(
            kode_barang='ITM-LEGACY-KEEP',
            nama_barang='Legacy Expiring Item',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
        )

        Stock.objects.create(
            item=stock_item,
            location=self.location,
            batch_lot='LEG-STK-01',
            expiry_date=None,
            quantity=Decimal('5'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            source_document_number='SRC-DOC-TRF',
        )
        from apps.receiving.models import Receiving, ReceivingItem

        receiving = Receiving.objects.create(
            receiving_date=date(2026, 1, 10),
            receiving_type=Receiving.ReceivingType.GRANT,
            sumber_dana=self.funding,
            created_by=User.objects.create_superuser(username='migration-backfill-admin', password='secret12345'),
        )
        ReceivingItem.objects.create(
            receiving=receiving,
            item=receiving_item,
            batch_lot='LEG-RCV-01',
            expiry_date=None,
            quantity=Decimal('7'),
            unit_price=Decimal('1500'),
        )
        Stock.objects.create(
            item=unaffected_item,
            location=self.location,
            batch_lot='LEG-KEEP-01',
            expiry_date=date(2027, 1, 1),
            quantity=Decimal('9'),
            reserved=Decimal('0'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
        )

        class MigrationApps:
            @staticmethod
            def get_model(app_label, model_name):
                mapping = {
                    ('items', 'Item'): Item,
                    ('stock', 'Stock'): Stock,
                    ('receiving', 'ReceivingItem'): ReceivingItem,
                }
                return mapping[(app_label, model_name)]

        migration_module.backfill_non_expiring_items(MigrationApps(), None)

        stock_item.refresh_from_db()
        receiving_item.refresh_from_db()
        unaffected_item.refresh_from_db()

        self.assertFalse(stock_item.requires_expiry_date)
        self.assertFalse(receiving_item.requires_expiry_date)
        self.assertTrue(unaffected_item.requires_expiry_date)


class SourceDocumentBackfillMigrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username='source-doc-backfill-admin',
            password='secret12345',
        )
        self.unit = Unit.objects.create(code='SDM', name='Source Doc Unit')
        self.category = Category.objects.create(
            code='SDM-CAT',
            name='Source Doc Category',
            sort_order=1,
        )
        self.item = Item.objects.create(
            kode_barang='ITM-SDM-001',
            nama_barang='Source Doc Item',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
        )
        self.location = Location.objects.create(code='SDM-LOC', name='Source Doc Location')
        self.funding = FundingSource.objects.create(code='SDM-FUND', name='Source Doc Fund')

    class MigrationApps:
        @staticmethod
        def get_model(app_label, model_name):
            mapping = {
                ('receiving', 'Receiving'): Receiving,
                ('stock', 'OpeningBalanceImport'): OpeningBalanceImport,
                ('stock', 'SourceDocumentNumberClaim'): SourceDocumentNumberClaim,
                ('stock', 'Stock'): Stock,
                ('stock', 'StockTransferItem'): StockTransferItem,
                ('stock', 'Transaction'): Transaction,
                ('expired', 'ExpiredItem'): ExpiredItem,
                ('recall', 'RecallItem'): RecallItem,
                ('stock_opname', 'StockOpnameItem'): StockOpnameItem,
                ('distribution', 'DistributionItem'): DistributionItem,
                ('allocation', 'AllocationItem'): AllocationItem,
            }
            return mapping[(app_label, model_name)]

    def _create_receiving(self, document_number):
        return Receiving.objects.create(
            document_number=document_number,
            receiving_date=date(2026, 1, 10),
            receiving_type=Receiving.ReceivingType.GRANT,
            sumber_dana=self.funding,
            created_by=self.user,
        )

    def _create_receiving_transaction(self, receiving, quantity, unit_price=Decimal('1000')):
        return Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='SDM-BATCH',
            quantity=quantity,
            unit_price=unit_price,
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=receiving.pk,
            user=self.user,
        )

    def test_stock_backfill_marks_multi_document_aggregate_as_legacy(self):
        migration_module = importlib.import_module(
            'apps.stock.migrations.0009_stock_source_document_number'
        )
        first_receiving = self._create_receiving('RCV-SDM-001')
        second_receiving = self._create_receiving('RCV-SDM-002')
        stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='SDM-BATCH',
            expiry_date=date(2030, 1, 1),
            quantity=Decimal('12'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            receiving_ref=first_receiving,
            source_document_number='',
        )
        self._create_receiving_transaction(first_receiving, Decimal('5'))
        self._create_receiving_transaction(second_receiving, Decimal('7'))

        migration_module.backfill_source_document_number(self.MigrationApps(), None)

        stock.refresh_from_db()
        self.assertEqual(stock.source_document_number, f'LEGACY-{stock.pk}')

    def test_transaction_backfill_uses_legacy_stock_layer_when_receiving_is_ambiguous(self):
        migration_module = importlib.import_module(
            'apps.stock.migrations.0010_transaction_source_document_number'
        )
        receiving = self._create_receiving('RCV-SDM-LEGACY')
        stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='SDM-BATCH',
            expiry_date=date(2030, 1, 1),
            quantity=Decimal('12'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            receiving_ref=receiving,
            source_document_number='LEGACY-SDM-STOCK',
        )
        tx = self._create_receiving_transaction(
            receiving,
            Decimal('12'),
            unit_price=Decimal('2000'),
        )
        Transaction.objects.filter(pk=tx.pk).update(source_document_number='')

        migration_module.backfill_transaction_source_document_number(
            self.MigrationApps(),
            None,
        )

        tx.refresh_from_db()
        self.assertEqual(tx.source_document_number, stock.source_document_number)

    def test_stock_and_transaction_backfill_preserve_opening_balance_transfer_layer(self):
        stock_migration = importlib.import_module(
            'apps.stock.migrations.0009_stock_source_document_number'
        )
        transaction_migration = importlib.import_module(
            'apps.stock.migrations.0010_transaction_source_document_number'
        )
        destination = Location.objects.create(code='SDM-DST', name='Transfer Destination')
        opening_balance = OpeningBalanceImport.objects.create(
            document_number='SALDO-SDM-TRANSFER',
            effective_date=date(2026, 1, 1),
            created_by=self.user,
        )
        source_stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='SDM-BATCH',
            expiry_date=date(2030, 1, 1),
            quantity=Decimal('5'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            source_document_number='',
        )
        destination_stock = Stock.objects.create(
            item=self.item,
            location=destination,
            batch_lot='SDM-BATCH',
            expiry_date=date(2030, 1, 1),
            quantity=Decimal('5'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            source_document_number='',
        )
        opening_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='SDM-BATCH',
            quantity=Decimal('10'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.INITIAL_IMPORT,
            reference_id=opening_balance.pk,
            user=self.user,
        )
        transfer_out = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.item,
            location=self.location,
            batch_lot='SDM-BATCH',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=777,
            user=self.user,
        )
        transfer_in = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='SDM-BATCH',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=777,
            user=self.user,
        )

        stock_migration.backfill_source_document_number(self.MigrationApps(), None)
        source_stock.refresh_from_db()
        destination_stock.refresh_from_db()

        self.assertEqual(source_stock.source_document_number, 'SALDO-SDM-TRANSFER')
        self.assertEqual(destination_stock.source_document_number, 'SALDO-SDM-TRANSFER')

        transaction_migration.backfill_transaction_source_document_number(
            self.MigrationApps(),
            None,
        )
        opening_tx.refresh_from_db()
        transfer_out.refresh_from_db()
        transfer_in.refresh_from_db()
        self.assertEqual(opening_tx.source_document_number, 'SALDO-SDM-TRANSFER')
        self.assertEqual(transfer_out.source_document_number, 'SALDO-SDM-TRANSFER')
        self.assertEqual(transfer_in.source_document_number, 'SALDO-SDM-TRANSFER')

    def test_backfill_preserves_ambiguous_destination_receipts_during_transfer(self):
        stock_migration = importlib.import_module(
            'apps.stock.migrations.0009_stock_source_document_number'
        )
        transaction_migration = importlib.import_module(
            'apps.stock.migrations.0010_transaction_source_document_number'
        )
        destination = Location.objects.create(
            code='SDM-AMB-DST',
            name='Ambiguous Transfer Destination',
        )
        first_receiving = Receiving.objects.create(
            document_number='RCV-SDM-AMB-001',
            receiving_date=date(2026, 1, 12),
            receiving_type=Receiving.ReceivingType.GRANT,
            sumber_dana=self.funding,
            created_by=self.user,
        )
        second_receiving = Receiving.objects.create(
            document_number='RCV-SDM-AMB-002',
            receiving_date=date(2026, 1, 13),
            receiving_type=Receiving.ReceivingType.GRANT,
            sumber_dana=self.funding,
            created_by=self.user,
        )
        opening_balance = OpeningBalanceImport.objects.create(
            document_number='SALDO-SDM-AMB-SRC',
            effective_date=date(2026, 1, 1),
            created_by=self.user,
        )
        source_stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='SDM-AMB',
            expiry_date=date(2030, 1, 1),
            quantity=Decimal('5'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            source_document_number='',
        )
        destination_stock = Stock.objects.create(
            item=self.item,
            location=destination,
            batch_lot='SDM-AMB',
            expiry_date=date(2031, 1, 1),
            quantity=Decimal('17'),
            reserved=Decimal('0'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
            receiving_ref=first_receiving,
            source_document_number='',
        )
        opening_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='SDM-AMB',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.INITIAL_IMPORT,
            reference_id=opening_balance.pk,
            user=self.user,
        )
        first_receiving_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='SDM-AMB',
            quantity=Decimal('7'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=first_receiving.pk,
            user=self.user,
        )
        second_receiving_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='SDM-AMB',
            quantity=Decimal('5'),
            unit_price=Decimal('3000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=second_receiving.pk,
            user=self.user,
        )
        transfer_out = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.item,
            location=self.location,
            batch_lot='SDM-AMB',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=880,
            user=self.user,
        )
        transfer_in = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='SDM-AMB',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=880,
            user=self.user,
        )

        stock_migration.backfill_source_document_number(self.MigrationApps(), None)

        source_stock.refresh_from_db()
        destination_stock.refresh_from_db()
        destination_legacy_layer = f'LEGACY-{destination_stock.pk}'
        self.assertEqual(source_stock.source_document_number, 'SALDO-SDM-AMB-SRC')
        self.assertEqual(destination_stock.source_document_number, destination_legacy_layer)
        self.assertEqual(destination_stock.quantity, Decimal('17'))
        self.assertFalse(
            Stock.objects.filter(
                item=self.item,
                location=destination,
                batch_lot='SDM-AMB',
                sumber_dana=self.funding,
                source_document_number='SALDO-SDM-AMB-SRC',
            ).exists()
        )

        transaction_migration.backfill_transaction_source_document_number(
            self.MigrationApps(),
            None,
        )
        opening_tx.refresh_from_db()
        first_receiving_tx.refresh_from_db()
        second_receiving_tx.refresh_from_db()
        transfer_out.refresh_from_db()
        transfer_in.refresh_from_db()
        self.assertEqual(opening_tx.source_document_number, 'SALDO-SDM-AMB-SRC')
        self.assertEqual(first_receiving_tx.source_document_number, destination_legacy_layer)
        self.assertEqual(second_receiving_tx.source_document_number, destination_legacy_layer)
        self.assertEqual(transfer_out.source_document_number, 'SALDO-SDM-AMB-SRC')
        self.assertEqual(transfer_in.source_document_number, 'SALDO-SDM-AMB-SRC')

    def test_stock_backfill_resolves_transfer_source_chains(self):
        stock_migration = importlib.import_module(
            'apps.stock.migrations.0009_stock_source_document_number'
        )
        middle = Location.objects.create(code='SDM-MID', name='Transfer Middle')
        destination = Location.objects.create(code='SDM-END', name='Transfer End')
        opening_balance = OpeningBalanceImport.objects.create(
            document_number='SALDO-SDM-CHAIN',
            effective_date=date(2026, 1, 1),
            created_by=self.user,
        )
        source_stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='SDM-CHAIN',
            expiry_date=date(2030, 1, 1),
            quantity=Decimal('10'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            source_document_number='',
        )
        middle_stock = Stock.objects.create(
            item=self.item,
            location=middle,
            batch_lot='SDM-CHAIN',
            expiry_date=date(2030, 1, 1),
            quantity=Decimal('5'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            source_document_number='',
        )
        destination_stock = Stock.objects.create(
            item=self.item,
            location=destination,
            batch_lot='SDM-CHAIN',
            expiry_date=date(2030, 1, 1),
            quantity=Decimal('2'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            source_document_number='',
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='SDM-CHAIN',
            quantity=Decimal('10'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.INITIAL_IMPORT,
            reference_id=opening_balance.pk,
            user=self.user,
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.item,
            location=self.location,
            batch_lot='SDM-CHAIN',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=801,
            user=self.user,
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=middle,
            batch_lot='SDM-CHAIN',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=801,
            user=self.user,
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.item,
            location=middle,
            batch_lot='SDM-CHAIN',
            quantity=Decimal('2'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=802,
            user=self.user,
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='SDM-CHAIN',
            quantity=Decimal('2'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=802,
            user=self.user,
        )

        stock_migration.backfill_source_document_number(self.MigrationApps(), None)

        source_stock.refresh_from_db()
        middle_stock.refresh_from_db()
        destination_stock.refresh_from_db()
        self.assertEqual(source_stock.source_document_number, 'SALDO-SDM-CHAIN')
        self.assertEqual(middle_stock.source_document_number, 'SALDO-SDM-CHAIN')
        self.assertEqual(destination_stock.source_document_number, 'SALDO-SDM-CHAIN')

    def test_backfill_uses_transfer_price_to_resolve_chained_split_source_layer(self):
        stock_migration = importlib.import_module(
            'apps.stock.migrations.0009_stock_source_document_number'
        )
        transaction_migration = importlib.import_module(
            'apps.stock.migrations.0010_transaction_source_document_number'
        )
        middle = Location.objects.create(code='SDM-PRICE-MID', name='Price Middle')
        destination = Location.objects.create(code='SDM-PRICE-END', name='Price End')
        middle_receiving = Receiving.objects.create(
            document_number='RCV-SDM-PRICE-MID',
            receiving_date=date(2026, 1, 12),
            receiving_type=Receiving.ReceivingType.GRANT,
            sumber_dana=self.funding,
            created_by=self.user,
        )
        opening_balance = OpeningBalanceImport.objects.create(
            document_number='SALDO-SDM-PRICE-SRC',
            effective_date=date(2026, 1, 1),
            created_by=self.user,
        )
        source_stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='SDM-PRICE-CHAIN',
            expiry_date=date(2030, 1, 1),
            quantity=Decimal('5'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            source_document_number='',
        )
        middle_stock = Stock.objects.create(
            item=self.item,
            location=middle,
            batch_lot='SDM-PRICE-CHAIN',
            expiry_date=date(2031, 1, 1),
            quantity=Decimal('12'),
            reserved=Decimal('0'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
            receiving_ref=middle_receiving,
            source_document_number='',
        )
        destination_stock = Stock.objects.create(
            item=self.item,
            location=destination,
            batch_lot='SDM-PRICE-CHAIN',
            expiry_date=date(2030, 1, 1),
            quantity=Decimal('5'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            source_document_number='',
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='SDM-PRICE-CHAIN',
            quantity=Decimal('10'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.INITIAL_IMPORT,
            reference_id=opening_balance.pk,
            user=self.user,
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=middle,
            batch_lot='SDM-PRICE-CHAIN',
            quantity=Decimal('7'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=middle_receiving.pk,
            user=self.user,
        )
        transfer_out = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.item,
            location=self.location,
            batch_lot='SDM-PRICE-CHAIN',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=805,
            user=self.user,
        )
        transfer_in = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=middle,
            batch_lot='SDM-PRICE-CHAIN',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=805,
            user=self.user,
        )
        chained_transfer_out = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.item,
            location=middle,
            batch_lot='SDM-PRICE-CHAIN',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=806,
            user=self.user,
        )
        chained_transfer_in = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='SDM-PRICE-CHAIN',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=806,
            user=self.user,
        )

        stock_migration.backfill_source_document_number(self.MigrationApps(), None)

        source_stock.refresh_from_db()
        middle_stock.refresh_from_db()
        destination_stock.refresh_from_db()
        self.assertEqual(source_stock.source_document_number, 'SALDO-SDM-PRICE-SRC')
        self.assertEqual(middle_stock.source_document_number, 'RCV-SDM-PRICE-MID')
        self.assertTrue(
            Stock.objects.filter(
                item=self.item,
                location=middle,
                batch_lot='SDM-PRICE-CHAIN',
                sumber_dana=self.funding,
                source_document_number='SALDO-SDM-PRICE-SRC',
                unit_price=Decimal('1000'),
            ).exists()
        )
        self.assertEqual(destination_stock.source_document_number, 'SALDO-SDM-PRICE-SRC')

        transaction_migration.backfill_transaction_source_document_number(
            self.MigrationApps(),
            None,
        )
        transfer_out.refresh_from_db()
        transfer_in.refresh_from_db()
        chained_transfer_out.refresh_from_db()
        chained_transfer_in.refresh_from_db()
        self.assertEqual(transfer_out.source_document_number, 'SALDO-SDM-PRICE-SRC')
        self.assertEqual(transfer_in.source_document_number, 'SALDO-SDM-PRICE-SRC')
        self.assertEqual(chained_transfer_out.source_document_number, 'SALDO-SDM-PRICE-SRC')
        self.assertEqual(chained_transfer_in.source_document_number, 'SALDO-SDM-PRICE-SRC')

    def test_backfill_splits_transfer_into_existing_destination_stock_layer(self):
        stock_migration = importlib.import_module(
            'apps.stock.migrations.0009_stock_source_document_number'
        )
        transaction_migration = importlib.import_module(
            'apps.stock.migrations.0010_transaction_source_document_number'
        )
        destination = Location.objects.create(
            code='SDM-MIX-DST',
            name='Mixed Transfer Destination',
        )
        destination_receiving = Receiving.objects.create(
            document_number='RCV-SDM-MIX-DST',
            receiving_date=date(2026, 1, 12),
            receiving_type=Receiving.ReceivingType.GRANT,
            sumber_dana=self.funding,
            created_by=self.user,
        )
        opening_balance = OpeningBalanceImport.objects.create(
            document_number='SALDO-SDM-MIX-SRC',
            effective_date=date(2026, 1, 1),
            created_by=self.user,
        )
        source_stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='SDM-MIX',
            expiry_date=date(2030, 1, 1),
            quantity=Decimal('5'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            source_document_number='',
        )
        destination_stock = Stock.objects.create(
            item=self.item,
            location=destination,
            batch_lot='SDM-MIX',
            expiry_date=date(2031, 1, 1),
            quantity=Decimal('12'),
            reserved=Decimal('0'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
            receiving_ref=destination_receiving,
            source_document_number='',
        )
        opening_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='SDM-MIX',
            quantity=Decimal('10'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.INITIAL_IMPORT,
            reference_id=opening_balance.pk,
            user=self.user,
        )
        destination_receiving_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='SDM-MIX',
            quantity=Decimal('7'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=destination_receiving.pk,
            user=self.user,
        )
        transfer_out = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.item,
            location=self.location,
            batch_lot='SDM-MIX',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=803,
            user=self.user,
        )
        transfer_in = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='SDM-MIX',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=803,
            user=self.user,
        )

        stock_migration.backfill_source_document_number(self.MigrationApps(), None)

        source_stock.refresh_from_db()
        destination_stock.refresh_from_db()
        transferred_destination_stock = Stock.objects.get(
            item=self.item,
            location=destination,
            batch_lot='SDM-MIX',
            sumber_dana=self.funding,
            source_document_number='SALDO-SDM-MIX-SRC',
        )
        self.assertEqual(source_stock.source_document_number, 'SALDO-SDM-MIX-SRC')
        self.assertEqual(destination_stock.source_document_number, 'RCV-SDM-MIX-DST')
        self.assertEqual(destination_stock.quantity, Decimal('7'))
        self.assertEqual(transferred_destination_stock.quantity, Decimal('5'))
        self.assertEqual(transferred_destination_stock.unit_price, Decimal('1000'))
        self.assertEqual(transferred_destination_stock.expiry_date, date(2030, 1, 1))

        transaction_migration.backfill_transaction_source_document_number(
            self.MigrationApps(),
            None,
        )
        opening_tx.refresh_from_db()
        destination_receiving_tx.refresh_from_db()
        transfer_out.refresh_from_db()
        transfer_in.refresh_from_db()
        self.assertEqual(opening_tx.source_document_number, 'SALDO-SDM-MIX-SRC')
        self.assertEqual(destination_receiving_tx.source_document_number, 'RCV-SDM-MIX-DST')
        self.assertEqual(transfer_out.source_document_number, 'SALDO-SDM-MIX-SRC')
        self.assertEqual(transfer_in.source_document_number, 'SALDO-SDM-MIX-SRC')

    def test_backfill_keeps_reserved_mixed_transfer_destination_unsplit(self):
        stock_migration = importlib.import_module(
            'apps.stock.migrations.0009_stock_source_document_number'
        )
        transaction_migration = importlib.import_module(
            'apps.stock.migrations.0010_transaction_source_document_number'
        )
        destination = Location.objects.create(
            code='SDM-RSV-DST',
            name='Reserved Transfer Destination',
        )
        destination_receiving = Receiving.objects.create(
            document_number='RCV-SDM-RSV-DST',
            receiving_date=date(2026, 1, 12),
            receiving_type=Receiving.ReceivingType.GRANT,
            sumber_dana=self.funding,
            created_by=self.user,
        )
        opening_balance = OpeningBalanceImport.objects.create(
            document_number='SALDO-SDM-RSV-SRC',
            effective_date=date(2026, 1, 1),
            created_by=self.user,
        )
        source_stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='SDM-RSV',
            expiry_date=date(2030, 1, 1),
            quantity=Decimal('5'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            source_document_number='',
        )
        destination_stock = Stock.objects.create(
            item=self.item,
            location=destination,
            batch_lot='SDM-RSV',
            expiry_date=date(2031, 1, 1),
            quantity=Decimal('12'),
            reserved=Decimal('8'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
            receiving_ref=destination_receiving,
            source_document_number='',
        )
        opening_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='SDM-RSV',
            quantity=Decimal('10'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.INITIAL_IMPORT,
            reference_id=opening_balance.pk,
            user=self.user,
        )
        destination_receiving_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='SDM-RSV',
            quantity=Decimal('7'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=destination_receiving.pk,
            user=self.user,
        )
        transfer_out = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.item,
            location=self.location,
            batch_lot='SDM-RSV',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=804,
            user=self.user,
        )
        transfer_in = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='SDM-RSV',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=804,
            user=self.user,
        )

        stock_migration.backfill_source_document_number(self.MigrationApps(), None)

        source_stock.refresh_from_db()
        destination_stock.refresh_from_db()
        self.assertEqual(source_stock.source_document_number, 'SALDO-SDM-RSV-SRC')
        self.assertEqual(destination_stock.source_document_number, 'RCV-SDM-RSV-DST')
        self.assertEqual(destination_stock.quantity, Decimal('12'))
        self.assertEqual(destination_stock.reserved, Decimal('8'))
        self.assertFalse(
            Stock.objects.filter(
                item=self.item,
                location=destination,
                batch_lot='SDM-RSV',
                sumber_dana=self.funding,
                source_document_number='SALDO-SDM-RSV-SRC',
            ).exists()
        )

        transaction_migration.backfill_transaction_source_document_number(
            self.MigrationApps(),
            None,
        )
        opening_tx.refresh_from_db()
        destination_receiving_tx.refresh_from_db()
        transfer_out.refresh_from_db()
        transfer_in.refresh_from_db()
        self.assertEqual(opening_tx.source_document_number, 'SALDO-SDM-RSV-SRC')
        self.assertEqual(destination_receiving_tx.source_document_number, 'RCV-SDM-RSV-DST')
        self.assertEqual(transfer_out.source_document_number, 'SALDO-SDM-RSV-SRC')
        self.assertEqual(transfer_in.source_document_number, 'SALDO-SDM-RSV-SRC')

    def test_backfill_keeps_draft_transfer_destination_unsplit(self):
        stock_migration = importlib.import_module(
            'apps.stock.migrations.0009_stock_source_document_number'
        )
        transaction_migration = importlib.import_module(
            'apps.stock.migrations.0010_transaction_source_document_number'
        )
        destination = Location.objects.create(
            code='SDM-DRF-DST',
            name='Draft Transfer Destination',
        )
        destination_receiving = Receiving.objects.create(
            document_number='RCV-SDM-DRF-DST',
            receiving_date=date(2026, 1, 12),
            receiving_type=Receiving.ReceivingType.GRANT,
            sumber_dana=self.funding,
            created_by=self.user,
        )
        opening_balance = OpeningBalanceImport.objects.create(
            document_number='SALDO-SDM-DRF-SRC',
            effective_date=date(2026, 1, 1),
            created_by=self.user,
        )
        source_stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='SDM-DRF',
            expiry_date=date(2030, 1, 1),
            quantity=Decimal('5'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            source_document_number='',
        )
        destination_stock = Stock.objects.create(
            item=self.item,
            location=destination,
            batch_lot='SDM-DRF',
            expiry_date=date(2031, 1, 1),
            quantity=Decimal('12'),
            reserved=Decimal('0'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
            receiving_ref=destination_receiving,
            source_document_number='',
        )
        draft_transfer = StockTransfer.objects.create(
            source_location=destination,
            destination_location=self.location,
            created_by=self.user,
        )
        StockTransferItem.objects.create(
            transfer=draft_transfer,
            stock=destination_stock,
            item=self.item,
            quantity=Decimal('8'),
        )
        opening_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='SDM-DRF',
            quantity=Decimal('10'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.INITIAL_IMPORT,
            reference_id=opening_balance.pk,
            user=self.user,
        )
        destination_receiving_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='SDM-DRF',
            quantity=Decimal('7'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=destination_receiving.pk,
            user=self.user,
        )
        transfer_out = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.item,
            location=self.location,
            batch_lot='SDM-DRF',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=805,
            user=self.user,
        )
        transfer_in = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='SDM-DRF',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=805,
            user=self.user,
        )

        stock_migration.backfill_source_document_number(self.MigrationApps(), None)

        source_stock.refresh_from_db()
        destination_stock.refresh_from_db()
        self.assertEqual(source_stock.source_document_number, 'SALDO-SDM-DRF-SRC')
        self.assertEqual(destination_stock.source_document_number, 'RCV-SDM-DRF-DST')
        self.assertEqual(destination_stock.quantity, Decimal('12'))
        self.assertFalse(
            Stock.objects.filter(
                item=self.item,
                location=destination,
                batch_lot='SDM-DRF',
                sumber_dana=self.funding,
                source_document_number='SALDO-SDM-DRF-SRC',
            ).exists()
        )

        transaction_migration.backfill_transaction_source_document_number(
            self.MigrationApps(),
            None,
        )
        opening_tx.refresh_from_db()
        destination_receiving_tx.refresh_from_db()
        transfer_out.refresh_from_db()
        transfer_in.refresh_from_db()
        self.assertEqual(opening_tx.source_document_number, 'SALDO-SDM-DRF-SRC')
        self.assertEqual(destination_receiving_tx.source_document_number, 'RCV-SDM-DRF-DST')
        self.assertEqual(transfer_out.source_document_number, 'SALDO-SDM-DRF-SRC')
        self.assertEqual(transfer_in.source_document_number, 'SALDO-SDM-DRF-SRC')

    def test_backfill_keeps_pending_recall_destination_unsplit(self):
        stock_migration = importlib.import_module(
            'apps.stock.migrations.0009_stock_source_document_number'
        )
        transaction_migration = importlib.import_module(
            'apps.stock.migrations.0010_transaction_source_document_number'
        )
        destination = Location.objects.create(
            code='SDM-RCL-DST',
            name='Recall Transfer Destination',
        )
        destination_receiving = Receiving.objects.create(
            document_number='RCV-SDM-RCL-DST',
            receiving_date=date(2026, 1, 12),
            receiving_type=Receiving.ReceivingType.GRANT,
            sumber_dana=self.funding,
            created_by=self.user,
        )
        opening_balance = OpeningBalanceImport.objects.create(
            document_number='SALDO-SDM-RCL-SRC',
            effective_date=date(2026, 1, 1),
            created_by=self.user,
        )
        source_stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='SDM-RCL',
            expiry_date=date(2030, 1, 1),
            quantity=Decimal('5'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            source_document_number='',
        )
        destination_stock = Stock.objects.create(
            item=self.item,
            location=destination,
            batch_lot='SDM-RCL',
            expiry_date=date(2031, 1, 1),
            quantity=Decimal('12'),
            reserved=Decimal('0'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
            receiving_ref=destination_receiving,
            source_document_number='',
        )
        supplier = Supplier.objects.create(code='SDM-RCL-SUP', name='Recall Supplier')
        recall = Recall.objects.create(
            supplier=supplier,
            status=Recall.Status.SUBMITTED,
            created_by=self.user,
        )
        RecallItem.objects.create(
            recall=recall,
            item=self.item,
            stock=destination_stock,
            quantity=Decimal('8'),
        )
        opening_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='SDM-RCL',
            quantity=Decimal('10'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.INITIAL_IMPORT,
            reference_id=opening_balance.pk,
            user=self.user,
        )
        destination_receiving_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='SDM-RCL',
            quantity=Decimal('7'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=destination_receiving.pk,
            user=self.user,
        )
        transfer_out = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.item,
            location=self.location,
            batch_lot='SDM-RCL',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=808,
            user=self.user,
        )
        transfer_in = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='SDM-RCL',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=808,
            user=self.user,
        )

        stock_migration.backfill_source_document_number(self.MigrationApps(), None)

        source_stock.refresh_from_db()
        destination_stock.refresh_from_db()
        self.assertEqual(source_stock.source_document_number, 'SALDO-SDM-RCL-SRC')
        self.assertEqual(destination_stock.source_document_number, 'RCV-SDM-RCL-DST')
        self.assertEqual(destination_stock.quantity, Decimal('12'))
        self.assertFalse(
            Stock.objects.filter(
                item=self.item,
                location=destination,
                batch_lot='SDM-RCL',
                sumber_dana=self.funding,
                source_document_number='SALDO-SDM-RCL-SRC',
            ).exists()
        )

        transaction_migration.backfill_transaction_source_document_number(
            self.MigrationApps(),
            None,
        )
        opening_tx.refresh_from_db()
        destination_receiving_tx.refresh_from_db()
        transfer_out.refresh_from_db()
        transfer_in.refresh_from_db()
        self.assertEqual(opening_tx.source_document_number, 'SALDO-SDM-RCL-SRC')
        self.assertEqual(destination_receiving_tx.source_document_number, 'RCV-SDM-RCL-DST')
        self.assertEqual(transfer_out.source_document_number, 'SALDO-SDM-RCL-SRC')
        self.assertEqual(transfer_in.source_document_number, 'SALDO-SDM-RCL-SRC')

    def test_backfill_keeps_pending_expired_destination_unsplit(self):
        stock_migration = importlib.import_module(
            'apps.stock.migrations.0009_stock_source_document_number'
        )
        transaction_migration = importlib.import_module(
            'apps.stock.migrations.0010_transaction_source_document_number'
        )
        destination = Location.objects.create(
            code='SDM-EXP-DST',
            name='Expired Transfer Destination',
        )
        destination_receiving = Receiving.objects.create(
            document_number='RCV-SDM-EXP-DST',
            receiving_date=date(2026, 1, 12),
            receiving_type=Receiving.ReceivingType.GRANT,
            sumber_dana=self.funding,
            created_by=self.user,
        )
        opening_balance = OpeningBalanceImport.objects.create(
            document_number='SALDO-SDM-EXP-SRC',
            effective_date=date(2026, 1, 1),
            created_by=self.user,
        )
        source_stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='SDM-EXP',
            expiry_date=date(2030, 1, 1),
            quantity=Decimal('5'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            source_document_number='',
        )
        destination_stock = Stock.objects.create(
            item=self.item,
            location=destination,
            batch_lot='SDM-EXP',
            expiry_date=date(2031, 1, 1),
            quantity=Decimal('12'),
            reserved=Decimal('0'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
            receiving_ref=destination_receiving,
            source_document_number='',
        )
        expired_doc = Expired.objects.create(
            status=Expired.Status.SUBMITTED,
            created_by=self.user,
        )
        ExpiredItem.objects.create(
            expired=expired_doc,
            item=self.item,
            stock=destination_stock,
            quantity=Decimal('8'),
        )
        opening_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='SDM-EXP',
            quantity=Decimal('10'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.INITIAL_IMPORT,
            reference_id=opening_balance.pk,
            user=self.user,
        )
        destination_receiving_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='SDM-EXP',
            quantity=Decimal('7'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=destination_receiving.pk,
            user=self.user,
        )
        transfer_out = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.item,
            location=self.location,
            batch_lot='SDM-EXP',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=809,
            user=self.user,
        )
        transfer_in = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='SDM-EXP',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=809,
            user=self.user,
        )

        stock_migration.backfill_source_document_number(self.MigrationApps(), None)

        source_stock.refresh_from_db()
        destination_stock.refresh_from_db()
        self.assertEqual(source_stock.source_document_number, 'SALDO-SDM-EXP-SRC')
        self.assertEqual(destination_stock.source_document_number, 'RCV-SDM-EXP-DST')
        self.assertEqual(destination_stock.quantity, Decimal('12'))
        self.assertFalse(
            Stock.objects.filter(
                item=self.item,
                location=destination,
                batch_lot='SDM-EXP',
                sumber_dana=self.funding,
                source_document_number='SALDO-SDM-EXP-SRC',
            ).exists()
        )

        transaction_migration.backfill_transaction_source_document_number(
            self.MigrationApps(),
            None,
        )
        opening_tx.refresh_from_db()
        destination_receiving_tx.refresh_from_db()
        transfer_out.refresh_from_db()
        transfer_in.refresh_from_db()
        self.assertEqual(opening_tx.source_document_number, 'SALDO-SDM-EXP-SRC')
        self.assertEqual(destination_receiving_tx.source_document_number, 'RCV-SDM-EXP-DST')
        self.assertEqual(transfer_out.source_document_number, 'SALDO-SDM-EXP-SRC')
        self.assertEqual(transfer_in.source_document_number, 'SALDO-SDM-EXP-SRC')

    def test_backfill_keeps_in_progress_opname_destination_unsplit(self):
        stock_migration = importlib.import_module(
            'apps.stock.migrations.0009_stock_source_document_number'
        )
        transaction_migration = importlib.import_module(
            'apps.stock.migrations.0010_transaction_source_document_number'
        )
        destination = Location.objects.create(
            code='SDM-OPN-DST',
            name='Opname Transfer Destination',
        )
        destination_receiving = Receiving.objects.create(
            document_number='RCV-SDM-OPN-DST',
            receiving_date=date(2026, 1, 12),
            receiving_type=Receiving.ReceivingType.GRANT,
            sumber_dana=self.funding,
            created_by=self.user,
        )
        opening_balance = OpeningBalanceImport.objects.create(
            document_number='SALDO-SDM-OPN-SRC',
            effective_date=date(2026, 1, 1),
            created_by=self.user,
        )
        source_stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='SDM-OPN',
            expiry_date=date(2030, 1, 1),
            quantity=Decimal('5'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            source_document_number='',
        )
        destination_stock = Stock.objects.create(
            item=self.item,
            location=destination,
            batch_lot='SDM-OPN',
            expiry_date=date(2031, 1, 1),
            quantity=Decimal('12'),
            reserved=Decimal('0'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
            receiving_ref=destination_receiving,
            source_document_number='',
        )
        opname = StockOpname.objects.create(
            document_number='SO-SDM-OPN-001',
            period_type=StockOpname.PeriodType.MONTHLY,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            status=StockOpname.Status.IN_PROGRESS,
            created_by=self.user,
        )
        StockOpnameItem.objects.create(
            stock_opname=opname,
            stock=destination_stock,
            system_quantity=Decimal('12'),
        )
        opening_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='SDM-OPN',
            quantity=Decimal('10'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.INITIAL_IMPORT,
            reference_id=opening_balance.pk,
            user=self.user,
        )
        destination_receiving_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='SDM-OPN',
            quantity=Decimal('7'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=destination_receiving.pk,
            user=self.user,
        )
        transfer_out = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.item,
            location=self.location,
            batch_lot='SDM-OPN',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=811,
            user=self.user,
        )
        transfer_in = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='SDM-OPN',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=811,
            user=self.user,
        )

        stock_migration.backfill_source_document_number(self.MigrationApps(), None)

        source_stock.refresh_from_db()
        destination_stock.refresh_from_db()
        self.assertEqual(source_stock.source_document_number, 'SALDO-SDM-OPN-SRC')
        self.assertEqual(destination_stock.source_document_number, 'RCV-SDM-OPN-DST')
        self.assertEqual(destination_stock.quantity, Decimal('12'))
        self.assertEqual(
            StockOpnameItem.objects.get(stock=destination_stock).system_quantity,
            Decimal('12'),
        )
        self.assertFalse(
            Stock.objects.filter(
                item=self.item,
                location=destination,
                batch_lot='SDM-OPN',
                sumber_dana=self.funding,
                source_document_number='SALDO-SDM-OPN-SRC',
            ).exists()
        )

        transaction_migration.backfill_transaction_source_document_number(
            self.MigrationApps(),
            None,
        )
        opening_tx.refresh_from_db()
        destination_receiving_tx.refresh_from_db()
        transfer_out.refresh_from_db()
        transfer_in.refresh_from_db()
        self.assertEqual(opening_tx.source_document_number, 'SALDO-SDM-OPN-SRC')
        self.assertEqual(destination_receiving_tx.source_document_number, 'RCV-SDM-OPN-DST')
        self.assertEqual(transfer_out.source_document_number, 'SALDO-SDM-OPN-SRC')
        self.assertEqual(transfer_in.source_document_number, 'SALDO-SDM-OPN-SRC')

    def test_backfill_keeps_rejected_distribution_destination_unsplit(self):
        stock_migration = importlib.import_module(
            'apps.stock.migrations.0009_stock_source_document_number'
        )
        destination = Location.objects.create(
            code='SDM-DST-PEND',
            name='Pending Distribution Destination',
        )
        facility = Facility.objects.create(
            code='SDM-DIST-FAC',
            name='Distribution Facility',
            facility_type=Facility.FacilityType.PUSKESMAS,
        )
        destination_receiving = Receiving.objects.create(
            document_number='RCV-SDM-DIST-DST',
            receiving_date=date(2026, 1, 12),
            receiving_type=Receiving.ReceivingType.GRANT,
            sumber_dana=self.funding,
            created_by=self.user,
        )
        opening_balance = OpeningBalanceImport.objects.create(
            document_number='SALDO-SDM-DIST-SRC',
            effective_date=date(2026, 1, 1),
            created_by=self.user,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='SDM-DIST',
            expiry_date=date(2030, 1, 1),
            quantity=Decimal('5'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            source_document_number='',
        )
        destination_stock = Stock.objects.create(
            item=self.item,
            location=destination,
            batch_lot='SDM-DIST',
            expiry_date=date(2031, 1, 1),
            quantity=Decimal('12'),
            reserved=Decimal('0'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
            receiving_ref=destination_receiving,
            source_document_number='',
        )
        distribution = Distribution.objects.create(
            distribution_type=Distribution.DistributionType.SPECIAL_REQUEST,
            request_date=date(2026, 1, 20),
            facility=facility,
            status=Distribution.Status.REJECTED,
            created_by=self.user,
        )
        DistributionItem.objects.create(
            distribution=distribution,
            item=self.item,
            stock=destination_stock,
            quantity_requested=Decimal('8'),
            quantity_approved=Decimal('8'),
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='SDM-DIST',
            quantity=Decimal('10'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.INITIAL_IMPORT,
            reference_id=opening_balance.pk,
            user=self.user,
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='SDM-DIST',
            quantity=Decimal('7'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=destination_receiving.pk,
            user=self.user,
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.item,
            location=self.location,
            batch_lot='SDM-DIST',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=812,
            user=self.user,
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='SDM-DIST',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=812,
            user=self.user,
        )

        stock_migration.backfill_source_document_number(self.MigrationApps(), None)

        destination_stock.refresh_from_db()
        self.assertEqual(destination_stock.source_document_number, 'RCV-SDM-DIST-DST')
        self.assertEqual(destination_stock.quantity, Decimal('12'))
        self.assertFalse(
            Stock.objects.filter(
                item=self.item,
                location=destination,
                batch_lot='SDM-DIST',
                sumber_dana=self.funding,
                source_document_number='SALDO-SDM-DIST-SRC',
            ).exists()
        )

    def test_backfill_keeps_rejected_allocation_destination_unsplit(self):
        stock_migration = importlib.import_module(
            'apps.stock.migrations.0009_stock_source_document_number'
        )
        destination = Location.objects.create(
            code='SDM-ALK-DST',
            name='Pending Allocation Destination',
        )
        destination_receiving = Receiving.objects.create(
            document_number='RCV-SDM-ALK-DST',
            receiving_date=date(2026, 1, 12),
            receiving_type=Receiving.ReceivingType.GRANT,
            sumber_dana=self.funding,
            created_by=self.user,
        )
        opening_balance = OpeningBalanceImport.objects.create(
            document_number='SALDO-SDM-ALK-SRC',
            effective_date=date(2026, 1, 1),
            created_by=self.user,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='SDM-ALK',
            expiry_date=date(2030, 1, 1),
            quantity=Decimal('5'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            source_document_number='',
        )
        destination_stock = Stock.objects.create(
            item=self.item,
            location=destination,
            batch_lot='SDM-ALK',
            expiry_date=date(2031, 1, 1),
            quantity=Decimal('12'),
            reserved=Decimal('0'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
            receiving_ref=destination_receiving,
            source_document_number='',
        )
        allocation = Allocation.objects.create(
            allocation_date=date(2026, 1, 20),
            status=Allocation.Status.REJECTED,
            created_by=self.user,
        )
        AllocationItem.objects.create(
            allocation=allocation,
            item=self.item,
            stock=destination_stock,
            total_qty_available=Decimal('12'),
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='SDM-ALK',
            quantity=Decimal('10'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.INITIAL_IMPORT,
            reference_id=opening_balance.pk,
            user=self.user,
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='SDM-ALK',
            quantity=Decimal('7'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=destination_receiving.pk,
            user=self.user,
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.item,
            location=self.location,
            batch_lot='SDM-ALK',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=813,
            user=self.user,
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='SDM-ALK',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=813,
            user=self.user,
        )

        stock_migration.backfill_source_document_number(self.MigrationApps(), None)

        destination_stock.refresh_from_db()
        self.assertEqual(destination_stock.source_document_number, 'RCV-SDM-ALK-DST')
        self.assertEqual(destination_stock.quantity, Decimal('12'))
        self.assertFalse(
            Stock.objects.filter(
                item=self.item,
                location=destination,
                batch_lot='SDM-ALK',
                sumber_dana=self.funding,
                source_document_number='SALDO-SDM-ALK-SRC',
            ).exists()
        )

    def test_backfill_keeps_equal_price_destination_with_later_outbound_unsplit(self):
        stock_migration = importlib.import_module(
            'apps.stock.migrations.0009_stock_source_document_number'
        )
        transaction_migration = importlib.import_module(
            'apps.stock.migrations.0010_transaction_source_document_number'
        )
        destination = Location.objects.create(
            code='SDM-EQP-DST',
            name='Equal Price Destination',
        )
        destination_receiving = Receiving.objects.create(
            document_number='RCV-SDM-EQP-DST',
            receiving_date=date(2026, 1, 12),
            receiving_type=Receiving.ReceivingType.GRANT,
            sumber_dana=self.funding,
            created_by=self.user,
        )
        opening_balance = OpeningBalanceImport.objects.create(
            document_number='SALDO-SDM-EQP-SRC',
            effective_date=date(2026, 1, 1),
            created_by=self.user,
        )
        source_stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='SDM-EQP',
            expiry_date=date(2030, 1, 1),
            quantity=Decimal('5'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            source_document_number='',
        )
        destination_stock = Stock.objects.create(
            item=self.item,
            location=destination,
            batch_lot='SDM-EQP',
            expiry_date=date(2031, 1, 1),
            quantity=Decimal('10'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            receiving_ref=destination_receiving,
            source_document_number='',
        )
        opening_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='SDM-EQP',
            quantity=Decimal('10'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.INITIAL_IMPORT,
            reference_id=opening_balance.pk,
            user=self.user,
        )
        destination_receiving_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='SDM-EQP',
            quantity=Decimal('7'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=destination_receiving.pk,
            user=self.user,
        )
        transfer_out = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.item,
            location=self.location,
            batch_lot='SDM-EQP',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=807,
            user=self.user,
        )
        transfer_in = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='SDM-EQP',
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=807,
            user=self.user,
        )
        later_outbound = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.item,
            location=destination,
            batch_lot='SDM-EQP',
            quantity=Decimal('2'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.DISTRIBUTION,
            reference_id=9001,
            user=self.user,
        )

        stock_migration.backfill_source_document_number(self.MigrationApps(), None)

        source_stock.refresh_from_db()
        destination_stock.refresh_from_db()
        self.assertEqual(source_stock.source_document_number, 'SALDO-SDM-EQP-SRC')
        self.assertEqual(destination_stock.source_document_number, 'RCV-SDM-EQP-DST')
        self.assertEqual(destination_stock.quantity, Decimal('10'))
        self.assertFalse(
            Stock.objects.filter(
                item=self.item,
                location=destination,
                batch_lot='SDM-EQP',
                sumber_dana=self.funding,
                source_document_number='SALDO-SDM-EQP-SRC',
            ).exists()
        )

        transaction_migration.backfill_transaction_source_document_number(
            self.MigrationApps(),
            None,
        )
        opening_tx.refresh_from_db()
        destination_receiving_tx.refresh_from_db()
        transfer_out.refresh_from_db()
        transfer_in.refresh_from_db()
        later_outbound.refresh_from_db()
        self.assertEqual(opening_tx.source_document_number, 'SALDO-SDM-EQP-SRC')
        self.assertEqual(destination_receiving_tx.source_document_number, 'RCV-SDM-EQP-DST')
        self.assertEqual(transfer_out.source_document_number, 'SALDO-SDM-EQP-SRC')
        self.assertEqual(transfer_in.source_document_number, 'SALDO-SDM-EQP-SRC')
        self.assertEqual(later_outbound.source_document_number, 'RCV-SDM-EQP-DST')

    def test_backfills_disambiguate_cross_type_document_number_collision(self):
        stock_migration = importlib.import_module(
            'apps.stock.migrations.0009_stock_source_document_number'
        )
        transaction_migration = importlib.import_module(
            'apps.stock.migrations.0010_transaction_source_document_number'
        )
        opening_location = Location.objects.create(
            code='SDM-OBI-COLLIDE',
            name='Opening Collision Location',
        )
        receiving = self._create_receiving('SRC-COLLIDE')
        opening_balance = OpeningBalanceImport.objects.create(
            document_number='SRC-COLLIDE',
            effective_date=date(2026, 1, 1),
            created_by=self.user,
        )
        receiving_stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='SDM-BATCH',
            expiry_date=date(2030, 1, 1),
            quantity=Decimal('5'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            receiving_ref=receiving,
            source_document_number='',
        )
        opening_stock = Stock.objects.create(
            item=self.item,
            location=opening_location,
            batch_lot='SDM-BATCH',
            expiry_date=date(2030, 1, 1),
            quantity=Decimal('7'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            source_document_number='',
        )
        receiving_tx = self._create_receiving_transaction(receiving, Decimal('5'))
        opening_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=opening_location,
            batch_lot='SDM-BATCH',
            quantity=Decimal('7'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.INITIAL_IMPORT,
            reference_id=opening_balance.pk,
            user=self.user,
        )

        stock_migration.backfill_source_document_number(self.MigrationApps(), None)
        receiving_stock.refresh_from_db()
        opening_stock.refresh_from_db()

        self.assertNotEqual(
            receiving_stock.source_document_number,
            opening_stock.source_document_number,
        )
        self.assertNotEqual(receiving_stock.source_document_number, 'SRC-COLLIDE')
        self.assertNotEqual(opening_stock.source_document_number, 'SRC-COLLIDE')
        self.assertTrue(receiving_stock.source_document_number.startswith('RCV-'))
        self.assertTrue(opening_stock.source_document_number.startswith('OBI-'))

        transaction_migration.backfill_transaction_source_document_number(
            self.MigrationApps(),
            None,
        )
        receiving_tx.refresh_from_db()
        opening_tx.refresh_from_db()

        self.assertEqual(
            receiving_tx.source_document_number,
            receiving_stock.source_document_number,
        )
        self.assertEqual(
            opening_tx.source_document_number,
            opening_stock.source_document_number,
        )

    def test_claim_backfill_reserves_migrated_source_identifiers(self):
        migration_module = importlib.import_module(
            'apps.stock.migrations.0011_sourcedocumentnumberclaim'
        )
        receiving = self._create_receiving('RCV-SDM-CLAIM')
        header_only_receiving = self._create_receiving('RCV-SDM-HEADER-CLAIM')
        opening_balance = OpeningBalanceImport.objects.create(
            document_number='SALDO-SDM-CLAIM',
            effective_date=date(2026, 1, 1),
            created_by=self.user,
        )
        SourceDocumentNumberClaim.objects.filter(
            document_number__in=[
                'RCV-SDM-CLAIM',
                'RCV-SDM-HEADER-CLAIM',
                'SALDO-SDM-CLAIM',
            ]
        ).delete()
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='SDM-BATCH-CLAIM',
            expiry_date=date(2030, 1, 1),
            quantity=Decimal('5'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            receiving_ref=receiving,
            source_document_number='RCV-SDM-CLAIM',
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='SDM-BATCH-CLAIM',
            source_document_number='LEGACY-SDM-CLAIM',
            quantity=Decimal('3'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.INITIAL_IMPORT,
            reference_id=opening_balance.pk,
            user=self.user,
        )

        migration_module.backfill_source_document_number_claims(
            self.MigrationApps(),
            None,
        )

        receiving_claim = SourceDocumentNumberClaim.objects.get(
            document_number='RCV-SDM-CLAIM'
        )
        header_only_receiving_claim = SourceDocumentNumberClaim.objects.get(
            document_number='RCV-SDM-HEADER-CLAIM'
        )
        opening_balance_claim = SourceDocumentNumberClaim.objects.get(
            document_number='SALDO-SDM-CLAIM'
        )
        legacy_claim = SourceDocumentNumberClaim.objects.get(
            document_number='LEGACY-SDM-CLAIM'
        )
        self.assertEqual(
            receiving_claim.source_type,
            SourceDocumentNumberClaim.SourceType.RECEIVING,
        )
        self.assertEqual(receiving_claim.source_id, receiving.pk)
        self.assertEqual(
            header_only_receiving_claim.source_type,
            SourceDocumentNumberClaim.SourceType.RECEIVING,
        )
        self.assertEqual(header_only_receiving_claim.source_id, header_only_receiving.pk)
        self.assertEqual(
            opening_balance_claim.source_type,
            SourceDocumentNumberClaim.SourceType.OPENING_BALANCE,
        )
        self.assertEqual(opening_balance_claim.source_id, opening_balance.pk)
        self.assertEqual(
            legacy_claim.source_type,
            SourceDocumentNumberClaim.SourceType.OPENING_BALANCE,
        )
        self.assertIsNone(legacy_claim.source_id)


class DownstreamNoExpirySentinelBackfillMigrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username='downstream-backfill-admin',
            password='secret12345',
        )
        self.unit = Unit.objects.create(code='SET', name='Set')
        self.category = Category.objects.create(code='SUP', name='Supply', sort_order=1)
        self.facility = Facility.objects.create(
            code='PKM-DOWN',
            name='Puskesmas Downstream',
            facility_type=Facility.FacilityType.PUSKESMAS,
        )
        self.location = Location.objects.create(code='DOWN', name='Gudang Downstream')
        self.funding = FundingSource.objects.create(code='DAU2', name='Dana Alokasi Umum 2')
        self.item = Item.objects.create(
            kode_barang='ITM-DOWN-001',
            nama_barang='Downstream Sentinel Item',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
            requires_expiry_date=False,
        )

    def test_backfill_clears_distribution_and_receipt_confirmation_sentinels(self):
        import importlib
        distribution_migration = importlib.import_module(
            'apps.distribution.migrations.0008_backfill_no_expiry_sentinel'
        )
        puskesmas_migration = importlib.import_module(
            'apps.puskesmas.migrations.0009_backfill_no_expiry_sentinel'
        )

        distribution = Distribution.objects.create(
            distribution_type=Distribution.DistributionType.SPECIAL_REQUEST,
            request_date=date(2026, 2, 10),
            facility=self.facility,
            status=Distribution.Status.DISTRIBUTED,
            created_by=self.user,
            distributed_date=date(2026, 2, 11),
        )
        distribution_item = DistributionItem.objects.create(
            distribution=distribution,
            item=self.item,
            quantity_requested=Decimal('5'),
            quantity_approved=Decimal('5'),
            issued_batch_lot='DOWN-01',
            issued_expiry_date=date(2099, 12, 31),
            issued_unit_price=Decimal('1000'),
            issued_sumber_dana=self.funding,
        )
        receipt = PuskesmasReceiptConfirmation.objects.create(
            facility=self.facility,
            distribution=distribution,
            received_date=date(2026, 2, 12),
            status=PuskesmasReceiptConfirmation.ReceiptStatus.CONFIRMED,
            created_by=self.user,
        )
        receipt_item = PuskesmasReceiptConfirmationItem.objects.create(
            sbbk=receipt,
            distribution_item=distribution_item,
            item=self.item,
            quantity=Decimal('5'),
            unit_price=Decimal('1000'),
            batch_lot='DOWN-01',
            expiry_date=date(2099, 12, 31),
            notes='legacy sentinel',
        )

        class MigrationApps:
            @staticmethod
            def get_model(app_label, model_name):
                mapping = {
                    ('distribution', 'DistributionItem'): DistributionItem,
                    ('puskesmas', 'PuskesmasReceiptConfirmationItem'): PuskesmasReceiptConfirmationItem,
                }
                return mapping[(app_label, model_name)]

        distribution_migration.backfill_no_expiry_sentinel(MigrationApps(), None)
        puskesmas_migration.backfill_no_expiry_sentinel(MigrationApps(), None)

        distribution_item.refresh_from_db()
        receipt_item.refresh_from_db()

        self.assertIsNone(distribution_item.issued_expiry_date)
        self.assertIsNone(receipt_item.expiry_date)


@override_settings(SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class StockCardTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username='admin_stock',
            password='secret12345',
        )
        self.client.force_login(self.user)

        self.unit = Unit.objects.create(code='TAB', name='Tablet')
        self.category = Category.objects.create(code='OBAT', name='Obat', sort_order=1)
        self.item = Item.objects.create(
            kode_barang='ITM-0001',
            nama_barang='Paracetamol 500mg',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
        )
        self.location = Location.objects.create(code='GUDANG', name='Gudang Utama')
        self.funding = FundingSource.objects.create(code='APBD', name='APBD')
        settings = SystemSettings.get_settings()
        settings.facility_name = "Instalasi Farmasi"
        settings.save()

        # Create transactions for testing running balance
        # TX 1: IN 100
        self.tx1 = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='B01',
            quantity=Decimal('100'),
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=1,
            user=self.user,
        )
        # TX 2: OUT 20
        self.tx2 = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.item,
            location=self.location,
            batch_lot='B01',
            quantity=Decimal('20'),
            reference_type=Transaction.ReferenceType.DISTRIBUTION,
            reference_id=1,
            user=self.user,
        )
        # Shift tx1 dates to be purely sequential
        self.tx1.created_at = timezone.now() - timedelta(days=5)
        self.tx1.save()
        self.tx2.created_at = timezone.now() - timedelta(days=2)
        self.tx2.save()

    def test_stock_card_select_view(self):
        response = self.client.get(reverse('stock:stock_card_select'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'stock/stock_card_select.html')

    def test_api_item_search(self):
        response = self.client.get(reverse('stock:api_item_search'), {'q': 'Parace'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['results']), 1)
        self.assertEqual(data['results'][0]['id'], self.item.id)
        self.assertIn('Paracetamol', data['results'][0]['text'])
        self.assertIsInstance(data['results'][0]['stock'], float)
        self.assertEqual(data['results'][0]['stock'], 0.0)

    def test_stock_card_detail_view_and_balance(self):
        response = self.client.get(reverse('stock:stock_card_detail', args=[self.item.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'stock/stock_card_detail.html')

        # Verify context contains funding_source_cards
        cards = response.context['funding_source_cards']
        self.assertTrue(len(cards) >= 1)

        # All transactions share one sumber_dana (or None), so should be in one card
        card = cards[0]
        transactions = card['transactions']
        self.assertEqual(len(transactions), 2)
        self.assertEqual(card['closing_balance'], Decimal('80'))  # 100 - 20
        self.assertEqual(card['total_in'], Decimal('100'))
        self.assertEqual(card['total_out'], Decimal('20'))

        # Verify running balance on individual objects
        self.assertEqual(transactions[0].running_balance, Decimal('100'))
        self.assertEqual(transactions[1].running_balance, Decimal('80'))

    def test_stock_card_detail_date_filter(self):
        # Filter starting after tx1, so tx1 becomes opening balance
        filter_date = (timezone.now() - timedelta(days=3)).strftime('%Y-%m-%d')
        response = self.client.get(f"{reverse('stock:stock_card_detail', args=[self.item.id])}?date_from={filter_date}")

        self.assertEqual(response.status_code, 200)
        cards = response.context['funding_source_cards']
        self.assertTrue(len(cards) >= 1)

        card = cards[0]
        transactions = card['transactions']

        # Only tx2 should be in list
        self.assertEqual(len(transactions), 1)
        self.assertEqual(card['opening_balance'], Decimal('100'))
        self.assertEqual(card['closing_balance'], Decimal('80'))

        # tx2 running balance should still be 80
        self.assertEqual(transactions[0].running_balance, Decimal('80'))

    def test_stock_card_date_filter_shows_zero_opening_balance_row(self):
        tx3 = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.item,
            location=self.location,
            batch_lot='B01',
            quantity=Decimal('80'),
            reference_type=Transaction.ReferenceType.ADJUSTMENT,
            reference_id=2,
            user=self.user,
        )
        tx4 = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='B01',
            quantity=Decimal('15'),
            reference_type=Transaction.ReferenceType.ADJUSTMENT,
            reference_id=3,
            user=self.user,
        )
        tx3.created_at = timezone.now() - timedelta(days=4)
        tx3.save(update_fields=['created_at'])
        tx4.created_at = timezone.now() - timedelta(days=1)
        tx4.save(update_fields=['created_at'])

        filter_date = (timezone.now() - timedelta(days=1)).strftime('%Y-%m-%d')

        detail_response = self.client.get(
            reverse('stock:stock_card_detail', args=[self.item.id]),
            {'date_from': filter_date},
        )
        self.assertEqual(detail_response.status_code, 200)
        detail_card = detail_response.context['funding_source_cards'][0]
        self.assertEqual(detail_card['opening_balance'], Decimal('0'))
        self.assertTrue(detail_card['show_opening_balance'])
        self.assertContains(detail_response, 'SALDO AWAL')

        print_response = self.client.get(
            reverse('stock:stock_card_print', args=[self.item.id]),
            {'date_from': filter_date},
        )
        self.assertEqual(print_response.status_code, 200)
        print_card = print_response.context['funding_source_cards'][0]
        self.assertEqual(print_card['opening_balance'], Decimal('0'))
        self.assertTrue(print_card['show_opening_balance'])
        self.assertContains(print_response, 'SALDO AWAL')

    def test_stock_card_location_filter_excludes_transfer_from_totals(self):
        destination = Location.objects.create(code='PKM', name='Puskesmas Tujuan')
        transfer = StockTransfer.objects.create(
            source_location=self.location,
            destination_location=destination,
            created_by=self.user,
        )

        transfer_out = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.item,
            location=self.location,
            batch_lot='B01',
            quantity=Decimal('5'),
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=transfer.id,
            user=self.user,
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='B01',
            quantity=Decimal('5'),
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=transfer.id,
            user=self.user,
        )
        transfer_out.created_at = timezone.now() - timedelta(days=1)
        transfer_out.save(update_fields=['created_at'])

        response = self.client.get(
            reverse('stock:stock_card_detail', args=[self.item.id]),
            {'location': self.location.id},
        )

        self.assertEqual(response.status_code, 200)
        card = response.context['funding_source_cards'][0]
        transactions = card['transactions']

        self.assertEqual(len(transactions), 3)
        self.assertEqual(card['closing_balance'], Decimal('75'))
        self.assertEqual(card['total_in'], Decimal('100'))
        self.assertEqual(card['total_out'], Decimal('20'))
        self.assertEqual(transactions[-1].reference_type, Transaction.ReferenceType.TRANSFER)
        self.assertEqual(transactions[-1].running_balance, Decimal('75'))

    def test_stock_card_date_filter_uses_full_day_boundaries(self):
        filter_day = date(2026, 1, 10)
        self.tx1.created_at = timezone.make_aware(datetime(2026, 1, 10, 0, 0, 0))
        self.tx1.save(update_fields=['created_at'])
        self.tx2.created_at = timezone.make_aware(datetime(2026, 1, 10, 23, 59, 59))
        self.tx2.save(update_fields=['created_at'])

        tx3 = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='B01',
            quantity=Decimal('5'),
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=99,
            user=self.user,
        )
        tx3.created_at = timezone.make_aware(datetime(2026, 1, 11, 0, 0, 0))
        tx3.save(update_fields=['created_at'])

        response = self.client.get(
            reverse('stock:stock_card_detail', args=[self.item.id]),
            {
                'date_from': filter_day.strftime('%Y-%m-%d'),
                'date_to': filter_day.strftime('%Y-%m-%d'),
            },
        )

        self.assertEqual(response.status_code, 200)
        card = response.context['funding_source_cards'][0]
        self.assertEqual([tx.id for tx in card['transactions']], [self.tx1.id, self.tx2.id])
        self.assertEqual(card['total_in'], Decimal('100'))
        self.assertEqual(card['total_out'], Decimal('20'))

    def test_stock_card_keeps_expiry_lookup_scoped_by_location_and_funding(self):
        other_location = Location.objects.create(code='SATELIT', name='Gudang Satelit')
        other_funding = FundingSource.objects.create(code='BOS', name='BOS')
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='SHARED-01',
            expiry_date=date(2031, 5, 1),
            quantity=Decimal('10'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
        )
        Stock.objects.create(
            item=self.item,
            location=other_location,
            batch_lot='SHARED-01',
            expiry_date=None,
            quantity=Decimal('8'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=other_funding,
        )

        dated_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='SHARED-01',
            quantity=Decimal('10'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=2,
            user=self.user,
        )
        null_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=other_location,
            batch_lot='SHARED-01',
            quantity=Decimal('8'),
            sumber_dana=other_funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=3,
            user=self.user,
        )
        dated_tx.created_at = timezone.now() - timedelta(hours=2)
        dated_tx.save(update_fields=['created_at'])
        null_tx.created_at = timezone.now() - timedelta(hours=1)
        null_tx.save(update_fields=['created_at'])

        response = self.client.get(reverse('stock:stock_card_detail', args=[self.item.id]))

        self.assertEqual(response.status_code, 200)
        cards = response.context['funding_source_cards']
        txs = [tx for card in cards for tx in card['transactions'] if tx.batch_lot == 'SHARED-01']
        self.assertEqual(len(txs), 2)

        tx_by_scope = {
            (tx.location_id, tx.sumber_dana_id): tx
            for tx in txs
        }
        self.assertEqual(
            tx_by_scope[(self.location.id, self.funding.id)].expiry_display,
            '01/05/2031',
        )
        self.assertEqual(
            tx_by_scope[(other_location.id, other_funding.id)].expiry_display,
            'Tanpa kedaluwarsa',
        )

    def test_stock_card_keeps_expiry_lookup_scoped_by_source_document(self):
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='SOURCE-SHARED-01',
            source_document_number='RCV-SOURCE-A',
            expiry_date=date(2031, 5, 1),
            quantity=Decimal('10'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='SOURCE-SHARED-01',
            source_document_number='RCV-SOURCE-B',
            expiry_date=date(2032, 6, 1),
            quantity=Decimal('8'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
        )

        first_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='SOURCE-SHARED-01',
            source_document_number='RCV-SOURCE-A',
            quantity=Decimal('10'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=4,
            user=self.user,
        )
        second_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='SOURCE-SHARED-01',
            source_document_number='RCV-SOURCE-B',
            quantity=Decimal('8'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=5,
            user=self.user,
        )
        first_tx.created_at = timezone.now() - timedelta(hours=2)
        first_tx.save(update_fields=['created_at'])
        second_tx.created_at = timezone.now() - timedelta(hours=1)
        second_tx.save(update_fields=['created_at'])

        response = self.client.get(reverse('stock:stock_card_detail', args=[self.item.id]))

        self.assertEqual(response.status_code, 200)
        cards = response.context['funding_source_cards']
        txs = [
            tx
            for card in cards
            for tx in card['transactions']
            if tx.batch_lot == 'SOURCE-SHARED-01'
        ]
        self.assertEqual(len(txs), 2)

        tx_by_source = {tx.source_document_number: tx for tx in txs}
        self.assertEqual(tx_by_source['RCV-SOURCE-A'].expiry_display, '01/05/2031')
        self.assertEqual(tx_by_source['RCV-SOURCE-B'].expiry_display, '01/06/2032')

    def test_stock_card_splits_same_funding_by_source_document_price(self):
        first_receiving = Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            document_number='RCV-PRICE-A',
            receiving_date=date(2026, 1, 15),
            sumber_dana=self.funding,
            created_by=self.user,
        )
        second_receiving = Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            document_number='RCV-PRICE-B',
            receiving_date=date(2026, 1, 20),
            sumber_dana=self.funding,
            created_by=self.user,
        )
        ReceivingItem.objects.create(
            receiving=first_receiving,
            item=self.item,
            quantity=Decimal('10'),
            batch_lot='PRICE-SHARED-01',
            expiry_date=date(2031, 5, 1),
            unit_price=Decimal('1000'),
            location=self.location,
        )
        ReceivingItem.objects.create(
            receiving=second_receiving,
            item=self.item,
            quantity=Decimal('8'),
            batch_lot='PRICE-SHARED-01',
            expiry_date=date(2031, 5, 1),
            unit_price=Decimal('2000'),
            location=self.location,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='PRICE-SHARED-01',
            source_document_number='RCV-PRICE-A',
            expiry_date=date(2031, 5, 1),
            quantity=Decimal('10'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='PRICE-SHARED-01',
            source_document_number='RCV-PRICE-B',
            expiry_date=date(2031, 5, 1),
            quantity=Decimal('8'),
            reserved=Decimal('0'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
        )
        first_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='PRICE-SHARED-01',
            source_document_number='RCV-PRICE-A',
            quantity=Decimal('10'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=first_receiving.id,
            user=self.user,
        )
        second_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='PRICE-SHARED-01',
            source_document_number='RCV-PRICE-B',
            quantity=Decimal('8'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=second_receiving.id,
            user=self.user,
        )

        response = self.client.get(reverse('stock:stock_card_detail', args=[self.item.id]))

        self.assertEqual(response.status_code, 200)
        cards_by_source = {
            card['source_document_number']: card
            for card in response.context['funding_source_cards']
            if card['source_document_number'] in {'RCV-PRICE-A', 'RCV-PRICE-B'}
        }
        self.assertEqual(set(cards_by_source), {'RCV-PRICE-A', 'RCV-PRICE-B'})
        self.assertEqual(cards_by_source['RCV-PRICE-A']['unit_price'], Decimal('1000'))
        self.assertEqual(cards_by_source['RCV-PRICE-B']['unit_price'], Decimal('2000'))
        self.assertEqual(cards_by_source['RCV-PRICE-A']['transactions'], [first_tx])
        self.assertEqual(cards_by_source['RCV-PRICE-B']['transactions'], [second_tx])
        self.assertContains(response, 'Dokumen Sumber: RCV-PRICE-A')
        self.assertContains(response, 'Dokumen Sumber: RCV-PRICE-B')

    def test_stock_card_displays_exact_high_precision_unit_price(self):
        precise_price = Decimal('5000.1234567890')
        source_document_number = 'RCV-PRECISE-STOCK-CARD'
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='PRECISE-CARD',
            source_document_number=source_document_number,
            expiry_date=date(2031, 5, 1),
            quantity=Decimal('10'),
            reserved=Decimal('0'),
            unit_price=precise_price,
            sumber_dana=self.funding,
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='PRECISE-CARD',
            source_document_number=source_document_number,
            quantity=Decimal('10'),
            unit_price=precise_price,
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=9001,
            user=self.user,
        )

        response = self.client.get(reverse('stock:stock_card_detail', args=[self.item.id]))
        print_response = self.client.get(reverse('stock:stock_card_print', args=[self.item.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(print_response.status_code, 200)
        self.assertContains(response, 'Harga Satuan: Rp 5.000,123456789')
        self.assertContains(print_response, 'Harga Satuan: Rp 5.000,123456789')
        self.assertNotContains(response, 'Harga Satuan: Rp 5.000,12</div>', html=False)
        self.assertNotContains(print_response, 'Harga Satuan: Rp 5.000,12<br>', html=False)

    def test_stock_card_filter_includes_quiet_opening_balance_layers(self):
        old_timestamp = timezone.make_aware(datetime(2026, 1, 1, 9, 0))
        active_timestamp = timezone.make_aware(datetime(2026, 1, 2, 9, 0))
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='QUIET-LAYER-A',
            source_document_number='OBI-ACTIVE-LAYER',
            expiry_date=date(2031, 5, 1),
            quantity=Decimal('8'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='QUIET-LAYER-B',
            source_document_number='OBI-QUIET-LAYER',
            expiry_date=date(2031, 5, 1),
            quantity=Decimal('7'),
            reserved=Decimal('0'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
        )
        active_opening_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='QUIET-LAYER-A',
            source_document_number='OBI-ACTIVE-LAYER',
            quantity=Decimal('10'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.INITIAL_IMPORT,
            reference_id=801,
            user=self.user,
        )
        quiet_opening_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='QUIET-LAYER-B',
            source_document_number='OBI-QUIET-LAYER',
            quantity=Decimal('7'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.INITIAL_IMPORT,
            reference_id=802,
            user=self.user,
        )
        active_out_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.item,
            location=self.location,
            batch_lot='QUIET-LAYER-A',
            source_document_number='OBI-ACTIVE-LAYER',
            quantity=Decimal('2'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.DISTRIBUTION,
            reference_id=803,
            user=self.user,
        )
        active_opening_tx.created_at = old_timestamp
        active_opening_tx.save(update_fields=['created_at'])
        quiet_opening_tx.created_at = old_timestamp
        quiet_opening_tx.save(update_fields=['created_at'])
        active_out_tx.created_at = active_timestamp
        active_out_tx.save(update_fields=['created_at'])

        response = self.client.get(
            reverse('stock:stock_card_detail', args=[self.item.id]),
            {'date_from': '2026-01-02'},
        )

        self.assertEqual(response.status_code, 200)
        cards_by_source = {
            card['source_document_number']: card
            for card in response.context['funding_source_cards']
            if card['source_document_number'] in {
                'OBI-ACTIVE-LAYER',
                'OBI-QUIET-LAYER',
            }
        }
        self.assertEqual(set(cards_by_source), {'OBI-ACTIVE-LAYER', 'OBI-QUIET-LAYER'})
        self.assertEqual(cards_by_source['OBI-ACTIVE-LAYER']['opening_balance'], Decimal('10'))
        self.assertEqual(cards_by_source['OBI-ACTIVE-LAYER']['closing_balance'], Decimal('8'))
        self.assertEqual(cards_by_source['OBI-ACTIVE-LAYER']['transactions'], [active_out_tx])
        self.assertEqual(cards_by_source['OBI-QUIET-LAYER']['opening_balance'], Decimal('7'))
        self.assertEqual(cards_by_source['OBI-QUIET-LAYER']['closing_balance'], Decimal('7'))
        self.assertEqual(cards_by_source['OBI-QUIET-LAYER']['transactions'], [])
        self.assertEqual(cards_by_source['OBI-QUIET-LAYER']['unit_price'], Decimal('2000'))
        self.assertEqual(cards_by_source['OBI-QUIET-LAYER']['location_name'], self.location.name)
        self.assertEqual(cards_by_source['OBI-QUIET-LAYER']['batch_lot'], 'QUIET-LAYER-B')
        self.assertContains(response, f'Lokasi: {self.location.name}')
        self.assertContains(response, 'Batch: QUIET-LAYER-B')
        print_response = self.client.get(
            reverse('stock:stock_card_print', args=[self.item.id]),
            {'date_from': '2026-01-02'},
        )
        self.assertEqual(print_response.status_code, 200)
        self.assertContains(print_response, f'Lokasi: {self.location.name}')
        self.assertContains(print_response, 'Batch: QUIET-LAYER-B')

    def test_stock_card_preserves_batch_prices_within_one_receiving_document(self):
        receiving = Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            document_number='RCV-BATCH-PRICE',
            receiving_date=date(2026, 1, 15),
            sumber_dana=self.funding,
            created_by=self.user,
        )
        ReceivingItem.objects.create(
            receiving=receiving,
            item=self.item,
            quantity=Decimal('10'),
            batch_lot='PRICE-BATCH-A',
            expiry_date=date(2031, 5, 1),
            unit_price=Decimal('1000'),
            location=self.location,
        )
        ReceivingItem.objects.create(
            receiving=receiving,
            item=self.item,
            quantity=Decimal('8'),
            batch_lot='PRICE-BATCH-B',
            expiry_date=date(2031, 6, 1),
            unit_price=Decimal('2000'),
            location=self.location,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='PRICE-BATCH-A',
            source_document_number='RCV-BATCH-PRICE',
            expiry_date=date(2031, 5, 1),
            quantity=Decimal('10'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='PRICE-BATCH-B',
            source_document_number='RCV-BATCH-PRICE',
            expiry_date=date(2031, 6, 1),
            quantity=Decimal('8'),
            reserved=Decimal('0'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
        )
        first_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='PRICE-BATCH-A',
            source_document_number='RCV-BATCH-PRICE',
            quantity=Decimal('10'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=receiving.id,
            user=self.user,
        )
        second_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='PRICE-BATCH-B',
            source_document_number='RCV-BATCH-PRICE',
            quantity=Decimal('8'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=receiving.id,
            user=self.user,
        )

        response = self.client.get(reverse('stock:stock_card_detail', args=[self.item.id]))

        self.assertEqual(response.status_code, 200)
        cards_by_batch = {
            card['batch_lot']: card
            for card in response.context['funding_source_cards']
            if card['source_document_number'] == 'RCV-BATCH-PRICE'
        }
        self.assertEqual(set(cards_by_batch), {'PRICE-BATCH-A', 'PRICE-BATCH-B'})
        self.assertEqual(cards_by_batch['PRICE-BATCH-A']['unit_price'], Decimal('1000'))
        self.assertEqual(cards_by_batch['PRICE-BATCH-B']['unit_price'], Decimal('2000'))
        self.assertEqual(cards_by_batch['PRICE-BATCH-A']['transactions'], [first_tx])
        self.assertEqual(cards_by_batch['PRICE-BATCH-B']['transactions'], [second_tx])

    def test_stock_card_prefers_layer_price_for_row_level_funding(self):
        other_funding = FundingSource.objects.create(code='DAK-STOCK', name='DAK Stock')
        receiving = Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            document_number='RCV-ROW-FUNDING-PRICE',
            receiving_date=date(2026, 1, 15),
            sumber_dana=self.funding,
            created_by=self.user,
        )
        ReceivingItem.objects.create(
            receiving=receiving,
            item=self.item,
            quantity=Decimal('10'),
            batch_lot='ROW-FUNDING-BATCH',
            expiry_date=date(2031, 5, 1),
            unit_price=Decimal('1000'),
            location=self.location,
        )
        ReceivingItem.objects.create(
            receiving=receiving,
            item=self.item,
            quantity=Decimal('8'),
            batch_lot='ROW-FUNDING-BATCH',
            expiry_date=date(2031, 5, 1),
            unit_price=Decimal('2500'),
            location=self.location,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='ROW-FUNDING-BATCH',
            source_document_number='RCV-ROW-FUNDING-PRICE',
            expiry_date=date(2031, 5, 1),
            quantity=Decimal('10'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='ROW-FUNDING-BATCH',
            source_document_number='RCV-ROW-FUNDING-PRICE',
            expiry_date=date(2031, 5, 1),
            quantity=Decimal('8'),
            reserved=Decimal('0'),
            unit_price=Decimal('2500'),
            sumber_dana=other_funding,
        )
        first_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='ROW-FUNDING-BATCH',
            source_document_number='RCV-ROW-FUNDING-PRICE',
            quantity=Decimal('10'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=receiving.id,
            user=self.user,
        )
        second_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='ROW-FUNDING-BATCH',
            source_document_number='RCV-ROW-FUNDING-PRICE',
            quantity=Decimal('8'),
            unit_price=Decimal('2500'),
            sumber_dana=other_funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=receiving.id,
            user=self.user,
        )

        response = self.client.get(reverse('stock:stock_card_detail', args=[self.item.id]))

        self.assertEqual(response.status_code, 200)
        cards_by_funding = {
            card['sumber_dana'].code: card
            for card in response.context['funding_source_cards']
            if card['source_document_number'] == 'RCV-ROW-FUNDING-PRICE'
        }
        self.assertEqual(set(cards_by_funding), {'APBD', 'DAK-STOCK'})
        self.assertEqual(cards_by_funding['APBD']['unit_price'], Decimal('1000'))
        self.assertEqual(cards_by_funding['DAK-STOCK']['unit_price'], Decimal('2500'))
        self.assertEqual(cards_by_funding['APBD']['transactions'], [first_tx])
        self.assertEqual(cards_by_funding['DAK-STOCK']['transactions'], [second_tx])

    def test_stock_card_keeps_same_source_batch_prices_location_specific(self):
        other_location = Location.objects.create(
            code='GUDANG-HARGA',
            name='Gudang Harga Berbeda',
        )
        receiving = Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            document_number='RCV-LOCATION-PRICE',
            receiving_date=date(2026, 1, 15),
            sumber_dana=self.funding,
            created_by=self.user,
        )
        ReceivingItem.objects.create(
            receiving=receiving,
            item=self.item,
            quantity=Decimal('10'),
            batch_lot='LOCATION-PRICE-BATCH',
            expiry_date=date(2031, 5, 1),
            unit_price=Decimal('1000'),
            location=self.location,
        )
        ReceivingItem.objects.create(
            receiving=receiving,
            item=self.item,
            quantity=Decimal('8'),
            batch_lot='LOCATION-PRICE-BATCH',
            expiry_date=date(2031, 5, 1),
            unit_price=Decimal('2000'),
            location=other_location,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='LOCATION-PRICE-BATCH',
            source_document_number='RCV-LOCATION-PRICE',
            expiry_date=date(2031, 5, 1),
            quantity=Decimal('10'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
        )
        Stock.objects.create(
            item=self.item,
            location=other_location,
            batch_lot='LOCATION-PRICE-BATCH',
            source_document_number='RCV-LOCATION-PRICE',
            expiry_date=date(2031, 5, 1),
            quantity=Decimal('8'),
            reserved=Decimal('0'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
        )
        first_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='LOCATION-PRICE-BATCH',
            source_document_number='RCV-LOCATION-PRICE',
            quantity=Decimal('10'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=receiving.id,
            user=self.user,
        )
        second_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=other_location,
            batch_lot='LOCATION-PRICE-BATCH',
            source_document_number='RCV-LOCATION-PRICE',
            quantity=Decimal('8'),
            unit_price=Decimal('2000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=receiving.id,
            user=self.user,
        )

        response = self.client.get(reverse('stock:stock_card_detail', args=[self.item.id]))

        self.assertEqual(response.status_code, 200)
        cards_by_location = {
            card['location_id']: card
            for card in response.context['funding_source_cards']
            if card['source_document_number'] == 'RCV-LOCATION-PRICE'
        }
        self.assertEqual(set(cards_by_location), {self.location.id, other_location.id})
        self.assertEqual(cards_by_location[self.location.id]['unit_price'], Decimal('1000'))
        self.assertEqual(cards_by_location[other_location.id]['unit_price'], Decimal('2000'))
        self.assertEqual(cards_by_location[self.location.id]['transactions'], [first_tx])
        self.assertEqual(cards_by_location[other_location.id]['transactions'], [second_tx])

    def test_stock_card_derives_budget_year_from_aliased_receiving_transactions(self):
        receiving = Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            document_number='SRC-COLLIDE-BUDGET',
            receiving_date=date(2024, 12, 15),
            sumber_dana=self.funding,
            created_by=self.user,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='ALIAS-BUDGET-BATCH',
            source_document_number='RCV-HASHED-SRC-COLLIDE-BUDGET',
            expiry_date=date(2031, 5, 1),
            quantity=Decimal('10'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            receiving_ref=receiving,
        )
        tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='ALIAS-BUDGET-BATCH',
            source_document_number='RCV-HASHED-SRC-COLLIDE-BUDGET',
            quantity=Decimal('10'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=receiving.id,
            user=self.user,
        )

        response = self.client.get(reverse('stock:stock_card_detail', args=[self.item.id]))

        self.assertEqual(response.status_code, 200)
        card = next(
            card
            for card in response.context['funding_source_cards']
            if card['source_document_number'] == 'RCV-HASHED-SRC-COLLIDE-BUDGET'
        )
        self.assertEqual(card['tahun_anggaran'], 2024)
        self.assertEqual(card['transactions'], [tx])

    def test_stock_card_transfer_transactions_display_computed_fields(self):
        """Verify transfer transactions have computed display fields for UI rendering."""
        destination = Location.objects.create(code='PKM2', name='Puskesmas Pembantu')
        transfer = StockTransfer.objects.create(
            source_location=self.location,
            destination_location=destination,
            created_by=self.user,
        )

        # Create receiving transaction
        Transaction.objects.create(
            item=self.item,
            transaction_type=Transaction.TransactionType.IN,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=1,
            quantity=Decimal('100'),
            location=self.location,
            sumber_dana=self.funding,
            user=self.user,
            batch_lot="BATCH-001",
        )

        # Create transfer out (internal move)
        transfer_out = Transaction.objects.create(
            item=self.item,
            transaction_type=Transaction.TransactionType.OUT,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=transfer.id,
            quantity=Decimal('30'),
            location=self.location,
            sumber_dana=self.funding,
            user=self.user,
            batch_lot="BATCH-001",
        )
        transfer_in = Transaction.objects.create(
            item=self.item,
            transaction_type=Transaction.TransactionType.IN,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=transfer.id,
            quantity=Decimal('30'),
            location=destination,
            sumber_dana=self.funding,
            user=self.user,
            batch_lot="BATCH-001",
        )
        transfer_out.created_at = timezone.now() - timedelta(days=1)
        transfer_out.save(update_fields=['created_at'])
        transfer_in.created_at = timezone.now() - timedelta(hours=12)
        transfer_in.save(update_fields=['created_at'])

        response = self.client.get(
            reverse('stock:stock_card_detail', args=[self.item.id]),
            {'sumber_dana': self.funding.id},
        )

        self.assertEqual(response.status_code, 200)
        cards = response.context['funding_source_cards']
        self.assertGreater(len(cards), 0)

        transactions = [
            tx
            for card in cards
            if card['sumber_dana'] == self.funding
            for tx in card['transactions']
        ]
        self.assertGreater(len(transactions), 0)

        # The transfer_out should be in the transactions (created last, so last in list)
        # Find it by reference_type
        transfer_out_tx = None
        transfer_in_tx = None
        receiving_tx = None
        for tx in transactions:
            if (
                tx.reference_type == Transaction.ReferenceType.TRANSFER
                and tx.transaction_type == Transaction.TransactionType.OUT
            ):
                transfer_out_tx = tx
            elif (
                tx.reference_type == Transaction.ReferenceType.TRANSFER
                and tx.transaction_type == Transaction.TransactionType.IN
            ):
                transfer_in_tx = tx
            elif tx.reference_type == Transaction.ReferenceType.RECEIVING:
                receiving_tx = tx
        self.assertIsNotNone(transfer_out_tx, "Transfer out transaction not found in card")
        self.assertIsNotNone(transfer_in_tx, "Transfer in transaction not found in card")
        self.assertIsNotNone(receiving_tx, "Receiving transaction not found in card")

        # Verify transfer transaction has display fields
        self.assertTrue(hasattr(transfer_out_tx, 'is_transfer_transaction'))
        self.assertTrue(transfer_out_tx.is_transfer_transaction)
        self.assertEqual(transfer_out_tx.transfer_quantity, Decimal('30'))
        self.assertEqual(transfer_out_tx.activity_label, 'Mutasi Keluar')
        self.assertEqual(transfer_out_tx.dari_kepada, 'Instalasi Farmasi')
        self.assertEqual(transfer_out_tx.location_label, self.location.name)

        self.assertTrue(transfer_in_tx.is_transfer_transaction)
        self.assertEqual(transfer_in_tx.transfer_quantity, Decimal('30'))
        self.assertEqual(transfer_in_tx.activity_label, 'Mutasi Masuk')
        self.assertEqual(transfer_in_tx.dari_kepada, 'Instalasi Farmasi')
        self.assertEqual(transfer_in_tx.location_label, destination.name)

        # Verify non-transfer transaction does not have transfer marker
        self.assertTrue(hasattr(receiving_tx, 'is_transfer_transaction'))
        self.assertFalse(receiving_tx.is_transfer_transaction)
        self.assertIsNone(receiving_tx.transfer_quantity)
        self.assertEqual(receiving_tx.activity_label, 'Penerimaan')
        self.assertEqual(receiving_tx.dari_kepada, 'Instalasi Farmasi')
        self.assertEqual(receiving_tx.location_label, self.location.name)

        self.assertContains(response, 'Aktivitas')
        self.assertContains(response, 'Mutasi Masuk')
        self.assertContains(response, 'Mutasi Keluar')
        self.assertContains(response, 'Lokasi Stok')
        self.assertContains(response, 'Harga Satuan: Rp 0')
        self.assertContains(response, 'Instalasi Farmasi')
        self.assertContains(response, 'Gudang Utama')
        self.assertContains(response, 'Kolom <strong>Dari / Kepada</strong> menunjukkan fasilitas atau mitra dokumen', html=False)

        print_response = self.client.get(
            reverse('stock:stock_card_print', args=[self.item.id]),
            {'sumber_dana': self.funding.id},
        )
        self.assertEqual(print_response.status_code, 200)
        self.assertContains(print_response, 'Aktivitas')
        self.assertContains(print_response, 'Mutasi Masuk')
        self.assertContains(print_response, 'Mutasi Keluar')
        self.assertContains(print_response, 'Lokasi')
        self.assertContains(print_response, 'Harga Satuan: Rp 0')
        self.assertContains(print_response, 'Instalasi Farmasi')
        self.assertContains(print_response, 'Kolom Dari / Kepada menunjukkan fasilitas atau mitra dokumen.')

    def test_stock_card_receiving_counterparty_uses_supplier_name(self):
        supplier = Supplier.objects.create(code='SUP-001', name='PT Sumber Sehat')
        supplier_receiving = Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            document_number='TER-SUP-001',
            receiving_date=date(2026, 1, 15),
            supplier=supplier,
            sumber_dana=self.funding,
            created_by=self.user,
        )

        supplier_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='SUP-01',
            quantity=Decimal('25'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=supplier_receiving.id,
            user=self.user,
        )

        response = self.client.get(
            reverse('stock:stock_card_detail', args=[self.item.id]),
            {'sumber_dana': self.funding.id},
        )

        self.assertEqual(response.status_code, 200)
        card = response.context['funding_source_cards'][0]
        tx = next(tx for tx in card['transactions'] if tx.id == supplier_tx.id)
        self.assertEqual(tx.dari_kepada, 'PT Sumber Sehat')

    def test_stock_card_receiving_counterparty_uses_grant_origin(self):
        grant_receiving = Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.GRANT,
            document_number='TER-HIB-001',
            receiving_date=date(2026, 2, 20),
            grant_origin='Dinas Kesehatan Provinsi',
            sumber_dana=self.funding,
            created_by=self.user,
        )
        grant_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='HIB-01',
            quantity=Decimal('30'),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=grant_receiving.id,
            user=self.user,
        )

        response = self.client.get(
            reverse('stock:stock_card_detail', args=[self.item.id]),
            {'sumber_dana': self.funding.id},
        )

        self.assertEqual(response.status_code, 200)
        card = response.context['funding_source_cards'][0]
        tx = next(tx for tx in card['transactions'] if tx.id == grant_tx.id)
        self.assertEqual(tx.dari_kepada, 'Dinas Kesehatan Provinsi')

    def test_stock_card_build_data_batches_multi_funding_metadata_queries(self):
        Transaction.objects.all().delete()

        funding_sources = [
            FundingSource.objects.create(code='DAK1', name='DAK 1'),
            FundingSource.objects.create(code='DAK2', name='DAK 2'),
            FundingSource.objects.create(code='DAK3', name='DAK 3'),
        ]

        for index, funding in enumerate(funding_sources, start=1):
            receiving = Receiving.objects.create(
                receiving_type=Receiving.ReceivingType.PROCUREMENT,
                document_number=f'TER-{index:03d}',
                receiving_date=date(2026, index, 15),
                sumber_dana=funding,
                created_by=self.user,
            )
            ReceivingItem.objects.create(
                receiving=receiving,
                item=self.item,
                quantity=Decimal('10'),
                batch_lot=f'QRY-{index:03d}',
                expiry_date=date(2027, index, 1),
                unit_price=Decimal(str(1000 + index)),
                location=self.location,
            )
            Transaction.objects.create(
                transaction_type=Transaction.TransactionType.IN,
                item=self.item,
                location=self.location,
                batch_lot=f'QRY-{index:03d}',
                quantity=Decimal('10'),
                sumber_dana=funding,
                reference_type=Transaction.ReferenceType.RECEIVING,
                reference_id=receiving.id,
                user=self.user,
            )

        with CaptureQueriesContext(connection) as captured_queries:
            data = stock_views._build_stock_card_data(self.item)

        self.assertEqual(len(data['funding_source_cards']), 3)
        self.assertLessEqual(len(captured_queries), 12)


class StockTransferModelTests(SimpleTestCase):
    def test_new_transfer_starts_without_document_number(self):
        transfer = StockTransfer(
            source_location_id=1,
            destination_location_id=2,
            created_by_id=1,
        )
        self.assertIsNone(transfer.document_number)

    def test_stock_transfer_item_clean_rejects_non_finite_quantity(self):
        transfer_item = StockTransferItem(quantity=Decimal("-Infinity"))

        with self.assertRaises(ValidationError) as exc:
            transfer_item.clean()

        self.assertEqual(
            exc.exception.message_dict["quantity"],
            ["Jumlah mutasi tidak boleh NaN atau Infinity."],
        )


@override_settings(
    SECURE_SSL_REDIRECT=False,
    ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'],
)
class StockTransferConcurrencyTests(TransactionTestCase):
    def setUp(self):
        DocumentNumberRule.objects.get_or_create(
            key=DocumentNumberRule.Key.STOCK_TRANSFER,
            defaults={
                "label": "Mutasi Lokasi",
                "template": "TRF-{year}{month}-{seq}",
                "reset_period": DocumentNumberRule.ResetPeriod.MONTHLY,
                "padding": 5,
            },
        )
        self.user = User.objects.create_superuser(
            username='admin_transfer_concurrency',
            password='secret12345',
        )
        unit = Unit.objects.create(code='TABTRF', name='Tablet Transfer')
        category = Category.objects.create(
            code='OBATTRF',
            name='Obat Transfer',
            sort_order=2,
        )
        self.item = Item.objects.create(
            kode_barang='ITM-TRF-CONC-0001',
            nama_barang='Amoxicillin 500mg',
            satuan=unit,
            kategori=category,
            minimum_stock=Decimal('0'),
        )
        self.source_location = Location.objects.create(
            code='SRC-TRF',
            name='Gudang Sumber',
        )
        self.destination_location = Location.objects.create(
            code='DST-TRF',
            name='Gudang Tujuan',
        )
        self.funding = FundingSource.objects.create(code='APBDTRF', name='APBD Transfer')
        self.source_stock = Stock.objects.create(
            item=self.item,
            location=self.source_location,
            batch_lot='TRF-BATCH-01',
            expiry_date=date(2030, 1, 1),
            quantity=Decimal('10'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            source_document_number='SRC-DOC-TRF',
        )
        self.transfer = StockTransfer.objects.create(
            source_location=self.source_location,
            destination_location=self.destination_location,
            created_by=self.user,
            status=StockTransfer.Status.DRAFT,
        )
        StockTransferItem.objects.create(
            transfer=self.transfer,
            stock=self.source_stock,
            item=self.item,
            quantity=Decimal('4'),
        )

    def _post_transfer_complete(self, client, results, key):
        try:
            response = client.post(
                reverse('stock:transfer_complete', args=[self.transfer.pk]),
                secure=True,
            )
            results[key] = {'status_code': response.status_code}
        except Exception as exc:
            results[key] = {'error': repr(exc)}
        finally:
            connections.close_all()

    def test_transfer_complete_concurrent_posts_apply_once(self):
        from apps.stock import views as stock_views

        barrier = threading.Barrier(2)
        original_helper = stock_views._get_locked_transfer_for_completion

        def synchronized_lock(transfer_id):
            barrier.wait(timeout=5)
            return original_helper(transfer_id)

        client_one = Client()
        client_two = Client()
        client_one.force_login(self.user)
        client_two.force_login(self.user)
        results = {}

        with patch(
            'apps.stock.views._get_locked_transfer_for_completion',
            side_effect=synchronized_lock,
        ):
            thread_one = threading.Thread(
                target=self._post_transfer_complete,
                args=(client_one, results, 'one'),
            )
            thread_two = threading.Thread(
                target=self._post_transfer_complete,
                args=(client_two, results, 'two'),
            )
            thread_one.start()
            thread_two.start()
            thread_one.join(timeout=10)
            thread_two.join(timeout=10)

        self.assertFalse(thread_one.is_alive())
        self.assertFalse(thread_two.is_alive())
        self.assertNotIn('error', results.get('one', {}))
        self.assertNotIn('error', results.get('two', {}))
        self.assertEqual(
            sorted(result['status_code'] for result in results.values()),
            [302, 302],
        )

        self.transfer.refresh_from_db()
        self.source_stock.refresh_from_db()
        self.assertEqual(self.transfer.status, StockTransfer.Status.COMPLETED)
        self.assertEqual(self.source_stock.quantity, Decimal('6'))

        destination_stock = Stock.objects.get(
            item=self.item,
            location=self.destination_location,
            batch_lot='TRF-BATCH-01',
            sumber_dana=self.funding,
            source_document_number='SRC-DOC-TRF',
        )
        self.assertEqual(destination_stock.quantity, Decimal('4'))
        self.assertEqual(destination_stock.source_document_number, 'SRC-DOC-TRF')
        self.assertEqual(
            Stock.objects.filter(
                item=self.item,
                location=self.destination_location,
                batch_lot='TRF-BATCH-01',
                sumber_dana=self.funding,
                source_document_number='SRC-DOC-TRF',
            ).count(),
            1,
        )
        self.assertEqual(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.TRANSFER,
                reference_id=self.transfer.pk,
            ).count(),
            2,
        )

    def test_transfer_complete_rejects_conflicting_destination_source_layer(self):
        Stock.objects.create(
            item=self.item,
            location=self.destination_location,
            batch_lot='TRF-BATCH-01',
            expiry_date=date(2030, 2, 1),
            quantity=Decimal('2'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
            source_document_number='SRC-DOC-TRF',
        )
        client = Client()
        client.force_login(self.user)

        response = client.post(
            reverse('stock:transfer_complete', args=[self.transfer.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.transfer.refresh_from_db()
        self.source_stock.refresh_from_db()
        self.assertEqual(self.transfer.status, StockTransfer.Status.DRAFT)
        self.assertEqual(self.source_stock.quantity, Decimal('10'))
        self.assertEqual(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.TRANSFER,
                reference_id=self.transfer.pk,
            ).count(),
            0,
        )


@override_settings(SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class StockTransferCreateValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username='admin_transfer_create',
            password='secret12345',
        )
        self.client.force_login(self.user)
        self.unit = Unit.objects.create(code='TABTRFC', name='Tablet Transfer Create')
        self.category = Category.objects.create(
            code='OBATTRFC',
            name='Obat Transfer Create',
            sort_order=3,
        )
        self.item = Item.objects.create(
            kode_barang='ITM-TRF-CREATE-0001',
            nama_barang='Ciprofloxacin 500mg',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
        )
        self.source_location = Location.objects.create(code='SRC-CREATE', name='Gudang Asal')
        self.destination_location = Location.objects.create(code='DST-CREATE', name='Gudang Tujuan')
        self.other_location = Location.objects.create(code='OTH-CREATE', name='Gudang Lain')
        self.funding = FundingSource.objects.create(code='BOKTRF', name='BOK Transfer')
        self.stock = Stock.objects.create(
            item=self.item,
            location=self.source_location,
            batch_lot='TRF-CREATE-01',
            expiry_date=date(2030, 1, 1),
            quantity=Decimal('10'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
        )
        self.other_stock = Stock.objects.create(
            item=self.item,
            location=self.other_location,
            batch_lot='TRF-CREATE-02',
            expiry_date=date(2030, 2, 1),
            quantity=Decimal('8'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
        )
        self.url = reverse('stock:transfer_create')

    def _payload(self, *, stock_id=None, quantity='0'):
        return {
            'transfer_date': '2026-07-13',
            'source_location': str(self.source_location.pk),
            'destination_location': str(self.destination_location.pk),
            'notes': 'Transfer validation test',
            'stock_id': [str(stock_id if stock_id is not None else self.stock.pk)],
            'quantity': [quantity],
        }

    def test_admin_locks_completion_fields_and_items_after_draft(self):
        transfer = StockTransfer.objects.create(
            transfer_date=date(2026, 7, 13),
            source_location=self.source_location,
            destination_location=self.destination_location,
            status=StockTransfer.Status.COMPLETED,
            created_by=self.user,
            completed_by=self.user,
            completed_at=timezone.now(),
        )
        request = RequestFactory().get('/admin/stock/stocktransfer/')
        request.user = self.user
        transfer_admin = StockTransferAdmin(StockTransfer, AdminSite())
        item_inline = StockTransferItemInline(StockTransfer, AdminSite())
        form = transfer_admin.get_form(request)

        for field_name in {
            'document_number',
            'status',
            'completed_by',
            'completed_at',
        }:
            self.assertNotIn(field_name, form.base_fields)
        self.assertNotIn('delete_selected', transfer_admin.get_actions(request))
        self.assertFalse(transfer_admin.has_change_permission(request, transfer))
        self.assertFalse(transfer_admin.has_delete_permission(request, transfer))
        self.assertFalse(item_inline.has_add_permission(request, transfer))
        self.assertFalse(item_inline.has_change_permission(request, transfer))
        self.assertFalse(item_inline.has_delete_permission(request, transfer))

    def test_transfer_create_rejects_nan_quantity_without_creating_transfer(self):
        response = self.client.post(self.url, self._payload(quantity='NaN'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Jumlah mutasi tidak boleh NaN atau Infinity.')
        self.assertFalse(StockTransfer.objects.exists())

    def test_transfer_create_rejects_infinity_quantity_without_creating_transfer(self):
        response = self.client.post(self.url, self._payload(quantity='Infinity'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Jumlah mutasi tidak boleh NaN atau Infinity.')
        self.assertFalse(StockTransfer.objects.exists())

    def test_transfer_create_rejects_negative_quantity_without_creating_transfer(self):
        response = self.client.post(self.url, self._payload(quantity='-1'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Jumlah mutasi harus lebih dari 0.')
        self.assertFalse(StockTransfer.objects.exists())

    def test_transfer_create_rejects_invalid_stock_id_without_creating_transfer(self):
        response = self.client.post(self.url, self._payload(stock_id='not-a-stock', quantity='2'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Batch stok sumber tidak valid.')
        self.assertFalse(StockTransfer.objects.exists())

    def test_transfer_create_rejects_source_location_mismatch_without_creating_transfer(self):
        response = self.client.post(
            self.url,
            self._payload(stock_id=self.other_stock.pk, quantity='2'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Batch stok tidak berada di lokasi asal yang dipilih.')
        self.assertFalse(StockTransfer.objects.exists())

    def test_transfer_create_rejects_mixed_valid_and_invalid_rows_atomically(self):
        response = self.client.post(
            self.url,
            {
                'transfer_date': '2026-07-13',
                'source_location': str(self.source_location.pk),
                'destination_location': str(self.destination_location.pk),
                'notes': 'Transfer validation test',
                'stock_id': [str(self.stock.pk), str(self.stock.pk)],
                'quantity': ['2', 'NaN'],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Periksa kembali baris mutasi yang tidak valid.')
        self.assertContains(response, 'Baris 2: Jumlah mutasi tidak boleh NaN atau Infinity.')
        self.assertFalse(StockTransfer.objects.exists())

    def test_transfer_create_creates_transfer_when_all_rows_valid(self):
        response = self.client.post(self.url, self._payload(quantity='2'))

        self.assertEqual(response.status_code, 302)
        transfer = StockTransfer.objects.get()
        self.assertEqual(transfer.status, StockTransfer.Status.DRAFT)
        self.assertEqual(transfer.items.count(), 1)
        self.assertEqual(transfer.items.get().quantity, Decimal('2'))

    def test_location_stock_search_exposes_source_document_layer(self):
        self.stock.source_document_number = 'RCV-TRF-CREATE-001'
        self.stock.save(update_fields=['source_document_number', 'updated_at'])

        response = self.client.get(
            reverse('stock:api_location_stock_search'),
            {'location': self.source_location.pk},
        )

        self.assertEqual(response.status_code, 200)
        stock_row = next(
            row
            for row in response.json()['results']
            if row['stock_id'] == self.stock.pk
        )
        self.assertEqual(
            stock_row['source_document_number'],
            'RCV-TRF-CREATE-001',
        )
        self.assertIn('Dokumen: RCV-TRF-CREATE-001', stock_row['label'])

    def test_transfer_detail_displays_selected_source_document_layer(self):
        self.stock.source_document_number = 'RCV-TRF-CREATE-DETAIL'
        self.stock.save(update_fields=['source_document_number', 'updated_at'])
        transfer = StockTransfer.objects.create(
            source_location=self.source_location,
            destination_location=self.destination_location,
            created_by=self.user,
            status=StockTransfer.Status.DRAFT,
        )
        StockTransferItem.objects.create(
            transfer=transfer,
            stock=self.stock,
            item=self.item,
            quantity=Decimal('2'),
        )

        response = self.client.get(
            reverse('stock:transfer_detail', args=[transfer.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dokumen Sumber')
        self.assertContains(response, 'RCV-TRF-CREATE-DETAIL')

@override_settings(SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class StockListViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username='stock-list-admin',
            password='secret12345',
        )
        self.client.force_login(self.user)

        self.unit = Unit.objects.create(code='TAB2', name='Tablet 2')
        self.category = Category.objects.create(code='OBT2', name='Obat 2', sort_order=1)
        self.location_a = Location.objects.create(code='LOC-A', name='Gudang A')
        self.location_b = Location.objects.create(code='LOC-B', name='Gudang B')
        self.funding_hibah = FundingSource.objects.create(code='HIBAH', name='Hibah')
        self.funding_dau = FundingSource.objects.create(code='DAU', name='Dana Alokasi Umum')
        self.funding_pad = FundingSource.objects.create(code='PAD', name='Pendapatan Asli Daerah')
        self.funding_other = FundingSource.objects.create(code='APBD', name='APBD')
        self.today = timezone.localdate()

        self.item_expired = Item.objects.create(
            kode_barang='ITM-EXPIRED',
            nama_barang='Stok Expired',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
        )
        self.item_expiring = Item.objects.create(
            kode_barang='ITM-EXPIRING',
            nama_barang='Stok Warning',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
        )
        self.item_safe = Item.objects.create(
            kode_barang='ITM-SAFE',
            nama_barang='Stok Aman',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
        )
        self.item_other = Item.objects.create(
            kode_barang='ITM-OTHER',
            nama_barang='Stok Lain',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
        )
        self.item_non_expiring = Item.objects.create(
            kode_barang='ITM-NOEXP',
            nama_barang='Zzz Tanpa ED',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
            requires_expiry_date=False,
        )

        self.expired_stock = Stock.objects.create(
            item=self.item_expired,
            location=self.location_a,
            batch_lot='EXP-01',
            expiry_date=self.today - timedelta(days=3),
            quantity=Decimal('10'),
            reserved=Decimal('2'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding_hibah,
        )
        self.expiring_stock = Stock.objects.create(
            item=self.item_expiring,
            location=self.location_a,
            batch_lot='WARN-01',
            expiry_date=self.today + timedelta(days=10),
            quantity=Decimal('5'),
            reserved=Decimal('1'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding_dau,
        )
        self.safe_stock = Stock.objects.create(
            item=self.item_safe,
            location=self.location_a,
            batch_lot='SAFE-01',
            expiry_date=self.today + timedelta(days=45),
            quantity=Decimal('20'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding_pad,
        )
        self.other_stock = Stock.objects.create(
            item=self.item_other,
            location=self.location_b,
            batch_lot='OTHER-01',
            expiry_date=self.today + timedelta(days=70),
            quantity=Decimal('7'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding_other,
        )
        self.item_today = Item.objects.create(
            kode_barang='ITM-TODAY',
            nama_barang='Stok Hari Ini',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
        )
        self.today_stock = Stock.objects.create(
            item=self.item_today,
            location=self.location_a,
            batch_lot='TODAY-01',
            expiry_date=self.today,
            quantity=Decimal('9'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding_dau,
        )
        self.non_expiring_stock = Stock.objects.create(
            item=self.item_non_expiring,
            location=self.location_a,
            batch_lot='NOEXP-01',
            expiry_date=None,
            quantity=Decimal('4'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding_other,
        )

    def test_stock_list_exposes_read_only_table_and_whole_number_quantities(self):
        response = self.client.get(reverse('stock:stock_list'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'stock/stock_list.html')
        self.assertEqual(response.context['stock_stats']['total_entries'], 6)
        self.assertEqual(response.context['stock_stats']['total_quantity'], Decimal('55'))
        self.assertEqual(response.context['stock_stats']['total_reserved'], Decimal('3'))
        self.assertEqual(response.context['stock_stats']['total_available'], Decimal('52'))
        self.assertEqual(response.context['stock_stats']['attention_count'], 5)
        self.assertEqual(response.context['quick_counts']['expired'], 2)
        self.assertEqual(response.context['quick_counts']['expiring'], 3)
        self.assertEqual(response.context['quick_counts']['safe'], 0)

        stocks_by_batch = {stock.batch_lot: stock for stock in response.context['stocks'].object_list}
        self.assertEqual(stocks_by_batch['EXP-01'].expiry_badge_class, 'text-bg-danger')
        self.assertEqual(stocks_by_batch['WARN-01'].expiry_badge_class, 'text-bg-warning')
        self.assertEqual(stocks_by_batch['SAFE-01'].expiry_badge_class, 'text-bg-warning')
        self.assertEqual(stocks_by_batch['TODAY-01'].expiry_badge_class, 'text-bg-danger')
        self.assertEqual(stocks_by_batch['EXP-01'].source_fund_badge_class, 'text-bg-warning')
        self.assertEqual(stocks_by_batch['WARN-01'].source_fund_badge_class, 'text-bg-info')
        self.assertEqual(stocks_by_batch['SAFE-01'].source_fund_badge_class, 'text-bg-success')
        self.assertContains(response, 'sticky-top')
        self.assertContains(response, '>55<', html=False)
        self.assertContains(response, '>3<', html=False)
        self.assertContains(response, '>52<', html=False)
        self.assertContains(response, '>20<', html=False)
        self.assertEqual(stocks_by_batch['NOEXP-01'].expiry_badge_class, 'text-bg-secondary')
        self.assertContains(response, 'Tanpa kedaluwarsa')
        self.assertContains(response, 'Stok Reserved')
        self.assertContains(response, 'Stok Tersedia')
        self.assertContains(response, 'Stok Fisik')
        self.assertNotContains(response, 'Ada Reserved')
        self.assertNotContains(response, 'stock-bulk-bar')
        self.assertNotContains(response, 'data-row-actions')
        self.assertNotContains(response, 'data-row-checkbox')


    def test_stock_list_treats_today_expiry_as_expired(self):
        response = self.client.get(
            reverse('stock:stock_list'),
            {'quick': 'expired'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_quick'], 'expired')
        self.assertEqual(response.context['quick_counts']['expired'], 2)
        self.assertEqual(
            [stock.batch_lot for stock in response.context['stocks'].object_list],
            ['EXP-01', 'TODAY-01'],
        )
        self.assertContains(response, 'TODAY-01')
        self.assertNotContains(response, 'WARN-01')

    def test_stock_list_filters_by_quick_filter_and_expiry_range(self):
        response = self.client.get(
            reverse('stock:stock_list'),
            {
                'quick': 'expiring',
                'expiry_from': (self.today + timedelta(days=1)).strftime('%Y-%m-%d'),
                'expiry_to': (self.today + timedelta(days=90)).strftime('%Y-%m-%d'),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_quick'], 'expiring')
        self.assertEqual(
            [stock.batch_lot for stock in response.context['stocks'].object_list],
            ['SAFE-01', 'OTHER-01', 'WARN-01'],
        )
        self.assertEqual(response.context['stock_stats']['total_entries'], 3)
        self.assertContains(response, 'WARN-01')
        self.assertContains(response, 'SAFE-01')
        self.assertContains(response, 'OTHER-01')
        self.assertNotContains(response, 'EXP-01')

    def test_stock_list_preserves_active_quick_filter_in_filter_form(self):
        response = self.client.get(
            reverse('stock:stock_list'),
            {'quick': 'expired', 'location': str(self.location_a.id)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_quick'], 'expired')
        self.assertContains(
            response,
            '<input type="hidden" name="quick" value="expired">',
            html=True,
        )

    def test_stock_list_preloads_item_units_for_rendered_rows(self):
        response = self.client.get(reverse('stock:stock_list'))

        self.assertEqual(response.status_code, 200)
        for stock in response.context['stocks'].object_list:
            self.assertIn('satuan', stock.item._state.fields_cache)

    def test_stock_list_ignores_invalid_filter_values(self):
        response = self.client.get(
            reverse('stock:stock_list'),
            {
                'location': 'abc',
                'sumber_dana': '999999',
                'expiry_from': '2026-99-99',
                'expiry_to': '0001-01-01',
                'quick': 'unknown',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_location'], '')
        self.assertEqual(response.context['selected_sumber_dana'], '')
        self.assertEqual(response.context['selected_quick'], '')
        self.assertIsNone(response.context['expiry_from'])
        self.assertIsNone(response.context['expiry_to'])
        self.assertEqual(response.context['stocks'].paginator.count, 6)


@override_settings(SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class PuskesmasStockViewTests(TestCase):
    def setUp(self):
        from apps.lplpo.models import LPLPO, LPLPOItem
        from apps.puskesmas.models import (
            PuskesmasConsumption,
            PuskesmasConsumptionEntry,
            PuskesmasReceiptConfirmation,
            PuskesmasReceiptConfirmationItem,
        )

        self.admin = User.objects.create_user(
            username='stock-planner',
            password='secret12345',
            role=User.Role.GUDANG,
        )
        ModuleAccess.objects.update_or_create(
            user=self.admin,
            module=ModuleAccess.Module.STOCK,
            defaults={"scope": ModuleAccess.Scope.VIEW},
        )
        self.client.force_login(self.admin)

        self.unit = Unit.objects.create(code='TAB-PKM', name='Tablet Puskesmas')
        self.category = Category.objects.create(code='OBT-PKM', name='Obat PKM', sort_order=1)
        self.item_a = Item.objects.create(
            kode_barang='ITM-PKM-001',
            nama_barang='Amoxicillin',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('5'),
        )
        self.item_b = Item.objects.create(
            kode_barang='ITM-PKM-002',
            nama_barang='Vitamin C',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
        )
        self.item_c = Item.objects.create(
            kode_barang='ITM-PKM-003',
            nama_barang='ORS',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
        )

        self.facility_a = Facility.objects.create(
            code='PKM-A',
            name='Puskesmas A',
            facility_type=Facility.FacilityType.PUSKESMAS,
        )
        self.facility_b = Facility.objects.create(
            code='PKM-B',
            name='Puskesmas B',
            facility_type=Facility.FacilityType.PUSKESMAS,
        )
        self.facility_c = Facility.objects.create(
            code='PKM-C',
            name='Puskesmas C',
            facility_type=Facility.FacilityType.PUSKESMAS,
        )

        self.year = timezone.localdate().year

        self.subunit_a = self._create_subunit(self.facility_a, 'Poli Umum A')
        self.subunit_a_2 = self._create_subunit(self.facility_a, 'Poli Gigi A')
        self.subunit_b = self._create_subunit(self.facility_b, 'Poli Umum B')

        lplpo_a = LPLPO.objects.create(
            facility=self.facility_a,
            bulan=3,
            tahun=self.year,
            status=LPLPO.Status.CLOSED,
            created_by=self.admin,
        )
        LPLPOItem.objects.create(
            lplpo=lplpo_a,
            item=self.item_a,
            stock_awal=12,
            penerimaan=6,
            pemakaian=6,
        )
        LPLPOItem.objects.create(
            lplpo=lplpo_a,
            item=self.item_b,
            stock_awal=25,
            penerimaan=0,
            pemakaian=5,
        )

        lplpo_b = LPLPO.objects.create(
            facility=self.facility_b,
            bulan=4,
            tahun=self.year,
            status=LPLPO.Status.CLOSED,
            created_by=self.admin,
        )
        LPLPOItem.objects.create(
            lplpo=lplpo_b,
            item=self.item_c,
            stock_awal=30,
            penerimaan=5,
            pemakaian=5,
        )

        receipt_a = PuskesmasReceiptConfirmation.objects.create(
            facility=self.facility_a,
            received_date=date(self.year, 5, 10),
            status=PuskesmasReceiptConfirmation.ReceiptStatus.CONFIRMED,
            created_by=self.admin,
        )
        PuskesmasReceiptConfirmationItem.objects.create(
            sbbk=receipt_a,
            item=self.item_a,
            quantity=Decimal('4'),
            unit_price=Decimal('1000'),
            batch_lot='RCV-A1',
            expiry_date=date(self.year + 1, 1, 31),
        )
        PuskesmasReceiptConfirmationItem.objects.create(
            sbbk=receipt_a,
            item=self.item_a,
            quantity=Decimal('3'),
            unit_price=Decimal('1000'),
            batch_lot='RCV-A1',
            expiry_date=date(self.year + 1, 1, 31),
        )

        receipt_b = PuskesmasReceiptConfirmation.objects.create(
            facility=self.facility_b,
            received_date=date(self.year, 6, 12),
            status=PuskesmasReceiptConfirmation.ReceiptStatus.CONFIRMED,
            created_by=self.admin,
        )
        PuskesmasReceiptConfirmationItem.objects.create(
            sbbk=receipt_b,
            item=self.item_c,
            quantity=Decimal('5'),
            unit_price=Decimal('1500'),
            batch_lot='RCV-B1',
            expiry_date=date(self.year + 1, 2, 28),
        )

        draft_receipt = PuskesmasReceiptConfirmation.objects.create(
            facility=self.facility_a,
            received_date=date(self.year, 7, 15),
            status=PuskesmasReceiptConfirmation.ReceiptStatus.DRAFT,
            created_by=self.admin,
        )
        PuskesmasReceiptConfirmationItem.objects.create(
            sbbk=draft_receipt,
            item=self.item_a,
            quantity=Decimal('99'),
            unit_price=Decimal('2000'),
            batch_lot='DRAFT-A',
            expiry_date=date(self.year + 1, 3, 31),
        )

        consumption_a = PuskesmasConsumption.objects.create(
            facility=self.facility_a,
            bulan=6,
            tahun=self.year,
            notes='',
            created_by=self.admin,
        )
        PuskesmasConsumptionEntry.objects.create(
            consumption=consumption_a,
            item=self.item_a,
            subunit=self.subunit_a,
            quantity=2,
        )
        PuskesmasConsumptionEntry.objects.create(
            consumption=consumption_a,
            item=self.item_a,
            subunit=self.subunit_a_2,
            quantity=3,
        )

        consumption_b = PuskesmasConsumption.objects.create(
            facility=self.facility_b,
            bulan=7,
            tahun=self.year,
            notes='',
            created_by=self.admin,
        )
        PuskesmasConsumptionEntry.objects.create(
            consumption=consumption_b,
            item=self.item_c,
            subunit=self.subunit_b,
            quantity=7,
        )

    def _create_subunit(self, facility, name):
        from apps.puskesmas.models import PuskesmasSubunit

        return PuskesmasSubunit.objects.create(
            facility=facility,
            name=name,
            subunit_type=PuskesmasSubunit.SubunitType.TREATMENT_ROOM,
        )

    def test_puskesmas_stock_accessible_for_stock_users(self):
        response = self.client.get(reverse('stock:puskesmas_stock'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'stock/puskesmas_stock.html')
        self.assertEqual(response.context['active_tab'], 'stock')

    def test_puskesmas_stock_denies_puskesmas_role_even_with_stock_scope(self):
        puskesmas_user = User.objects.create_user(
            username='puskesmas-stock-user',
            password='secret12345',
            role=User.Role.PUSKESMAS,
            facility=self.facility_a,
        )
        ModuleAccess.objects.update_or_create(
            user=puskesmas_user,
            module=ModuleAccess.Module.STOCK,
            defaults={"scope": ModuleAccess.Scope.VIEW},
        )
        self.client.force_login(puskesmas_user)

        response = self.client.get(reverse('stock:puskesmas_stock'))

        self.assertEqual(response.status_code, 403)

    def test_sidebar_link_visible_for_non_puskesmas_stock_users(self):
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('stock:puskesmas_stock'))
        self.assertContains(response, 'Stok Puskesmas')

    def test_sidebar_link_hidden_for_puskesmas_users(self):
        puskesmas_user = User.objects.create_user(
            username='puskesmas-nav-user',
            password='secret12345',
            role=User.Role.PUSKESMAS,
            facility=self.facility_a,
        )
        ModuleAccess.objects.update_or_create(
            user=puskesmas_user,
            module=ModuleAccess.Module.STOCK,
            defaults={"scope": ModuleAccess.Scope.VIEW},
        )
        self.client.force_login(puskesmas_user)

        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse('stock:puskesmas_stock'))
        self.assertNotContains(response, 'Stok Puskesmas')

    def test_puskesmas_stock_defaults_to_current_year(self):
        response = self.client.get(reverse('stock:puskesmas_stock'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['filter_form'].cleaned_data['year'], self.year)
        self.assertEqual(response.context['active_tab'], 'stock')

    def test_puskesmas_stock_renders_ledger_filters_and_tabs(self):
        response = self.client.get(reverse('stock:puskesmas_stock'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Report Ledger')
        self.assertContains(response, 'Penerimaan')
        self.assertContains(response, 'Pemakaian')
        self.assertContains(response, 'Stok Saat Ini')
        self.assertContains(response, 'id="id_year"')
        self.assertContains(response, 'id="id_facility"')
        self.assertContains(response, 'id="id_q"')
        self.assertNotContains(response, 'type="radio"')
        self.assertNotContains(response, 'js/puskesmas-stock.js')

    def test_puskesmas_stock_invalid_filters_do_not_widen_scope(self):
        response = self.client.get(
            reverse('stock:puskesmas_stock'),
            {'year': '99999', 'facility': 'not-a-facility', 'tab': 'oops'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['filter_form'].errors)
        self.assertEqual(response.context['stock_rows'], [])
        self.assertEqual(response.context['receiving_rows'], [])
        self.assertEqual(response.context['consumption_rows'], [])
        self.assertEqual(response.context['ledger_stats']['total_rows'], 0)

    def test_puskesmas_stock_filters_single_facility_for_all_tabs(self):
        response = self.client.get(
            reverse('stock:puskesmas_stock'),
            {'year': str(self.year), 'facility': str(self.facility_b.pk), 'tab': 'receiving'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_facility'], self.facility_b)
        self.assertEqual(len(response.context['receiving_rows']), 1)
        self.assertEqual(response.context['receiving_rows'][0]['facility_name'], self.facility_b.name)
        self.assertEqual(response.context['ledger_page'].object_list[0]['facility_name'], self.facility_b.name)

    def test_puskesmas_stock_year_choices_include_receipt_or_consumption_only_years(self):
        from apps.puskesmas.models import PuskesmasConsumption, PuskesmasConsumptionEntry, PuskesmasReceiptConfirmation, PuskesmasReceiptConfirmationItem

        historical_year = self.year - 6

        receipt = PuskesmasReceiptConfirmation.objects.create(
            facility=self.facility_a,
            received_date=date(historical_year, 2, 10),
            status=PuskesmasReceiptConfirmation.ReceiptStatus.CONFIRMED,
            created_by=self.admin,
        )
        PuskesmasReceiptConfirmationItem.objects.create(
            sbbk=receipt,
            item=self.item_a,
            quantity=Decimal('1'),
            unit_price=Decimal('900'),
            batch_lot='OLD-RCV',
        )
        consumption = PuskesmasConsumption.objects.create(
            facility=self.facility_b,
            bulan=3,
            tahun=historical_year,
            notes='',
            created_by=self.admin,
        )
        PuskesmasConsumptionEntry.objects.create(
            consumption=consumption,
            item=self.item_c,
            subunit=self.subunit_b,
            quantity=2,
        )

        response = self.client.get(reverse('stock:puskesmas_stock'), {'year': str(historical_year)})

        self.assertEqual(response.status_code, 200)
        year_choices = [int(value) for value, _ in response.context['filter_form'].fields['year'].choices]
        self.assertIn(historical_year, year_choices)
        self.assertEqual(response.context['filter_form'].cleaned_data['year'], historical_year)

    def test_puskesmas_stock_only_populates_rows_for_active_tab(self):
        response = self.client.get(
            reverse('stock:puskesmas_stock'),
            {'year': str(self.year), 'tab': 'receiving'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['receiving_rows'])
        self.assertEqual(response.context['consumption_rows'], [])
        self.assertEqual(response.context['stock_rows'], [])
        self.assertGreater(response.context['consumption_stats']['total_rows'], 0)
        self.assertGreater(response.context['stock_stats']['total_rows'], 0)

    def test_puskesmas_stock_search_filters_by_item_code_or_name(self):
        response = self.client.get(
            reverse('stock:puskesmas_stock'),
            {'year': str(self.year), 'q': 'amoxi'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['stock_rows']), 1)
        self.assertEqual(response.context['stock_rows'][0]['kode_barang'], 'ITM-PKM-001')
        self.assertContains(response, 'Amoxicillin')
        self.assertNotContains(response, 'Vitamin C')

    def test_puskesmas_stock_tab_query_param_switches_rendered_dataset(self):
        receiving_response = self.client.get(
            reverse('stock:puskesmas_stock'),
            {'year': str(self.year), 'tab': 'receiving'},
        )
        consumption_response = self.client.get(
            reverse('stock:puskesmas_stock'),
            {'year': str(self.year), 'tab': 'consumption'},
        )

        self.assertEqual(receiving_response.status_code, 200)
        self.assertEqual(receiving_response.context['active_tab'], 'receiving')
        self.assertContains(receiving_response, 'Harga Satuan')
        self.assertContains(receiving_response, 'Total Penerimaan')
        self.assertNotContains(receiving_response, 'Total Pemakaian')

        self.assertEqual(consumption_response.status_code, 200)
        self.assertEqual(consumption_response.context['active_tab'], 'consumption')
        self.assertContains(consumption_response, 'Total Pemakaian')
        self.assertNotContains(consumption_response, 'Harga Satuan')

    def test_puskesmas_stock_receiving_aggregates_by_batch_and_excludes_draft(self):
        response = self.client.get(
            reverse('stock:puskesmas_stock'),
            {'year': str(self.year), 'tab': 'receiving', 'facility': str(self.facility_a.pk)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['receiving_rows']), 1)
        row = response.context['receiving_rows'][0]
        self.assertEqual(row['batch_lot'], 'RCV-A1')
        self.assertEqual(row['unit_price'], Decimal('1000'))
        self.assertEqual(row['total_received'], 7)
        self.assertNotContains(response, 'DRAFT-A')
        self.assertEqual(response.context['receiving_stats']['total_received'], 7)

    def test_puskesmas_stock_receiving_displays_exact_high_precision_prices(self):
        PuskesmasReceiptConfirmationItem.objects.filter(
            sbbk__facility=self.facility_a,
            batch_lot='RCV-A1',
        ).update(unit_price=Decimal('1000.1234567890'))

        response = self.client.get(
            reverse('stock:puskesmas_stock'),
            {'year': str(self.year), 'tab': 'receiving', 'facility': str(self.facility_a.pk)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Rp 1.000,123456789')
        self.assertNotContains(response, 'Rp 1.000,12</td>', html=False)

    def test_puskesmas_stock_consumption_aggregates_yearly_totals(self):
        response = self.client.get(
            reverse('stock:puskesmas_stock'),
            {'year': str(self.year), 'tab': 'consumption', 'facility': str(self.facility_a.pk)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['consumption_rows']), 1)
        row = response.context['consumption_rows'][0]
        self.assertEqual(row['kode_barang'], 'ITM-PKM-001')
        self.assertEqual(row['total_consumption'], 5)
        self.assertEqual(response.context['consumption_stats']['total_consumption'], 5)

    def test_puskesmas_stock_uses_latest_lplpo_only_when_no_later_adjustments_exist(self):
        response = self.client.get(reverse('stock:puskesmas_stock'), {'year': str(self.year)})

        self.assertEqual(response.status_code, 200)
        row = next(row for row in response.context['stock_rows'] if row['kode_barang'] == 'ITM-PKM-002')
        self.assertEqual(row['stock_current'], 20)
        self.assertEqual(row['receipt_adjustment'], 0)
        self.assertEqual(row['consumption_adjustment'], 0)

    def test_puskesmas_stock_applies_receipt_and_consumption_adjustments_together(self):
        response = self.client.get(reverse('stock:puskesmas_stock'), {'year': str(self.year), 'facility': str(self.facility_a.pk)})

        self.assertEqual(response.status_code, 200)
        row = next(row for row in response.context['stock_rows'] if row['kode_barang'] == 'ITM-PKM-001')
        self.assertEqual(row['receipt_adjustment'], 7)
        self.assertEqual(row['consumption_adjustment'], 5)
        self.assertEqual(row['stock_current'], 14)

    def test_puskesmas_stock_ignores_cross_facility_draft_lplpo_as_baseline(self):
        from apps.lplpo.models import LPLPO, LPLPOItem

        latest_draft = LPLPO.objects.create(
            facility=self.facility_a,
            bulan=8,
            tahun=self.year,
            status=LPLPO.Status.DRAFT,
            created_by=self.admin,
        )
        LPLPOItem.objects.create(
            lplpo=latest_draft,
            item=self.item_b,
            stock_awal=999,
            penerimaan=0,
            pemakaian=0,
        )

        response = self.client.get(
            reverse('stock:puskesmas_stock'),
            {'year': str(self.year), 'facility': str(self.facility_a.pk)},
        )

        self.assertEqual(response.status_code, 200)
        row = next(row for row in response.context['stock_rows'] if row['kode_barang'] == 'ITM-PKM-002')
        self.assertEqual(row['base_month'], 3)
        self.assertEqual(row['stock_current'], 20)

    def test_puskesmas_stock_uses_distributed_lplpo_as_latest_legacy_baseline(self):
        from apps.lplpo.models import LPLPO, LPLPOItem

        distributed_lplpo = LPLPO.objects.create(
            facility=self.facility_a,
            bulan=8,
            tahun=self.year,
            status=LPLPO.Status.DISTRIBUTED,
            created_by=self.admin,
        )
        LPLPOItem.objects.create(
            lplpo=distributed_lplpo,
            item=self.item_b,
            stock_awal=40,
            penerimaan=5,
            pemakaian=3,
        )

        response = self.client.get(
            reverse('stock:puskesmas_stock'),
            {'year': str(self.year), 'facility': str(self.facility_a.pk)},
        )

        self.assertEqual(response.status_code, 200)
        row = next(row for row in response.context['stock_rows'] if row['kode_barang'] == 'ITM-PKM-002')
        self.assertEqual(row['base_month'], 8)
        self.assertEqual(row['stock_current'], 42)

    def test_puskesmas_stock_returns_empty_rows_when_facility_has_no_usable_lplpo(self):
        response = self.client.get(
            reverse('stock:puskesmas_stock'),
            {'year': str(self.year), 'facility': str(self.facility_c.pk)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['stock_rows'], [])
        self.assertEqual(response.context['stock_stats']['total_facilities'], 0)

    def test_puskesmas_stock_active_tab_paginates_results(self):
        from apps.puskesmas.models import PuskesmasReceiptConfirmation, PuskesmasReceiptConfirmationItem

        for index in range(30):
            item = Item.objects.create(
                kode_barang=f'ITM-RCV-{index:03d}',
                nama_barang=f'Barang Terima {index:03d}',
                satuan=self.unit,
                kategori=self.category,
                minimum_stock=Decimal('0'),
            )
            receipt = PuskesmasReceiptConfirmation.objects.create(
                facility=self.facility_a,
                received_date=date(self.year, 8, 1),
                status=PuskesmasReceiptConfirmation.ReceiptStatus.CONFIRMED,
                created_by=self.admin,
            )
            PuskesmasReceiptConfirmationItem.objects.create(
                sbbk=receipt,
                item=item,
                quantity=Decimal('1'),
                unit_price=Decimal('500'),
                batch_lot=f'B-{index:03d}',
            )

        response = self.client.get(
            reverse('stock:puskesmas_stock'),
            {'year': str(self.year), 'tab': 'receiving', 'page': '2'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_tab'], 'receiving')
        self.assertEqual(response.context['ledger_page'].number, 2)
        self.assertGreater(response.context['ledger_page'].paginator.num_pages, 1)
        self.assertLessEqual(len(response.context['ledger_page'].object_list), 25)

    def test_puskesmas_stock_render_does_not_regress_into_obvious_n_plus_one_queries(self):
        with CaptureQueriesContext(connection) as captured_queries:
            response = self.client.get(reverse('stock:puskesmas_stock'), {'year': str(self.year), 'tab': 'stock'})

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(captured_queries), 60)
