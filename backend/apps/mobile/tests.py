from datetime import timedelta
from decimal import Decimal

from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.views import debug_page_not_found
from apps.items.models import (
    Category,
    FundingSource,
    Item,
    Location,
    Program,
    TherapeuticClass,
    Unit,
)
from apps.stock.models import Stock, Transaction
from apps.users.models import User


class MobileStockTestCase(TestCase):
    def setUp(self):
        self.unit = Unit.objects.create(code="TAB", name="Tablet")
        self.category = Category.objects.create(code="MED", name="Obat", sort_order=1)
        self.location = Location.objects.create(code="GUD", name="Gudang Farmasi")
        self.funding_source = FundingSource.objects.create(code="DAU", name="DAU")
        self.program = Program.objects.create(code="TB", name="Tuberkulosis")
        self.therapeutic_class = TherapeuticClass.objects.create(
            code="ABX",
            name="Antibiotik",
        )
        self.user = User.objects.create_user(
            username="gudang-mobile",
            password="TestPassword123!",
            role=User.Role.GUDANG,
        )

    def _make_item(self, *, code="ITM-001", name="Amoxicillin", program=True):
        item = Item.objects.create(
            kode_barang=code,
            nama_barang=name,
            satuan=self.unit,
            kategori=self.category,
            is_program_item=program,
            program=self.program if program else None,
            minimum_stock=Decimal("10"),
        )
        item.therapeutic_classes.add(self.therapeutic_class)
        return item

    def _make_stock(self, item, *, quantity=Decimal("30"), reserved=Decimal("5")):
        return Stock.objects.create(
            item=item,
            location=self.location,
            batch_lot="B-001",
            expiry_date=timezone.localdate() + timedelta(days=60),
            quantity=quantity,
            reserved=reserved,
            unit_price=Decimal("1000"),
            sumber_dana=self.funding_source,
            source_document_number="DOC-001",
        )


class RetiredReportingApiRouteTests(TestCase):
    def test_reporting_api_routes_are_not_exposed(self):
        removed_paths = [
            "/api/schema/",
            "/api/docs/swagger/",
            "/api/docs/redoc/",
            "/api/v1/reporting/stocks/latest/",
            "/api/v1/reporting/puskesmas-stocks/latest/",
        ]

        for path in removed_paths:
            with self.subTest(path=path):
                response = self.client.get(path, secure=True)
                self.assertEqual(response.status_code, 404)


class MobileEntryPointRedirectTests(TestCase):
    def test_debug_404_redirects_mobile_entrypoint_to_trailing_slash(self):
        request = RequestFactory().get(reverse("mobile:home").rstrip("/"), secure=True)

        response = debug_page_not_found(request, "mobile")

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], reverse("mobile:home"))


class MobileStockAccessTests(MobileStockTestCase):
    def test_mobile_stock_requires_login(self):
        response = self.client.get(reverse("mobile:stock_list"), secure=True)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_mobile_stock_requires_stock_view_scope(self):
        user = User.objects.create_user(
            username="puskesmas-mobile",
            password="TestPassword123!",
            role=User.Role.PUSKESMAS,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("mobile:stock_list"), secure=True)

        self.assertEqual(response.status_code, 403)


class MobileStockListTests(MobileStockTestCase):
    def test_mobile_stock_list_renders_stock_cards_with_available_quantity(self):
        item = self._make_item()
        self._make_stock(item)
        self.client.force_login(self.user)

        response = self.client.get(reverse("mobile:stock_list"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "mobile/stock_list.html")
        self.assertContains(response, "Amoxicillin")
        self.assertContains(response, "25")
        self.assertContains(response, "Kartu stok")

    def test_mobile_stock_list_filters_by_program_and_therapeutic_class(self):
        included = self._make_item(code="ITM-IN", name="Included Item")
        excluded = self._make_item(code="ITM-OUT", name="Excluded Item", program=False)
        self._make_stock(included)
        self._make_stock(excluded)
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("mobile:stock_list"),
            {
                "program": "1",
                "therapeutic_class": str(self.therapeutic_class.pk),
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Included Item")
        self.assertNotContains(response, "Excluded Item")


class MobileStockCardTests(MobileStockTestCase):
    def test_mobile_stock_card_renders_existing_stock_card_data(self):
        item = self._make_item()
        self._make_stock(item)
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=item,
            location=self.location,
            batch_lot="B-001",
            source_document_number="DOC-001",
            quantity=Decimal("30"),
            unit_price=Decimal("1000"),
            sumber_dana=self.funding_source,
            reference_type=Transaction.ReferenceType.INITIAL_IMPORT,
            reference_id=1,
            user=self.user,
            notes="Initial stock",
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("mobile:stock_card", args=[item.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "mobile/stock_card.html")
        self.assertContains(response, "Kartu Stok")
        self.assertContains(response, "DAU")
        self.assertContains(response, "30")
