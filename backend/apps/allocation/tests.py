from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.allocation.forms import AllocationItemForm
from apps.distribution.models import Distribution
from apps.items.models import Category, Facility, FundingSource, Item, Location, Unit
from apps.stock.models import Stock, Transaction
from apps.users.models import User

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
    execute_allocation_submission,
    execute_allocation_step_back_to_submitted,
    execute_distribution_delivery,
    execute_distribution_preparation,
)


def _create_test_fixtures():
    """Set up common master data, stock, and users for allocation tests."""
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

    def test_document_number_auto_generated(self):
        allocation = Allocation.objects.create(
            title="Alokasi Uji",
            allocation_date="2025-06-01",
            created_by=self.fixtures["admin"],
        )
        self.assertTrue(allocation.document_number.startswith("ALK-"))

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
class AllocationSubmissionTest(TestCase):
    def setUp(self):
        self.fixtures = _create_test_fixtures()

    def test_submit_success(self):
        allocation = _create_allocation(self.fixtures)
        execute_allocation_submission(allocation, self.fixtures["admin"])
        allocation.refresh_from_db()
        self.assertEqual(allocation.status, Allocation.Status.SUBMITTED)
        self.assertIsNotNone(allocation.submitted_at)

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
            self.assertEqual(dist.distribution_type, Distribution.DistributionType.ALLOCATION)
            self.assertEqual(dist.status, Distribution.Status.VERIFIED)
            self.assertIsNotNone(dist.document_number)
            self.assertEqual(dist.verified_by, self.fixtures["kepala"])
            self.assertIsNotNone(dist.verified_at)

        self.fixtures["stock"].refresh_from_db()
        self.assertEqual(self.fixtures["stock"].reserved, Decimal("50"))

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
        response = self.client.get(reverse("allocation:allocation_list"))
        self.assertEqual(response.status_code, 200)

    def test_create_page_loads(self):
        response = self.client.get(reverse("allocation:allocation_create"))
        self.assertEqual(response.status_code, 200)

    def test_detail_page_loads(self):
        allocation = _create_allocation(self.fixtures)
        response = self.client.get(
            reverse("allocation:allocation_detail", args=[allocation.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_edit_page_loads(self):
        allocation = _create_allocation(self.fixtures)
        response = self.client.get(
            reverse("allocation:allocation_edit", args=[allocation.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_edit_non_draft_redirects(self):
        allocation = _create_allocation(self.fixtures, status=Allocation.Status.SUBMITTED)
        response = self.client.get(
            reverse("allocation:allocation_edit", args=[allocation.pk])
        )
        self.assertEqual(response.status_code, 302)

    def test_delete_draft(self):
        allocation = _create_allocation(self.fixtures)
        response = self.client.post(
            reverse("allocation:allocation_delete", args=[allocation.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Allocation.objects.filter(pk=allocation.pk).exists())

    def test_delete_approved_fails(self):
        allocation = _create_allocation(self.fixtures, status=Allocation.Status.APPROVED)
        response = self.client.post(
            reverse("allocation:allocation_delete", args=[allocation.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Allocation.objects.filter(pk=allocation.pk).exists())

    def test_step_back_approved_to_submitted(self):
        allocation = _create_allocation(self.fixtures)
        execute_allocation_submission(allocation, self.fixtures["admin"])
        execute_allocation_approval(allocation, self.fixtures["admin"])

        response = self.client.post(
            reverse("allocation:allocation_step_back", args=[allocation.pk])
        )

        self.assertEqual(response.status_code, 302)
        allocation.refresh_from_db()
        self.assertEqual(allocation.status, Allocation.Status.SUBMITTED)
        self.assertEqual(allocation.distributions.count(), 0)
