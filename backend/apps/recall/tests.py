from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.items.models import Category, FundingSource, Item, Location, Supplier, Unit
from apps.recall.models import Recall, RecallItem
from apps.stock.models import Stock, Transaction
from apps.users.access import ensure_default_module_access
from apps.users.models import User


class RecallWorkflowTest(TestCase):
    """Tests for the recall module workflow transitions, stock posting, and edge cases."""

    def setUp(self):
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
        return recall

    # --- Auto-generated document number ---

    def test_auto_generated_document_number(self):
        recall = self._create_recall()
        self.assertTrue(recall.document_number.startswith("REC-"))
        now_prefix = timezone.now().strftime("%Y%m")
        self.assertIn(now_prefix, recall.document_number)

    def test_custom_document_number_preserved(self):
        recall = self._create_recall(document_number="CUSTOM-REC-001")
        self.assertEqual(recall.document_number, "CUSTOM-REC-001")

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

    # --- Edit access ---

    def test_edit_allowed_for_draft(self):
        recall = self._create_recall(status=Recall.Status.DRAFT)
        response = self.client.get(reverse("recall:recall_edit", args=[recall.pk]))
        self.assertEqual(response.status_code, 200)

    def test_edit_allowed_for_submitted(self):
        recall = self._create_recall(status=Recall.Status.SUBMITTED)
        response = self.client.get(reverse("recall:recall_edit", args=[recall.pk]))
        self.assertEqual(response.status_code, 200)

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
