from decimal import Decimal
from unittest.mock import patch

from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.distribution.forms import DistributionForm, DistributionItemForm
from apps.distribution.models import Distribution, DistributionItem
from apps.core.models import SystemSettings
from apps.items.models import Category, Facility, FundingSource, Item, Location, Unit
from apps.stock.models import Stock, Transaction
from apps.users.access import ensure_default_module_access
from apps.users.models import User


class DistributionWorkflowTest(TestCase):
    """Tests for the distribution module workflow transitions and stock posting."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser(
            username="gudang_dist",
            password="secret12345",
        )

        cls.unit = Unit.objects.create(code="TAB", name="Tablet")
        cls.category = Category.objects.create(
            code="TABLET", name="Tablet", sort_order=1
        )
        cls.item = Item.objects.create(
            nama_barang="Amoxicillin 500mg",
            satuan=cls.unit,
            kategori=cls.category,
            minimum_stock=Decimal("0"),
        )
        cls.location = Location.objects.create(code="LOC-01", name="Gudang Utama")
        cls.funding_source = FundingSource.objects.create(
            code="DAK", name="Dana Alokasi Khusus"
        )
        cls.facility = Facility.objects.create(
            code="PKM-01", name="Puskesmas Kota"
        )
        cls.rs_facility = Facility.objects.create(
            code="RS-02",
            name="RSUD Cut Nyak Dhien",
            facility_type=Facility.FacilityType.RS,
        )

        cls.stock = Stock.objects.create(
            item=cls.item,
            location=cls.location,
            batch_lot="BATCH-D01",
            expiry_date="2027-12-31",
            quantity=Decimal("200"),
            reserved=Decimal("0"),
            unit_price=Decimal("5000"),
            sumber_dana=cls.funding_source,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def _create_distribution(
        self,
        status=Distribution.Status.DRAFT,
        with_items=True,
        distribution_type=Distribution.DistributionType.LPLPO,
    ):
        """Helper to create a distribution with optional items."""
        dist = Distribution.objects.create(
            distribution_type=distribution_type,
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
        self.assertRegex(dist.document_number, r"^440/\d+/SBBK\.RF/\d{4}$")

    def test_special_request_document_number_uses_independent_rule(self):
        dist = self._create_distribution(
            distribution_type=Distribution.DistributionType.SPECIAL_REQUEST,
        )
        self.assertRegex(dist.document_number, r"^440/\d+/KD\.F/\d{4}$")

    def test_document_number_counter_is_independent_per_rule(self):
        lplpo_dist = self._create_distribution(
            distribution_type=Distribution.DistributionType.LPLPO,
        )
        special_dist = self._create_distribution(
            distribution_type=Distribution.DistributionType.SPECIAL_REQUEST,
        )
        self.assertEqual(lplpo_dist.document_number, "440/1/SBBK.RF/2026")
        self.assertEqual(special_dist.document_number, "440/1/KD.F/2026")

    def test_document_number_counter_resets_each_year(self):
        with patch("apps.distribution.numbering.timezone.now") as mocked_now:
            mocked_now.return_value = timezone.datetime(2026, 5, 1, tzinfo=timezone.get_current_timezone())
            first = self._create_distribution(
                distribution_type=Distribution.DistributionType.LPLPO,
            )

        with patch("apps.distribution.numbering.timezone.now") as mocked_now:
            mocked_now.return_value = timezone.datetime(2027, 1, 10, tzinfo=timezone.get_current_timezone())
            second = Distribution.objects.create(
                distribution_type=Distribution.DistributionType.LPLPO,
                request_date="2027-01-10",
                facility=self.facility,
                status=Distribution.Status.DRAFT,
                created_by=self.user,
            )

        self.assertEqual(first.document_number, "440/1/SBBK.RF/2026")
        self.assertEqual(second.document_number, "440/1/SBBK.RF/2027")

    def test_legacy_document_numbers_do_not_break_new_rule_counter(self):
        Distribution.objects.create(
            distribution_type=Distribution.DistributionType.LPLPO,
            document_number="DIST-202604-00001",
            request_date="2026-04-10",
            facility=self.facility,
            status=Distribution.Status.DRAFT,
            created_by=self.user,
        )

        dist = self._create_distribution(
            distribution_type=Distribution.DistributionType.LPLPO,
        )

        self.assertEqual(dist.document_number, "440/1/SBBK.RF/2026")

    def test_non_rule_distribution_type_keeps_dist_prefix_format(self):
        dist = self._create_distribution(
            distribution_type=Distribution.DistributionType.ALLOCATION,
        )

        self.assertRegex(dist.document_number, r"^DIST-\d{6}-\d{5}$")

    def test_custom_template_from_settings_is_used_for_lplpo(self):
        settings = SystemSettings.get_settings()
        settings.lplpo_distribution_number_template = "DOC/LPLPO/{year}/{seq}"
        settings.save(update_fields=["lplpo_distribution_number_template", "updated_at"])

        dist = self._create_distribution(
            distribution_type=Distribution.DistributionType.LPLPO,
        )

        self.assertEqual(dist.document_number, "DOC/LPLPO/2026/1")

    def test_custom_template_supports_year_outside_suffix_position(self):
        settings = SystemSettings.get_settings()
        settings.special_request_distribution_number_template = "PK/{year}/{seq}/KD.F"
        settings.save(update_fields=["special_request_distribution_number_template", "updated_at"])

        Distribution.objects.create(
            distribution_type=Distribution.DistributionType.SPECIAL_REQUEST,
            document_number="PK/2026/1/KD.F",
            request_date="2026-04-10",
            facility=self.facility,
            status=Distribution.Status.DRAFT,
            created_by=self.user,
        )

        dist = self._create_distribution(
            distribution_type=Distribution.DistributionType.SPECIAL_REQUEST,
        )

        self.assertEqual(dist.document_number, "PK/2026/2/KD.F")

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

    # --- Form validation ---

    def test_distribution_item_form_rejects_non_positive_approved_quantity(self):
        form = DistributionItemForm(
            data={
                "item": self.item.pk,
                "quantity_requested": "10",
                "quantity_approved": "0",
                "stock": self.stock.pk,
                "notes": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("quantity_approved", form.errors)

    def test_distribution_item_form_allows_approved_quantity_above_requested(self):
        form = DistributionItemForm(
            data={
                "item": self.item.pk,
                "quantity_requested": "10",
                "quantity_approved": "12",
                "stock": self.stock.pk,
                "notes": "",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_distribution_item_form_rejects_approved_quantity_above_available_stock(self):
        self.stock.quantity = Decimal("8")
        self.stock.save(update_fields=["quantity", "updated_at"])

        form = DistributionItemForm(
            data={
                "item": self.item.pk,
                "quantity_requested": "10",
                "quantity_approved": "9",
                "stock": self.stock.pk,
                "notes": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("quantity_approved", form.errors)

    def test_distribution_item_form_stock_queryset_filters_and_orders_fefo(self):
        early_stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="BATCH-D00",
            expiry_date="2027-01-01",
            quantity=Decimal("25"),
            reserved=Decimal("0"),
            unit_price=Decimal("5000"),
            sumber_dana=self.funding_source,
        )
        depleted_stock = Stock.objects.create(
            item=self.item,
            location=Location.objects.create(code="LOC-02", name="Gudang Cadangan"),
            batch_lot="BATCH-ZERO",
            expiry_date="2027-06-01",
            quantity=Decimal("5"),
            reserved=Decimal("5"),
            unit_price=Decimal("5000"),
            sumber_dana=self.funding_source,
        )

        form = DistributionItemForm()
        stock_ids = list(form.fields["stock"].queryset.values_list("id", flat=True))

        self.assertEqual(stock_ids[:2], [early_stock.id, self.stock.id])
        self.assertNotIn(depleted_stock.id, stock_ids)

    def test_distribution_form_hides_manual_lplpo_type(self):
        form = DistributionForm(user=self.user)

        type_values = [value for value, _label in form.fields["distribution_type"].choices]

        self.assertNotIn(Distribution.DistributionType.LPLPO, type_values)

    def test_distribution_form_rejects_manual_lplpo_type_submission(self):
        form = DistributionForm(
            data={
                "document_number": "",
                "distribution_type": Distribution.DistributionType.LPLPO,
                "request_date": "2026-03-10",
                "facility": self.facility.pk,
                "program": "",
                "notes": "",
                "assigned_staff": [self.user.pk],
            },
            user=self.user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("distribution_type", form.errors)

    def test_distribution_form_forces_special_request_type(self):
        form = DistributionForm(
            data={
                "document_number": "",
                "request_date": "2026-03-10",
                "facility": self.facility.pk,
                "program": "",
                "notes": "",
                "assigned_staff": [self.user.pk],
            },
            user=self.user,
            forced_distribution_type=Distribution.DistributionType.SPECIAL_REQUEST,
        )

        self.assertTrue(form.is_valid())
        self.assertEqual(
            form.cleaned_data["distribution_type"],
            Distribution.DistributionType.SPECIAL_REQUEST,
        )

    def test_distribution_form_special_request_prefills_preview_number(self):
        form = DistributionForm(
            user=self.user,
            forced_distribution_type=Distribution.DistributionType.SPECIAL_REQUEST,
        )

        self.assertFalse(form.fields["document_number"].disabled)
        self.assertEqual(form.fields["document_number"].initial, "440/1/KD.F/2026")
        self.assertEqual(
            form.fields["document_number_preview"].initial,
            "440/1/KD.F/2026",
        )
        self.assertEqual(
            form.fields["document_number"].widget.attrs.get("placeholder"),
            "Nomor dokumen permintaan khusus",
        )
        self.assertEqual(
            form.fields["document_number"].widget.attrs.get("readonly"),
            True,
        )
        self.assertIn("440/1/KD.F/2026", form.fields["document_number"].help_text)
        self.assertIn("440/{seq}/KD.F/{year}", form.fields["document_number"].help_text)

    def test_distribution_form_special_request_unchanged_preview_keeps_auto_generation(self):
        form = DistributionForm(
            data={
                "document_number": "440/1/KD.F/2026",
                "document_number_preview": "440/1/KD.F/2026",
                "request_date": "2026-03-10",
                "facility": self.facility.pk,
                "program": "",
                "notes": "",
                "assigned_staff": [self.user.pk],
            },
            user=self.user,
            forced_distribution_type=Distribution.DistributionType.SPECIAL_REQUEST,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["document_number"], "")

    def test_distribution_form_special_request_keeps_manual_override(self):
        form = DistributionForm(
            data={
                "document_number": "440/MANUAL/KD.F/2026",
                "document_number_preview": "440/1/KD.F/2026",
                "request_date": "2026-03-10",
                "facility": self.facility.pk,
                "program": "",
                "notes": "",
                "assigned_staff": [self.user.pk],
            },
            user=self.user,
            forced_distribution_type=Distribution.DistributionType.SPECIAL_REQUEST,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["document_number"],
            "440/MANUAL/KD.F/2026",
        )

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

    def test_verify_insufficient_stock_fails(self):
        self.stock.quantity = Decimal("10")
        self.stock.save(update_fields=["quantity", "updated_at"])
        dist = self._create_distribution(status=Distribution.Status.SUBMITTED)

        response = self.client.post(
            reverse("distribution:distribution_verify", args=[dist.pk])
        )

        self.assertEqual(response.status_code, 302)
        dist.refresh_from_db()
        self.assertEqual(dist.status, Distribution.Status.SUBMITTED)

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

        distribution_item = dist.items.get()
        self.assertEqual(distribution_item.issued_batch_lot, "BATCH-D01")
        self.assertEqual(distribution_item.issued_expiry_date.isoformat(), "2027-12-31")
        self.assertEqual(distribution_item.issued_unit_price, Decimal("5000"))
        self.assertEqual(distribution_item.issued_sumber_dana, self.funding_source)

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
            reverse("distribution:special_request_create"),
            {
                "document_number": "",
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
        self.assertEqual(
            dist.distribution_type,
            Distribution.DistributionType.SPECIAL_REQUEST,
        )
        assigned_usernames = list(
            dist.staff_assignments.order_by("user__username").values_list(
                "user__username", flat=True
            )
        )
        self.assertEqual(assigned_usernames, ["gudang_dist", "petugas_bantu"])

    def test_create_distribution_saves_program(self):
        response = self.client.post(
            reverse("distribution:special_request_create"),
            {
                "document_number": "",
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

    def test_special_request_create_hides_distribution_type_field(self):
        response = self.client.get(reverse("distribution:special_request_create"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Distribution Type")
        self.assertNotContains(response, "Tipe Distribusi")

    def test_special_request_create_shows_editable_preview_document_number(self):
        response = self.client.get(reverse("distribution:special_request_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="440/1/KD.F/2026"', html=False)
        self.assertContains(response, "Konfirmasi Edit Nomor Dokumen")
        self.assertContains(response, "Ubah Nomor")
        self.assertContains(response, "Nomor berikutnya saat ini: 440/1/KD.F/2026")
        self.assertContains(response, "440/{seq}/KD.F/{year}")
        self.assertNotContains(response, "DIST-YYYYMM-XXXXX")

    def test_special_request_create_uses_versioned_distribution_form_script(self):
        response = self.client.get(reverse("distribution:special_request_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "js/item-picker-table.js?v=")
        self.assertContains(response, "js/distribution-form.js?v=")

    def test_distribution_item_form_uses_name_only_item_labels(self):
        form = DistributionItemForm()

        self.assertEqual(form.fields["item"].label_from_instance(self.item), self.item.nama_barang)

    def test_distribution_form_static_asset_removes_old_approved_vs_requested_guard(self):
        asset_path = finders.find("js/distribution-form.js")

        self.assertIsNotNone(asset_path)
        with open(asset_path, encoding="utf-8") as asset_file:
            asset_content = asset_file.read()

        self.assertNotIn(
            "Jumlah disetujui tidak boleh melebihi jumlah diminta.",
            asset_content,
        )
        self.assertNotIn("validateApprovedQty", asset_content)

    def test_special_request_create_uses_auto_generation_when_preview_is_unchanged(self):
        response = self.client.post(
            reverse("distribution:special_request_create"),
            {
                "document_number": "440/1/KD.F/2026",
                "document_number_preview": "440/1/KD.F/2026",
                "request_date": "2026-03-10",
                "facility": self.facility.pk,
                "notes": "",
                "assigned_staff": [self.user.pk],
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
        self.assertEqual(dist.document_number, "440/1/KD.F/2026")

    def test_edit_distribution_updates_assigned_staff(self):
        dist = self._create_distribution(
            status=Distribution.Status.DRAFT,
            distribution_type=Distribution.DistributionType.SPECIAL_REQUEST,
        )
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

    def test_distribution_history_shows_report_button(self):
        response = self.client.get(reverse("distribution:distribution_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("reports:pengeluaran"))
        self.assertNotContains(response, "Buat Distribusi")

    def test_distribution_list_requires_view_permission(self):
        restricted_user = User.objects.create_user(
            username="puskesmas_no_distribution_view",
            password="secret12345",
            role=User.Role.PUSKESMAS,
        )
        self.client.force_login(restricted_user)

        response = self.client.get(reverse("distribution:distribution_list"))

        self.assertEqual(response.status_code, 403)

    def test_special_request_list_filters_special_request_records(self):
        special_request = self._create_distribution(
            distribution_type=Distribution.DistributionType.SPECIAL_REQUEST
        )
        history_only = self._create_distribution(
            distribution_type=Distribution.DistributionType.LPLPO,
            with_items=False,
        )

        response = self.client.get(reverse("distribution:special_request_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, special_request.document_number)
        self.assertNotContains(response, history_only.document_number)

    def test_special_request_list_requires_view_permission(self):
        restricted_user = User.objects.create_user(
            username="puskesmas_no_special_request_view",
            password="secret12345",
            role=User.Role.PUSKESMAS,
        )
        self.client.force_login(restricted_user)

        response = self.client.get(reverse("distribution:special_request_list"))

        self.assertEqual(response.status_code, 403)

    def test_detail_shows_assigned_staff(self):
        dist = self._create_distribution(status=Distribution.Status.DRAFT)
        dist.staff_assignments.create(user=self.user)

        response = self.client.get(
            reverse("distribution:distribution_detail", args=[dist.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Petugas")
        self.assertContains(response, str(self.user))

    def test_distribution_detail_requires_view_permission(self):
        dist = self._create_distribution(status=Distribution.Status.DRAFT)
        restricted_user = User.objects.create_user(
            username="puskesmas_no_distribution_detail_view",
            password="secret12345",
            role=User.Role.PUSKESMAS,
        )
        self.client.force_login(restricted_user)

        response = self.client.get(
            reverse("distribution:distribution_detail", args=[dist.pk])
        )

        self.assertEqual(response.status_code, 403)

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

    def test_gudang_cannot_distribute_distribution(self):
        dist = self._create_distribution(status=Distribution.Status.PREPARED)
        gudang = User.objects.create_user(
            username="gudang_only_distribute",
            password="secret12345",
            role=User.Role.GUDANG,
        )
        ensure_default_module_access(gudang, overwrite=True)
        self.client.force_login(gudang)

        response = self.client.post(
            reverse("distribution:distribution_distribute", args=[dist.pk])
        )

        self.assertEqual(response.status_code, 403)
        dist.refresh_from_db()
        self.stock.refresh_from_db()
        self.assertEqual(dist.status, Distribution.Status.PREPARED)
        self.assertEqual(self.stock.quantity, Decimal("200"))

    # --- Model-level validation (Issue #11) ---

    def test_model_clean_allows_approved_above_requested(self):
        """DistributionItem.full_clean() should allow approved quantity above requested."""
        dist = self._create_distribution(with_items=False)
        di = DistributionItem(
            distribution=dist,
            item=self.item,
            quantity_requested=Decimal("50"),
            quantity_approved=Decimal("100"),
            stock=self.stock,
        )
        di.full_clean()

    def test_create_post_allows_approved_above_requested(self):
        """POST to special_request_create may save even when approved quantity exceeds requested."""
        response = self.client.post(
            reverse("distribution:special_request_create"),
            {
                "document_number": "",
                "request_date": "2026-03-10",
                "facility": self.facility.pk,
                "notes": "",
                "assigned_staff": [self.user.pk],
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-item": self.item.pk,
                "items-0-quantity_requested": "50",
                "items-0-quantity_approved": "100",
                "items-0-stock": self.stock.pk,
                "items-0-notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)

        dist = Distribution.objects.latest("id")
        self.assertEqual(dist.items.get().quantity_requested, Decimal("50"))
        self.assertEqual(dist.items.get().quantity_approved, Decimal("100"))

    def test_edit_post_allows_approved_above_requested(self):
        """POST to distribution_edit may save even when approved quantity exceeds requested."""
        dist = self._create_distribution(
            status=Distribution.Status.DRAFT,
            distribution_type=Distribution.DistributionType.SPECIAL_REQUEST,
        )
        item_line = dist.items.first()

        response = self.client.post(
            reverse("distribution:distribution_edit", args=[dist.pk]),
            {
                "document_number": dist.document_number,
                "request_date": "2026-03-10",
                "facility": self.facility.pk,
                "notes": "",
                "assigned_staff": [self.user.pk],
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "1",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-id": item_line.pk,
                "items-0-item": self.item.pk,
                "items-0-quantity_requested": "50",
                "items-0-quantity_approved": "100",
                "items-0-stock": self.stock.pk,
                "items-0-notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)

        item_line.refresh_from_db()
        self.assertEqual(item_line.quantity_requested, Decimal("50"))
        self.assertEqual(item_line.quantity_approved, Decimal("100"))

