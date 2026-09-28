from datetime import date, timedelta
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps as django_apps
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import DocumentNumberIssue, DocumentNumberRule
from apps.items.models import Category, FundingSource, Item, Location, Supplier, Unit
from apps.procurement.forms import (
    ProcurementAmendmentForm,
    ProcurementAmendmentLineForm,
    ProcurementContractForm,
    ProcurementContractLineForm,
)
from apps.procurement.admin import (
    ProcurementAmendmentAdmin,
    ProcurementAmendmentLineInline,
    ProcurementContractAdmin,
    ProcurementContractLineInline,
)
from apps.procurement.models import (
    PROCUREMENT_CONTRACT_NUMBER_MAX_LENGTH,
    ProcurementAmendment,
    ProcurementAmendmentLine,
    ProcurementContract,
    ProcurementContractLine,
    ProcurementWorkflowError,
)
from apps.procurement.services import (
    approve_amendment,
    approve_contract,
    close_contract,
    contract_is_cancellable,
    submit_amendment,
    submit_contract,
)
from apps.receiving.models import Receiving, ReceivingItem, ReceivingOrderItem
from apps.stock.models import Stock, Transaction
from apps.users.access import ensure_default_module_access
from apps.users.models import ModuleAccess, User


class ProcurementWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        DocumentNumberRule.objects.get_or_create(
            key=DocumentNumberRule.Key.PROCUREMENT_CONTRACT,
            defaults={
                "label": "SPJ / Kontrak",
                "template": "SPJ-{year}-{seq}",
                "reset_period": DocumentNumberRule.ResetPeriod.YEARLY,
                "padding": 5,
            },
        )
        DocumentNumberRule.objects.get_or_create(
            key=DocumentNumberRule.Key.PROCUREMENT_AMENDMENT,
            defaults={
                "label": "Amandemen SPJ",
                "template": "SPJ/{year}/{month}/{seq}",
                "reset_period": DocumentNumberRule.ResetPeriod.MONTHLY,
                "padding": 1,
            },
        )
        DocumentNumberRule.objects.get_or_create(
            key=DocumentNumberRule.Key.RECEIVING,
            defaults={
                "label": "Penerimaan",
                "template": "RCV-{year}-{seq}",
                "reset_period": DocumentNumberRule.ResetPeriod.YEARLY,
                "padding": 5,
            },
        )
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
        cls.gudang = User.objects.create_user(
            username="proc-gudang",
            password="secret12345",
            role=User.Role.GUDANG,
        )
        for user in [cls.kepala, cls.puskesmas, cls.gudang]:
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

    def test_admin_forms_do_not_expose_workflow_managed_fields(self):
        request = RequestFactory().get("/admin/procurement/")
        request.user = self.admin

        contract_form = ProcurementContractAdmin(
            ProcurementContract,
            admin.site,
        ).get_form(request)
        amendment_form = ProcurementAmendmentAdmin(
            ProcurementAmendment,
            admin.site,
        ).get_form(request)

        for field_name in {
            "document_number",
            "status",
            "submitted_by",
            "submitted_at",
            "approved_by",
            "approved_at",
            "closed_by",
            "closed_at",
            "cancelled_by",
            "cancelled_at",
            "cancel_reason",
        }:
            self.assertNotIn(field_name, contract_form.base_fields)
        for field_name in {
            "document_number",
            "status",
            "submitted_by",
            "submitted_at",
            "approved_by",
            "approved_at",
        }:
            self.assertNotIn(field_name, amendment_form.base_fields)

    def test_admin_inlines_are_editable_only_while_parent_is_draft(self):
        request = RequestFactory().get("/admin/procurement/")
        request.user = self.admin
        contract, contract_line = self._create_contract()
        amendment = ProcurementAmendment.objects.create(
            contract=contract,
            amendment_date=date(2026, 7, 2),
            created_by=self.admin,
        )
        ProcurementAmendmentLine.objects.create(
            amendment=amendment,
            contract_line=contract_line,
            revised_quantity=Decimal("11"),
            revised_unit_price=Decimal("5000"),
        )
        contract_inline = ProcurementContractLineInline(
            ProcurementContract,
            admin.site,
        )
        amendment_inline = ProcurementAmendmentLineInline(
            ProcurementAmendment,
            admin.site,
        )

        self.assertTrue(contract_inline.has_change_permission(request, contract))
        self.assertTrue(amendment_inline.has_change_permission(request, amendment))

        contract.status = ProcurementContract.Status.SUBMITTED
        amendment.status = ProcurementAmendment.Status.SUBMITTED
        self.assertFalse(contract_inline.has_add_permission(request, contract))
        self.assertFalse(contract_inline.has_change_permission(request, contract))
        self.assertFalse(contract_inline.has_delete_permission(request, contract))
        self.assertFalse(amendment_inline.has_add_permission(request, amendment))
        self.assertFalse(amendment_inline.has_change_permission(request, amendment))
        self.assertFalse(amendment_inline.has_delete_permission(request, amendment))

    def test_repair_migration_restores_backfilled_void_metadata(self):
        cancelled_at = timezone.now()
        submitted_at = cancelled_at - timedelta(days=2)
        contract, _line = self._create_contract()
        contract.status = ProcurementContract.Status.CANCELLED
        contract.document_number = "SPJ-2026-00001"
        contract.submitted_by = self.kepala
        contract.submitted_at = submitted_at
        contract.cancelled_by = self.admin
        contract.cancelled_at = cancelled_at
        contract.cancel_reason = "Dibatalkan oleh pengelola"
        contract.save(
            update_fields=[
                "status",
                "document_number",
                "submitted_by",
                "submitted_at",
                "cancelled_by",
                "cancelled_at",
                "cancel_reason",
                "updated_at",
            ]
        )
        rule = DocumentNumberRule.objects.get(
            key=DocumentNumberRule.Key.PROCUREMENT_CONTRACT
        )
        issue = DocumentNumberIssue.objects.create(
            rule=rule,
            document_number=contract.document_number,
            sequence_value=1,
            period_key="2026",
            business_date=contract.contract_date,
            status=DocumentNumberIssue.Status.VOID,
            content_type=ContentType.objects.get_for_model(ProcurementContract),
            object_id=contract.pk,
            target_label=f"procurement.ProcurementContract #{contract.pk}",
            rule_label_snapshot=rule.label,
            template_snapshot=rule.template,
            reset_period_snapshot=rule.reset_period,
            padding_snapshot=rule.padding,
            issued_by=self.admin,
            void_reason="Dokumen sudah dibatalkan sebelum migrasi.",
        )
        receiving = Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            document_number="RCV-2026-00001",
            receiving_date=date(2026, 7, 1),
            supplier=self.supplier,
            sumber_dana=self.funding,
            status=Receiving.Status.CANCELLED,
            created_by=self.admin,
            verified_by=self.kepala,
            verified_at=submitted_at,
            cancelled_by=self.kepala,
            cancelled_at=cancelled_at,
            cancel_reason="Penerimaan dibatalkan",
        )
        receiving_rule = DocumentNumberRule.objects.get(
            key=DocumentNumberRule.Key.RECEIVING
        )
        receiving_issue = DocumentNumberIssue.objects.create(
            rule=receiving_rule,
            document_number=receiving.document_number,
            sequence_value=1,
            period_key="2026",
            business_date=receiving.receiving_date,
            status=DocumentNumberIssue.Status.VOID,
            content_type=ContentType.objects.get_for_model(Receiving),
            object_id=receiving.pk,
            target_label=f"receiving.Receiving #{receiving.pk}",
            rule_label_snapshot=receiving_rule.label,
            template_snapshot=receiving_rule.template,
            reset_period_snapshot=receiving_rule.reset_period,
            padding_snapshot=receiving_rule.padding,
            issued_by=self.admin,
            void_reason="Dokumen sudah dibatalkan sebelum migrasi.",
        )
        planned_receiving = Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            document_number="RCV-2026-00002",
            receiving_date=date(2026, 7, 1),
            is_planned=True,
            contract=contract,
            supplier=self.supplier,
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            created_by=self.admin,
            approved_by=self.admin,
            approved_at=submitted_at,
        )
        planned_issue = DocumentNumberIssue.objects.create(
            rule=receiving_rule,
            document_number=planned_receiving.document_number,
            sequence_value=2,
            period_key="2026",
            business_date=planned_receiving.receiving_date,
            content_type=ContentType.objects.get_for_model(Receiving),
            object_id=planned_receiving.pk,
            target_label=f"receiving.Receiving #{planned_receiving.pk}",
            rule_label_snapshot=receiving_rule.label,
            template_snapshot=receiving_rule.template,
            reset_period_snapshot=receiving_rule.reset_period,
            padding_snapshot=receiving_rule.padding,
            issued_by=self.kepala,
        )

        migration = import_module(
            "apps.core.migrations.0007_repair_backfilled_void_metadata"
        )
        migration.repair_backfilled_void_metadata(
            django_apps,
            SimpleNamespace(connection=connection),
        )
        issuance_migration = import_module(
            "apps.core.migrations.0008_document_number_issue_issued_at"
        )
        issuance_migration.repair_backfilled_issuance_metadata(
            django_apps,
            SimpleNamespace(connection=connection),
        )
        receiving_migration = import_module(
            "apps.core.migrations.0009_repair_receiving_issuance_metadata"
        )
        receiving_migration.repair_receiving_issuance_metadata(
            django_apps,
            SimpleNamespace(connection=connection),
        )

        issue.refresh_from_db()
        self.assertEqual(issue.issued_by, self.kepala)
        self.assertEqual(issue.issued_at, submitted_at)
        self.assertEqual(issue.voided_by, self.admin)
        self.assertEqual(issue.voided_at, cancelled_at)
        self.assertEqual(issue.void_reason, contract.cancel_reason)
        receiving_issue.refresh_from_db()
        self.assertEqual(receiving_issue.voided_by, self.kepala)
        self.assertEqual(receiving_issue.voided_at, cancelled_at)
        self.assertEqual(receiving_issue.void_reason, receiving.cancel_reason)
        self.assertEqual(receiving_issue.issued_by, self.kepala)
        self.assertEqual(receiving_issue.issued_at, submitted_at)
        planned_issue.refresh_from_db()
        self.assertEqual(planned_issue.issued_by, self.admin)
        self.assertEqual(planned_issue.issued_at, submitted_at)

    def _create_contract(
        self,
        *,
        quantity="10",
        unit_price="5000",
        external_document_number="",
    ):
        contract = ProcurementContract.objects.create(
            contract_date=date(2026, 7, 1),
            supplier=self.supplier,
            sumber_dana=self.funding,
            external_document_number=external_document_number,
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
        submit_contract(contract, self.admin)
        approve_contract(contract, self.kepala)
        contract.refresh_from_db()
        return contract, line

    def test_contract_form_does_not_expose_document_number(self):
        form = ProcurementContractForm(
            data={
                "document_number": "SPJ\x00BAD",
                "contract_date": "2026-07-01",
                "supplier": self.supplier.pk,
                "sumber_dana": self.funding.pk,
                "external_document_number": "  800/8766.a/KD.F  ",
                "notes": "catatan",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertNotIn("document_number", form.fields)
        self.assertNotIn("document_number", form.cleaned_data)
        self.assertEqual(
            form.cleaned_data["external_document_number"],
            "800/8766.a/KD.F",
        )

    def test_contract_form_ignores_manual_document_number_override(self):
        form = ProcurementContractForm(
            data={
                "document_number": "S" * (PROCUREMENT_CONTRACT_NUMBER_MAX_LENGTH + 1),
                "contract_date": "2026-07-01",
                "supplier": self.supplier.pk,
                "sumber_dana": self.funding.pk,
                "notes": "catatan",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        contract = form.save(commit=False)
        self.assertIsNone(contract.document_number)

    def test_contract_form_rejects_invalid_external_document_number(self):
        form = ProcurementContractForm(
            data={
                "contract_date": "2026-07-01",
                "supplier": self.supplier.pk,
                "sumber_dana": self.funding.pk,
                "external_document_number": "800/8766\x00/KD.F",
                "notes": "catatan",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("external_document_number", form.errors)

    def test_contract_model_validation_enforces_document_number_length(self):
        contract = ProcurementContract(
            document_number="S" * (PROCUREMENT_CONTRACT_NUMBER_MAX_LENGTH + 1),
            contract_date=date(2026, 7, 1),
            supplier=self.supplier,
            sumber_dana=self.funding,
            notes="Kontrak panjang",
            created_by=self.admin,
        )

        with self.assertRaisesMessage(
            ValidationError,
            f"Nomor dokumen tidak boleh lebih dari {PROCUREMENT_CONTRACT_NUMBER_MAX_LENGTH} karakter.",
        ):
            contract.full_clean()

    def test_contract_line_unit_price_accepts_indonesian_decimal_separator(self):
        form = ProcurementContractLineForm(
            data={
                "item": self.item.pk,
                "original_quantity": "10",
                "original_unit_price": "5000,50",
                "notes": "",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["original_unit_price"],
            Decimal("5000.50"),
        )

    def test_contract_line_unit_price_rejects_dot_decimal_separator(self):
        form = ProcurementContractLineForm(
            data={
                "item": self.item.pk,
                "original_quantity": "10",
                "original_unit_price": "5000.50",
                "notes": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["original_unit_price"],
            ["Gunakan angka tanpa pemisah ribuan. Gunakan koma untuk desimal."],
        )

    def test_contract_line_unit_price_preserves_allowed_high_precision(self):
        form = ProcurementContractLineForm(
            data={
                "item": self.item.pk,
                "original_quantity": "10",
                "original_unit_price": "5000,1234567890",
                "notes": "",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["original_unit_price"],
            Decimal("5000.1234567890"),
        )

    def test_contract_line_unit_price_rejects_more_than_ten_decimals(self):
        form = ProcurementContractLineForm(
            data={
                "item": self.item.pk,
                "original_quantity": "10",
                "original_unit_price": "5000,12345678901",
                "notes": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("original_unit_price", form.errors)

    def test_amendment_line_unit_price_accepts_indonesian_decimal_separator(self):
        contract, line = self._approve_contract()
        form = ProcurementAmendmentLineForm(
            data={
                "contract_line": line.pk,
                "revised_quantity": "11",
                "revised_unit_price": "5100,50",
                "notes": "",
            },
            contract=contract,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["revised_unit_price"],
            Decimal("5100.50"),
        )

    def test_amendment_line_unit_price_rejects_dot_decimal_separator(self):
        contract, line = self._approve_contract()
        form = ProcurementAmendmentLineForm(
            data={
                "contract_line": line.pk,
                "revised_quantity": "11",
                "revised_unit_price": "5100.50",
                "notes": "",
            },
            contract=contract,
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["revised_unit_price"],
            ["Gunakan angka tanpa pemisah ribuan. Gunakan koma untuk desimal."],
        )

    def test_contract_approval_creates_linked_planned_receiving(self):
        precise_price = Decimal("7500.1234567890")
        contract, line = self._approve_contract(quantity="12", unit_price=str(precise_price))

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
        self.assertEqual(order_item.unit_price, precise_price)

    def test_contract_approval_uses_plan_creation_date_not_contract_date(self):
        contract, _line = self._create_contract(quantity="12", unit_price="7500")
        contract.status = ProcurementContract.Status.SUBMITTED
        contract.submitted_by = self.admin
        contract.submitted_at = timezone.now()
        contract.save(
            update_fields=["status", "submitted_by", "submitted_at", "updated_at"]
        )

        with patch("apps.procurement.services.timezone.localdate", return_value=date(2026, 7, 2)):
            approve_contract(contract, self.kepala)

        receiving = Receiving.objects.get(contract=contract)
        self.assertEqual(receiving.receiving_date, date(2026, 7, 2))
        self.assertNotEqual(receiving.receiving_date, contract.contract_date)

    def test_amendment_approval_resyncs_open_receiving_plan(self):
        contract, line = self._approve_contract(quantity="10", unit_price="5000")
        precise_price = Decimal("6500.1234567890")
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
            revised_unit_price=precise_price,
            notes="Naik qty",
        )

        original_receiving_date = Receiving.objects.get(contract=contract).receiving_date

        approve_amendment(amendment, self.kepala)

        amendment.refresh_from_db()
        receiving = Receiving.objects.get(contract=contract)
        order_item = ReceivingOrderItem.objects.get(
            receiving=receiving,
            contract_line=line,
        )
        self.assertEqual(amendment.status, ProcurementAmendment.Status.APPROVED)
        self.assertEqual(receiving.receiving_date, original_receiving_date)
        self.assertEqual(order_item.planned_quantity, Decimal("15"))
        self.assertEqual(order_item.unit_price, precise_price)

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

    def test_draft_contract_can_be_cancelled_with_reason(self):
        contract, _line = self._create_contract(quantity="10", unit_price="5000")

        response = self.client.post(
            reverse("procurement:contract_cancel", args=[contract.pk]),
            {"cancel_reason": "Duplikat input"},
            secure=True,
        )

        self.assertRedirects(
            response,
            reverse("procurement:contract_detail", args=[contract.pk]),
            fetch_redirect_response=False,
        )
        contract.refresh_from_db()
        self.assertEqual(contract.status, ProcurementContract.Status.CANCELLED)
        self.assertEqual(contract.cancel_reason, "Duplikat input")
        self.assertEqual(contract.cancelled_by, self.admin)
        self.assertIsNotNone(contract.cancelled_at)

    def test_contract_detail_shows_cancel_action_when_cancellable(self):
        contract, _line = self._create_contract(quantity="10", unit_price="5000")

        response = self.client.get(
            reverse("procurement:contract_detail", args=[contract.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Batalkan SPJ")
        self.assertContains(response, reverse("procurement:contract_cancel", args=[contract.pk]))

    def test_approved_contract_detail_shows_cancel_action_when_linked_plan_unused(self):
        contract, _line = self._approve_contract(quantity="10", unit_price="5000")

        response = self.client.get(
            reverse("procurement:contract_detail", args=[contract.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Batalkan SPJ")
        self.assertContains(
            response,
            reverse("procurement:contract_cancel", args=[contract.pk]),
        )

    def test_approved_contract_detail_hides_cancel_action_when_plan_received(self):
        contract, _line = self._approve_contract(quantity="10", unit_price="5000")
        receiving = Receiving.objects.get(contract=contract)
        order_item = ReceivingOrderItem.objects.get(receiving=receiving)
        order_item.received_quantity = Decimal("10")
        order_item.save(update_fields=["received_quantity", "updated_at"])
        receiving.status = Receiving.Status.RECEIVED
        receiving.save(update_fields=["status", "updated_at"])

        response = self.client.get(
            reverse("procurement:contract_detail", args=[contract.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Batalkan SPJ")
        self.assertNotContains(
            response,
            reverse("procurement:contract_cancel", args=[contract.pk]),
        )

    def test_approved_contract_detail_hides_cancel_action_with_receipt_rows(self):
        contract, _line = self._approve_contract(quantity="10", unit_price="5000")
        receiving = Receiving.objects.get(contract=contract)
        order_item = ReceivingOrderItem.objects.get(receiving=receiving)
        ReceivingItem.objects.create(
            receiving=receiving,
            order_item=order_item,
            item=self.item,
            quantity=Decimal("1"),
            batch_lot="PROC-CANCEL-UI-ROW",
            expiry_date=date(2030, 1, 1),
            unit_price=Decimal("5000"),
            location=self.location,
        )

        response = self.client.get(
            reverse("procurement:contract_detail", args=[contract.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Batalkan SPJ")
        self.assertNotContains(
            response,
            reverse("procurement:contract_cancel", args=[contract.pk]),
        )

    def test_submitted_contract_can_be_cancelled_with_reason(self):
        contract, _line = self._create_contract(quantity="10", unit_price="5000")
        contract.status = ProcurementContract.Status.SUBMITTED
        contract.submitted_by = self.admin
        contract.submitted_at = timezone.now()
        contract.save(update_fields=["status", "submitted_by", "submitted_at", "updated_at"])

        response = self.client.post(
            reverse("procurement:contract_cancel", args=[contract.pk]),
            {"cancel_reason": "Pengadaan dibatalkan"},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        contract.refresh_from_db()
        self.assertEqual(contract.status, ProcurementContract.Status.CANCELLED)
        self.assertEqual(contract.cancel_reason, "Pengadaan dibatalkan")

    def test_approved_contract_with_unused_plan_cancels_linked_receiving(self):
        contract, _line = self._approve_contract(quantity="10", unit_price="5000")
        receiving = Receiving.objects.get(contract=contract)

        response = self.client.post(
            reverse("procurement:contract_cancel", args=[contract.pk]),
            {"cancel_reason": "Supplier gagal memenuhi kontrak"},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        contract.refresh_from_db()
        receiving.refresh_from_db()
        self.assertEqual(contract.status, ProcurementContract.Status.CANCELLED)
        self.assertEqual(receiving.status, Receiving.Status.CANCELLED)
        self.assertEqual(receiving.cancel_reason, "Supplier gagal memenuhi kontrak")
        self.assertEqual(receiving.cancelled_by, self.admin)

    def test_cancelled_approved_contract_plan_detail_shows_cancellation_metadata(self):
        contract, _line = self._approve_contract(quantity="10", unit_price="5000")
        self.client.post(
            reverse("procurement:contract_cancel", args=[contract.pk]),
            {"cancel_reason": "Supplier gagal memenuhi kontrak"},
            secure=True,
        )
        receiving = Receiving.objects.get(contract=contract)

        response = self.client.get(
            reverse("receiving:receiving_plan_detail", args=[receiving.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dibatalkan")
        self.assertContains(response, self.admin.username)
        self.assertContains(response, "Alasan Batal")
        self.assertContains(response, "Supplier gagal memenuhi kontrak")

    def test_approved_contract_with_received_quantity_cannot_be_cancelled(self):
        contract, _line = self._approve_contract(quantity="10", unit_price="5000")
        receiving = Receiving.objects.get(contract=contract)
        order_item = ReceivingOrderItem.objects.get(receiving=receiving)
        order_item.received_quantity = Decimal("1")
        order_item.save(update_fields=["received_quantity", "updated_at"])

        response = self.client.post(
            reverse("procurement:contract_cancel", args=[contract.pk]),
            {"cancel_reason": "Batal setelah realisasi"},
            secure=True,
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        contract.refresh_from_db()
        receiving.refresh_from_db()
        self.assertEqual(contract.status, ProcurementContract.Status.APPROVED)
        self.assertEqual(receiving.status, Receiving.Status.APPROVED)
        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("sudah memiliki realisasi penerimaan" in message for message in messages))

    def test_approved_contract_with_received_plan_status_cannot_be_cancelled(self):
        contract, _line = self._approve_contract(quantity="10", unit_price="5000")
        receiving = Receiving.objects.get(contract=contract)
        receiving.status = Receiving.Status.RECEIVED
        receiving.save(update_fields=["status", "updated_at"])

        self.assertFalse(contract_is_cancellable(contract, receiving))

        response = self.client.post(
            reverse("procurement:contract_cancel", args=[contract.pk]),
            {"cancel_reason": "Batal setelah rencana selesai"},
            secure=True,
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        contract.refresh_from_db()
        receiving.refresh_from_db()
        self.assertEqual(contract.status, ProcurementContract.Status.APPROVED)
        self.assertEqual(receiving.status, Receiving.Status.RECEIVED)
        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertTrue(
            any("sudah memiliki realisasi penerimaan" in message for message in messages)
        )

    def test_approved_contract_with_receipt_rows_cannot_be_cancelled(self):
        contract, _line = self._approve_contract(quantity="10", unit_price="5000")
        receiving = Receiving.objects.get(contract=contract)
        order_item = ReceivingOrderItem.objects.get(receiving=receiving)
        ReceivingItem.objects.create(
            receiving=receiving,
            order_item=order_item,
            item=self.item,
            quantity=Decimal("1"),
            batch_lot="PROC-CANCEL-ROW",
            expiry_date=date(2030, 1, 1),
            unit_price=Decimal("5000"),
            location=self.location,
        )

        response = self.client.post(
            reverse("procurement:contract_cancel", args=[contract.pk]),
            {"cancel_reason": "Batal setelah baris realisasi"},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        contract.refresh_from_db()
        receiving.refresh_from_db()
        self.assertEqual(contract.status, ProcurementContract.Status.APPROVED)
        self.assertEqual(receiving.status, Receiving.Status.APPROVED)

    def test_contract_cancel_requires_post_and_procurement_access(self):
        contract, _line = self._create_contract(quantity="10", unit_price="5000")

        get_response = self.client.get(
            reverse("procurement:contract_cancel", args=[contract.pk]),
            secure=True,
        )
        self.assertEqual(get_response.status_code, 405)

        self.client.force_login(self.puskesmas)
        denied = self.client.post(
            reverse("procurement:contract_cancel", args=[contract.pk]),
            {"cancel_reason": "Tidak berwenang"},
            secure=True,
        )
        self.assertEqual(denied.status_code, 403)

    def test_contract_cancel_honors_direct_django_change_permission(self):
        contract, _line = self._create_contract(quantity="10", unit_price="5000")
        permission_user = User.objects.create_user(
            username="proc-direct-permission",
            password="secret12345",
            role=User.Role.AUDITOR,
        )
        ModuleAccess.objects.update_or_create(
            user=permission_user,
            module=ModuleAccess.Module.PROCUREMENT,
            defaults={"scope": ModuleAccess.Scope.VIEW},
        )
        permission_user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="procurement",
                codename="view_procurementcontract",
            ),
            Permission.objects.get(
                content_type__app_label="procurement",
                codename="change_procurementcontract",
            ),
        )

        self.client.force_login(permission_user)
        detail_response = self.client.get(
            reverse("procurement:contract_detail", args=[contract.pk]),
            secure=True,
        )

        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "Batalkan SPJ")
        self.assertContains(
            detail_response,
            reverse("procurement:contract_cancel", args=[contract.pk]),
        )

        cancel_response = self.client.post(
            reverse("procurement:contract_cancel", args=[contract.pk]),
            {"cancel_reason": "Dibatalkan oleh pemegang izin Django"},
            secure=True,
        )

        self.assertRedirects(
            cancel_response,
            reverse("procurement:contract_detail", args=[contract.pk]),
            fetch_redirect_response=False,
        )
        contract.refresh_from_db()
        self.assertEqual(contract.status, ProcurementContract.Status.CANCELLED)
        self.assertEqual(
            contract.cancel_reason,
            "Dibatalkan oleh pemegang izin Django",
        )
        self.assertEqual(contract.cancelled_by, permission_user)

    def test_cancelled_contract_cannot_be_mutated_through_other_actions(self):
        contract, _line = self._create_contract(quantity="10", unit_price="5000")
        self.client.post(
            reverse("procurement:contract_cancel", args=[contract.pk]),
            {"cancel_reason": "Batal permanen"},
            secure=True,
        )
        contract.refresh_from_db()
        self.assertEqual(contract.status, ProcurementContract.Status.CANCELLED)

        edit_response = self.client.get(
            reverse("procurement:contract_edit", args=[contract.pk]),
            secure=True,
        )
        submit_response = self.client.post(
            reverse("procurement:contract_submit", args=[contract.pk]),
            secure=True,
        )
        approve_response = self.client.post(
            reverse("procurement:contract_approve", args=[contract.pk]),
            secure=True,
        )
        amend_response = self.client.get(
            reverse("procurement:amendment_create", args=[contract.pk]),
            secure=True,
        )
        close_response = self.client.post(
            reverse("procurement:contract_close", args=[contract.pk]),
            secure=True,
        )

        self.assertEqual(edit_response.status_code, 302)
        self.assertEqual(submit_response.status_code, 302)
        self.assertEqual(approve_response.status_code, 302)
        self.assertEqual(amend_response.status_code, 302)
        self.assertEqual(close_response.status_code, 302)
        contract.refresh_from_db()
        self.assertEqual(contract.status, ProcurementContract.Status.CANCELLED)

    def test_stale_submit_cannot_resurrect_cancelled_contract(self):
        contract, _line = self._create_contract(quantity="10", unit_price="5000")
        ProcurementContract.objects.filter(pk=contract.pk).update(
            status=ProcurementContract.Status.CANCELLED,
            cancelled_by=self.admin,
            cancelled_at=timezone.now(),
            cancel_reason="Dibatalkan request lain",
        )

        with self.assertRaisesMessage(
            ProcurementWorkflowError,
            "Hanya kontrak Draft yang dapat diajukan.",
        ):
            submit_contract(contract, self.admin)

        contract.refresh_from_db()
        self.assertEqual(contract.status, ProcurementContract.Status.CANCELLED)
        self.assertEqual(Receiving.objects.filter(contract=contract).count(), 0)

    def test_stale_approve_cannot_resurrect_cancelled_contract(self):
        contract, _line = self._create_contract(quantity="10", unit_price="5000")
        contract.status = ProcurementContract.Status.SUBMITTED
        contract.submitted_by = self.admin
        contract.submitted_at = timezone.now()
        contract.save(update_fields=["status", "submitted_by", "submitted_at", "updated_at"])
        ProcurementContract.objects.filter(pk=contract.pk).update(
            status=ProcurementContract.Status.CANCELLED,
            cancelled_by=self.admin,
            cancelled_at=timezone.now(),
            cancel_reason="Dibatalkan request lain",
        )

        with self.assertRaisesMessage(
            ProcurementWorkflowError,
            "Hanya kontrak Diajukan yang dapat disetujui.",
        ):
            approve_contract(contract, self.kepala)

        contract.refresh_from_db()
        self.assertEqual(contract.status, ProcurementContract.Status.CANCELLED)
        self.assertEqual(Receiving.objects.filter(contract=contract).count(), 0)

    def test_stale_close_cannot_mutate_cancelled_contract(self):
        contract, _line = self._approve_contract(quantity="10", unit_price="5000")
        ProcurementContract.objects.filter(pk=contract.pk).update(
            status=ProcurementContract.Status.CANCELLED,
            cancelled_by=self.admin,
            cancelled_at=timezone.now(),
            cancel_reason="Dibatalkan request lain",
        )

        with self.assertRaisesMessage(
            ProcurementWorkflowError,
            "Hanya kontrak Disetujui yang dapat ditutup.",
        ):
            close_contract(contract, self.admin)

        contract.refresh_from_db()
        receiving = Receiving.objects.get(contract=contract)
        self.assertEqual(contract.status, ProcurementContract.Status.CANCELLED)
        self.assertEqual(receiving.status, Receiving.Status.APPROVED)

    def test_stale_contract_edit_cannot_resurrect_cancelled_contract(self):
        contract, line = self._create_contract(quantity="10", unit_price="5000")
        original_is_valid = ProcurementContractForm.is_valid

        def cancel_during_validation(form):
            ProcurementContract.objects.filter(pk=contract.pk).update(
                status=ProcurementContract.Status.CANCELLED,
                cancelled_by=self.admin,
                cancelled_at=timezone.now(),
                cancel_reason="Dibatalkan request lain",
            )
            return original_is_valid(form)

        with patch.object(
            ProcurementContractForm,
            "is_valid",
            autospec=True,
            side_effect=cancel_during_validation,
        ):
            response = self.client.post(
                reverse("procurement:contract_edit", args=[contract.pk]),
                {
                    "contract_date": "2026-07-01",
                    "supplier": str(self.supplier.pk),
                    "sumber_dana": str(self.funding.pk),
                    "notes": "Edit setelah batal",
                    "lines-TOTAL_FORMS": "1",
                    "lines-INITIAL_FORMS": "1",
                    "lines-MIN_NUM_FORMS": "0",
                    "lines-MAX_NUM_FORMS": "1000",
                    "lines-0-id": str(line.pk),
                    "lines-0-item": str(self.item.pk),
                    "lines-0-original_quantity": "12",
                    "lines-0-original_unit_price": "6000",
                    "lines-0-notes": "Baris stale",
                },
                secure=True,
            )

        self.assertEqual(response.status_code, 302)
        contract.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual(contract.status, ProcurementContract.Status.CANCELLED)
        self.assertEqual(contract.cancel_reason, "Dibatalkan request lain")
        self.assertEqual(contract.notes, "Kontrak awal")
        self.assertEqual(line.original_quantity, Decimal("10.00"))
        self.assertEqual(line.original_unit_price, Decimal("5000.0000000000"))

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

    def test_gudang_cannot_approve_submitted_amendment_even_with_approve_scope(self):
        contract, line = self._approve_contract(quantity="10", unit_price="5000")
        amendment = ProcurementAmendment.objects.create(
            contract=contract,
            amendment_date=date(2026, 7, 6),
            notes="Menunggu persetujuan",
            status=ProcurementAmendment.Status.SUBMITTED,
            created_by=self.gudang,
            submitted_by=self.gudang,
        )
        ProcurementAmendmentLine.objects.create(
            amendment=amendment,
            contract_line=line,
            revised_quantity=Decimal("8"),
            revised_unit_price=Decimal("5000"),
        )
        ModuleAccess.objects.update_or_create(
            user=self.gudang,
            module=ModuleAccess.Module.PROCUREMENT,
            defaults={"scope": ModuleAccess.Scope.APPROVE},
        )

        self.client.force_login(self.gudang)
        detail_response = self.client.get(
            reverse("procurement:amendment_detail", args=[amendment.pk]),
            secure=True,
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "Diajukan")
        self.assertNotContains(detail_response, "Setujui")
        self.assertNotContains(
            detail_response,
            reverse("procurement:amendment_approve", args=[amendment.pk]),
        )

        approve_response = self.client.post(
            reverse("procurement:amendment_approve", args=[amendment.pk]),
            secure=True,
        )

        self.assertEqual(approve_response.status_code, 403)
        amendment.refresh_from_db()
        self.assertEqual(amendment.status, ProcurementAmendment.Status.SUBMITTED)

    def test_kepala_can_see_submitted_amendment_approval_action(self):
        contract, line = self._approve_contract(quantity="10", unit_price="5000")
        amendment = ProcurementAmendment.objects.create(
            contract=contract,
            amendment_date=date(2026, 7, 6),
            notes="Menunggu persetujuan",
            status=ProcurementAmendment.Status.SUBMITTED,
            created_by=self.gudang,
            submitted_by=self.gudang,
        )
        ProcurementAmendmentLine.objects.create(
            amendment=amendment,
            contract_line=line,
            revised_quantity=Decimal("8"),
            revised_unit_price=Decimal("5000"),
        )

        self.client.force_login(self.kepala)
        response = self.client.get(
            reverse("procurement:amendment_detail", args=[amendment.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Setujui")
        self.assertContains(
            response,
            reverse("procurement:amendment_approve", args=[amendment.pk]),
        )

    def test_contract_create_page_renders_quick_create_hooks(self):
        response = self.client.get(reverse("procurement:contract_create"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="contract_date"', html=False)
        self.assertContains(response, 'placeholder="DD/MM/YYYY"', html=False)
        self.assertContains(response, 'data-native-date-picker="true"', html=False)
        self.assertContains(response, 'class="form-control js-date-mask"', html=False)
        self.assertNotContains(response, 'name="contract_date" type="date"', html=False)
        self.assertContains(response, 'id="modal-supplier"')
        self.assertContains(
            response,
            reverse("procurement:quick_create_supplier"),
        )
        self.assertContains(response, 'id="modal-sumber_dana"')
        self.assertContains(
            response,
            reverse("procurement:quick_create_funding_source"),
        )
        self.assertContains(response, 'class="card content-card table-container form-page-card"', html=False)
        self.assertContains(response, 'data-formset="procurement-lines"')
        self.assertContains(response, 'style="table-layout: fixed; min-width: 960px;"', html=False)
        self.assertContains(response, '<col style="width: 52%;">', html=False)
        self.assertContains(response, 'class="btn btn-outline-primary btn-sm formset-add"', html=False)
        self.assertContains(response, 'class="btn btn-outline-danger btn-sm formset-remove"', html=False)
        self.assertContains(response, 'id="procurement-lines-empty"')
        self.assertContains(response, "Nomor Dokumen Eksternal")
        self.assertContains(response, 'name="external_document_number"', html=False)
        self.assertContains(response, "800/8766.a/KD.F")
        content = response.content.decode()
        self.assertLess(
            content.index('id="id_sumber_dana"'),
            content.index('id="id_external_document_number"'),
        )
        self.assertLess(
            content.index('id="id_external_document_number"'),
            content.index('id="id_notes"'),
        )

    def test_external_document_number_is_visible_and_searchable(self):
        contract, _line = self._create_contract(
            external_document_number="800/8766.a/KD.F"
        )

        detail_response = self.client.get(
            reverse("procurement:contract_detail", args=[contract.pk]),
            secure=True,
        )
        list_response = self.client.get(
            reverse("procurement:contract_list"),
            {"q": "8766.a"},
            secure=True,
        )

        self.assertContains(detail_response, "Nomor Dokumen Eksternal")
        self.assertContains(detail_response, "800/8766.a/KD.F")
        self.assertContains(list_response, "800/8766.a/KD.F")
        self.assertContains(
            list_response,
            reverse("procurement:contract_detail", args=[contract.pk]),
        )

    def test_contract_form_accepts_indonesian_date_input(self):
        form = ProcurementContractForm(
            data={
                "document_number": "",
                "contract_date": "01/07/2026",
                "supplier": self.supplier.pk,
                "sumber_dana": self.funding.pk,
                "notes": "",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["contract_date"], date(2026, 7, 1))

    def test_amendment_form_accepts_indonesian_date_input(self):
        form = ProcurementAmendmentForm(
            data={
                "amendment_date": "08/07/2026",
                "notes": "",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["amendment_date"], date(2026, 7, 8))

    def test_contract_create_accepts_multiple_lines(self):
        response = self.client.post(
            reverse("procurement:contract_create"),
            {
                "document_number": "",
                "contract_date": "2026-07-01",
                "supplier": str(self.supplier.pk),
                "sumber_dana": str(self.funding.pk),
                "external_document_number": "800/8766.a/KD.F",
                "notes": "Kontrak dua baris",
                "lines-TOTAL_FORMS": "2",
                "lines-INITIAL_FORMS": "0",
                "lines-MIN_NUM_FORMS": "0",
                "lines-MAX_NUM_FORMS": "1000",
                "lines-0-item": str(self.item.pk),
                "lines-0-original_quantity": "10",
                "lines-0-original_unit_price": "5000",
                "lines-0-notes": "Baris pertama",
                "lines-1-item": str(self.second_item.pk),
                "lines-1-original_quantity": "20",
                "lines-1-original_unit_price": "7000",
                "lines-1-notes": "Baris kedua",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        contract = ProcurementContract.objects.latest("pk")
        lines = list(contract.lines.select_related("item").order_by("pk"))
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].item, self.item)
        self.assertEqual(lines[0].original_quantity, Decimal("10"))
        self.assertEqual(lines[1].item, self.second_item)
        self.assertEqual(lines[1].original_quantity, Decimal("20"))
        self.assertEqual(contract.external_document_number, "800/8766.a/KD.F")

    def test_contract_create_accepts_comma_decimal_unit_price(self):
        response = self.client.post(
            reverse("procurement:contract_create"),
            {
                "document_number": "",
                "contract_date": "2026-07-01",
                "supplier": str(self.supplier.pk),
                "sumber_dana": str(self.funding.pk),
                "notes": "Harga koma",
                "lines-TOTAL_FORMS": "1",
                "lines-INITIAL_FORMS": "0",
                "lines-MIN_NUM_FORMS": "0",
                "lines-MAX_NUM_FORMS": "1000",
                "lines-0-item": str(self.item.pk),
                "lines-0-original_quantity": "10",
                "lines-0-original_unit_price": "5000,50",
                "lines-0-notes": "Baris harga koma",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        line = ProcurementContract.objects.latest("pk").lines.get()
        self.assertEqual(line.original_unit_price, Decimal("5000.50"))

    def test_contract_create_rejects_dot_decimal_unit_price(self):
        response = self.client.post(
            reverse("procurement:contract_create"),
            {
                "document_number": "",
                "contract_date": "2026-07-01",
                "supplier": str(self.supplier.pk),
                "sumber_dana": str(self.funding.pk),
                "notes": "Harga titik",
                "lines-TOTAL_FORMS": "1",
                "lines-INITIAL_FORMS": "0",
                "lines-MIN_NUM_FORMS": "0",
                "lines-MAX_NUM_FORMS": "1000",
                "lines-0-item": str(self.item.pk),
                "lines-0-original_quantity": "10",
                "lines-0-original_unit_price": "5000.50",
                "lines-0-notes": "Baris harga titik",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Gunakan angka tanpa pemisah ribuan. Gunakan koma untuk desimal.",
        )
        self.assertEqual(ProcurementContract.objects.count(), 0)

    def test_amendment_create_page_renders_formset_controls(self):
        contract, line = self._approve_contract(quantity="10", unit_price="5000")
        receiving = Receiving.objects.get(contract=contract)
        order_item = ReceivingOrderItem.objects.get(receiving=receiving, contract_line=line)
        order_item.received_quantity = Decimal("4")
        order_item.save(update_fields=["received_quantity", "updated_at"])

        response = self.client.get(
            reverse("procurement:amendment_create", args=[contract.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-formset="procurement-amendment-lines"')
        self.assertContains(response, 'data-formset-allow-empty="true"')
        self.assertContains(response, 'class="btn btn-outline-primary btn-sm formset-add"', html=False)
        self.assertContains(response, 'class="btn btn-outline-danger btn-sm formset-remove"', html=False)
        self.assertContains(response, 'id="procurement-amendment-lines-empty"')
        self.assertContains(response, str(line.pk))
        self.assertNotContains(response, 'name="document_number"', html=False)
        self.assertContains(response, "Ringkasan Kontrak vs Realisasi")
        self.assertContains(response, "Qty Kontrak Saat Ini")
        self.assertContains(response, "Harga Saat Ini")
        self.assertContains(response, "Sisa Saat Ini")
        self.assertContains(response, "Qty Kontrak Baru")
        self.assertContains(response, "Harga Baru")
        self.assertNotContains(response, "Revisi Qty")
        self.assertNotContains(response, "Revisi Harga")
        self.assertNotContains(response, "Qty Revisi")
        self.assertNotContains(response, "Harga Revisi")
        self.assertContains(response, self.item.nama_barang)
        self.assertContains(response, '<td class="text-end">10</td>', html=False)
        self.assertContains(response, '<td class="text-end">4</td>', html=False)
        self.assertContains(response, '<td class="text-end fw-semibold">6</td>', html=False)
        self.assertContains(response, "Rp 5.000")
        self.assertNotContains(response, '<td class="text-end">10,00</td>', html=False)
        self.assertNotContains(response, '<td class="text-end">4,00</td>', html=False)
        self.assertNotContains(response, '<td class="text-end fw-semibold">6,00</td>', html=False)
        self.assertContains(response, "Saat ini: 10")
        self.assertContains(response, "Diterima: 4")
        self.assertContains(response, "Sisa: 6")

    def test_stale_amendment_create_cannot_attach_to_cancelled_contract(self):
        contract, line = self._approve_contract(quantity="10", unit_price="5000")
        original_is_valid = ProcurementAmendmentForm.is_valid

        def cancel_during_validation(form):
            ProcurementContract.objects.filter(pk=contract.pk).update(
                status=ProcurementContract.Status.CANCELLED,
                cancelled_by=self.admin,
                cancelled_at=timezone.now(),
                cancel_reason="Dibatalkan request lain",
            )
            return original_is_valid(form)

        with patch.object(
            ProcurementAmendmentForm,
            "is_valid",
            autospec=True,
            side_effect=cancel_during_validation,
        ):
            response = self.client.post(
                reverse("procurement:amendment_create", args=[contract.pk]),
                {
                    "amendment_date": "2026-07-08",
                    "notes": "Amandemen stale",
                    "lines-TOTAL_FORMS": "1",
                    "lines-INITIAL_FORMS": "0",
                    "lines-MIN_NUM_FORMS": "0",
                    "lines-MAX_NUM_FORMS": "1000",
                    "lines-0-contract_line": str(line.pk),
                    "lines-0-revised_quantity": "12",
                    "lines-0-revised_unit_price": "6000",
                    "lines-0-notes": "Tidak boleh dibuat",
                },
                secure=True,
            )

        self.assertEqual(response.status_code, 302)
        contract.refresh_from_db()
        self.assertEqual(contract.status, ProcurementContract.Status.CANCELLED)
        self.assertEqual(contract.cancel_reason, "Dibatalkan request lain")
        self.assertEqual(ProcurementAmendment.objects.filter(contract=contract).count(), 0)

    def test_amendment_edit_allows_deleting_line(self):
        contract, line = self._approve_contract(quantity="10", unit_price="5000")
        amendment = ProcurementAmendment.objects.create(
            contract=contract,
            amendment_date=date(2026, 7, 8),
            notes="Edit line",
            status=ProcurementAmendment.Status.DRAFT,
            created_by=self.admin,
        )
        amendment_line = ProcurementAmendmentLine.objects.create(
            amendment=amendment,
            contract_line=line,
            revised_quantity=Decimal("12"),
            revised_unit_price=Decimal("6000"),
            notes="Hapus baris ini",
        )

        response = self.client.post(
            reverse("procurement:amendment_edit", args=[amendment.pk]),
            {
                "amendment_date": "2026-07-08",
                "notes": "Tanpa baris lama",
                "lines-TOTAL_FORMS": "1",
                "lines-INITIAL_FORMS": "1",
                "lines-MIN_NUM_FORMS": "0",
                "lines-MAX_NUM_FORMS": "1000",
                "lines-0-id": str(amendment_line.pk),
                "lines-0-contract_line": str(line.pk),
                "lines-0-revised_quantity": "12",
                "lines-0-revised_unit_price": "6000",
                "lines-0-notes": "Hapus baris ini",
                "lines-0-DELETE": "on",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        amendment.refresh_from_db()
        self.assertEqual(amendment.lines.count(), 0)

    def test_cancelled_contract_hides_and_rejects_draft_amendment_edit(self):
        contract, line = self._approve_contract(quantity="10", unit_price="5000")
        amendment = ProcurementAmendment.objects.create(
            contract=contract,
            amendment_date=date(2026, 7, 8),
            notes="Draft sebelum batal",
            status=ProcurementAmendment.Status.DRAFT,
            created_by=self.admin,
        )
        ProcurementAmendmentLine.objects.create(
            amendment=amendment,
            contract_line=line,
            revised_quantity=Decimal("12"),
            revised_unit_price=Decimal("6000"),
            notes="Draft line",
        )
        self.client.post(
            reverse("procurement:contract_cancel", args=[contract.pk]),
            {"cancel_reason": "Pengadaan dibatalkan"},
            secure=True,
        )

        detail_response = self.client.get(
            reverse("procurement:amendment_detail", args=[amendment.pk]),
            secure=True,
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertNotContains(
            detail_response,
            reverse("procurement:amendment_edit", args=[amendment.pk]),
        )
        self.assertNotContains(
            detail_response,
            reverse("procurement:amendment_submit", args=[amendment.pk]),
        )

        edit_response = self.client.post(
            reverse("procurement:amendment_edit", args=[amendment.pk]),
            {
                "amendment_date": "2026-07-08",
                "notes": "Edit setelah kontrak batal",
                "lines-TOTAL_FORMS": "1",
                "lines-INITIAL_FORMS": "1",
                "lines-MIN_NUM_FORMS": "0",
                "lines-MAX_NUM_FORMS": "1000",
                "lines-0-id": str(amendment.lines.get().pk),
                "lines-0-contract_line": str(line.pk),
                "lines-0-revised_quantity": "14",
                "lines-0-revised_unit_price": "6500",
                "lines-0-notes": "Tidak boleh tersimpan",
            },
            secure=True,
        )

        self.assertEqual(edit_response.status_code, 302)
        amendment.refresh_from_db()
        self.assertEqual(amendment.notes, "Draft sebelum batal")

    def test_procurement_quick_create_supplier_creates_lookup(self):
        response = self.client.post(
            reverse("procurement:quick_create_supplier"),
            {
                "code": " sup-proc-new ",
                "name": "  PT Pengadaan Baru  ",
                "address": "  Jl. Pengadaan 1  ",
                "phone": " 021-555 ",
                "email": " supplier@example.com ",
                "notes": "  Mitra kontrak  ",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        supplier = Supplier.objects.get(code="SUP-PROC-NEW")
        self.assertEqual(supplier.name, "PT Pengadaan Baru")
        self.assertEqual(supplier.address, "Jl. Pengadaan 1")
        self.assertEqual(supplier.phone, "021-555")
        self.assertEqual(supplier.email, "supplier@example.com")
        self.assertEqual(supplier.notes, "Mitra kontrak")
        self.assertEqual(response.json()["id"], supplier.pk)

    def test_procurement_quick_create_funding_source_creates_lookup(self):
        response = self.client.post(
            reverse("procurement:quick_create_funding_source"),
            {
                "code": "  blud  ",
                "name": "  Badan Layanan Umum Daerah  ",
                "description": "  Dana operasional  ",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        funding_source = FundingSource.objects.get(code="BLUD")
        self.assertEqual(funding_source.name, "Badan Layanan Umum Daerah")
        self.assertEqual(funding_source.description, "Dana operasional")
        self.assertEqual(response.json()["id"], funding_source.pk)

    def test_contract_number_is_issued_on_submit_using_contract_date(self):
        first, _line = self._create_contract()
        second, _line = self._create_contract()

        submit_contract(first, self.admin)
        submit_contract(second, self.admin)
        first.refresh_from_db()
        second.refresh_from_db()

        self.assertEqual(first.document_number, "SPJ-2026-00001")
        self.assertEqual(second.document_number, "SPJ-2026-00002")

    def test_amendment_number_generation_uses_shared_monthly_sequence(self):
        contract, line = self._approve_contract(quantity="10", unit_price="5000")
        other_contract, other_line = self._approve_contract(quantity="5", unit_price="2500")
        first = ProcurementAmendment.objects.create(
            contract=contract,
            amendment_date=date(2026, 7, 4),
            notes="Amandemen pertama",
            created_by=self.admin,
        )
        second = ProcurementAmendment.objects.create(
            contract=contract,
            amendment_date=date(2026, 7, 5),
            notes="Amandemen kedua",
            created_by=self.admin,
        )
        other = ProcurementAmendment.objects.create(
            contract=other_contract,
            amendment_date=date(2026, 7, 5),
            notes="Amandemen kontrak lain",
            created_by=self.admin,
        )
        next_month = ProcurementAmendment.objects.create(
            contract=other_contract,
            amendment_date=date(2026, 8, 1),
            notes="Amandemen bulan berikutnya",
            created_by=self.admin,
        )
        for amendment, contract_line in (
            (first, line),
            (second, line),
            (other, other_line),
            (next_month, other_line),
        ):
            ProcurementAmendmentLine.objects.create(
                amendment=amendment,
                contract_line=contract_line,
                revised_quantity=contract_line.original_quantity,
                revised_unit_price=contract_line.original_unit_price,
            )
            submit_amendment(amendment, self.admin)
            amendment.refresh_from_db()

        self.assertEqual(first.document_number, "SPJ/2026/07/1")
        self.assertEqual(second.document_number, "SPJ/2026/07/2")
        self.assertEqual(other.document_number, "SPJ/2026/07/3")
        self.assertEqual(next_month.document_number, "SPJ/2026/08/1")

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
        contract, _line = self._approve_contract(quantity="10000.50", unit_price="5000")
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
                "items-0-quantity": "4000.25",
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
            revised_quantity=Decimal("14000.75"),
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
        self.assertEqual(summary_rows[0]["original_quantity"], Decimal("10000.50"))
        self.assertEqual(summary_rows[0]["current_quantity"], Decimal("14000.75"))
        self.assertEqual(summary_rows[0]["received_quantity"], Decimal("4000.25"))
        self.assertEqual(summary_rows[0]["remaining_quantity"], Decimal("10000.50"))
        self.assertContains(response, '<td class="text-end">10000.5</td>', html=False)
        self.assertContains(response, '<td class="text-end">14000.75</td>', html=False)
        self.assertContains(response, '<td class="text-end">4000.25</td>', html=False)
        self.assertContains(response, "Rp 5.000")
        self.assertContains(response, "Rp 5.500")
        self.assertNotContains(response, '<td class="text-end">10.000,00</td>', html=False)
        self.assertNotContains(response, '<td class="text-end">14.000,00</td>', html=False)
        self.assertNotContains(response, '<td class="text-end">4.000,00</td>', html=False)

    def test_procurement_surfaces_display_exact_high_precision_prices(self):
        contract, line = self._approve_contract(
            quantity="10",
            unit_price="123.1234567891",
        )
        amendment = ProcurementAmendment.objects.create(
            contract=contract,
            amendment_date=date(2026, 7, 8),
            notes="Harga presisi",
            status=ProcurementAmendment.Status.DRAFT,
            created_by=self.admin,
        )
        ProcurementAmendmentLine.objects.create(
            amendment=amendment,
            contract_line=line,
            revised_quantity=Decimal("11"),
            revised_unit_price=Decimal("456.1234567891"),
        )

        contract_response = self.client.get(
            reverse("procurement:contract_detail", args=[contract.pk]),
            secure=True,
        )
        amendment_response = self.client.get(
            reverse("procurement:amendment_detail", args=[amendment.pk]),
            secure=True,
        )
        amendment_form_response = self.client.get(
            reverse("procurement:amendment_create", args=[contract.pk]),
            secure=True,
        )

        self.assertEqual(contract_response.status_code, 200)
        self.assertEqual(amendment_response.status_code, 200)
        self.assertEqual(amendment_form_response.status_code, 200)
        self.assertContains(contract_response, "Rp 123,1234567891")
        self.assertContains(amendment_response, "Rp 123,1234567891")
        self.assertContains(amendment_response, "Rp 456,1234567891")
        self.assertContains(amendment_form_response, "Rp 123,1234567891")
        self.assertNotContains(contract_response, "Rp 123,12</td>", html=False)
        self.assertNotContains(amendment_response, "Rp 123,12</td>", html=False)
        self.assertNotContains(amendment_form_response, "Rp 123,12</td>", html=False)

    def test_amendment_line_selector_label_uses_exact_unit_price(self):
        contract, line = self._approve_contract(
            quantity="10",
            unit_price="123.1234567891",
        )
        form = ProcurementAmendmentLineForm(contract=contract)
        label = form.fields["contract_line"].label_from_instance(line)

        self.assertIn("@ 123,1234567891", label)
        self.assertIn("Awal: 10 @", label)
        self.assertNotEqual(label, "Paracetamol 500mg | Awal: 10,00 @ 123,12")
