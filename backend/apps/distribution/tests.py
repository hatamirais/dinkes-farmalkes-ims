from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.distribution.models import Distribution, DistributionItem
from apps.items.models import Category, Facility, FundingSource, Item, Location, Unit
from apps.stock.models import Stock, Transaction
from apps.users.access import ensure_default_module_access
from apps.users.models import User


class DistributionWorkflowTest(TestCase):
    """Tests for the distribution module workflow transitions and stock posting."""

    def setUp(self):
        self.user = User.objects.create_superuser(
            username="gudang_dist",
            password="secret12345",
        )

        self.unit = Unit.objects.create(code="TAB", name="Tablet")
        self.category = Category.objects.create(
            code="TABLET", name="Tablet", sort_order=1
        )
        self.item = Item.objects.create(
            nama_barang="Amoxicillin 500mg",
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal("0"),
        )
        self.location = Location.objects.create(code="LOC-01", name="Gudang Utama")
        self.funding_source = FundingSource.objects.create(
            code="DAK", name="Dana Alokasi Khusus"
        )
        self.facility = Facility.objects.create(code="PKM-01", name="Puskesmas Kota")

        self.stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="BATCH-D01",
            expiry_date="2027-12-31",
            quantity=Decimal("200"),
            reserved=Decimal("0"),
            unit_price=Decimal("5000"),
            sumber_dana=self.funding_source,
        )

        self.client.force_login(self.user)

    def _create_distribution(self, status=Distribution.Status.DRAFT, with_items=True):
        """Helper to create a distribution with optional items."""
        dist = Distribution.objects.create(
            distribution_type=Distribution.DistributionType.LPLPO,
            request_date="2026-03-10",
            facility=self.facility,
            status=status,
            created_by=self.user,
        )
        if with_items:
            DistributionItem.objects.create(
                distribution=dist,
                item=self.item,
                quantity_requested=Decimal("50"),
                quantity_approved=Decimal("40"),
                stock=self.stock,
            )
        return dist

    # --- Auto-generated document number ---

    def test_auto_generated_document_number(self):
        dist = self._create_distribution()
        self.assertTrue(dist.document_number.startswith("DIST-"))
        self.assertEqual(len(dist.document_number), 17)  # DIST-YYYYMM-XXXXX

    # --- Submit workflow ---

    def test_submit_draft_to_submitted(self):
        dist = self._create_distribution(status=Distribution.Status.DRAFT)
        response = self.client.post(
            reverse("distribution:distribution_submit", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)
        dist.refresh_from_db()
        self.assertEqual(dist.status, Distribution.Status.SUBMITTED)

    def test_submit_requires_items(self):
        dist = self._create_distribution(
            status=Distribution.Status.DRAFT, with_items=False
        )
        response = self.client.post(
            reverse("distribution:distribution_submit", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)
        dist.refresh_from_db()
        self.assertEqual(dist.status, Distribution.Status.DRAFT)  # unchanged

    def test_submit_only_from_draft(self):
        dist = self._create_distribution(status=Distribution.Status.SUBMITTED)
        response = self.client.post(
            reverse("distribution:distribution_submit", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)
        dist.refresh_from_db()
        self.assertEqual(dist.status, Distribution.Status.SUBMITTED)

    # --- Verify workflow ---

    def test_verify_submitted_to_verified(self):
        dist = self._create_distribution(status=Distribution.Status.SUBMITTED)
        response = self.client.post(
            reverse("distribution:distribution_verify", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)
        dist.refresh_from_db()
        self.assertEqual(dist.status, Distribution.Status.VERIFIED)
        self.assertEqual(dist.verified_by, self.user)
        self.assertIsNotNone(dist.verified_at)

    def test_verify_requires_approved_qty(self):
        dist = self._create_distribution(
            status=Distribution.Status.SUBMITTED, with_items=False
        )
        DistributionItem.objects.create(
            distribution=dist,
            item=self.item,
            quantity_requested=Decimal("50"),
            quantity_approved=None,
            stock=self.stock,
        )
        response = self.client.post(
            reverse("distribution:distribution_verify", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)
        dist.refresh_from_db()
        self.assertEqual(dist.status, Distribution.Status.SUBMITTED)  # unchanged

    def test_verify_requires_stock_batch(self):
        dist = self._create_distribution(
            status=Distribution.Status.SUBMITTED, with_items=False
        )
        DistributionItem.objects.create(
            distribution=dist,
            item=self.item,
            quantity_requested=Decimal("50"),
            quantity_approved=Decimal("40"),
            stock=None,
        )
        response = self.client.post(
            reverse("distribution:distribution_verify", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)
        dist.refresh_from_db()
        self.assertEqual(dist.status, Distribution.Status.SUBMITTED)  # unchanged

    # --- Prepare workflow ---

    def test_prepare_verified_to_prepared(self):
        dist = self._create_distribution(status=Distribution.Status.VERIFIED)
        response = self.client.post(
            reverse("distribution:distribution_prepare", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)
        dist.refresh_from_db()
        self.assertEqual(dist.status, Distribution.Status.PREPARED)

    # --- Distribute workflow (stock deduction + transaction) ---

    def test_distribute_deducts_stock_and_creates_transaction(self):
        dist = self._create_distribution(status=Distribution.Status.PREPARED)
        response = self.client.post(
            reverse("distribution:distribution_distribute", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)

        dist.refresh_from_db()
        self.stock.refresh_from_db()

        self.assertEqual(dist.status, Distribution.Status.DISTRIBUTED)
        self.assertEqual(dist.approved_by, self.user)
        self.assertIsNotNone(dist.approved_at)
        self.assertIsNotNone(dist.distributed_date)
        self.assertEqual(self.stock.quantity, Decimal("160"))  # 200 - 40

        txn = Transaction.objects.get(
            reference_type=Transaction.ReferenceType.DISTRIBUTION,
            reference_id=dist.id,
        )
        self.assertEqual(txn.transaction_type, Transaction.TransactionType.OUT)
        self.assertEqual(txn.quantity, Decimal("40"))
        self.assertEqual(txn.item, self.item)

    def test_distribute_insufficient_stock_fails(self):
        self.stock.quantity = Decimal("10")
        self.stock.save()
        dist = self._create_distribution(status=Distribution.Status.PREPARED)
        response = self.client.post(
            reverse("distribution:distribution_distribute", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)
        dist.refresh_from_db()
        self.assertEqual(dist.status, Distribution.Status.PREPARED)  # unchanged
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal("10"))  # unchanged

    # --- Reject workflow ---

    def test_reject_submitted_to_rejected(self):
        dist = self._create_distribution(status=Distribution.Status.SUBMITTED)
        response = self.client.post(
            reverse("distribution:distribution_reject", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)
        dist.refresh_from_db()
        self.assertEqual(dist.status, Distribution.Status.REJECTED)

    def test_reject_only_from_submitted(self):
        dist = self._create_distribution(status=Distribution.Status.DRAFT)
        response = self.client.post(
            reverse("distribution:distribution_reject", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)
        dist.refresh_from_db()
        self.assertEqual(dist.status, Distribution.Status.DRAFT)  # unchanged

    # --- Reset-to-draft workflow ---

    def test_reset_to_draft_from_submitted(self):
        dist = self._create_distribution(status=Distribution.Status.SUBMITTED)
        response = self.client.post(
            reverse("distribution:distribution_reset_to_draft", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)
        dist.refresh_from_db()
        self.assertEqual(dist.status, Distribution.Status.DRAFT)

    def test_reset_to_draft_clears_verification_and_distribution_fields(self):
        dist = self._create_distribution(status=Distribution.Status.VERIFIED)
        dist.verified_by = self.user
        dist.verified_at = timezone.now()
        dist.approved_by = self.user
        dist.approved_at = timezone.now()
        dist.distributed_date = timezone.now().date()
        dist.save(
            update_fields=[
                "verified_by",
                "verified_at",
                "approved_by",
                "approved_at",
                "distributed_date",
                "updated_at",
            ]
        )

        response = self.client.post(
            reverse("distribution:distribution_reset_to_draft", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)

        dist.refresh_from_db()
        self.assertEqual(dist.status, Distribution.Status.DRAFT)
        self.assertIsNone(dist.verified_by)
        self.assertIsNone(dist.verified_at)
        self.assertIsNone(dist.approved_by)
        self.assertIsNone(dist.approved_at)
        self.assertIsNone(dist.distributed_date)

    def test_reset_to_draft_blocked_for_distributed(self):
        dist = self._create_distribution(status=Distribution.Status.DISTRIBUTED)
        response = self.client.post(
            reverse("distribution:distribution_reset_to_draft", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)
        dist.refresh_from_db()
        self.assertEqual(dist.status, Distribution.Status.DISTRIBUTED)  # unchanged

    # --- Edit access ---

    def test_edit_allowed_for_draft(self):
        dist = self._create_distribution(status=Distribution.Status.DRAFT)
        response = self.client.get(
            reverse("distribution:distribution_edit", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_edit_blocked_for_verified(self):
        dist = self._create_distribution(status=Distribution.Status.VERIFIED)
        response = self.client.get(
            reverse("distribution:distribution_edit", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)  # redirect with error

    def test_gudang_cannot_verify_distribution(self):
        dist = self._create_distribution(status=Distribution.Status.SUBMITTED)
        gudang = User.objects.create_user(
            username="gudang_only_dist",
            password="secret12345",
            role=User.Role.GUDANG,
        )
        ensure_default_module_access(gudang, overwrite=True)
        self.client.force_login(gudang)

        response = self.client.post(
            reverse("distribution:distribution_verify", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 403)
