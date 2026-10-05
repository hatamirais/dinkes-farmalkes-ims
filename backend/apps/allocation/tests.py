from datetime import timedelta
from decimal import Decimal
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps as django_apps
from django.contrib import admin
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.allocation.forms import AllocationForm, AllocationItemForm
from apps.core.models import DocumentNumberIssue, DocumentNumberRule
from apps.core.numbering import issue_document_number
from apps.distribution.models import Distribution
from apps.items.models import Category, Facility, FundingSource, Item, Location, Unit
from apps.stock.models import Stock, Transaction
from apps.users.models import User

from .admin import (
    AllocationAdmin,
    AllocationFacilityInline,
    AllocationItemAdmin,
    AllocationItemFacilityInline,
    AllocationItemInline,
    AllocationStaffAssignmentInline,
)
from .models import (
    Allocation,
    AllocationFacility,
    AllocationItem,
    AllocationItemFacility,
    AllocationStaffAssignment,
)
from .services import (
    AllocationWorkflowError,
    execute_allocation_approval,
    execute_allocation_rejection,
    execute_allocation_reset_to_draft,
    execute_allocation_submission,
    execute_allocation_step_back_to_submitted,
    execute_distribution_delivery,
    execute_distribution_preparation,
)


def _create_test_fixtures():
    """Set up common master data, stock, and users for allocation tests."""
    for key, label, template, padding in (
        (DocumentNumberRule.Key.ALLOCATION, "Alokasi", "ALK-{year}-{seq}", 4),
        (
            DocumentNumberRule.Key.DISTRIBUTION_SPECIAL_REQUEST,
            "Permintaan Khusus",
            "440/{seq}/KD.F/{year}",
            1,
        ),
    ):
        DocumentNumberRule.objects.get_or_create(
            key=key,
            defaults={
                "label": label,
                "template": template,
                "reset_period": DocumentNumberRule.ResetPeriod.YEARLY,
                "padding": padding,
            },
        )
    unit = Unit.objects.create(code="PCS", name="Pcs")
    category = Category.objects.create(code="OBT", name="Obat")
    funding = FundingSource.objects.create(code="APBD", name="APBD", is_active=True)
    location = Location.objects.create(code="LOC1", name="Gudang Utama", is_active=True)

    item = Item.objects.create(
        nama_barang="Paracetamol 500mg",
        satuan=unit,
        kategori=category,
        kode_barang="ITM-TEST-001",
    )
    facility1 = Facility.objects.create(code="PKM1", name="Puskesmas Alpha", facility_type="PUSKESMAS")
    facility2 = Facility.objects.create(code="PKM2", name="Puskesmas Beta", facility_type="PUSKESMAS")

    stock = Stock.objects.create(
        item=item,
        location=location,
        sumber_dana=funding,
        batch_lot="BATCH-001",
        expiry_date="2027-12-31",
        quantity=100,
        reserved=0,
        unit_price=Decimal("5000.00"),
    )

    admin_user = User.objects.create_superuser(
        username="admin_test", password="testpass1234"
    )
    operator = User.objects.create_user(
        username="operator_test", password="testpass1234", role=User.Role.GUDANG
    )
    kepala = User.objects.create_user(
        username="kepala_test", password="testpass1234", role=User.Role.KEPALA
    )

    return {
        "unit": unit,
        "category": category,
        "funding": funding,
        "location": location,
        "item": item,
        "facility1": facility1,
        "facility2": facility2,
        "stock": stock,
        "admin": admin_user,
        "operator": operator,
        "kepala": kepala,
    }


def _create_allocation(fixtures, user=None, status=Allocation.Status.DRAFT):
    """Create a complete allocation with items and facility allocations."""
    allocation = Allocation.objects.create(
        title="Alokasi Buffer Gudang April 2026",
        allocation_date="2025-06-01",
        status=status,
        created_by=user or fixtures["admin"],
    )
    AllocationFacility.objects.create(allocation=allocation, facility=fixtures["facility1"])
    AllocationFacility.objects.create(allocation=allocation, facility=fixtures["facility2"])
    AllocationStaffAssignment.objects.create(allocation=allocation, user=fixtures["operator"])

    alloc_item = AllocationItem.objects.create(
        allocation=allocation,
        item=fixtures["item"],
        stock=fixtures["stock"],
        total_qty_available=Decimal("100"),
    )
    AllocationItemFacility.objects.create(
        allocation_item=alloc_item,
        facility=fixtures["facility1"],
        qty_allocated=Decimal("30"),
    )
    AllocationItemFacility.objects.create(
        allocation_item=alloc_item,
        facility=fixtures["facility2"],
        qty_allocated=Decimal("20"),
    )
    return allocation


@override_settings(FEATURE_ALLOCATION_UI_ENABLED=True)
class AllocationModelTest(TestCase):
    def setUp(self):
        self.fixtures = _create_test_fixtures()

    def test_document_number_is_not_issued_while_draft(self):
        allocation = Allocation.objects.create(
            title="Alokasi Uji",
            allocation_date="2025-06-01",
            created_by=self.fixtures["admin"],
        )
        self.assertIsNone(allocation.document_number)

    def test_title_is_stored(self):
        allocation = Allocation.objects.create(
            title="Alokasi Program Triwulan II",
            allocation_date="2025-06-01",
            created_by=self.fixtures["admin"],
        )
        self.assertEqual(allocation.title, "Alokasi Program Triwulan II")

    def test_delivery_progress_empty(self):
        allocation = _create_allocation(self.fixtures)
        delivered, total = allocation.delivery_progress
        self.assertEqual(delivered, 0)
        self.assertEqual(total, 0)

    def test_allocation_item_total_qty_allocated(self):
        allocation = _create_allocation(self.fixtures)
        alloc_item = allocation.items.first()
        self.assertEqual(alloc_item.total_qty_allocated, Decimal("50"))

    def test_allocation_item_is_over_allocated(self):
        allocation = _create_allocation(self.fixtures)
        alloc_item = allocation.items.first()
        self.assertFalse(alloc_item.is_over_allocated)

        # Make it over-allocated
        alloc_item.total_qty_available = Decimal("40")
        alloc_item.save()
        self.assertTrue(alloc_item.is_over_allocated)

    def test_allocation_item_facility_clean_rejects_non_finite_quantity(self):
        allocation = _create_allocation(self.fixtures)
        alloc_item = allocation.items.first()
        facility_allocation = AllocationItemFacility(
            allocation_item=alloc_item,
            facility=self.fixtures["facility1"],
            qty_allocated=Decimal("NaN"),
        )

        with self.assertRaises(ValidationError) as exc:
            facility_allocation.clean()

        self.assertEqual(
            exc.exception.message_dict["qty_allocated"],
            ["Jumlah alokasi tidak boleh NaN atau Infinity."],
        )


@override_settings(FEATURE_ALLOCATION_UI_ENABLED=True)
class AllocationAdminTest(TestCase):
    def setUp(self):
        self.fixtures = _create_test_fixtures()
        self.request = RequestFactory().get("/admin/allocation/")
        self.request.user = self.fixtures["admin"]

    def test_workflow_fields_are_not_editable(self):
        form = AllocationAdmin(Allocation, admin.site).get_form(self.request)

        for field_name in {
            "document_number",
            "status",
            "submitted_by",
            "submitted_at",
            "approved_by",
            "approved_at",
            "rejection_reason",
        }:
            self.assertNotIn(field_name, form.base_fields)

    def test_allocation_and_related_rows_are_locked_after_draft(self):
        allocation = _create_allocation(
            self.fixtures,
            status=Allocation.Status.SUBMITTED,
        )
        allocation_item = allocation.items.get()
        allocation_admin = AllocationAdmin(Allocation, admin.site)
        item_admin = AllocationItemAdmin(AllocationItem, admin.site)

        self.assertFalse(allocation_admin.has_change_permission(self.request, allocation))
        self.assertFalse(item_admin.has_add_permission(self.request))
        self.assertFalse(item_admin.has_change_permission(self.request, allocation_item))
        self.assertFalse(item_admin.has_delete_permission(self.request, allocation_item))

        for inline_class in (
            AllocationFacilityInline,
            AllocationItemInline,
            AllocationStaffAssignmentInline,
        ):
            inline = inline_class(Allocation, admin.site)
            self.assertFalse(inline.has_add_permission(self.request, allocation))
            self.assertFalse(inline.has_change_permission(self.request, allocation))
            self.assertFalse(inline.has_delete_permission(self.request, allocation))

        facility_inline = AllocationItemFacilityInline(AllocationItem, admin.site)
        self.assertFalse(facility_inline.has_add_permission(self.request, allocation_item))
        self.assertFalse(facility_inline.has_change_permission(self.request, allocation_item))
        self.assertFalse(facility_inline.has_delete_permission(self.request, allocation_item))

    def test_admin_disables_allocation_deletion_and_bulk_delete(self):
        allocation = _create_allocation(self.fixtures)
        allocation_admin = AllocationAdmin(Allocation, admin.site)
        item_admin = AllocationItemAdmin(AllocationItem, admin.site)

        self.assertFalse(allocation_admin.has_delete_permission(self.request))
        self.assertFalse(
            allocation_admin.has_delete_permission(self.request, allocation)
        )
        self.assertNotIn("delete_selected", allocation_admin.get_actions(self.request))
        self.assertNotIn("delete_selected", item_admin.get_actions(self.request))

    def test_admin_locks_business_date_after_number_issuance(self):
        allocation = _create_allocation(self.fixtures)
        execute_allocation_submission(allocation, self.fixtures["admin"])
        execute_allocation_reset_to_draft(allocation)
        allocation.refresh_from_db()
        allocation_admin = AllocationAdmin(Allocation, admin.site)

        self.assertIn(
            "allocation_date",
            allocation_admin.get_readonly_fields(self.request, allocation),
        )


@override_settings(FEATURE_ALLOCATION_UI_ENABLED=True)
class AllocationSubmissionTest(TestCase):
    def setUp(self):
        self.fixtures = _create_test_fixtures()

    def test_submit_success(self):
        allocation = _create_allocation(self.fixtures)
        execute_allocation_submission(allocation, self.fixtures["admin"])
        allocation.refresh_from_db()
        self.assertEqual(allocation.status, Allocation.Status.SUBMITTED)
        self.assertIsNotNone(allocation.submitted_at)

    def test_repeated_submission_preserves_original_audit_metadata(self):
        allocation = _create_allocation(self.fixtures)
        first_actor = self.fixtures["admin"]
        second_actor = self.fixtures["operator"]

        execute_allocation_submission(allocation, first_actor)
        allocation.refresh_from_db()
        original_submitted_at = allocation.submitted_at
        issue = DocumentNumberIssue.objects.get(
            rule__key=DocumentNumberRule.Key.ALLOCATION,
            object_id=allocation.pk,
        )
        original_issued_at = issue.issued_at

        with self.assertRaisesMessage(
            AllocationWorkflowError,
            "Hanya alokasi berstatus Draft yang dapat diajukan.",
        ):
            execute_allocation_submission(allocation, second_actor)

        allocation.refresh_from_db()
        issue.refresh_from_db()
        self.assertEqual(allocation.status, Allocation.Status.SUBMITTED)
        self.assertEqual(allocation.submitted_by, first_actor)
        self.assertEqual(allocation.submitted_at, original_submitted_at)
        self.assertEqual(issue.issued_by, first_actor)
        self.assertEqual(issue.issued_at, original_issued_at)

    def test_numbered_allocation_form_ignores_changed_business_date(self):
        allocation = _create_allocation(self.fixtures)
        execute_allocation_submission(allocation, self.fixtures["admin"])
        execute_allocation_reset_to_draft(allocation)
        allocation.refresh_from_db()
        original_date = allocation.allocation_date
        form = AllocationForm(
            data={
                "title": allocation.title,
                "referensi": allocation.referensi,
                "allocation_date": "2025-07-01",
                "notes": allocation.notes,
            },
            instance=allocation,
        )

        self.assertTrue(form.fields["allocation_date"].disabled)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        allocation.refresh_from_db()
        self.assertEqual(allocation.allocation_date, original_date)

        draft_form = AllocationForm(instance=_create_allocation(self.fixtures))
        self.assertFalse(draft_form.fields["allocation_date"].disabled)

    def test_submit_no_items_fails(self):
        allocation = Allocation.objects.create(
            title="Alokasi Tanpa Item",
            allocation_date="2025-06-01",
            created_by=self.fixtures["admin"],
        )
        AllocationFacility.objects.create(allocation=allocation, facility=self.fixtures["facility1"])
        AllocationStaffAssignment.objects.create(allocation=allocation, user=self.fixtures["operator"])

        with self.assertRaises(AllocationWorkflowError):
            execute_allocation_submission(allocation, self.fixtures["admin"])

    def test_submit_no_facilities_fails(self):
        allocation = Allocation.objects.create(
            title="Alokasi Tanpa Fasilitas",
            allocation_date="2025-06-01",
            created_by=self.fixtures["admin"],
        )
        AllocationStaffAssignment.objects.create(allocation=allocation, user=self.fixtures["operator"])
        alloc_item = AllocationItem.objects.create(
            allocation=allocation,
            item=self.fixtures["item"],
            stock=self.fixtures["stock"],
            total_qty_available=Decimal("100"),
        )
        AllocationItemFacility.objects.create(
            allocation_item=alloc_item,
            facility=self.fixtures["facility1"],
            qty_allocated=Decimal("10"),
        )
        AllocationFacility.objects.create(allocation=allocation, facility=self.fixtures["facility1"])

        # Remove the facility association — service validates selected_facilities
        allocation.selected_facilities.all().delete()

        with self.assertRaises(AllocationWorkflowError):
            execute_allocation_submission(allocation, self.fixtures["admin"])

    def test_submit_over_allocated_fails(self):
        allocation = _create_allocation(self.fixtures)
        # Make total exceed available
        alloc_item = allocation.items.first()
        fa = alloc_item.facility_allocations.first()
        fa.qty_allocated = Decimal("90")
        fa.save()

        with self.assertRaises(AllocationWorkflowError):
            execute_allocation_submission(allocation, self.fixtures["admin"])

    def test_allocation_item_form_uses_name_only_item_labels(self):
        form = AllocationItemForm()

        self.assertEqual(form.fields["item"].label_from_instance(self.fixtures["item"]), self.fixtures["item"].nama_barang)


@override_settings(FEATURE_ALLOCATION_UI_ENABLED=True)
class AllocationApprovalTest(TestCase):
    def setUp(self):
        self.fixtures = _create_test_fixtures()

    def test_approve_generates_distributions(self):
        allocation = _create_allocation(self.fixtures)
        execute_allocation_submission(allocation, self.fixtures["admin"])
        execute_allocation_approval(allocation, self.fixtures["kepala"])

        allocation.refresh_from_db()
        self.assertEqual(allocation.status, Allocation.Status.APPROVED)

        # Should have 2 distributions (one per facility)
        distributions = allocation.distributions.all()
        self.assertEqual(distributions.count(), 2)

        for dist in distributions:
            self.assertEqual(
                dist.distribution_type,
                Distribution.DistributionType.SPECIAL_REQUEST,
            )
            self.assertEqual(dist.status, Distribution.Status.VERIFIED)
            self.assertIsNotNone(dist.document_number)
            self.assertEqual(dist.verified_by, self.fixtures["kepala"])
            self.assertIsNotNone(dist.verified_at)

        self.fixtures["stock"].refresh_from_db()
        self.assertEqual(self.fixtures["stock"].reserved, Decimal("50"))

    def test_generated_children_continue_standalone_special_request_sequence(self):
        standalone = Distribution.objects.create(
            distribution_type=Distribution.DistributionType.SPECIAL_REQUEST,
            request_date="2025-06-01",
            facility=self.fixtures["facility1"],
            created_by=self.fixtures["admin"],
        )
        issue_document_number(
            DocumentNumberRule.Key.DISTRIBUTION_SPECIAL_REQUEST,
            business_date=standalone.request_date,
            target=standalone,
            actor=self.fixtures["admin"],
        )

        allocation = _create_allocation(self.fixtures)
        execute_allocation_submission(allocation, self.fixtures["admin"])
        execute_allocation_approval(allocation, self.fixtures["kepala"])

        child_numbers = list(
            allocation.distributions.order_by("document_number").values_list(
                "document_number", flat=True
            )
        )
        self.assertEqual(standalone.document_number, "440/1/KD.F/2025")
        self.assertEqual(child_numbers, ["440/2/KD.F/2025", "440/3/KD.F/2025"])

    def test_migration_repairs_only_allocation_child_issuance_metadata(self):
        standalone = Distribution.objects.create(
            distribution_type=Distribution.DistributionType.SPECIAL_REQUEST,
            request_date="2025-06-01",
            facility=self.fixtures["facility1"],
            created_by=self.fixtures["admin"],
        )
        issue_document_number(
            DocumentNumberRule.Key.DISTRIBUTION_SPECIAL_REQUEST,
            business_date=standalone.request_date,
            target=standalone,
            actor=self.fixtures["admin"],
        )

        allocation = _create_allocation(self.fixtures)
        execute_allocation_submission(allocation, self.fixtures["admin"])
        execute_allocation_approval(allocation, self.fixtures["kepala"])
        child = allocation.distributions.order_by("pk").first()
        distribution_content_type = ContentType.objects.get_for_model(Distribution)
        child_issue = DocumentNumberIssue.objects.get(
            content_type=distribution_content_type,
            object_id=child.pk,
        )
        standalone_issue = DocumentNumberIssue.objects.get(
            content_type=distribution_content_type,
            object_id=standalone.pk,
        )
        DocumentNumberIssue.objects.filter(
            pk__in=[child_issue.pk, standalone_issue.pk]
        ).update(issued_by=None, issued_at=None)

        migration = import_module(
            "apps.core.migrations.0011_repair_allocation_child_issuance_metadata"
        )
        migration.repair_allocation_child_issuance_metadata(
            django_apps,
            SimpleNamespace(connection=connection),
        )

        child_issue.refresh_from_db()
        standalone_issue.refresh_from_db()
        self.assertEqual(child_issue.issued_by, child.verified_by)
        self.assertEqual(child_issue.issued_at, child.verified_at)
        self.assertIsNone(standalone_issue.issued_by)
        self.assertIsNone(standalone_issue.issued_at)

    def test_migration_clears_only_legacy_allocation_submission_metadata(self):
        legacy_allocation = _create_allocation(self.fixtures)
        execute_allocation_submission(legacy_allocation, self.fixtures["admin"])
        legacy_issue = DocumentNumberIssue.objects.get(
            rule__key=DocumentNumberRule.Key.ALLOCATION,
            object_id=legacy_allocation.pk,
        )
        original_number = legacy_issue.document_number
        original_sequence = legacy_issue.sequence_value
        copied_submission_at = timezone.now() - timedelta(days=30)
        legacy_allocation.submitted_by = self.fixtures["operator"]
        legacy_allocation.submitted_at = copied_submission_at
        legacy_allocation.save(
            update_fields=["submitted_by", "submitted_at", "updated_at"]
        )
        DocumentNumberIssue.objects.filter(pk=legacy_issue.pk).update(
            issued_by=self.fixtures["operator"],
            issued_at=copied_submission_at,
        )

        live_allocation = _create_allocation(self.fixtures)
        execute_allocation_submission(live_allocation, self.fixtures["admin"])
        live_issue = DocumentNumberIssue.objects.get(
            rule__key=DocumentNumberRule.Key.ALLOCATION,
            object_id=live_allocation.pk,
        )
        live_allocation.submitted_at = live_issue.issued_at + timedelta(seconds=1)
        live_allocation.save(update_fields=["submitted_at", "updated_at"])

        migration = import_module(
            "apps.core.migrations.0016_clear_legacy_allocation_issuance_metadata"
        )
        migration.clear_legacy_allocation_issuance_metadata(
            django_apps,
            SimpleNamespace(connection=connection),
        )

        legacy_issue.refresh_from_db()
        live_issue.refresh_from_db()
        self.assertIsNone(legacy_issue.issued_by)
        self.assertIsNone(legacy_issue.issued_at)
        self.assertEqual(legacy_issue.document_number, original_number)
        self.assertEqual(legacy_issue.sequence_value, original_sequence)
        self.assertEqual(live_issue.issued_by, self.fixtures["admin"])
        self.assertIsNotNone(live_issue.issued_at)

    def test_approve_copies_distribution_items(self):
        allocation = _create_allocation(self.fixtures)
        execute_allocation_submission(allocation, self.fixtures["admin"])
        execute_allocation_approval(allocation, self.fixtures["kepala"])

        dist_f1 = allocation.distributions.get(facility=self.fixtures["facility1"])
        dist_f2 = allocation.distributions.get(facility=self.fixtures["facility2"])

        self.assertEqual(dist_f1.items.count(), 1)
        self.assertEqual(dist_f1.items.first().quantity_requested, Decimal("30"))

        self.assertEqual(dist_f2.items.count(), 1)
        self.assertEqual(dist_f2.items.first().quantity_requested, Decimal("20"))

    def test_approve_insufficient_stock_raises(self):
        allocation = _create_allocation(self.fixtures)
        execute_allocation_submission(allocation, self.fixtures["admin"])

        # Drain stock after submission
        self.fixtures["stock"].quantity = 10
        self.fixtures["stock"].save()

        with self.assertRaises(AllocationWorkflowError):
            execute_allocation_approval(allocation, self.fixtures["kepala"])

    def test_approve_wraps_reservation_failures(self):
        allocation = Allocation.objects.create(
            title="Alokasi Double Batch",
            allocation_date="2025-06-01",
            status=Allocation.Status.DRAFT,
            created_by=self.fixtures["admin"],
        )
        AllocationFacility.objects.create(
            allocation=allocation, facility=self.fixtures["facility1"]
        )
        AllocationStaffAssignment.objects.create(
            allocation=allocation, user=self.fixtures["operator"]
        )

        first_item = AllocationItem.objects.create(
            allocation=allocation,
            item=self.fixtures["item"],
            stock=self.fixtures["stock"],
            total_qty_available=Decimal("100"),
        )
        second_item = AllocationItem.objects.create(
            allocation=allocation,
            item=self.fixtures["item"],
            stock=self.fixtures["stock"],
            total_qty_available=Decimal("100"),
        )
        AllocationItemFacility.objects.create(
            allocation_item=first_item,
            facility=self.fixtures["facility1"],
            qty_allocated=Decimal("60"),
        )
        AllocationItemFacility.objects.create(
            allocation_item=second_item,
            facility=self.fixtures["facility1"],
            qty_allocated=Decimal("60"),
        )

        execute_allocation_submission(allocation, self.fixtures["admin"])

        with self.assertRaises(AllocationWorkflowError):
            execute_allocation_approval(allocation, self.fixtures["kepala"])

        allocation.refresh_from_db()
        self.fixtures["stock"].refresh_from_db()
        self.assertEqual(allocation.status, Allocation.Status.SUBMITTED)
        self.assertEqual(self.fixtures["stock"].reserved, Decimal("0"))
        self.assertEqual(allocation.distributions.count(), 0)

    def test_step_back_to_submitted_removes_generated_distributions(self):
        allocation = _create_allocation(self.fixtures)
        execute_allocation_submission(allocation, self.fixtures["admin"])
        execute_allocation_approval(allocation, self.fixtures["kepala"])

        self.assertEqual(allocation.distributions.count(), 2)

        execute_allocation_step_back_to_submitted(allocation)

        allocation.refresh_from_db()
        self.fixtures["stock"].refresh_from_db()
        self.assertEqual(allocation.status, Allocation.Status.SUBMITTED)
        self.assertIsNone(allocation.approved_by)
        self.assertIsNone(allocation.approved_at)
        self.assertEqual(allocation.distributions.count(), 0)
        self.assertEqual(self.fixtures["stock"].reserved, Decimal("0"))


@override_settings(FEATURE_ALLOCATION_UI_ENABLED=True)
class AllocationRejectionTest(TestCase):
    def setUp(self):
        self.fixtures = _create_test_fixtures()

    def test_reject_returns_to_draft(self):
        allocation = _create_allocation(self.fixtures)
        execute_allocation_submission(allocation, self.fixtures["admin"])
        execute_allocation_rejection(allocation, "Alokasi tidak sesuai.")

        allocation.refresh_from_db()
        self.assertEqual(allocation.status, Allocation.Status.DRAFT)
        self.assertEqual(allocation.rejection_reason, "Alokasi tidak sesuai.")
        self.assertIsNone(allocation.submitted_by)


@override_settings(FEATURE_ALLOCATION_UI_ENABLED=True)
class DistributionDeliveryTest(TestCase):
    def setUp(self):
        self.fixtures = _create_test_fixtures()
        self.allocation = _create_allocation(self.fixtures)
        execute_allocation_submission(self.allocation, self.fixtures["admin"])
        execute_allocation_approval(self.allocation, self.fixtures["kepala"])

    def test_prepare_distribution(self):
        dist = self.allocation.distributions.first()
        execute_distribution_preparation(dist, self.fixtures["operator"])
        dist.refresh_from_db()
        self.assertEqual(dist.status, Distribution.Status.PREPARED)

    def test_generated_distributions_store_reserved_quantity(self):
        reserved_quantities = list(
            self.allocation.distributions.order_by("facility__code").values_list(
                "items__reserved_quantity", flat=True
            )
        )
        self.assertEqual(reserved_quantities, [Decimal("30"), Decimal("20")])

    def test_deliver_deducts_stock(self):
        dist = self.allocation.distributions.get(facility=self.fixtures["facility1"])
        execute_distribution_preparation(dist, self.fixtures["operator"])
        execute_distribution_delivery(dist, self.fixtures["operator"], self.allocation)

        dist.refresh_from_db()
        self.assertEqual(dist.status, Distribution.Status.DISTRIBUTED)

        self.fixtures["stock"].refresh_from_db()
        # Original 100, allocated 30 to facility1
        self.assertEqual(self.fixtures["stock"].quantity, Decimal("70"))
        self.assertEqual(self.fixtures["stock"].reserved, Decimal("20"))

        # Transaction should be written
        self.assertTrue(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.ALLOCATION,
                reference_id=self.allocation.id,
                transaction_type=Transaction.TransactionType.OUT,
            ).exists()
        )

    def test_deliver_all_auto_closes_to_fulfilled(self):
        # Deliver both distributions
        for dist in self.allocation.distributions.all():
            execute_distribution_preparation(dist, self.fixtures["operator"])
            execute_distribution_delivery(dist, self.fixtures["operator"], self.allocation)

        self.allocation.refresh_from_db()
        self.assertEqual(self.allocation.status, Allocation.Status.FULFILLED)

    def test_partial_delivery_sets_partially_fulfilled(self):
        # Deliver only the first distribution
        dist = self.allocation.distributions.first()
        execute_distribution_preparation(dist, self.fixtures["operator"])
        execute_distribution_delivery(dist, self.fixtures["operator"], self.allocation)

        self.allocation.refresh_from_db()
        self.assertEqual(self.allocation.status, Allocation.Status.PARTIALLY_FULFILLED)

    def test_deliver_insufficient_stock_raises(self):
        dist = self.allocation.distributions.get(facility=self.fixtures["facility1"])
        execute_distribution_preparation(dist, self.fixtures["operator"])

        # Drain stock
        self.fixtures["stock"].quantity = 5
        self.fixtures["stock"].save()

        with self.assertRaises(AllocationWorkflowError):
            execute_distribution_delivery(dist, self.fixtures["operator"], self.allocation)


@override_settings(FEATURE_ALLOCATION_UI_ENABLED=True)
class AllocationRouteTest(TestCase):
    def setUp(self):
        self.fixtures = _create_test_fixtures()
        self.client.force_login(self.fixtures["admin"])

    def test_list_page_loads(self):
        response = self.client.get(reverse("allocation:allocation_list"), secure=True)
        self.assertEqual(response.status_code, 200)

    def test_create_page_loads(self):
        response = self.client.get(reverse("allocation:allocation_create"), secure=True)
        self.assertEqual(response.status_code, 200)

    def test_detail_page_loads(self):
        allocation = _create_allocation(self.fixtures)
        response = self.client.get(
            reverse("allocation:allocation_detail", args=[allocation.pk]),
            secure=True,
        )
        self.assertEqual(response.status_code, 200)

    def test_distribution_detail_routes_prepare_through_parent_allocation(self):
        allocation = _create_allocation(self.fixtures)
        execute_allocation_submission(allocation, self.fixtures["admin"])
        execute_allocation_approval(allocation, self.fixtures["kepala"])
        distribution = allocation.distributions.first()

        response = self.client.get(
            reverse("distribution:distribution_detail", args=[distribution.pk]),
            secure=True,
        )

        allocation_prepare_url = reverse(
            "allocation:allocation_distribution_prepare",
            args=[allocation.pk, distribution.pk],
        )
        generic_prepare_url = reverse(
            "distribution:distribution_prepare", args=[distribution.pk]
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'action="{allocation_prepare_url}"')
        self.assertNotContains(response, f'action="{generic_prepare_url}"')

    def test_distribution_detail_routes_delivery_through_parent_allocation(self):
        allocation = _create_allocation(self.fixtures)
        execute_allocation_submission(allocation, self.fixtures["admin"])
        execute_allocation_approval(allocation, self.fixtures["kepala"])
        distribution = allocation.distributions.first()
        execute_distribution_preparation(distribution, self.fixtures["operator"])

        response = self.client.get(
            reverse("distribution:distribution_detail", args=[distribution.pk]),
            secure=True,
        )

        allocation_delivery_url = reverse(
            "allocation:allocation_distribution_deliver",
            args=[allocation.pk, distribution.pk],
        )
        generic_delivery_url = reverse(
            "distribution:distribution_distribute", args=[distribution.pk]
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'action="{allocation_delivery_url}"')
        self.assertNotContains(response, f'action="{generic_delivery_url}"')

    def test_edit_page_loads(self):
        allocation = _create_allocation(self.fixtures)
        response = self.client.get(
            reverse("allocation:allocation_edit", args=[allocation.pk]),
            secure=True,
        )
        self.assertEqual(response.status_code, 200)

    def test_edit_non_draft_redirects(self):
        allocation = _create_allocation(self.fixtures, status=Allocation.Status.SUBMITTED)
        response = self.client.get(
            reverse("allocation:allocation_edit", args=[allocation.pk]),
            secure=True,
        )
        self.assertEqual(response.status_code, 302)

    def test_edit_reloads_row_after_concurrent_submission(self):
        allocation = _create_allocation(self.fixtures)
        alloc_item = allocation.items.get()
        stale_draft = Allocation.objects.get(pk=allocation.pk)

        execute_allocation_submission(allocation, self.fixtures["admin"])
        allocation.refresh_from_db()
        issued_number = allocation.document_number

        with patch("apps.allocation.views.get_object_or_404", return_value=stale_draft):
            response = self.client.post(
                reverse("allocation:allocation_edit", args=[allocation.pk]),
                {
                    "title": "Perubahan yang terlambat",
                    "referensi": "REF-LATE",
                    "allocation_date": "2025-07-01",
                    "notes": "Tidak boleh tersimpan",
                    "selected_facilities": [
                        str(self.fixtures["facility1"].pk),
                        str(self.fixtures["facility2"].pk),
                    ],
                    "assigned_staff": [str(self.fixtures["operator"].pk)],
                    "items-TOTAL_FORMS": "1",
                    "items-INITIAL_FORMS": "1",
                    "items-MIN_NUM_FORMS": "0",
                    "items-MAX_NUM_FORMS": "1000",
                    "items-0-id": str(alloc_item.pk),
                    "items-0-item": str(self.fixtures["item"].pk),
                    "items-0-stock": str(self.fixtures["stock"].pk),
                    "items-0-total_qty_available": "100",
                    "items-0-notes": "",
                    f"alloc_{alloc_item.pk}_{self.fixtures['facility1'].pk}": "30",
                    f"alloc_{alloc_item.pk}_{self.fixtures['facility2'].pk}": "20",
                },
                secure=True,
            )

        self.assertEqual(response.status_code, 302)
        allocation.refresh_from_db()
        self.assertEqual(allocation.status, Allocation.Status.SUBMITTED)
        self.assertEqual(allocation.document_number, issued_number)
        self.assertEqual(allocation.title, "Alokasi Buffer Gudang April 2026")
        self.assertEqual(str(allocation.allocation_date), "2025-06-01")

    def test_delete_draft(self):
        allocation = _create_allocation(self.fixtures)
        response = self.client.post(
            reverse("allocation:allocation_delete", args=[allocation.pk]),
            secure=True,
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Allocation.objects.filter(pk=allocation.pk).exists())

    def test_delete_approved_fails(self):
        allocation = _create_allocation(self.fixtures, status=Allocation.Status.APPROVED)
        response = self.client.post(
            reverse("allocation:allocation_delete", args=[allocation.pk]),
            secure=True,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Allocation.objects.filter(pk=allocation.pk).exists())

    def test_step_back_approved_to_submitted(self):
        allocation = _create_allocation(self.fixtures)
        execute_allocation_submission(allocation, self.fixtures["admin"])
        execute_allocation_approval(allocation, self.fixtures["admin"])

        response = self.client.post(
            reverse("allocation:allocation_step_back", args=[allocation.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        allocation.refresh_from_db()
        self.assertEqual(allocation.status, Allocation.Status.SUBMITTED)
        self.assertEqual(allocation.distributions.count(), 0)



class AllocationFrontendSecurityTest(TestCase):
    def test_review_renderer_does_not_use_dynamic_innerhtml_sink(self):
        script_path = (
            Path(__file__).resolve().parents[2] / 'static' / 'js' / 'allocation-form.js'
        )
        script = script_path.read_text(encoding='utf-8')

        self.assertNotIn('container.innerHTML = html;', script)
        self.assertIn('container.replaceChildren();', script)
