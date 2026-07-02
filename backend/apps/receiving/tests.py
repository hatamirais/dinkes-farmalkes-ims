from io import BytesIO
import shutil
import threading
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from apps.distribution.models import Distribution, DistributionItem
from apps.items.models import Category, Facility, FundingSource, Item, Location, Supplier, Unit
from apps.procurement.models import ProcurementContract
from apps.receiving.admin import ReceivingAdmin, ReceivingCSVImportForm
from apps.receiving.forms import (
    PlannedReceivingForm,
    ReceivingForm,
    ReceivingOrderItemForm,
)
from apps.receiving.models import (
    Receiving,
    ReceivingDocument,
    ReceivingItem,
    ReceivingOrderItem,
    ReceivingTypeOption,
)
from apps.stock.models import Stock, Transaction
from apps.users.access import ensure_default_module_access
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

    @staticmethod
    def _uploaded_file(name, content, content_type="text/plain"):
        return SimpleUploadedFile(name, content, content_type=content_type)

    def test_csv_import_form_rejects_non_csv_extension(self):
        form = ReceivingCSVImportForm(
            data={},
            files={
                "csv_file": self._uploaded_file(
                    "receiving.pdf",
                    b"%PDF-1.4\n",
                    content_type="application/pdf",
                )
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("csv_file", form.errors)

    def test_csv_import_form_rejects_non_csv_content(self):
        form = ReceivingCSVImportForm(
            data={},
            files={
                "csv_file": self._uploaded_file(
                    "receiving.csv",
                    b"\x89PNG\r\n\x1a\n",
                    content_type="text/csv",
                )
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("csv_file", form.errors)

    def test_csv_import_form_rejects_non_csv_mime_type(self):
        form = ReceivingCSVImportForm(
            data={},
            files={
                "csv_file": self._uploaded_file(
                    "receiving.csv",
                    b"document_number,receiving_type\nRCV-1,GRANT\n",
                    content_type="application/octet-stream",
                )
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("csv_file", form.errors)

    def test_process_csv_applies_defaults_for_empty_optional_fields(self):
        csv_content = (
            "document_number,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-TEST-0001,10,,,\n"
        )

        result = self.admin._process_csv(self._csv_file(csv_content), self.user)

        self.assertEqual(result["receivings"], 1)
        self.assertEqual(result["items"], 1)
        self.assertEqual(result["stock"], 1)
        self.assertEqual(result["transactions"], 1)

        receiving_item = ReceivingItem.objects.get()
        self.assertEqual(receiving_item.quantity, Decimal("10"))
        self.assertEqual(receiving_item.unit_price, Decimal("0"))
        self.assertEqual(receiving_item.batch_lot, "SALDO-0002")
        self.assertEqual(receiving_item.expiry_date, date(2099, 12, 31))

        stock = Stock.objects.get()
        self.assertEqual(stock.quantity, Decimal("10"))
        self.assertEqual(stock.batch_lot, "SALDO-0002")

    def test_process_csv_rejects_blank_quantity(self):
        csv_content = (
            "document_number,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-TEST-0001,,B-001,01/01/2030,1000\n"
        )

        with self.assertRaisesMessage(ValueError, "Baris 2: quantity wajib diisi"):
            self.admin._process_csv(self._csv_file(csv_content), self.user)

        self.assertEqual(Receiving.objects.count(), 0)
        self.assertEqual(ReceivingItem.objects.count(), 0)
        self.assertEqual(Stock.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_process_csv_rejects_zero_quantity(self):
        csv_content = (
            "document_number,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-TEST-0001,0,B-001,01/01/2030,1000\n"
        )

        with self.assertRaisesMessage(ValueError, "Baris 2: quantity harus lebih dari 0"):
            self.admin._process_csv(self._csv_file(csv_content), self.user)

        self.assertEqual(Receiving.objects.count(), 0)
        self.assertEqual(ReceivingItem.objects.count(), 0)
        self.assertEqual(Stock.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_process_csv_rejects_negative_quantity(self):
        csv_content = (
            "document_number,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-TEST-0001,-5,B-001,01/01/2030,1000\n"
        )

        with self.assertRaisesMessage(ValueError, "Baris 2: quantity harus lebih dari 0"):
            self.admin._process_csv(self._csv_file(csv_content), self.user)

        self.assertEqual(Receiving.objects.count(), 0)
        self.assertEqual(ReceivingItem.objects.count(), 0)
        self.assertEqual(Stock.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)

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

        self.assertEqual(Receiving.objects.count(), 0)
        self.assertEqual(ReceivingItem.objects.count(), 0)
        self.assertEqual(Stock.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_process_csv_rejects_nan_decimal(self):
        csv_content = (
            "document_number,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-TEST-0001,NaN,B-001,01/01/2030,1000\n"
        )

        with self.assertRaisesMessage(
            ValueError, "Baris 2: quantity tidak boleh NaN atau Infinity"
        ):
            self.admin._process_csv(self._csv_file(csv_content), self.user)

        self.assertEqual(Receiving.objects.count(), 0)
        self.assertEqual(ReceivingItem.objects.count(), 0)
        self.assertEqual(Stock.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_import_view_requires_add_permission(self):
        user = User.objects.create_user(
            username="receiving_staff",
            password="secret12345",
            is_staff=True,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("admin:receiving_import_csv"))

        self.assertEqual(response.status_code, 403)

    def test_import_view_logs_success(self):
        self.client.force_login(self.user)
        csv_content = (
            "document_number,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-TEST-0001,10,B-001,01/01/2030,1000\n"
        )

        with self.assertLogs("security", level="INFO") as logs:
            response = self.client.post(
                reverse("admin:receiving_import_csv"),
                {"csv_file": self._csv_file(csv_content)},
            )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            any("receiving_csv_import_succeeded" in message for message in logs.output)
        )

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

    def test_process_csv_rejects_invalid_receiving_type(self):
        csv_content = (
            "document_number,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,FOO,12/03/2026,,APBD,GUDANG,ITM-TEST-0001,10,B-001,01/01/2030,1000\n"
        )

        with self.assertRaisesMessage(ValueError, "Baris 2: Masukkan pilihan yang valid."):
            self.admin._process_csv(self._csv_file(csv_content), self.user)


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
        self.rs_facility = Facility.objects.create(
            code="RS-01",
            name="RSUD Meulaboh",
            facility_type=Facility.FacilityType.RS,
        )

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
            secure=True,
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

    def test_regular_receiving_create_rejects_non_finite_quantity(self):
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
                "items-0-quantity": "NaN",
                "items-0-batch_lot": "BATCH-001",
                "items-0-expiry_date": "2030-01-01",
                "items-0-unit_price": "1500",
                "items-0-location": self.location.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Masukkan sebuah bilangan.")
        self.assertEqual(Receiving.objects.count(), 0)

    def test_regular_receiving_create_accepts_custom_receiving_type(self):
        ReceivingTypeOption.objects.create(code="DON", name="Donasi")

        response = self.client.post(
            reverse("receiving:receiving_create"),
            {
                "document_number": "",
                "receiving_type": "DON",
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
                "items-0-batch_lot": "BATCH-DON-001",
                "items-0-expiry_date": "2030-01-01",
                "items-0-unit_price": "1500",
                "items-0-location": self.location.pk,
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        receiving = Receiving.objects.get(document_number__startswith="RCV-")
        self.assertEqual(receiving.receiving_type, "DON")
        self.assertEqual(receiving.receiving_type_label, "Donasi")
        self.assertEqual(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.RECEIVING,
                reference_id=receiving.pk,
                transaction_type=Transaction.TransactionType.IN,
            ).count(),
            1,
        )


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

    def test_quick_create_supplier_creates_normalized_lookup(self):
        response = self.client.post(
            reverse("receiving:quick_create_supplier"),
            {
                "code": " sup-01 ",
                "name": "  PT   Farmasi Nusantara  ",
                "address": "  Jl.  Merdeka   10  ",
                "phone": " 08123  ",
                "email": "vendor@example.com",
                "notes": "  Mitra   utama  ",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        supplier = Supplier.objects.get(code="SUP-01")
        self.assertEqual(supplier.name, "PT Farmasi Nusantara")
        self.assertEqual(supplier.address, "Jl. Merdeka 10")
        self.assertEqual(supplier.phone, "08123")
        self.assertEqual(supplier.notes, "Mitra utama")

    def test_quick_create_supplier_rejects_invalid_email(self):
        response = self.client.post(
            reverse("receiving:quick_create_supplier"),
            {"code": "SUP-01", "name": "PT Farmasi", "email": "tidak-valid"},
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Masukkan alamat email yang valid.", response.json()["error"])
        self.assertEqual(Supplier.objects.count(), 0)

    def test_quick_create_supplier_rejects_null_byte_input(self):
        response = self.client.post(
            reverse("receiving:quick_create_supplier"),
            {"code": "SUP-01", "name": "PT Farma\x00si"},
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Karakter null tidak diizinkan.", response.json()["error"])
        self.assertEqual(Supplier.objects.count(), 0)

    def test_quick_create_supplier_rejects_duplicate_name_case_insensitive(self):
        Supplier.objects.create(code="SUP-00", name="PT Farmasi Nusantara")

        response = self.client.post(
            reverse("receiving:quick_create_supplier"),
            {"code": "SUP-01", "name": "  pt   farmasi   nusantara  "},
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Nama sudah digunakan", response.json()["error"])
        self.assertEqual(Supplier.objects.count(), 1)

    def test_quick_create_funding_source_creates_normalized_lookup(self):
        response = self.client.post(
            reverse("receiving:quick_create_funding_source"),
            {
                "code": " apbn ",
                "name": "  Dana   Alokasi Khusus  ",
                "description": "  Bantuan   pusat  ",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        funding = FundingSource.objects.get(code="APBN")
        self.assertEqual(funding.name, "Dana Alokasi Khusus")
        self.assertEqual(funding.description, "Bantuan pusat")

    def test_quick_create_funding_source_rejects_overlong_code(self):
        response = self.client.post(
            reverse("receiving:quick_create_funding_source"),
            {"code": "X" * 21, "name": "Dana Baru"},
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("paling banyak 20 karakter", response.json()["error"])
        self.assertEqual(FundingSource.objects.count(), 1)

    def test_quick_create_funding_source_rejects_duplicate_name_case_insensitive(self):
        FundingSource.objects.create(code="DAU", name="Dana Alokasi Umum")

        response = self.client.post(
            reverse("receiving:quick_create_funding_source"),
            {"code": "DAU-2", "name": "  dana   alokasi umum  "},
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Nama sudah digunakan", response.json()["error"])

    def test_quick_create_receiving_type_adds_option_to_form_choices(self):
        response = self.client.post(
            reverse("receiving:quick_create_receiving_type"),
            {"code": "MUTASI", "name": "Mutasi Internal"},
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(ReceivingTypeOption.objects.filter(code="MUTASI").exists())

        form_page = self.client.get(
            reverse("receiving:receiving_create"),
            secure=True,
        )
        self.assertEqual(form_page.status_code, 200)
        self.assertContains(form_page, "Mutasi Internal")

        create_response = self.client.post(
            reverse("receiving:receiving_create"),
            {
                "document_number": "",
                "receiving_type": "MUTASI",
                "receiving_date": "2026-03-16",
                "supplier": "",
                "sumber_dana": self.funding.pk,
                "notes": "",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-item": self.item.pk,
                "items-0-quantity": "4",
                "items-0-batch_lot": "BATCH-MUT-001",
                "items-0-expiry_date": "2030-01-01",
                "items-0-unit_price": "1000",
                "items-0-location": self.location.pk,
            },
            secure=True,
        )

        self.assertEqual(create_response.status_code, 302)
        self.assertTrue(Receiving.objects.filter(receiving_type="MUTASI").exists())

    def test_quick_create_receiving_type_rejects_builtin_code(self):
        response = self.client.post(
            reverse("receiving:quick_create_receiving_type"),
            {"code": "GRANT", "name": "Hibah Khusus"},
            secure=True,
        )
        self.assertEqual(response.status_code, 400)

    def test_quick_create_receiving_type_rejects_reserved_internal_code(self):
        response = self.client.post(
            reverse("receiving:quick_create_receiving_type"),
            {"code": "RETURN_RS", "name": "Pengembalian RS"},
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(ReceivingTypeOption.objects.filter(code="RETURN_RS").exists())

    def test_quick_create_receiving_type_rejects_duplicate_name_case_insensitive(self):
        ReceivingTypeOption.objects.create(code="MUTASI", name="Mutasi Internal")

        response = self.client.post(
            reverse("receiving:quick_create_receiving_type"),
            {"code": "MUT-2", "name": "  mutasi   internal  "},
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Nama sudah digunakan", response.json()["error"])

    @override_settings(ITEM_MUTATION_RATE_LIMIT="1/m", RATELIMIT_USE_CACHE="locmem")
    def test_receiving_quick_create_uses_shared_item_mutation_rate_limit(self):
        first = self.client.post(
            reverse("receiving:quick_create_supplier"),
            {"code": "SUP-01", "name": "PT Farmasi"},
            secure=True,
        )
        second = self.client.post(
            reverse("receiving:quick_create_supplier"),
            {"code": "SUP-02", "name": "PT Farmasi Dua"},
            secure=True,
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)

    def test_receiving_item_forms_use_name_only_item_labels(self):
        self.item.nama_barang = "Paracetamol 500mg [P]"
        self.item.save(update_fields=["nama_barang", "updated_at"])

        receiving_form = ReceivingOrderItemForm()
        receipt_form = ReceivingForm()

        self.assertEqual(receiving_form.fields["item"].label_from_instance(self.item), "Paracetamol 500mg")
        self.assertNotIn("kode_barang", receipt_form.fields)

    def test_receiving_str_uses_safe_label_for_builtin_and_custom_types(self):
        builtin_receiving = Receiving.objects.create(
            document_number="RCV-2026-STR-001",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.VERIFIED,
            created_by=self.user,
            verified_by=self.user,
        )
        ReceivingTypeOption.objects.create(code="DON", name="Donasi")
        custom_receiving = Receiving.objects.create(
            document_number="RCV-2026-STR-002",
            receiving_type="DON",
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.VERIFIED,
            created_by=self.user,
            verified_by=self.user,
        )

        self.assertEqual(str(builtin_receiving), "RCV-2026-STR-001 (Hibah)")
        self.assertEqual(str(custom_receiving), "RCV-2026-STR-002 (Donasi)")

    def test_receiving_create_includes_item_picker_table_script(self):
        response = self.client.get(reverse("receiving:receiving_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "js/item-picker-table.js?v=")

    def test_receiving_plan_create_includes_item_picker_table_script(self):
        response = self.client.get(reverse("receiving:receiving_plan_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "js/item-picker-table.js?v=")

    def test_regular_receiving_list_does_not_show_redundant_status_filter(self):
        Receiving.objects.create(
            document_number="RCV-2026-99994",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.VERIFIED,
            is_planned=False,
            created_by=self.user,
            verified_by=self.user,
        )

        response = self.client.get(reverse("receiving:receiving_list"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="status"', html=False)
        self.assertNotContains(response, 'Status:</span>', html=False)
        self.assertContains(response, 'badge-status badge-verified', html=False)

    def test_regular_receiving_create_page_does_not_show_rs_settlement_column(self):
        response = self.client.get(reverse("receiving:receiving_create"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Dokumen RS Asal")
        self.assertNotContains(response, 'name="items-0-settlement_distribution_item"', html=False)

    def test_regular_receiving_create_page_hides_facility_and_shows_required_markers(self):
        response = self.client.get(reverse("receiving:receiving_create"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="facility"', html=False)
        self.assertContains(response, 'placeholder="Kosongkan untuk generate otomatis"', html=False)
        self.assertContains(response, 'Receiving type <span class="text-danger">*</span>', html=False)
        self.assertContains(response, 'Receiving date <span class="text-danger">*</span>', html=False)
        self.assertContains(response, 'Sumber dana <span class="text-danger">*</span>', html=False)

    def test_planned_receiving_create_page_shows_required_markers_and_placeholder(self):
        response = self.client.get(reverse("receiving:receiving_plan_create"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="facility"', html=False)
        self.assertContains(response, 'placeholder="Kosongkan untuk generate otomatis"', html=False)
        self.assertContains(response, 'Receiving type <span class="text-danger">*</span>', html=False)
        self.assertContains(response, 'Receiving date <span class="text-danger">*</span>', html=False)
        self.assertContains(response, 'Sumber dana <span class="text-danger">*</span>', html=False)
        self.assertNotContains(response, '>Pengadaan</option>', html=False)
        self.assertContains(response, '>Hibah</option>', html=False)

    def test_planned_receiving_list_keeps_manual_create_for_non_procurement_types(self):
        response = self.client.get(reverse("receiving:receiving_plan_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("receiving:receiving_plan_create"))
        self.assertContains(response, "Buat Rencana Non-Pengadaan")
        self.assertContains(response, "Gunakan buat manual hanya untuk hibah")

    def test_regular_receiving_detail_rejects_planned_receiving(self):
        planned_receiving = Receiving.objects.create(
            document_number="RCV-2026-99993",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )

        response = self.client.get(
            reverse("receiving:receiving_detail", args=[planned_receiving.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_procurement_receiving_forms_require_supplier(self):
        form_data = {
            "document_number": "",
            "receiving_type": Receiving.ReceivingType.PROCUREMENT,
            "receiving_date": "2026-03-16",
            "supplier": "",
            "facility": "",
            "sumber_dana": self.funding.pk,
            "notes": "",
        }

        regular_form = ReceivingForm(data=form_data)
        planned_form = PlannedReceivingForm(data=form_data)

        self.assertFalse(regular_form.is_valid())
        self.assertFalse(planned_form.is_valid())
        self.assertEqual(
            regular_form.errors["supplier"],
            ["Supplier wajib diisi untuk tipe Pengadaan."],
        )
        self.assertEqual(
            planned_form.errors["receiving_type"],
            ["Rencana penerimaan pengadaan baru wajib dibuat melalui modul SPJ / Pengadaan."],
        )

    def test_receiving_forms_reject_unknown_custom_receiving_type(self):
        form_data = {
            "document_number": "",
            "receiving_type": "TIDAKADA",
            "receiving_date": "2026-03-16",
            "supplier": "",
            "sumber_dana": self.funding.pk,
            "notes": "",
        }

        regular_form = ReceivingForm(data=form_data)
        planned_form = PlannedReceivingForm(data=form_data)

        self.assertFalse(regular_form.is_valid())
        self.assertFalse(planned_form.is_valid())
        self.assertEqual(regular_form.errors["receiving_type"], ["Masukkan pilihan yang valid."])
        self.assertEqual(planned_form.errors["receiving_type"], ["Masukkan pilihan yang valid."])

    def test_receiving_forms_reject_null_byte_receiving_type_as_field_error(self):
        form_data = {
            "document_number": "",
            "receiving_type": "DON\x00ASI",
            "receiving_date": "2026-03-16",
            "supplier": "",
            "sumber_dana": self.funding.pk,
            "notes": "",
        }

        regular_form = ReceivingForm(data=form_data)
        planned_form = PlannedReceivingForm(data=form_data)

        self.assertFalse(regular_form.is_valid())
        self.assertFalse(planned_form.is_valid())
        self.assertEqual(
            regular_form.errors["receiving_type"],
            ["Karakter null tidak diizinkan."],
        )
        self.assertEqual(
            planned_form.errors["receiving_type"],
            ["Karakter null tidak diizinkan."],
        )

    def test_receiving_forms_reject_reserved_internal_receiving_type(self):
        form_data = {
            "document_number": "",
            "receiving_type": "RETURN_RS",
            "receiving_date": "2026-03-16",
            "supplier": "",
            "sumber_dana": self.funding.pk,
            "notes": "",
        }

        regular_form = ReceivingForm(data=form_data)
        planned_form = PlannedReceivingForm(data=form_data)

        self.assertFalse(regular_form.is_valid())
        self.assertFalse(planned_form.is_valid())
        self.assertEqual(regular_form.errors["receiving_type"], ["Masukkan pilihan yang valid."])
        self.assertEqual(planned_form.errors["receiving_type"], ["Masukkan pilihan yang valid."])

    def test_receiving_model_full_clean_rejects_invalid_receiving_type(self):
        receiving = Receiving(
            document_number="RCV-2026-INVALID",
            receiving_type="FOO",
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.VERIFIED,
            created_by=self.user,
            verified_by=self.user,
        )

        with self.assertRaises(ValidationError) as exc:
            receiving.full_clean()

        self.assertEqual(
            exc.exception.message_dict["receiving_type"],
            ["Masukkan pilihan yang valid."],
        )

    def test_receiving_model_full_clean_requires_supplier_for_procurement(self):
        receiving = Receiving(
            document_number="RCV-2026-PROC-001",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.VERIFIED,
            created_by=self.user,
            verified_by=self.user,
        )

        with self.assertRaises(ValidationError) as exc:
            receiving.full_clean()

        self.assertEqual(
            exc.exception.message_dict["supplier"],
            ["Supplier wajib diisi untuk tipe Pengadaan."],
        )

    def test_receiving_forms_require_explicit_receiving_type_selection(self):
        regular_form = ReceivingForm(
            data={
                "document_number": "",
                "receiving_type": "",
                "receiving_date": "2026-03-16",
                "supplier": "",
                "sumber_dana": self.funding.pk,
                "notes": "",
            }
        )
        planned_form = PlannedReceivingForm(
            data={
                "document_number": "",
                "receiving_type": "",
                "receiving_date": "2026-03-16",
                "supplier": "",
                "sumber_dana": self.funding.pk,
                "notes": "",
            }
        )

        self.assertEqual(regular_form.fields["receiving_type"].widget.choices[0], ("", "---------"))
        self.assertEqual(planned_form.fields["receiving_type"].widget.choices[0], ("", "---------"))
        self.assertFalse(regular_form.is_valid())
        self.assertFalse(planned_form.is_valid())
        self.assertEqual(regular_form.errors["receiving_type"], ["Tipe penerimaan wajib dipilih."])
        self.assertEqual(planned_form.errors["receiving_type"], ["Tipe penerimaan wajib dipilih."])

    def test_planned_receiving_create_accepts_custom_receiving_type(self):
        ReceivingTypeOption.objects.create(code="DON", name="Donasi")

        response = self.client.post(
            reverse("receiving:receiving_plan_create"),
            {
                "document_number": "",
                "receiving_type": "DON",
                "receiving_date": "2026-03-16",
                "supplier": "",
                "sumber_dana": self.funding.pk,
                "notes": "",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-item": self.item.pk,
                "items-0-planned_quantity": "5",
                "items-0-unit_price": "1000",
                "items-0-notes": "",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        receiving = Receiving.objects.get(is_planned=True)
        self.assertEqual(receiving.receiving_type, "DON")
        self.assertEqual(receiving.receiving_type_label, "Donasi")
        self.assertEqual(receiving.status, Receiving.Status.DRAFT)
        self.assertTrue(receiving.order_items.filter(item=self.item).exists())

    def test_planned_receiving_create_blocks_manual_procurement_type(self):
        response = self.client.post(
            reverse("receiving:receiving_plan_create"),
            {
                "document_number": "",
                "receiving_type": Receiving.ReceivingType.PROCUREMENT,
                "receiving_date": "2026-03-16",
                "supplier": "",
                "sumber_dana": self.funding.pk,
                "notes": "",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-item": self.item.pk,
                "items-0-planned_quantity": "5",
                "items-0-unit_price": "1000",
                "items-0-notes": "",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Rencana penerimaan pengadaan baru wajib dibuat melalui modul SPJ / Pengadaan.",
            response.context["form"].errors["receiving_type"],
        )
        self.assertFalse(Receiving.objects.filter(is_planned=True).exists())

    def test_receiving_full_clean_rejects_duplicate_planned_contract_link(self):
        supplier = Supplier.objects.create(code="SUP-RCV-001", name="PT Supplier Receiving")
        contract = ProcurementContract.objects.create(
            document_number="SPJ-RCV-001",
            contract_date=date(2026, 3, 16),
            supplier=supplier,
            sumber_dana=self.funding,
            notes="Kontrak receiving",
            created_by=self.user,
        )
        Receiving.objects.create(
            document_number="RCV-2026-CONTRACT-001",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            is_planned=True,
            contract=contract,
            supplier=supplier,
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            created_by=self.user,
        )
        duplicate = Receiving(
            document_number="RCV-2026-CONTRACT-002",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 17),
            is_planned=True,
            contract=contract,
            supplier=supplier,
            sumber_dana=self.funding,
            status=Receiving.Status.DRAFT,
            created_by=self.user,
        )

        with self.assertRaises(ValidationError) as exc:
            duplicate.full_clean()

        self.assertEqual(
            exc.exception.message_dict["contract"],
            ["Setiap kontrak SPJ hanya boleh memiliki satu rencana penerimaan."],
        )

    def test_receiving_db_constraint_rejects_duplicate_planned_contract_link(self):
        supplier = Supplier.objects.create(code="SUP-RCV-002", name="PT Supplier Receiving 2")
        contract = ProcurementContract.objects.create(
            document_number="SPJ-RCV-002",
            contract_date=date(2026, 3, 16),
            supplier=supplier,
            sumber_dana=self.funding,
            notes="Kontrak receiving",
            created_by=self.user,
        )
        Receiving.objects.create(
            document_number="RCV-2026-CONTRACT-003",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            is_planned=True,
            contract=contract,
            supplier=supplier,
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            created_by=self.user,
        )

        with self.assertRaises(IntegrityError):
            Receiving.objects.create(
                document_number="RCV-2026-CONTRACT-004",
                receiving_type=Receiving.ReceivingType.PROCUREMENT,
                receiving_date=date(2026, 3, 17),
                is_planned=True,
                contract=contract,
                supplier=supplier,
                sumber_dana=self.funding,
                status=Receiving.Status.DRAFT,
                created_by=self.user,
            )

    def test_plan_receive_page_uses_fixed_rows_without_delete_control(self):
        receiving = Receiving.objects.create(
            document_number="RCV-2026-99997",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )
        ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=self.item,
            planned_quantity=Decimal("5000"),
            received_quantity=Decimal("0"),
            unit_price=Decimal("1000"),
            is_cancelled=False,
        )

        response = self.client.get(
            reverse("receiving:receiving_plan_receive", args=[receiving.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sisa Rencana")
        self.assertContains(response, "Kuantitas Diterima")
        self.assertContains(response, self.item.nama_barang)
        self.assertNotContains(response, self.item.kode_barang)
        self.assertContains(response, 'name="items-0-order_item"', html=False)
        self.assertContains(response, 'value="5.000,00"', html=False)
        self.assertContains(response, self.location.name)
        self.assertNotContains(response, self.location.code)
        self.assertNotContains(response, "Hapus")

    def test_plan_receive_page_shows_only_outstanding_items_and_remaining_quantity(self):
        receiving = Receiving.objects.create(
            document_number="RCV-2026-99988",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.PARTIAL,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )
        partial_order = ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=self.item,
            planned_quantity=Decimal("10000"),
            received_quantity=Decimal("5000"),
            unit_price=Decimal("1000"),
            is_cancelled=False,
        )
        second_item = Item.objects.create(
            kode_barang="ITM-TEST-0103",
            nama_barang="Alopurinol 100 mg",
            satuan=self.item.satuan,
            kategori=self.item.kategori,
            minimum_stock=Decimal("0"),
        )
        ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=second_item,
            planned_quantity=Decimal("20000"),
            received_quantity=Decimal("20000"),
            unit_price=Decimal("2000"),
            is_cancelled=False,
        )

        response = self.client.get(
            reverse("receiving:receiving_plan_receive", args=[receiving.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.item.nama_barang)
        self.assertContains(response, 'value="5.000,00"', html=False)
        self.assertNotContains(response, second_item.nama_barang)
        self.assertNotContains(response, 'value="20.000,00"', html=False)
        self.assertContains(response, f'value="{partial_order.pk}"', html=False)

    def test_plan_receive_accepts_zero_qty_as_no_receipt_for_row(self):
        receiving = Receiving.objects.create(
            document_number="RCV-2026-99996",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )
        oi = ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=self.item,
            planned_quantity=Decimal("5"),
            received_quantity=Decimal("0"),
            unit_price=Decimal("1000"),
            is_cancelled=False,
        )

        response = self.client.post(
            reverse("receiving:receiving_plan_receive", args=[receiving.pk]),
            {
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-order_item": str(oi.pk),
                "items-0-quantity": "0",
                "items-0-batch_lot": "",
                "items-0-expiry_date": "",
                "items-0-unit_price": "1000",
                "items-0-location": "",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        receiving.refresh_from_db()
        self.assertEqual(receiving.status, Receiving.Status.APPROVED)
        self.assertEqual(ReceivingItem.objects.filter(receiving=receiving).count(), 0)

    def test_plan_receive_allows_partial_and_full_receipt_mix(self):
        receiving = Receiving.objects.create(
            document_number="RCV-2026-99990",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )
        amoxicillin_order = ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=self.item,
            planned_quantity=Decimal("10000"),
            received_quantity=Decimal("0"),
            unit_price=Decimal("100"),
            is_cancelled=False,
        )
        second_item = Item.objects.create(
            kode_barang="ITM-TEST-0102",
            nama_barang="Alopurinol 100 mg",
            satuan=self.item.satuan,
            kategori=self.item.kategori,
            minimum_stock=Decimal("0"),
        )
        alopurinol_order = ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=second_item,
            planned_quantity=Decimal("20000"),
            received_quantity=Decimal("0"),
            unit_price=Decimal("0"),
            is_cancelled=False,
        )

        response = self.client.post(
            reverse("receiving:receiving_plan_receive", args=[receiving.pk]),
            {
                "items-TOTAL_FORMS": "2",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-order_item": str(amoxicillin_order.pk),
                "items-0-quantity": "5000",
                "items-0-batch_lot": "AHSGK",
                "items-0-expiry_date": "2030-11-30",
                "items-0-unit_price": "100.00",
                "items-0-location": str(self.location.pk),
                "items-1-order_item": str(alopurinol_order.pk),
                "items-1-quantity": "20000",
                "items-1-batch_lot": "DSAGJK",
                "items-1-expiry_date": "2030-12-02",
                "items-1-unit_price": "200.00",
                "items-1-location": str(self.location.pk),
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        receiving.refresh_from_db()
        amoxicillin_order.refresh_from_db()
        alopurinol_order.refresh_from_db()
        self.assertEqual(receiving.status, Receiving.Status.PARTIAL)
        self.assertEqual(amoxicillin_order.received_quantity, Decimal("5000"))
        self.assertEqual(alopurinol_order.received_quantity, Decimal("20000"))
        self.assertEqual(ReceivingItem.objects.filter(receiving=receiving).count(), 2)
        self.assertTrue(
            Stock.objects.filter(
                item=self.item,
                batch_lot="AHSGK",
                quantity=Decimal("5000"),
            ).exists()
        )
        self.assertTrue(
            Stock.objects.filter(
                item=second_item,
                batch_lot="DSAGJK",
                quantity=Decimal("20000"),
                unit_price=Decimal("200.00"),
            ).exists()
        )

    def test_plan_receive_rejects_stale_locked_overage(self):
        from apps.receiving import views as receiving_views

        receiving = Receiving.objects.create(
            document_number="RCV-2026-99991",
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

        original_helper = receiving_views._get_locked_planned_receiving_order_items

        def mutate_before_lock(order_item_ids):
            locked_order_items = original_helper(order_item_ids)
            locked_order_items[order_item.pk].received_quantity = Decimal("4")
            return locked_order_items

        with patch(
            "apps.receiving.views._get_locked_planned_receiving_order_items",
            side_effect=mutate_before_lock,
        ):
            response = self.client.post(
                reverse("receiving:receiving_plan_receive", args=[receiving.pk]),
                {
                    "items-TOTAL_FORMS": "1",
                    "items-INITIAL_FORMS": "0",
                    "items-MIN_NUM_FORMS": "0",
                    "items-MAX_NUM_FORMS": "1000",
                    "items-0-order_item": str(order_item.pk),
                    "items-0-quantity": "3",
                    "items-0-batch_lot": "BATCH-STALE",
                    "items-0-expiry_date": "2030-01-01",
                    "items-0-unit_price": "1000",
                    "items-0-location": str(self.location.pk),
                },
                secure=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Jumlah melebihi sisa pesanan.")
        order_item.refresh_from_db()
        receiving.refresh_from_db()
        self.assertEqual(order_item.received_quantity, Decimal("0"))
        self.assertEqual(receiving.status, Receiving.Status.APPROVED)
        self.assertEqual(ReceivingItem.objects.filter(receiving=receiving).count(), 0)
        self.assertEqual(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.RECEIVING,
                reference_id=receiving.pk,
            ).count(),
            0,
        )
        self.assertFalse(Stock.objects.filter(batch_lot="BATCH-STALE").exists())

    def test_plan_receive_invalid_post_rerenders_row_errors(self):
        receiving = Receiving.objects.create(
            document_number="RCV-2026-99989",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )
        oi = ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=self.item,
            planned_quantity=Decimal("5"),
            received_quantity=Decimal("0"),
            unit_price=Decimal("1000"),
            is_cancelled=False,
        )

        response = self.client.post(
            reverse("receiving:receiving_plan_receive", args=[receiving.pk]),
            {
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-order_item": str(oi.pk),
                "items-0-quantity": "3",
                "items-0-batch_lot": "BATCH-ERR",
                "items-0-expiry_date": "2030-01-01",
                "items-0-unit_price": "1000",
                "items-0-location": "",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lokasi wajib dipilih.")
        self.assertContains(response, 'value="3"', html=False)

    def test_receiving_order_item_form_rejects_zero_unit_price(self):
        form = ReceivingOrderItemForm(
            data={
                "item": self.item.pk,
                "planned_quantity": "5",
                "unit_price": "0",
                "notes": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["unit_price"],
            ["Harga satuan harus lebih dari 0."],
        )

    def test_receiving_order_item_form_rejects_infinite_unit_price(self):
        form = ReceivingOrderItemForm(
            data={
                "item": self.item.pk,
                "planned_quantity": "5",
                "unit_price": "Infinity",
                "notes": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["unit_price"],
            ["Masukkan sebuah bilangan."],
        )

    def test_gudang_cannot_approve_receiving_plan(self):
        receiving = Receiving.objects.create(
            document_number="RCV-2026-99995",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.SUBMITTED,
            is_planned=True,
            created_by=self.user,
        )
        gudang = User.objects.create_user(
            username="gudang_only_rcv",
            password="secret12345",
            role=User.Role.GUDANG,
        )
        ensure_default_module_access(gudang, overwrite=True)
        self.client.force_login(gudang)

        response = self.client.post(
            reverse("receiving:receiving_plan_approve", args=[receiving.pk])
        )
        self.assertEqual(response.status_code, 403)


class PlannedReceivingConcurrencyTest(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="admin_receiving_concurrency",
            password="secret12345",
        )
        unit = Unit.objects.create(code="TABC", name="Tablet Concurrency")
        category = Category.objects.create(code="OBATC", name="Obat C", sort_order=3)
        self.item = Item.objects.create(
            kode_barang="ITM-TEST-CONC-0001",
            nama_barang="Cefixime 200mg",
            satuan=unit,
            kategori=category,
            minimum_stock=Decimal("0"),
        )
        self.funding = FundingSource.objects.create(code="DAKC", name="DAK C")
        self.location = Location.objects.create(code="LOC-C1", name="Gudang Concurrency")

    def _build_payload(self, order_item):
        return {
            "items-TOTAL_FORMS": "1",
            "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0",
            "items-MAX_NUM_FORMS": "1000",
            "items-0-order_item": str(order_item.pk),
            "items-0-quantity": "5",
            "items-0-batch_lot": "BATCH-CONC",
            "items-0-expiry_date": "2030-01-01",
            "items-0-unit_price": "1000",
            "items-0-location": str(self.location.pk),
        }

    def _post_receipt(self, client, receiving_pk, order_item, results, key):
        try:
            response = client.post(
                reverse("receiving:receiving_plan_receive", args=[receiving_pk]),
                self._build_payload(order_item),
                secure=True,
            )
            results[key] = {
                "status_code": response.status_code,
                "body": response.content.decode("utf-8", errors="ignore"),
            }
        finally:
            connections.close_all()

    def test_plan_receive_concurrent_posts_do_not_over_receive(self):
        from apps.receiving import views as receiving_views

        receiving = Receiving.objects.create(
            document_number="RCV-2026-CONC-0001",
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

        barrier = threading.Barrier(2)
        original_helper = receiving_views._get_locked_planned_receiving_order_items

        def synchronized_lock(order_item_ids):
            barrier.wait(timeout=5)
            return original_helper(order_item_ids)

        client_one = Client()
        client_two = Client()
        client_one.force_login(self.user)
        client_two.force_login(self.user)
        results = {}

        with patch(
            "apps.receiving.views._get_locked_planned_receiving_order_items",
            side_effect=synchronized_lock,
        ):
            thread_one = threading.Thread(
                target=self._post_receipt,
                args=(client_one, receiving.pk, order_item, results, "one"),
            )
            thread_two = threading.Thread(
                target=self._post_receipt,
                args=(client_two, receiving.pk, order_item, results, "two"),
            )
            thread_one.start()
            thread_two.start()
            thread_one.join(timeout=10)
            thread_two.join(timeout=10)

        self.assertFalse(thread_one.is_alive())
        self.assertFalse(thread_two.is_alive())
        self.assertEqual(sorted(result["status_code"] for result in results.values()), [200, 302])
        self.assertTrue(
            any(
                "Jumlah melebihi sisa pesanan." in result["body"]
                for result in results.values()
                if result["status_code"] == 200
            )
        )

        order_item.refresh_from_db()
        receiving.refresh_from_db()
        self.assertEqual(order_item.received_quantity, Decimal("5"))
        self.assertEqual(receiving.status, Receiving.Status.RECEIVED)
        self.assertEqual(ReceivingItem.objects.filter(receiving=receiving).count(), 1)
        self.assertEqual(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.RECEIVING,
                reference_id=receiving.pk,
            ).count(),
            1,
        )
        stock = Stock.objects.get(batch_lot="BATCH-CONC")
        self.assertEqual(stock.quantity, Decimal("5"))


class ReceivingStockConcurrencyTest(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="admin_receiving_stock_concurrency",
            password="secret12345",
        )
        unit = Unit.objects.create(code="TABS", name="Tablet Stock")
        category = Category.objects.create(code="OBATS", name="Obat Stock", sort_order=4)
        self.item = Item.objects.create(
            kode_barang="ITM-TEST-STOCK-0001",
            nama_barang="Azithromycin 500mg",
            satuan=unit,
            kategori=category,
            minimum_stock=Decimal("0"),
        )
        self.funding = FundingSource.objects.create(code="APBDS", name="APBD Stock")
        self.location = Location.objects.create(code="LOC-S1", name="Gudang Stock Race")
        self.batch_lot = "BATCH-STOCK-RACE"
        self.expiry_date = "2030-01-01"

    @staticmethod
    def _csv_file(content):
        return SimpleUploadedFile(
            "receiving.csv",
            content.encode("utf-8"),
            content_type="text/csv",
        )

    def _regular_payload(self, document_number, quantity):
        return {
            "document_number": document_number,
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
            "items-0-quantity": str(quantity),
            "items-0-batch_lot": self.batch_lot,
            "items-0-expiry_date": self.expiry_date,
            "items-0-unit_price": "1500",
            "items-0-location": self.location.pk,
        }

    def _planned_payload(self, order_item, quantity):
        return {
            "items-TOTAL_FORMS": "1",
            "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0",
            "items-MAX_NUM_FORMS": "1000",
            "items-0-order_item": str(order_item.pk),
            "items-0-quantity": str(quantity),
            "items-0-batch_lot": self.batch_lot,
            "items-0-expiry_date": self.expiry_date,
            "items-0-unit_price": "1000",
            "items-0-location": str(self.location.pk),
        }

    def _csv_content(self, document_number, quantity):
        return (
            "document_number,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            f"{document_number},GRANT,12/03/2026,,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},{quantity},{self.batch_lot},01/01/2030,1000\n"
        )

    def _post_regular_receiving(self, client, payload, results, key):
        try:
            response = client.post(
                reverse("receiving:receiving_create"),
                payload,
                secure=True,
            )
            results[key] = {"status_code": response.status_code}
        except Exception as exc:
            results[key] = {"error": repr(exc)}
        finally:
            connections.close_all()

    def _post_planned_receiving(self, client, receiving_pk, payload, results, key):
        try:
            response = client.post(
                reverse("receiving:receiving_plan_receive", args=[receiving_pk]),
                payload,
                secure=True,
            )
            results[key] = {"status_code": response.status_code}
        except Exception as exc:
            results[key] = {"error": repr(exc)}
        finally:
            connections.close_all()

    def _run_csv_import(self, csv_content, results, key):
        admin = ReceivingAdmin(Receiving, AdminSite())
        try:
            counts = admin._process_csv(self._csv_file(csv_content), self.user)
            results[key] = {"counts": counts}
        except Exception as exc:
            results[key] = {"error": repr(exc)}
        finally:
            connections.close_all()

    def test_regular_receiving_concurrent_posts_accumulate_single_stock_row(self):
        from apps.receiving import models as receiving_models

        barrier = threading.Barrier(2)
        original_create = receiving_models._create_receiving_stock_row

        def synchronized_create(**kwargs):
            barrier.wait(timeout=5)
            return original_create(**kwargs)

        client_one = Client()
        client_two = Client()
        client_one.force_login(self.user)
        client_two.force_login(self.user)
        results = {}

        with patch(
            "apps.receiving.models._create_receiving_stock_row",
            side_effect=synchronized_create,
        ):
            thread_one = threading.Thread(
                target=self._post_regular_receiving,
                args=(
                    client_one,
                    self._regular_payload("RCV-2026-RACE-REG-1", Decimal("3")),
                    results,
                    "one",
                ),
            )
            thread_two = threading.Thread(
                target=self._post_regular_receiving,
                args=(
                    client_two,
                    self._regular_payload("RCV-2026-RACE-REG-2", Decimal("4")),
                    results,
                    "two",
                ),
            )
            thread_one.start()
            thread_two.start()
            thread_one.join(timeout=10)
            thread_two.join(timeout=10)

        self.assertFalse(thread_one.is_alive())
        self.assertFalse(thread_two.is_alive())
        self.assertNotIn("error", results.get("one", {}))
        self.assertNotIn("error", results.get("two", {}))
        self.assertEqual(
            sorted(result["status_code"] for result in results.values()),
            [302, 302],
        )
        stock = Stock.objects.get(
            item=self.item,
            location=self.location,
            batch_lot=self.batch_lot,
            sumber_dana=self.funding,
        )
        self.assertEqual(stock.quantity, Decimal("7"))
        self.assertEqual(
            Stock.objects.filter(
                item=self.item,
                location=self.location,
                batch_lot=self.batch_lot,
                sumber_dana=self.funding,
            ).count(),
            1,
        )
        self.assertEqual(Receiving.objects.count(), 2)
        self.assertEqual(ReceivingItem.objects.count(), 2)
        self.assertEqual(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.RECEIVING,
            ).count(),
            2,
        )

    def test_planned_receiving_concurrent_posts_accumulate_existing_stock(self):
        from apps.receiving import models as receiving_models

        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot=self.batch_lot,
            sumber_dana=self.funding,
            expiry_date=date(2030, 1, 1),
            quantity=Decimal("10"),
            unit_price=Decimal("800"),
        )
        receiving_one = Receiving.objects.create(
            document_number="RCV-2026-RACE-PLAN-1",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )
        receiving_two = Receiving.objects.create(
            document_number="RCV-2026-RACE-PLAN-2",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )
        order_item_one = ReceivingOrderItem.objects.create(
            receiving=receiving_one,
            item=self.item,
            planned_quantity=Decimal("3"),
            received_quantity=Decimal("0"),
            unit_price=Decimal("1000"),
            is_cancelled=False,
        )
        order_item_two = ReceivingOrderItem.objects.create(
            receiving=receiving_two,
            item=self.item,
            planned_quantity=Decimal("4"),
            received_quantity=Decimal("0"),
            unit_price=Decimal("1000"),
            is_cancelled=False,
        )

        barrier = threading.Barrier(2)

        def synchronized_increment(**kwargs):
            barrier.wait(timeout=5)
            return receiving_models.increment_receiving_stock(**kwargs)

        client_one = Client()
        client_two = Client()
        client_one.force_login(self.user)
        client_two.force_login(self.user)
        results = {}

        with patch(
            "apps.receiving.views.increment_receiving_stock",
            side_effect=synchronized_increment,
        ):
            thread_one = threading.Thread(
                target=self._post_planned_receiving,
                args=(
                    client_one,
                    receiving_one.pk,
                    self._planned_payload(order_item_one, Decimal("3")),
                    results,
                    "one",
                ),
            )
            thread_two = threading.Thread(
                target=self._post_planned_receiving,
                args=(
                    client_two,
                    receiving_two.pk,
                    self._planned_payload(order_item_two, Decimal("4")),
                    results,
                    "two",
                ),
            )
            thread_one.start()
            thread_two.start()
            thread_one.join(timeout=10)
            thread_two.join(timeout=10)

        self.assertFalse(thread_one.is_alive())
        self.assertFalse(thread_two.is_alive())
        self.assertNotIn("error", results.get("one", {}))
        self.assertNotIn("error", results.get("two", {}))
        self.assertEqual(
            sorted(result["status_code"] for result in results.values()),
            [302, 302],
        )
        stock = Stock.objects.get(
            item=self.item,
            location=self.location,
            batch_lot=self.batch_lot,
            sumber_dana=self.funding,
        )
        self.assertEqual(stock.quantity, Decimal("17"))
        order_item_one.refresh_from_db()
        order_item_two.refresh_from_db()
        self.assertEqual(order_item_one.received_quantity, Decimal("3"))
        self.assertEqual(order_item_two.received_quantity, Decimal("4"))
        self.assertEqual(ReceivingItem.objects.filter(batch_lot=self.batch_lot).count(), 2)
        self.assertEqual(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.RECEIVING,
                batch_lot=self.batch_lot,
            ).count(),
            2,
        )

    def test_csv_import_concurrent_runs_accumulate_single_stock_row(self):
        from apps.receiving import models as receiving_models

        barrier = threading.Barrier(2)
        original_create = receiving_models._create_receiving_stock_row

        def synchronized_create(**kwargs):
            barrier.wait(timeout=5)
            return original_create(**kwargs)

        results = {}

        with patch(
            "apps.receiving.models._create_receiving_stock_row",
            side_effect=synchronized_create,
        ):
            thread_one = threading.Thread(
                target=self._run_csv_import,
                args=(
                    self._csv_content("RCV-2026-RACE-CSV-1", Decimal("6")),
                    results,
                    "one",
                ),
            )
            thread_two = threading.Thread(
                target=self._run_csv_import,
                args=(
                    self._csv_content("RCV-2026-RACE-CSV-2", Decimal("8")),
                    results,
                    "two",
                ),
            )
            thread_one.start()
            thread_two.start()
            thread_one.join(timeout=10)
            thread_two.join(timeout=10)

        self.assertFalse(thread_one.is_alive())
        self.assertFalse(thread_two.is_alive())
        self.assertNotIn("error", results.get("one", {}))
        self.assertNotIn("error", results.get("two", {}))
        self.assertEqual(results["one"]["counts"]["stock"], 1)
        self.assertEqual(results["two"]["counts"]["stock"], 1)
        stock = Stock.objects.get(
            item=self.item,
            location=self.location,
            batch_lot=self.batch_lot,
            sumber_dana=self.funding,
        )
        self.assertEqual(stock.quantity, Decimal("14"))
        self.assertEqual(Receiving.objects.count(), 2)
        self.assertEqual(ReceivingItem.objects.count(), 2)
        self.assertEqual(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.RECEIVING,
                batch_lot=self.batch_lot,
            ).count(),
            2,
        )



class ReceivingDocumentUploadValidationTest(TestCase):
    def test_receiving_document_form_rejects_invalid_pdf_content(self):
        from apps.receiving.admin import ReceivingDocumentInlineForm

        form = ReceivingDocumentInlineForm(
            data={"file_name": "", "file_type": ""},
            files={
                "file": SimpleUploadedFile(
                    "dokumen.pdf",
                    b"not-a-pdf",
                    content_type="application/pdf",
                )
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)

    def test_receiving_document_form_sets_detected_metadata(self):
        from apps.receiving.admin import ReceivingDocumentInlineForm

        user = User.objects.create_superuser(
            username="doc-metadata-admin",
            password="secret12345",
        )
        funding = FundingSource.objects.create(code="DOCMETA", name="Doc Metadata")
        receiving = Receiving.objects.create(
            document_number="RCV-2026-DOCMETA",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=funding,
            status=Receiving.Status.DRAFT,
            created_by=user,
        )

        image_buffer = BytesIO()
        from PIL import Image

        Image.new("RGB", (10, 10), (255, 255, 255)).save(image_buffer, format="JPEG")
        image_buffer.seek(0)

        form = ReceivingDocumentInlineForm(
            data={
                "receiving": receiving.pk,
                "file_name": "manual name",
                "file_type": "manual/type",
            },
            files={
                "file": SimpleUploadedFile(
                    "dokumen.jpg",
                    image_buffer.read(),
                    content_type="image/jpeg",
                )
            },
        )

        self.assertTrue(form.is_valid(), form.errors)
        document = form.save(commit=False)
        self.assertEqual(document.file_name, "dokumen.jpg")
        self.assertEqual(document.file_type, "image/jpeg")

    def test_receiving_document_form_accepts_existing_file_without_revalidation(self):
        from apps.receiving.admin import ReceivingDocumentInlineForm

        user = User.objects.create_superuser(
            username="doc-existing-admin",
        )
        funding = FundingSource.objects.create(code="DOCEXIST", name="Doc Existing")
        receiving = Receiving.objects.create(
            document_number="RCV-2026-DOCEXIST",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=funding,
            status=Receiving.Status.DRAFT,
            created_by=user,
        )
        document = ReceivingDocument.objects.create(
            receiving=receiving,
            file="receiving/2026/06/dokumen.pdf",
            file_name="dokumen.pdf",
            file_type="application/pdf",
        )

        form = ReceivingDocumentInlineForm(
            data={
                "receiving": receiving.pk,
                "file_name": document.file_name,
                "file_type": document.file_type,
            },
            instance=document,
        )

        self.assertTrue(form.is_valid(), form.errors)
        saved_document = form.save(commit=False)
        self.assertEqual(saved_document.file_name, "dokumen.pdf")
        self.assertEqual(saved_document.file_type, "application/pdf")


class ReceivingDocumentAccessTest(TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[3] / "test_storage"
        self.media_dir = temp_root / "media"
        self.private_media_dir = temp_root / "private_media"
        shutil.rmtree(temp_root, ignore_errors=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.private_media_dir.mkdir(parents=True, exist_ok=True)
        self.settings_override = override_settings(
            ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"],
            MEDIA_ROOT=str(self.media_dir),
            PRIVATE_MEDIA_ROOT=str(self.private_media_dir),
            SECURE_SSL_REDIRECT=False,
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(lambda: shutil.rmtree(temp_root, ignore_errors=True))

        self.user = User.objects.create_superuser(
            username="receiving-doc-admin",
            password="secret12345",
        )
        self.client.force_login(self.user)
        self.funding = FundingSource.objects.create(code="DOCAUTH", name="Doc Auth")
        self.receiving = Receiving.objects.create(
            document_number="RCV-2026-DOCAUTH",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.VERIFIED,
            created_by=self.user,
            verified_by=self.user,
        )
        self.document = ReceivingDocument.objects.create(
            receiving=self.receiving,
            file=SimpleUploadedFile(
                "surat hibah.pdf",
                b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF",
                content_type="application/pdf",
            ),
            file_name="surat hibah.pdf",
            file_type="application/pdf",
        )

    def test_receiving_document_uses_private_storage_root(self):
        stored_path = Path(self.document.file.path)

        self.assertTrue(stored_path.exists())
        self.assertTrue(
            stored_path.is_relative_to(self.private_media_dir)
        )
        self.assertFalse(stored_path.is_relative_to(self.media_dir))

    def test_receiving_detail_shows_document_download_link(self):
        response = self.client.get(
            reverse("receiving:receiving_detail", args=[self.receiving.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lampiran Dokumen")
        self.assertContains(response, self.document.file_name)
        self.assertContains(
            response,
            reverse(
                "receiving:receiving_document_download",
                args=[self.receiving.pk, self.document.pk],
            ),
        )

    def test_receiving_document_download_requires_login(self):
        self.client.logout()

        response = self.client.get(
            reverse(
                "receiving:receiving_document_download",
                args=[self.receiving.pk, self.document.pk],
            )
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_receiving_document_download_requires_view_permission(self):
        restricted_user = User.objects.create_user(
            username="receiving-doc-puskesmas",
            password="secret12345",
            role=User.Role.PUSKESMAS,
        )
        self.client.force_login(restricted_user)

        response = self.client.get(
            reverse(
                "receiving:receiving_document_download",
                args=[self.receiving.pk, self.document.pk],
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_receiving_document_download_returns_attachment_and_logs(self):
        with self.assertLogs("security", level="INFO") as logs:
            response = self.client.get(
                reverse(
                    "receiving:receiving_document_download",
                    args=[self.receiving.pk, self.document.pk],
                )
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertIn('filename="surat hibah.pdf"', response["Content-Disposition"])
        self.assertEqual(
            b"".join(response.streaming_content),
            b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF",
        )
        self.assertTrue(
            any(
                "receiving_document_download_succeeded" in message
                for message in logs.output
            )
        )

