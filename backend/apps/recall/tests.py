from decimal import Decimal
from unittest.mock import patch

from django.contrib import admin
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import DocumentNumberRule
from apps.core.numbering import issue_document_number
from apps.core.tests.mixins import SecureClientDefaultsMixin
from apps.items.models import Category, FundingSource, Item, Location, Supplier, Unit
from apps.recall.forms import RecallForm, RecallItemForm
from apps.recall.models import Recall, RecallItem
from apps.stock.models import Stock, Transaction
from apps.users.access import ensure_default_module_access
from apps.users.models import User

from .admin import RecallAdmin, RecallItemInline


class RecallWorkflowTest(SecureClientDefaultsMixin, TestCase):
    """Tests for the recall module workflow transitions, stock posting, and edge cases."""

    def setUp(self):
        super().setUp()
        DocumentNumberRule.objects.get_or_create(
            key=DocumentNumberRule.Key.RECALL,
            defaults={
                "label": "Recall",
                "template": "REC-{year}{month}-{seq}",
                "reset_period": DocumentNumberRule.ResetPeriod.MONTHLY,
                "padding": 5,
            },
        )
        self.user = User.objects.create_superuser(
            username="gudang_recall",
            password="secret12345",
        )

        self.unit = Unit.objects.create(code="TAB", name="Tablet")
        self.category = Category.objects.create(
            code="TABLET", name="Tablet", sort_order=1
        )
        self.item = Item.objects.create(
            nama_barang="Paracetamol 500mg",
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal("0"),
        )
        self.location = Location.objects.create(code="LOC-01", name="Gudang Utama")
        self.funding_source = FundingSource.objects.create(
            code="DAK", name="Dana Alokasi Khusus"
        )
        self.supplier = Supplier.objects.create(code="SUP-01", name="Supplier A")

        self.stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="BATCH-001",
            expiry_date="2027-12-31",
            quantity=Decimal("100"),
            reserved=Decimal("0"),
            unit_price=Decimal("1000"),
            sumber_dana=self.funding_source,
        )

        self.client.force_login(self.user)

    def _create_recall(
        self, status=Recall.Status.DRAFT, with_items=True, document_number=""
    ):
        """Helper to create a recall with optional items."""
        kwargs = {
            "recall_date": "2026-03-10",
            "supplier": self.supplier,
            "status": status,
            "created_by": self.user,
        }
        if document_number:
            kwargs["document_number"] = document_number
        recall = Recall.objects.create(**kwargs)
        if with_items:
            RecallItem.objects.create(
                recall=recall,
                item=self.item,
                stock=self.stock,
                quantity=Decimal("10"),
                notes="Kemasan rusak",
            )
        if status != Recall.Status.DRAFT:
            issue_document_number(
                DocumentNumberRule.Key.RECALL,
                business_date=recall.recall_date,
                target=recall,
                actor=self.user,
            )
            recall.refresh_from_db()
        return recall

    # --- Auto-generated document number ---

    def test_auto_generated_document_number(self):
        recall = self._create_recall()
        self.assertIsNone(recall.document_number)

        self.client.post(reverse("recall:recall_submit", args=[recall.pk]))
        recall.refresh_from_db()

        self.assertEqual(recall.document_number, "REC-202603-00001")

    def test_form_does_not_expose_document_number(self):
        form = RecallForm()
        self.assertNotIn("document_number", form.fields)

    def test_numbered_recall_form_ignores_changed_business_date(self):
        recall = self._create_recall(status=Recall.Status.SUBMITTED)
        original_date = recall.recall_date
        form = RecallForm(
            data={
                "recall_date": "2026-04-10",
                "supplier": self.supplier.pk,
                "notes": "Catatan diperbarui",
            },
            instance=recall,
        )

        self.assertTrue(form.fields["recall_date"].disabled)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        recall.refresh_from_db()
        self.assertEqual(recall.recall_date, original_date)

        draft_form = RecallForm(instance=self._create_recall())
        self.assertFalse(draft_form.fields["recall_date"].disabled)

    def test_admin_locks_workflow_and_items_after_draft(self):
        recall = self._create_recall(status=Recall.Status.SUBMITTED)
        request = RequestFactory().get("/admin/recall/")
        request.user = self.user
        recall_admin = RecallAdmin(Recall, admin.site)
        item_inline = RecallItemInline(Recall, admin.site)
        form = RecallAdmin(Recall, admin.site).get_form(request)

        for field_name in {
            "document_number",
            "status",
            "verified_by",
            "verified_at",
            "completed_by",
            "completed_at",
        }:
            self.assertNotIn(field_name, form.base_fields)
        self.assertNotIn("mark_completed", recall_admin.get_actions(request))
        self.assertNotIn("delete_selected", recall_admin.get_actions(request))
        self.assertIn(
            "recall_date",
            recall_admin.get_readonly_fields(request, recall),
        )
        self.assertFalse(recall_admin.has_change_permission(request, recall))
        self.assertFalse(recall_admin.has_delete_permission(request))
        self.assertFalse(recall_admin.has_delete_permission(request, recall))
        self.assertFalse(item_inline.has_add_permission(request, recall))
        self.assertFalse(item_inline.has_change_permission(request, recall))
        self.assertFalse(item_inline.has_delete_permission(request, recall))

    # --- Submit workflow ---

    def test_submit_draft_to_submitted(self):
        recall = self._create_recall(status=Recall.Status.DRAFT)
        response = self.client.post(reverse("recall:recall_submit", args=[recall.pk]))
        self.assertEqual(response.status_code, 302)
        recall.refresh_from_db()
        self.assertEqual(recall.status, Recall.Status.SUBMITTED)

    def test_submit_requires_items(self):
        recall = self._create_recall(status=Recall.Status.DRAFT, with_items=False)
        response = self.client.post(reverse("recall:recall_submit", args=[recall.pk]))
        self.assertEqual(response.status_code, 302)
        recall.refresh_from_db()
        self.assertEqual(recall.status, Recall.Status.DRAFT)  # unchanged

    def test_submit_only_from_draft(self):
        recall = self._create_recall(status=Recall.Status.SUBMITTED)
        response = self.client.post(reverse("recall:recall_submit", args=[recall.pk]))
        self.assertEqual(response.status_code, 302)
        recall.refresh_from_db()
        self.assertEqual(recall.status, Recall.Status.SUBMITTED)  # unchanged

    # --- Verify workflow (stock deduction + transaction) ---

    def test_verify_deducts_stock_and_creates_transaction(self):
        recall = self._create_recall(status=Recall.Status.SUBMITTED)
        response = self.client.post(reverse("recall:recall_verify", args=[recall.pk]))
        self.assertEqual(response.status_code, 302)

        recall.refresh_from_db()
        self.stock.refresh_from_db()

        self.assertEqual(recall.status, Recall.Status.VERIFIED)
        self.assertEqual(recall.verified_by, self.user)
        self.assertIsNotNone(recall.verified_at)
        self.assertEqual(self.stock.quantity, Decimal("90"))  # 100 - 10

        txn = Transaction.objects.get(
            reference_type=Transaction.ReferenceType.RECALL,
            reference_id=recall.id,
        )
        self.assertEqual(txn.transaction_type, Transaction.TransactionType.OUT)
        self.assertEqual(txn.quantity, Decimal("10"))
        self.assertEqual(txn.item, self.item)

    def test_verify_insufficient_stock_fails(self):
        self.stock.quantity = Decimal("5")
        self.stock.save()
        recall = self._create_recall(status=Recall.Status.SUBMITTED)
        response = self.client.post(reverse("recall:recall_verify", args=[recall.pk]))
        self.assertEqual(response.status_code, 302)
        recall.refresh_from_db()
        self.assertEqual(recall.status, Recall.Status.SUBMITTED)  # unchanged
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal("5"))  # unchanged

    def test_verify_only_from_submitted(self):
        recall = self._create_recall(status=Recall.Status.DRAFT)
        response = self.client.post(reverse("recall:recall_verify", args=[recall.pk]))
        self.assertEqual(response.status_code, 302)
        recall.refresh_from_db()
        self.assertEqual(recall.status, Recall.Status.DRAFT)  # unchanged

    # --- Complete workflow ---

    def test_complete_verified_to_completed(self):
        recall = self._create_recall(status=Recall.Status.VERIFIED)
        recall.verified_by = self.user
        recall.verified_at = timezone.now()
        recall.save()

        response = self.client.post(reverse("recall:recall_complete", args=[recall.pk]))
        self.assertEqual(response.status_code, 302)
        recall.refresh_from_db()
        self.assertEqual(recall.status, Recall.Status.COMPLETED)
        self.assertEqual(recall.completed_by, self.user)
        self.assertIsNotNone(recall.completed_at)

    def test_complete_only_from_verified(self):
        recall = self._create_recall(status=Recall.Status.SUBMITTED)
        response = self.client.post(reverse("recall:recall_complete", args=[recall.pk]))
        self.assertEqual(response.status_code, 302)
        recall.refresh_from_db()
        self.assertEqual(recall.status, Recall.Status.SUBMITTED)  # unchanged

    def test_reset_to_draft_from_submitted(self):
        recall = self._create_recall(status=Recall.Status.SUBMITTED)
        response = self.client.post(
            reverse("recall:recall_reset_to_draft", args=[recall.pk])
        )
        self.assertEqual(response.status_code, 302)
        recall.refresh_from_db()
        self.assertEqual(recall.status, Recall.Status.DRAFT)

    def test_reset_to_draft_blocked_for_verified(self):
        recall = self._create_recall(status=Recall.Status.VERIFIED)
        response = self.client.post(
            reverse("recall:recall_reset_to_draft", args=[recall.pk])
        )
        self.assertEqual(response.status_code, 302)
        recall.refresh_from_db()
        self.assertEqual(recall.status, Recall.Status.VERIFIED)

    def test_step_back_completed_to_verified(self):
        recall = self._create_recall(status=Recall.Status.COMPLETED)
        recall.completed_by = self.user
        recall.completed_at = timezone.now()
        recall.save(update_fields=["completed_by", "completed_at", "updated_at"])

        response = self.client.post(reverse("recall:recall_step_back", args=[recall.pk]))
        self.assertEqual(response.status_code, 302)
        recall.refresh_from_db()
        self.assertEqual(recall.status, Recall.Status.VERIFIED)
        self.assertIsNone(recall.completed_by)
        self.assertIsNone(recall.completed_at)

    def test_step_back_blocked_for_verified(self):
        recall = self._create_recall(status=Recall.Status.VERIFIED)
        response = self.client.post(reverse("recall:recall_step_back", args=[recall.pk]))
        self.assertEqual(response.status_code, 302)
        recall.refresh_from_db()
        self.assertEqual(recall.status, Recall.Status.VERIFIED)

    # --- Edit access ---

    def test_edit_allowed_for_draft(self):
        recall = self._create_recall(status=Recall.Status.DRAFT)
        response = self.client.get(reverse("recall:recall_edit", args=[recall.pk]))
        self.assertEqual(response.status_code, 200)

    def test_recall_create_renders_item_validation_hooks(self):
        response = self.client.get(reverse("recall:recall_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-recall-form')
        self.assertContains(response, 'js-recall-table-error')
        self.assertContains(response, 'Kuantitas wajib diisi.')

    def test_recall_create_includes_recall_form_script(self):
        response = self.client.get(reverse("recall:recall_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'js/recall-form.js')

    def test_recall_item_form_uses_name_only_item_labels(self):
        form = RecallItemForm()

        self.assertEqual(form.fields["item"].label_from_instance(self.item), self.item.nama_barang)

    def test_edit_allowed_for_submitted(self):
        recall = self._create_recall(status=Recall.Status.SUBMITTED)
        response = self.client.get(reverse("recall:recall_edit", args=[recall.pk]))
        self.assertEqual(response.status_code, 200)

    def test_edit_reloads_row_after_concurrent_submission(self):
        recall = self._create_recall(status=Recall.Status.DRAFT)
        recall_item = recall.items.get()
        stale_draft = Recall.objects.get(pk=recall.pk)

        self.client.post(reverse("recall:recall_submit", args=[recall.pk]))
        recall.refresh_from_db()
        issued_number = recall.document_number

        with patch("apps.recall.views.get_object_or_404", return_value=stale_draft):
            response = self.client.post(
                reverse("recall:recall_edit", args=[recall.pk]),
                {
                    "recall_date": "2026-04-10",
                    "supplier": str(self.supplier.pk),
                    "notes": "Catatan setelah pengajuan",
                    "items-TOTAL_FORMS": "1",
                    "items-INITIAL_FORMS": "1",
                    "items-MIN_NUM_FORMS": "0",
                    "items-MAX_NUM_FORMS": "1000",
                    "items-0-id": str(recall_item.pk),
                    "items-0-item": str(self.item.pk),
                    "items-0-stock": str(self.stock.pk),
                    "items-0-quantity": "10",
                    "items-0-notes": "Kemasan rusak",
                },
            )

        self.assertEqual(response.status_code, 302)
        recall.refresh_from_db()
        self.assertEqual(recall.status, Recall.Status.SUBMITTED)
        self.assertEqual(recall.document_number, issued_number)
        self.assertEqual(str(recall.recall_date), "2026-03-10")
        self.assertEqual(recall.notes, "Catatan setelah pengajuan")

    def test_edit_blocked_for_verified(self):
        recall = self._create_recall(status=Recall.Status.VERIFIED)
        response = self.client.get(reverse("recall:recall_edit", args=[recall.pk]))
        self.assertEqual(response.status_code, 302)  # redirect with error

    def test_edit_blocked_for_completed(self):
        recall = self._create_recall(status=Recall.Status.COMPLETED)
        response = self.client.get(reverse("recall:recall_edit", args=[recall.pk]))
        self.assertEqual(response.status_code, 302)  # redirect with error

    # --- Delete ---

    def test_delete_draft_recall(self):
        recall = self._create_recall(status=Recall.Status.DRAFT)
        pk = recall.pk
        response = self.client.post(reverse("recall:recall_delete", args=[pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Recall.objects.filter(pk=pk).exists())

    def test_delete_blocked_for_submitted(self):
        recall = self._create_recall(status=Recall.Status.SUBMITTED)
        response = self.client.post(reverse("recall:recall_delete", args=[recall.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Recall.objects.filter(pk=recall.pk).exists())  # still exists

    def test_gudang_cannot_verify_recall(self):
        recall = self._create_recall(status=Recall.Status.SUBMITTED)
        gudang = User.objects.create_user(
            username="gudang_only_rec",
            password="secret12345",
            role=User.Role.GUDANG,
        )
        ensure_default_module_access(gudang, overwrite=True)
        self.client.force_login(gudang)

        response = self.client.post(reverse("recall:recall_verify", args=[recall.pk]))
        self.assertEqual(response.status_code, 403)
