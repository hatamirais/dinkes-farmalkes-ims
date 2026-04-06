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
        dist.staff_assignments.create(user=self.user)
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

    def test_submit_requires_assigned_staff(self):
        dist = self._create_distribution(status=Distribution.Status.DRAFT)
        response = self.client.post(
            reverse("distribution:distribution_submit", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)
        dist.refresh_from_db()
        self.assertEqual(dist.status, Distribution.Status.DRAFT)

    def test_submit_with_assigned_staff_moves_to_submitted(self):
        dist = self._create_distribution(status=Distribution.Status.DRAFT)
        dist.staff_assignments.create(user=self.user)

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

    # --- Step-back workflow ---

    def test_step_back_submitted_to_draft(self):
        dist = self._create_distribution(status=Distribution.Status.SUBMITTED)
        response = self.client.post(
            reverse("distribution:distribution_step_back", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)
        dist.refresh_from_db()
        self.assertEqual(dist.status, Distribution.Status.DRAFT)

    def test_step_back_prepared_to_verified(self):
        dist = self._create_distribution(status=Distribution.Status.PREPARED)
        response = self.client.post(
            reverse("distribution:distribution_step_back", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)
        dist.refresh_from_db()
        self.assertEqual(dist.status, Distribution.Status.VERIFIED)

    def test_step_back_rejected_to_submitted(self):
        dist = self._create_distribution(status=Distribution.Status.REJECTED)
        response = self.client.post(
            reverse("distribution:distribution_step_back", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)
        dist.refresh_from_db()
        self.assertEqual(dist.status, Distribution.Status.SUBMITTED)

    def test_step_back_clears_verification_when_back_to_submitted(self):
        dist = self._create_distribution(status=Distribution.Status.VERIFIED)
        dist.verified_by = self.user
        dist.verified_at = timezone.now()
        dist.save(update_fields=["verified_by", "verified_at", "updated_at"])

        response = self.client.post(
            reverse("distribution:distribution_step_back", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)

        dist.refresh_from_db()
        self.assertEqual(dist.status, Distribution.Status.SUBMITTED)
        self.assertIsNone(dist.verified_by)
        self.assertIsNone(dist.verified_at)

    def test_step_back_blocked_for_distributed(self):
        dist = self._create_distribution(status=Distribution.Status.DISTRIBUTED)
        response = self.client.post(
            reverse("distribution:distribution_step_back", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)
        dist.refresh_from_db()
        self.assertEqual(dist.status, Distribution.Status.DISTRIBUTED)  # unchanged

    # --- Delete workflow ---

    def test_delete_allowed_for_draft(self):
        dist = self._create_distribution(status=Distribution.Status.DRAFT)
        response = self.client.post(
            reverse("distribution:distribution_delete", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Distribution.objects.filter(pk=dist.pk).exists())

    def test_delete_allowed_for_rejected(self):
        dist = self._create_distribution(status=Distribution.Status.REJECTED)
        response = self.client.post(
            reverse("distribution:distribution_delete", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Distribution.objects.filter(pk=dist.pk).exists())

    def test_delete_blocked_for_submitted(self):
        dist = self._create_distribution(status=Distribution.Status.SUBMITTED)
        response = self.client.post(
            reverse("distribution:distribution_delete", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Distribution.objects.filter(pk=dist.pk).exists())

    def test_delete_blocked_for_distributed(self):
        dist = self._create_distribution(status=Distribution.Status.DISTRIBUTED)
        response = self.client.post(
            reverse("distribution:distribution_delete", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Distribution.objects.filter(pk=dist.pk).exists())

    # --- Edit access ---

    def test_edit_allowed_for_draft(self):
        dist = self._create_distribution(status=Distribution.Status.DRAFT)
        response = self.client.get(
            reverse("distribution:distribution_edit", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_create_distribution_saves_assigned_staff(self):
        staff = User.objects.create_user(
            username="petugas_bantu",
            password="secret12345",
            full_name="Petugas Bantu",
        )
        response = self.client.post(
            reverse("distribution:distribution_create"),
            {
                "document_number": "",
                "distribution_type": Distribution.DistributionType.LPLPO,
                "request_date": "2026-03-10",
                "facility": self.facility.pk,
                "notes": "",
                "assigned_staff": [self.user.pk, staff.pk],
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-item": self.item.pk,
                "items-0-quantity_requested": "50",
                "items-0-quantity_approved": "40",
                "items-0-stock": self.stock.pk,
                "items-0-notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)

        dist = Distribution.objects.latest("id")
        assigned_usernames = list(
            dist.staff_assignments.order_by("user__username").values_list(
                "user__username", flat=True
            )
        )
        self.assertEqual(assigned_usernames, ["gudang_dist", "petugas_bantu"])

    def test_create_distribution_saves_program(self):
        response = self.client.post(
            reverse("distribution:distribution_create"),
            {
                "document_number": "",
                "distribution_type": Distribution.DistributionType.ALLOCATION,
                "request_date": "2026-03-11",
                "facility": self.facility.pk,
                "program": "Imunisasi",
                "notes": "Distribusi program imunisasi",
                "assigned_staff": [self.user.pk],
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-item": self.item.pk,
                "items-0-quantity_requested": "10",
                "items-0-quantity_approved": "10",
                "items-0-stock": self.stock.pk,
                "items-0-notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)

        dist = Distribution.objects.latest("id")
        self.assertEqual(dist.program, "Imunisasi")

    def test_edit_distribution_updates_assigned_staff(self):
        dist = self._create_distribution(status=Distribution.Status.DRAFT)
        dist.staff_assignments.create(user=self.user)
        staff = User.objects.create_user(
            username="petugas_ganti",
            password="secret12345",
            full_name="Petugas Ganti",
        )
        item_line = dist.items.first()

        response = self.client.post(
            reverse("distribution:distribution_edit", args=[dist.pk]),
            {
                "document_number": dist.document_number,
                "distribution_type": dist.distribution_type,
                "request_date": "2026-03-10",
                "facility": self.facility.pk,
                "notes": "Direvisi",
                "assigned_staff": [staff.pk],
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "1",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-id": item_line.pk,
                "items-0-item": self.item.pk,
                "items-0-quantity_requested": "50",
                "items-0-quantity_approved": "40",
                "items-0-stock": self.stock.pk,
                "items-0-notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)

        dist.refresh_from_db()
        assigned_usernames = list(
            dist.staff_assignments.order_by("user__username").values_list(
                "user__username", flat=True
            )
        )
        self.assertEqual(assigned_usernames, ["petugas_ganti"])

    def test_detail_shows_assigned_staff(self):
        dist = self._create_distribution(status=Distribution.Status.DRAFT)
        dist.staff_assignments.create(user=self.user)

        response = self.client.get(
            reverse("distribution:distribution_detail", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Petugas")
        self.assertContains(response, str(self.user))

    def test_quick_create_facility_adds_option_for_distribution_form(self):
        response = self.client.post(
            reverse("items:quick_create_facility"),
            {
                "code": "PKM-02",
                "name": "Puskesmas Arongan",
                "facility_type": "PUSKESMAS",
                "phone": "0655123456",
                "address": "Jl. Meulaboh",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {
                "id": Facility.objects.get(code="PKM-02").pk,
                "text": "PKM-02 - Puskesmas Arongan",
            },
        )

    def test_quick_create_facility_rejects_duplicate_code(self):
        response = self.client.post(
            reverse("items:quick_create_facility"),
            {
                "code": self.facility.code,
                "name": "Nama Lain",
                "facility_type": "PUSKESMAS",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)

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
