from datetime import date
from decimal import Decimal

from django.contrib.admin.sites import AdminSite
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.items.models import Category, FundingSource, Item, Location, Unit
from apps.receiving.admin import ReceivingAdmin
from apps.receiving.models import (
    Receiving,
    ReceivingItem,
    ReceivingOrderItem,
    ReceivingTypeOption,
)
from apps.stock.models import Stock, Transaction
from apps.users.models import User


class ReceivingCSVImportTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="admin_receiving",
            password="secret12345",
        )

        unit = Unit.objects.create(code="TAB", name="Tablet")
        category = Category.objects.create(code="OBAT", name="Obat", sort_order=1)
        self.item = Item.objects.create(
            kode_barang="ITM-TEST-0001",
            nama_barang="Paracetamol 500mg",
            satuan=unit,
            kategori=category,
            minimum_stock=Decimal("0"),
        )
        self.funding = FundingSource.objects.create(code="APBD", name="APBD")
        self.location = Location.objects.create(code="GUDANG", name="Gudang Utama")

        self.admin = ReceivingAdmin(Receiving, AdminSite())

    @staticmethod
    def _csv_file(content):
        return SimpleUploadedFile(
            "receiving.csv",
            content.encode("utf-8"),
            content_type="text/csv",
        )

    def test_process_csv_applies_defaults_for_empty_optional_fields(self):
        csv_content = (
            "document_number,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-TEST-0001,,,,\n"
        )

        result = self.admin._process_csv(self._csv_file(csv_content), self.user)

        self.assertEqual(result["receivings"], 1)
        self.assertEqual(result["items"], 1)
        self.assertEqual(result["stock"], 1)
        self.assertEqual(result["transactions"], 1)

        receiving_item = ReceivingItem.objects.get()
        self.assertEqual(receiving_item.quantity, Decimal("0"))
        self.assertEqual(receiving_item.unit_price, Decimal("0"))
        self.assertEqual(receiving_item.batch_lot, "SALDO-0002")
        self.assertEqual(receiving_item.expiry_date, date(2099, 12, 31))

        stock = Stock.objects.get()
        self.assertEqual(stock.quantity, Decimal("0"))
        self.assertEqual(stock.batch_lot, "SALDO-0002")

    def test_process_csv_handles_missing_cell_without_strip_crash(self):
        csv_content = (
            "document_number,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,,10,B-001,01/01/2030,1000\n"
        )

        with self.assertRaisesMessage(ValueError, "Baris 2: item_code kosong"):
            self.admin._process_csv(self._csv_file(csv_content), self.user)

    def test_process_csv_invalid_foreign_key_has_clear_message(self):
        csv_content = (
            "document_number,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-NOT-FOUND,10,B-001,01/01/2030,1000\n"
        )

        with self.assertRaisesMessage(
            ValueError, "Baris 2: item_code 'ITM-NOT-FOUND' tidak ditemukan"
        ):
            self.admin._process_csv(self._csv_file(csv_content), self.user)

    def test_process_csv_invalid_decimal_has_clear_message(self):
        csv_content = (
            "document_number,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-TEST-0001,sepuluh,B-001,01/01/2030,1000\n"
        )

        with self.assertRaisesMessage(
            ValueError, "Baris 2: format quantity tidak valid: 'sepuluh'"
        ):
            self.admin._process_csv(self._csv_file(csv_content), self.user)

    def test_process_csv_missing_required_header_rejected(self):
        csv_content = (
            "document_number,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,10,B-001,01/01/2030,1000\n"
        )

        with self.assertRaisesMessage(
            ValueError, "Kolom wajib tidak ditemukan: item_code"
        ):
            self.admin._process_csv(self._csv_file(csv_content), self.user)

    def test_process_csv_invalid_date_has_clear_message(self):
        csv_content = (
            "document_number,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,notadate,,APBD,GUDANG,ITM-TEST-0001,10,B-001,01/01/2030,1000\n"
        )

        with self.assertRaisesMessage(
            ValueError,
            "Baris 2: format receiving_date tidak dikenali: 'notadate'. Gunakan DD/MM/YYYY.",
        ):
            self.admin._process_csv(self._csv_file(csv_content), self.user)

    def test_process_csv_rolls_back_on_error(self):
        csv_content = (
            "document_number,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-TEST-0001,10,B-001,01/01/2030,1000\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-NOT-FOUND,10,B-002,01/01/2030,1000\n"
        )

        with self.assertRaises(ValueError):
            self.admin._process_csv(self._csv_file(csv_content), self.user)

        self.assertEqual(Receiving.objects.count(), 0)
        self.assertEqual(ReceivingItem.objects.count(), 0)
        self.assertEqual(Stock.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)


class ReceivingWorkflowCleanupTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="admin_workflow",
            password="secret12345",
        )
        self.client.force_login(self.user)

        unit = Unit.objects.create(code="TAB", name="Tablet")
        category = Category.objects.create(code="OBAT2", name="Obat 2", sort_order=2)
        self.item = Item.objects.create(
            kode_barang="ITM-TEST-0101",
            nama_barang="Amoxicillin 500mg",
            satuan=unit,
            kategori=category,
            minimum_stock=Decimal("0"),
        )
        self.funding = FundingSource.objects.create(code="DAK", name="DAK")
        self.location = Location.objects.create(code="LOC-01", name="Gudang A")

    def test_regular_receiving_create_auto_verifies_and_posts_stock_transaction(self):
        response = self.client.post(
            reverse("receiving:receiving_create"),
            {
                "document_number": "",
                "receiving_type": Receiving.ReceivingType.GRANT,
                "receiving_date": "2026-03-16",
                "supplier": "",
                "sumber_dana": self.funding.pk,
                "notes": "",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-item": self.item.pk,
                "items-0-quantity": "10",
                "items-0-batch_lot": "BATCH-001",
                "items-0-expiry_date": "2030-01-01",
                "items-0-unit_price": "1500",
                "items-0-location": self.location.pk,
            },
        )

        self.assertEqual(response.status_code, 302)
        receiving = Receiving.objects.get()
        self.assertEqual(receiving.status, Receiving.Status.VERIFIED)
        self.assertEqual(receiving.verified_by, self.user)
        self.assertTrue(receiving.document_number.startswith("RCV-"))

        receiving_item = ReceivingItem.objects.get(receiving=receiving)
        self.assertEqual(receiving_item.received_by, self.user)
        self.assertEqual(receiving_item.location, self.location)

        stock = Stock.objects.get(item=self.item, batch_lot="BATCH-001")
        self.assertEqual(stock.quantity, Decimal("10"))
        self.assertEqual(stock.location, self.location)

        trx = Transaction.objects.get(reference_id=receiving.pk)
        self.assertEqual(trx.reference_type, Transaction.ReferenceType.RECEIVING)
        self.assertEqual(trx.transaction_type, Transaction.TransactionType.IN)
        self.assertEqual(trx.quantity, Decimal("10"))

    def test_plan_close_blocked_when_remaining_items_not_cancelled(self):
        receiving = Receiving.objects.create(
            document_number="RCV-2026-99998",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )
        order_item = ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=self.item,
            planned_quantity=Decimal("5"),
            received_quantity=Decimal("0"),
            unit_price=Decimal("1000"),
            is_cancelled=False,
        )

        response = self.client.post(
            reverse("receiving:receiving_plan_close_items", args=[receiving.pk]),
            {
                "order_items-TOTAL_FORMS": "1",
                "order_items-INITIAL_FORMS": "1",
                "order_items-MIN_NUM_FORMS": "0",
                "order_items-MAX_NUM_FORMS": "1000",
                "order_items-0-id": order_item.pk,
                "order_items-0-is_cancelled": "",
                "order_items-0-cancel_reason": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        receiving.refresh_from_db()
        self.assertNotEqual(receiving.status, Receiving.Status.CLOSED)

    def test_quick_create_receiving_type_adds_option_to_form_choices(self):
        response = self.client.post(
            reverse("receiving:quick_create_receiving_type"),
            {"code": "MUTASI", "name": "Mutasi Internal"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(ReceivingTypeOption.objects.filter(code="MUTASI").exists())

        form_page = self.client.get(reverse("receiving:receiving_create"))
        self.assertEqual(form_page.status_code, 200)
        self.assertContains(form_page, "Mutasi Internal")

    def test_quick_create_receiving_type_rejects_builtin_code(self):
        response = self.client.post(
            reverse("receiving:quick_create_receiving_type"),
            {"code": "GRANT", "name": "Hibah Khusus"},
        )
        self.assertEqual(response.status_code, 400)
