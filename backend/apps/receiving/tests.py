from datetime import date
from decimal import Decimal

from django.contrib.admin.sites import AdminSite
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.distribution.models import Distribution, DistributionItem
from apps.items.models import Category, Facility, FundingSource, Item, Location, Unit
from apps.receiving.admin import ReceivingAdmin
from apps.receiving.forms import PlannedReceivingForm, ReceivingForm, RsReturnReceivingForm
from apps.receiving.models import (
    Receiving,
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
        self.assertContains(response, '>Pengadaan</option>', html=False)
        self.assertContains(response, '>Hibah</option>', html=False)
        self.assertNotContains(response, '>Pengembalian RS</option>', html=False)

    def test_rs_return_create_page_shows_required_markers_and_placeholder(self):
        response = self.client.get(reverse("receiving:rs_return_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'placeholder="Kosongkan untuk generate otomatis"', html=False)
        self.assertContains(response, 'Receiving date <span class="text-danger">*</span>', html=False)
        self.assertContains(response, 'Facility <span class="text-danger">*</span>', html=False)
        self.assertContains(response, 'Sumber dana <span class="text-danger">*</span>', html=False)

    def test_rs_return_list_is_separated_from_regular_receiving_list(self):
        Receiving.objects.create(
            document_number="RCV-2026-99992",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 3, 15),
            sumber_dana=self.funding,
            status=Receiving.Status.VERIFIED,
            is_planned=False,
            created_by=self.user,
            verified_by=self.user,
        )
        rs_return = Receiving.objects.create(
            document_number="RCV-2026-99991",
            receiving_type=Receiving.ReceivingType.RETURN_RS,
            receiving_date=date(2026, 3, 15),
            facility=self.rs_facility,
            sumber_dana=self.funding,
            status=Receiving.Status.VERIFIED,
            is_planned=False,
            created_by=self.user,
            verified_by=self.user,
        )

        regular_response = self.client.get(reverse("receiving:receiving_list"))
        rs_response = self.client.get(reverse("receiving:rs_return_list"))

        self.assertEqual(regular_response.status_code, 200)
        self.assertEqual(rs_response.status_code, 200)
        self.assertNotContains(regular_response, rs_return.document_number)
        self.assertContains(rs_response, rs_return.document_number)

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
            planned_form.errors["supplier"],
            ["Supplier wajib diisi untuk tipe Pengadaan."],
        )

    def test_rs_return_receiving_requires_rs_facility(self):
        form = RsReturnReceivingForm(
            data={
                "document_number": "",
                "receiving_date": "2026-03-16",
                "facility": "",
                "sumber_dana": self.funding.pk,
                "notes": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["facility"], ["Rumah sakit asal wajib dipilih."])

    def test_rs_return_receiving_creates_settlement_link(self):
        distribution = Distribution.objects.create(
            distribution_type=Distribution.DistributionType.BORROW_RS,
            request_date=date(2026, 3, 10),
            facility=self.rs_facility,
            status=Distribution.Status.DISTRIBUTED,
            created_by=self.user,
            approved_by=self.user,
        )
        distribution_item = DistributionItem.objects.create(
            distribution=distribution,
            item=self.item,
            quantity_requested=Decimal("10"),
            quantity_approved=Decimal("10"),
            issued_batch_lot="BATCH-KELUAR-01",
            issued_expiry_date=date(2027, 1, 1),
            issued_unit_price=Decimal("1500"),
            issued_sumber_dana=self.funding,
        )

        response = self.client.post(
            reverse("receiving:rs_return_create"),
            {
                "document_number": "",
                "receiving_date": "2026-03-20",
                "facility": self.rs_facility.pk,
                "sumber_dana": self.funding.pk,
                "notes": "Pengembalian batch baru",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-item": self.item.pk,
                "items-0-settlement_distribution_item": distribution_item.pk,
                "items-0-quantity": "4",
                "items-0-batch_lot": "BATCH-MASUK-77",
                "items-0-expiry_date": "2030-01-01",
                "items-0-unit_price": "1600",
                "items-0-location": self.location.pk,
            },
        )

        self.assertEqual(response.status_code, 302)
        receiving = Receiving.objects.get(receiving_type=Receiving.ReceivingType.RETURN_RS)
        receiving_item = ReceivingItem.objects.get(receiving=receiving)
        self.assertEqual(receiving.facility, self.rs_facility)
        self.assertEqual(receiving_item.settlement_distribution_item, distribution_item)
        distribution_item.refresh_from_db()
        self.assertEqual(distribution_item.outstanding_quantity, Decimal("6"))

    def test_rs_return_create_page_shows_dedicated_settlement_column(self):
        response = self.client.get(reverse("receiving:rs_return_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dokumen RS Asal")
        self.assertContains(response, "Item Pengembalian RS")

    def test_rs_return_from_borrow_create_prefills_source_document(self):
        distribution = Distribution.objects.create(
            distribution_type=Distribution.DistributionType.BORROW_RS,
            request_date=date(2026, 3, 10),
            facility=self.rs_facility,
            status=Distribution.Status.DISTRIBUTED,
            created_by=self.user,
            approved_by=self.user,
        )
        DistributionItem.objects.create(
            distribution=distribution,
            item=self.item,
            quantity_requested=Decimal("10"),
            quantity_approved=Decimal("10"),
            issued_batch_lot="BATCH-KELUAR-01",
            issued_expiry_date=date(2027, 1, 1),
            issued_unit_price=Decimal("1500"),
            issued_sumber_dana=self.funding,
        )

        response = self.client.get(
            reverse("receiving:rs_return_from_borrow_create", args=[distribution.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Catat Pengembalian Pinjam RS")
        self.assertContains(response, distribution.document_number)
        self.assertContains(response, self.rs_facility.name)

    def test_rs_return_from_borrow_create_locks_item_price_and_funding_source(self):
        other_funding = FundingSource.objects.create(code="BLUD", name="BLUD")
        other_rs = Facility.objects.create(
            code="RS-02B",
            name="RSUD Cadangan",
            facility_type=Facility.FacilityType.RS,
        )
        distribution = Distribution.objects.create(
            distribution_type=Distribution.DistributionType.BORROW_RS,
            request_date=date(2026, 3, 10),
            facility=self.rs_facility,
            status=Distribution.Status.DISTRIBUTED,
            created_by=self.user,
            approved_by=self.user,
        )
        distribution_item = DistributionItem.objects.create(
            distribution=distribution,
            item=self.item,
            quantity_requested=Decimal("10"),
            quantity_approved=Decimal("10"),
            issued_batch_lot="BATCH-KELUAR-01",
            issued_expiry_date=date(2027, 1, 1),
            issued_unit_price=Decimal("1500"),
            issued_sumber_dana=self.funding,
        )

        response = self.client.post(
            reverse("receiving:rs_return_from_borrow_create", args=[distribution.pk]),
            {
                "document_number": "",
                "receiving_date": "2026-03-20",
                "facility": other_rs.pk,
                "sumber_dana": other_funding.pk,
                "notes": "Pengembalian batch baru",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-item": "",
                "items-0-settlement_distribution_item": "999999",
                "items-0-quantity": "4",
                "items-0-batch_lot": "BATCH-MASUK-77",
                "items-0-expiry_date": "2030-01-01",
                "items-0-unit_price": "9999",
                "items-0-location": self.location.pk,
            },
        )

        self.assertEqual(response.status_code, 302)
        receiving = Receiving.objects.get(receiving_type=Receiving.ReceivingType.RETURN_RS)
        receiving_item = ReceivingItem.objects.get(receiving=receiving)

        self.assertEqual(receiving.facility, self.rs_facility)
        self.assertEqual(receiving.sumber_dana, self.funding)
        self.assertEqual(receiving_item.item, self.item)
        self.assertEqual(receiving_item.settlement_distribution_item, distribution_item)
        self.assertEqual(receiving_item.unit_price, Decimal("1500"))

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
        self.assertContains(response, "Kuantitas Rencana")
        self.assertContains(response, "Kuantitas Diterima")
        self.assertContains(response, self.item.nama_barang)
        self.assertNotContains(response, self.item.kode_barang)
        self.assertContains(response, 'name="items-0-order_item"', html=False)
        self.assertContains(response, 'value="5.000,00"', html=False)
        self.assertContains(response, self.location.name)
        self.assertNotContains(response, self.location.code)
        self.assertNotContains(response, "Hapus")

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
        )

        self.assertEqual(response.status_code, 302)
        receiving.refresh_from_db()
        self.assertEqual(receiving.status, Receiving.Status.APPROVED)
        self.assertEqual(ReceivingItem.objects.filter(receiving=receiving).count(), 0)

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
