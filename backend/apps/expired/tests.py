from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.expired.models import Expired, ExpiredItem
from apps.items.models import Category, FundingSource, Item, Location, Unit
from apps.stock.models import Stock, Transaction
from apps.users.access import ensure_default_module_access
from apps.users.models import User


class ExpiredWorkflowTest(TestCase):
    """Tests for the expired module workflow transitions, stock posting, and edge cases."""

    def setUp(self):
        self.user = User.objects.create_superuser(
            username="gudang_expired",
            password="secret12345",
        )

        self.unit = Unit.objects.create(code="BOT", name="Botol")
        self.category = Category.objects.create(
            code="SYRUP", name="Sirup", sort_order=1
        )
        self.item = Item.objects.create(
            nama_barang="Sirup Cough 60ml",
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal("0"),
        )
        self.location = Location.objects.create(code="LOC-02", name="Gudang Farmasi")
        self.funding_source = FundingSource.objects.create(
            code="APBD", name="Anggaran APBD"
        )

        self.stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="BATCH-EXP-01",
            expiry_date="2026-01-01",
            quantity=Decimal("50"),
            reserved=Decimal("0"),
            unit_price=Decimal("2500"),
            sumber_dana=self.funding_source,
        )

        self.client.force_login(self.user)

    def _create_expired(
        self, status=Expired.Status.DRAFT, with_items=True, document_number=""
    ):
        """Helper to create an expired document with optional items."""
        kwargs = {
            "report_date": "2026-03-10",
            "status": status,
            "created_by": self.user,
        }
        if document_number:
            kwargs["document_number"] = document_number
        expired_doc = Expired.objects.create(**kwargs)
        if with_items:
            ExpiredItem.objects.create(
                expired=expired_doc,
                item=self.item,
                stock=self.stock,
                quantity=Decimal("5"),
                notes="Melewati tanggal ED",
            )
        return expired_doc

    # --- Auto-generated document number ---

    def test_auto_generated_document_number(self):
        expired_doc = self._create_expired()
        self.assertTrue(expired_doc.document_number.startswith("EXP-"))
        now_prefix = timezone.now().strftime("%Y%m")
        self.assertIn(now_prefix, expired_doc.document_number)

    def test_custom_document_number_preserved(self):
        expired_doc = self._create_expired(document_number="CUSTOM-EXP-001")
        self.assertEqual(expired_doc.document_number, "CUSTOM-EXP-001")

    # --- Submit workflow ---

    def test_submit_draft_to_submitted(self):
        expired_doc = self._create_expired(status=Expired.Status.DRAFT)
        response = self.client.post(
            reverse("expired:expired_submit", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)
        expired_doc.refresh_from_db()
        self.assertEqual(expired_doc.status, Expired.Status.SUBMITTED)

    def test_submit_requires_items(self):
        expired_doc = self._create_expired(
            status=Expired.Status.DRAFT, with_items=False
        )
        response = self.client.post(
            reverse("expired:expired_submit", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)
        expired_doc.refresh_from_db()
        self.assertEqual(expired_doc.status, Expired.Status.DRAFT)  # unchanged

    def test_submit_only_from_draft(self):
        expired_doc = self._create_expired(status=Expired.Status.SUBMITTED)
        response = self.client.post(
            reverse("expired:expired_submit", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)
        expired_doc.refresh_from_db()
        self.assertEqual(expired_doc.status, Expired.Status.SUBMITTED)  # unchanged

    # --- Verify workflow (stock deduction + transaction) ---

    def test_verify_deducts_stock_and_creates_transaction(self):
        expired_doc = self._create_expired(status=Expired.Status.SUBMITTED)
        response = self.client.post(
            reverse("expired:expired_verify", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)

        expired_doc.refresh_from_db()
        self.stock.refresh_from_db()

        self.assertEqual(expired_doc.status, Expired.Status.VERIFIED)
        self.assertEqual(expired_doc.verified_by, self.user)
        self.assertIsNotNone(expired_doc.verified_at)
        self.assertEqual(self.stock.quantity, Decimal("45"))  # 50 - 5

        txn = Transaction.objects.get(
            reference_type=Transaction.ReferenceType.EXPIRED,
            reference_id=expired_doc.id,
        )
        self.assertEqual(txn.transaction_type, Transaction.TransactionType.OUT)
        self.assertEqual(txn.quantity, Decimal("5"))
        self.assertEqual(txn.item, self.item)

    def test_verify_insufficient_stock_fails(self):
        self.stock.quantity = Decimal("3")
        self.stock.save()
        expired_doc = self._create_expired(status=Expired.Status.SUBMITTED)
        response = self.client.post(
            reverse("expired:expired_verify", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)
        expired_doc.refresh_from_db()
        self.assertEqual(expired_doc.status, Expired.Status.SUBMITTED)  # unchanged
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal("3"))  # unchanged

    def test_verify_only_from_submitted(self):
        expired_doc = self._create_expired(status=Expired.Status.DRAFT)
        response = self.client.post(
            reverse("expired:expired_verify", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)
        expired_doc.refresh_from_db()
        self.assertEqual(expired_doc.status, Expired.Status.DRAFT)  # unchanged

    # --- Dispose workflow ---

    def test_dispose_verified_to_disposed(self):
        expired_doc = self._create_expired(status=Expired.Status.VERIFIED)
        expired_doc.verified_by = self.user
        expired_doc.verified_at = timezone.now()
        expired_doc.save()

        response = self.client.post(
            reverse("expired:expired_dispose", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)
        expired_doc.refresh_from_db()
        self.assertEqual(expired_doc.status, Expired.Status.DISPOSED)
        self.assertEqual(expired_doc.disposed_by, self.user)
        self.assertIsNotNone(expired_doc.disposed_at)

    def test_dispose_only_from_verified(self):
        expired_doc = self._create_expired(status=Expired.Status.SUBMITTED)
        response = self.client.post(
            reverse("expired:expired_dispose", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)
        expired_doc.refresh_from_db()
        self.assertEqual(expired_doc.status, Expired.Status.SUBMITTED)  # unchanged

    # --- Edit access ---

    def test_edit_allowed_for_draft(self):
        expired_doc = self._create_expired(status=Expired.Status.DRAFT)
        response = self.client.get(
            reverse("expired:expired_edit", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_edit_allowed_for_submitted(self):
        expired_doc = self._create_expired(status=Expired.Status.SUBMITTED)
        response = self.client.get(
            reverse("expired:expired_edit", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_edit_blocked_for_verified(self):
        expired_doc = self._create_expired(status=Expired.Status.VERIFIED)
        response = self.client.get(
            reverse("expired:expired_edit", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)  # redirect with error

    def test_edit_blocked_for_disposed(self):
        expired_doc = self._create_expired(status=Expired.Status.DISPOSED)
        response = self.client.get(
            reverse("expired:expired_edit", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)  # redirect with error

    # --- Delete ---

    def test_delete_draft_expired(self):
        expired_doc = self._create_expired(status=Expired.Status.DRAFT)
        pk = expired_doc.pk
        response = self.client.post(reverse("expired:expired_delete", args=[pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Expired.objects.filter(pk=pk).exists())

    def test_delete_blocked_for_submitted(self):
        expired_doc = self._create_expired(status=Expired.Status.SUBMITTED)
        response = self.client.post(
            reverse("expired:expired_delete", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Expired.objects.filter(pk=expired_doc.pk).exists()
        )  # still exists

    def test_gudang_cannot_verify_expired(self):
        expired_doc = self._create_expired(status=Expired.Status.SUBMITTED)
        gudang = User.objects.create_user(
            username="gudang_only_exp",
            password="secret12345",
            role=User.Role.GUDANG,
        )
        ensure_default_module_access(gudang, overwrite=True)
        self.client.force_login(gudang)

        response = self.client.post(
            reverse("expired:expired_verify", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 403)
