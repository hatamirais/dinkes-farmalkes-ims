from datetime import date
from decimal import Decimal

from django.contrib.messages import get_messages
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.items.models import Category, FundingSource, Item, Location, Supplier, Unit
from apps.procurement.forms import ProcurementContractForm
from apps.procurement.models import (
    ProcurementAmendment,
    ProcurementAmendmentLine,
    ProcurementContract,
    ProcurementContractLine,
)
from apps.procurement.services import approve_amendment, approve_contract
from apps.receiving.models import Receiving, ReceivingItem, ReceivingOrderItem
from apps.stock.models import Stock, Transaction
from apps.users.access import ensure_default_module_access
from apps.users.models import User


class ProcurementWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="proc-admin",
            password="secret12345",
        )
        cls.kepala = User.objects.create_user(
            username="proc-kepala",
            password="secret12345",
            role=User.Role.KEPALA,
        )
        cls.puskesmas = User.objects.create_user(
            username="proc-puskesmas",
            password="secret12345",
            role=User.Role.PUSKESMAS,
        )
        for user in [cls.kepala, cls.puskesmas]:
            ensure_default_module_access(user, overwrite=True)

        cls.unit = Unit.objects.create(code="TAB", name="Tablet")
        cls.category = Category.objects.create(
            code="PROC", name="Pengadaan", sort_order=1
        )
        cls.item = Item.objects.create(
            kode_barang="PROC-ITEM-001",
            nama_barang="Paracetamol 500mg",
            satuan=cls.unit,
            kategori=cls.category,
            minimum_stock=Decimal("0"),
        )
        cls.second_item = Item.objects.create(
            kode_barang="PROC-ITEM-002",
            nama_barang="Amoxicillin 500mg",
            satuan=cls.unit,
            kategori=cls.category,
            minimum_stock=Decimal("0"),
        )
        cls.funding = FundingSource.objects.create(code="DAK", name="DAK")
        cls.supplier = Supplier.objects.create(
            code="SUP-PROC", name="PT Supplier Procurement"
        )
        cls.location = Location.objects.create(code="G-01", name="Gudang Utama")

    def setUp(self):
        self.client.force_login(self.admin)

    def _create_contract(self, *, quantity="10", unit_price="5000"):
        contract = ProcurementContract.objects.create(
            document_number="",
            contract_date=date(2026, 7, 1),
            supplier=self.supplier,
            sumber_dana=self.funding,
            notes="Kontrak awal",
            created_by=self.admin,
        )
        line = ProcurementContractLine.objects.create(
            contract=contract,
            item=self.item,
            original_quantity=Decimal(quantity),
            original_unit_price=Decimal(unit_price),
            notes="Baris awal",
        )
        return contract, line

    def _approve_contract(self, *, quantity="10", unit_price="5000"):
        contract, line = self._create_contract(quantity=quantity, unit_price=unit_price)
        contract.status = ProcurementContract.Status.SUBMITTED
        contract.submitted_by = self.admin
        contract.submitted_at = timezone.now()
        contract.save(
            update_fields=["status", "submitted_by", "submitted_at", "updated_at"]
        )
        approve_contract(contract, self.kepala)
        contract.refresh_from_db()
        return contract, line

    def test_contract_form_rejects_null_byte(self):
        form = ProcurementContractForm(
            data={
                "document_number": "SPJ\x00BAD",
                "contract_date": "2026-07-01",
                "supplier": self.supplier.pk,
                "sumber_dana": self.funding.pk,
                "notes": "catatan",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("document_number", form.errors)

    def test_contract_approval_creates_linked_planned_receiving(self):
        contract, line = self._approve_contract(quantity="12", unit_price="7500")

        receiving = Receiving.objects.get(contract=contract)
        order_item = ReceivingOrderItem.objects.get(receiving=receiving)

        self.assertEqual(contract.status, ProcurementContract.Status.APPROVED)
        self.assertTrue(receiving.is_planned)
        self.assertEqual(receiving.receiving_type, Receiving.ReceivingType.PROCUREMENT)
        self.assertEqual(receiving.status, Receiving.Status.APPROVED)
        self.assertEqual(receiving.supplier, self.supplier)
        self.assertEqual(receiving.sumber_dana, self.funding)
        self.assertEqual(order_item.contract_line, line)
        self.assertEqual(order_item.item, self.item)
        self.assertEqual(order_item.planned_quantity, Decimal("12"))
        self.assertEqual(order_item.unit_price, Decimal("7500"))

    def test_amendment_approval_resyncs_open_receiving_plan(self):
        contract, line = self._approve_contract(quantity="10", unit_price="5000")
        amendment = ProcurementAmendment.objects.create(
            contract=contract,
            amendment_date=date(2026, 7, 3),
            notes="Amandemen qty dan harga",
            status=ProcurementAmendment.Status.SUBMITTED,
            created_by=self.admin,
            submitted_by=self.admin,
        )
        ProcurementAmendmentLine.objects.create(
            amendment=amendment,
            contract_line=line,
            revised_quantity=Decimal("15"),
            revised_unit_price=Decimal("6500"),
            notes="Naik qty",
        )

        approve_amendment(amendment, self.kepala)

        amendment.refresh_from_db()
        receiving = Receiving.objects.get(contract=contract)
        order_item = ReceivingOrderItem.objects.get(
            receiving=receiving,
            contract_line=line,
        )
        self.assertEqual(amendment.status, ProcurementAmendment.Status.APPROVED)
        self.assertEqual(order_item.planned_quantity, Decimal("15"))
        self.assertEqual(order_item.unit_price, Decimal("6500"))

    def test_amendment_below_already_received_quantity_is_rejected(self):
        contract, _line = self._approve_contract(quantity="10", unit_price="5000")
        receiving = Receiving.objects.get(contract=contract)
        order_item = ReceivingOrderItem.objects.get(receiving=receiving)

        response = self.client.post(
            reverse("receiving:receiving_plan_receive", args=[receiving.pk]),
            {
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-order_item": str(order_item.pk),
                "items-0-quantity": "6",
                "items-0-batch_lot": "PROC-BATCH-001",
                "items-0-expiry_date": "2030-01-01",
                "items-0-unit_price": "5000",
                "items-0-location": str(self.location.pk),
            },
            secure=True,
        )
        self.assertEqual(response.status_code, 302)

        amendment = ProcurementAmendment.objects.create(
            contract=contract,
            amendment_date=date(2026, 7, 4),
            notes="Turun di bawah realisasi",
            status=ProcurementAmendment.Status.SUBMITTED,
            created_by=self.admin,
            submitted_by=self.admin,
        )
        ProcurementAmendmentLine.objects.create(
            amendment=amendment,
            contract_line=order_item.contract_line,
            revised_quantity=Decimal("5"),
            revised_unit_price=Decimal("5000"),
        )

        with self.assertRaisesMessage(
            ValueError,
            "tidak boleh lebih kecil dari jumlah yang sudah diterima",
        ):
            approve_amendment(amendment, self.kepala)

    def test_contract_linked_plan_cannot_be_submitted_or_approved_manually(self):
        contract, _line = self._approve_contract(quantity="10", unit_price="5000")
        receiving = Receiving.objects.get(contract=contract)

        receiving.status = Receiving.Status.DRAFT
        receiving.save(update_fields=["status", "updated_at"])
        submit_response = self.client.post(
            reverse("receiving:receiving_plan_submit", args=[receiving.pk]),
            secure=True,
            follow=True,
        )
        self.assertEqual(submit_response.status_code, 200)
        receiving.refresh_from_db()
        self.assertEqual(receiving.status, Receiving.Status.DRAFT)
        submit_messages = [
            message.message for message in get_messages(submit_response.wsgi_request)
        ]
        self.assertTrue(
            any("melalui modul SPJ / Pengadaan" in message for message in submit_messages)
        )

        receiving.status = Receiving.Status.SUBMITTED
        receiving.save(update_fields=["status", "updated_at"])
        approve_response = self.client.post(
            reverse("receiving:receiving_plan_approve", args=[receiving.pk]),
            secure=True,
            follow=True,
        )
        self.assertEqual(approve_response.status_code, 200)
        receiving.refresh_from_db()
        self.assertEqual(receiving.status, Receiving.Status.SUBMITTED)
        approve_messages = [
            message.message for message in get_messages(approve_response.wsgi_request)
        ]
        self.assertTrue(
            any(
                "tidak memerlukan persetujuan terpisah" in message
                for message in approve_messages
            )
        )

    def test_legacy_manual_planned_receiving_still_receives_stock_and_transactions(self):
        receiving = Receiving.objects.create(
            document_number="RCV-2026-LEGACY-0001",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 7, 5),
            is_planned=True,
            supplier=self.supplier,
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            created_by=self.admin,
            approved_by=self.admin,
        )
        order_item = ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=self.second_item,
            planned_quantity=Decimal("4"),
            received_quantity=Decimal("0"),
            unit_price=Decimal("4200"),
        )

        response = self.client.post(
            reverse("receiving:receiving_plan_receive", args=[receiving.pk]),
            {
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-order_item": str(order_item.pk),
                "items-0-quantity": "4",
                "items-0-batch_lot": "LEGACY-BATCH-001",
                "items-0-expiry_date": "2031-01-01",
                "items-0-unit_price": "4200",
                "items-0-location": str(self.location.pk),
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        receiving.refresh_from_db()
        order_item.refresh_from_db()
        self.assertEqual(receiving.status, Receiving.Status.RECEIVED)
        self.assertEqual(order_item.received_quantity, Decimal("4"))
        self.assertEqual(ReceivingItem.objects.filter(receiving=receiving).count(), 1)
        stock = Stock.objects.get(item=self.second_item, batch_lot="LEGACY-BATCH-001")
        self.assertEqual(stock.quantity, Decimal("4"))
        self.assertEqual(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.RECEIVING,
                reference_id=receiving.pk,
                transaction_type=Transaction.TransactionType.IN,
            ).count(),
            1,
        )

    def test_procurement_view_permissions_context_flag_and_notifications(self):
        contract, line = self._create_contract(quantity="10", unit_price="5000")
        contract.status = ProcurementContract.Status.SUBMITTED
        contract.submitted_by = self.admin
        contract.save(update_fields=["status", "submitted_by", "updated_at"])
        amendment = ProcurementAmendment.objects.create(
            contract=contract,
            amendment_date=date(2026, 7, 6),
            notes="Menunggu persetujuan",
            status=ProcurementAmendment.Status.SUBMITTED,
            created_by=self.admin,
            submitted_by=self.admin,
        )
        ProcurementAmendmentLine.objects.create(
            amendment=amendment,
            contract_line=line,
            revised_quantity=Decimal("12"),
            revised_unit_price=Decimal("5200"),
        )

        self.client.force_login(self.kepala)
        response = self.client.get(reverse("procurement:contract_list"), secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["can_view_procurement"])
        self.assertContains(response, "SPJ / Pengadaan")
        self.assertEqual(response.context["nav_notification_count"], 2)
        self.assertTrue(
            any(
                item["label"] == "SPJ / Pengadaan"
                for item in response.context["nav_notification_items"]
            )
        )

        self.client.force_login(self.puskesmas)
        denied = self.client.get(reverse("procurement:contract_list"), secure=True)
        self.assertEqual(denied.status_code, 403)

    @override_settings(
        PROCUREMENT_MUTATION_RATE_LIMIT="1/m",
        RATELIMIT_USE_CACHE="locmem",
    )
    def test_procurement_create_is_rate_limited(self):
        payload = {
            "document_number": "",
            "contract_date": "2026-07-01",
            "supplier": str(self.supplier.pk),
            "sumber_dana": str(self.funding.pk),
            "notes": "Pengadaan 1",
            "lines-TOTAL_FORMS": "1",
            "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "0",
            "lines-MAX_NUM_FORMS": "1000",
            "lines-0-item": str(self.item.pk),
            "lines-0-original_quantity": "10",
            "lines-0-original_unit_price": "5000",
            "lines-0-notes": "Baris",
        }

        first = self.client.post(
            reverse("procurement:contract_create"),
            payload,
            secure=True,
        )
        second = self.client.post(
            reverse("procurement:contract_create"),
            payload,
            secure=True,
        )

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 429)

    def test_contract_detail_summary_shows_original_current_received_and_remaining(self):
        contract, _line = self._approve_contract(quantity="10", unit_price="5000")
        receiving = Receiving.objects.get(contract=contract)
        order_item = ReceivingOrderItem.objects.get(receiving=receiving)
        self.client.post(
            reverse("receiving:receiving_plan_receive", args=[receiving.pk]),
            {
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-order_item": str(order_item.pk),
                "items-0-quantity": "4",
                "items-0-batch_lot": "SUMMARY-BATCH-001",
                "items-0-expiry_date": "2030-01-01",
                "items-0-unit_price": "5000",
                "items-0-location": str(self.location.pk),
            },
            secure=True,
        )

        amendment = ProcurementAmendment.objects.create(
            contract=contract,
            amendment_date=date(2026, 7, 7),
            notes="Tambah qty",
            status=ProcurementAmendment.Status.SUBMITTED,
            created_by=self.admin,
            submitted_by=self.admin,
        )
        ProcurementAmendmentLine.objects.create(
            amendment=amendment,
            contract_line=order_item.contract_line,
            revised_quantity=Decimal("14"),
            revised_unit_price=Decimal("5500"),
        )
        approve_amendment(amendment, self.kepala)

        response = self.client.get(
            reverse("procurement:contract_detail", args=[contract.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        summary_rows = response.context["summary_rows"]
        self.assertEqual(len(summary_rows), 1)
        self.assertEqual(summary_rows[0]["original_quantity"], Decimal("10"))
        self.assertEqual(summary_rows[0]["current_quantity"], Decimal("14"))
        self.assertEqual(summary_rows[0]["received_quantity"], Decimal("4"))
        self.assertEqual(summary_rows[0]["remaining_quantity"], Decimal("10"))
