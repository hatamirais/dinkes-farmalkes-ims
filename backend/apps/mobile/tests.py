from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission
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
from apps.users.models import ModuleAccess, User


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

    def _make_item(
        self,
        *,
        code="ITM-001",
        name="Amoxicillin",
        program=True,
        minimum_stock=Decimal("10"),
    ):
        item = Item.objects.create(
            kode_barang=code,
            nama_barang=name,
            satuan=self.unit,
            kategori=self.category,
            is_program_item=program,
            program=self.program if program else None,
            minimum_stock=minimum_stock,
        )
        item.therapeutic_classes.add(self.therapeutic_class)
        return item

    def _make_stock(
        self,
        item,
        *,
        quantity=Decimal("30"),
        reserved=Decimal("5"),
        location=None,
        batch_lot="B-001",
        source_document_number="DOC-001",
    ):
        return Stock.objects.create(
            item=item,
            location=location or self.location,
            batch_lot=batch_lot,
            expiry_date=timezone.localdate() + timedelta(days=60),
            quantity=quantity,
            reserved=reserved,
            unit_price=Decimal("1000"),
            sumber_dana=self.funding_source,
            source_document_number=source_document_number,
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

    def test_debug_404_does_not_redirect_slashless_mobile_mutation(self):
        request = RequestFactory().post(reverse("mobile:home").rstrip("/"), secure=True)

        response = debug_page_not_found(request, "mobile")

        self.assertEqual(response.status_code, 404)


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


class MobileDiscoveryTests(MobileStockTestCase):
    def test_mobile_stock_page_renders_install_prompt_container(self):
        item = self._make_item()
        self._make_stock(item)
        self.client.force_login(self.user)

        response = self.client.get(reverse("mobile:stock_list"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-pwa-install', html=False)
        self.assertContains(response, "Pasang IMS Mobile")
        self.assertContains(response, 'data-pwa-install-button', html=False)

    def test_desktop_shell_links_stock_users_to_mobile_surface(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("password_change"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/mobile/"', html=False)
        self.assertContains(response, "IMS Mobile tersedia untuk cek stok")

    def test_desktop_shell_hides_mobile_link_without_stock_scope(self):
        user = User.objects.create_user(
            username="no-stock-mobile-link",
            password="TestPassword123!",
            role=User.Role.ADMIN_UMUM,
        )
        ModuleAccess.objects.update_or_create(
            user=user,
            module=ModuleAccess.Module.STOCK,
            defaults={"scope": ModuleAccess.Scope.NONE},
        )
        self.client.force_login(user)

        response = self.client.get(reverse("password_change"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'href="/mobile/"', html=False)
        self.assertNotContains(response, "IMS Mobile tersedia untuk cek stok")

    def test_desktop_shell_links_django_permission_stock_users_to_mobile_surface(self):
        user = User.objects.create_user(
            username="django-perm-mobile-link",
            password="TestPassword123!",
            role=User.Role.PUSKESMAS,
        )
        ModuleAccess.objects.update_or_create(
            user=user,
            module=ModuleAccess.Module.STOCK,
            defaults={"scope": ModuleAccess.Scope.NONE},
        )
        view_stock = Permission.objects.get(
            content_type__app_label="stock",
            codename="view_stock",
        )
        user.user_permissions.add(view_stock)
        self.client.force_login(user)

        response = self.client.get(reverse("password_change"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/mobile/"', html=False)
        self.assertContains(response, "IMS Mobile tersedia untuk cek stok")


class MobileStockListTests(MobileStockTestCase):
    def test_mobile_stock_list_groups_stock_rows_by_item(self):
        item = self._make_item()
        self._make_stock(item)
        self._make_stock(
            item,
            quantity=Decimal("10"),
            reserved=Decimal("0"),
            batch_lot="B-002",
            source_document_number="DOC-002",
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("mobile:stock_list"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "mobile/stock_list.html")
        self.assertEqual(response.context["items"].paginator.count, 1)
        self.assertContains(response, "Amoxicillin")
        self.assertContains(response, "40")
        self.assertContains(response, "35")
        self.assertContains(response, "2 batch/lokasi")
        self.assertContains(response, "Filter detail")
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

    def test_mobile_stock_search_does_not_duplicate_multi_therapy_items(self):
        respiratory_class = TherapeuticClass.objects.create(
            code="RESP",
            name="Respiratory",
        )
        item = self._make_item(name="Multi Therapy Item")
        item.therapeutic_classes.add(respiratory_class)
        self._make_stock(item, quantity=Decimal("30"), reserved=Decimal("5"))
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("mobile:stock_list"),
            {"q": "Multi Therapy"},
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        row = response.context["items"].object_list[0]
        self.assertEqual(row["total_quantity"], Decimal("30"))
        self.assertEqual(row["total_available"], Decimal("25"))
        self.assertEqual(row["batch_count"], 1)

    def test_mobile_stock_low_stock_filter_uses_item_level_totals(self):
        enough_item = self._make_item(
            code="ITM-ENOUGH",
            name="Enough Aggregate",
            minimum_stock=Decimal("10"),
        )
        low_item = self._make_item(
            code="ITM-LOW",
            name="Low Aggregate",
            minimum_stock=Decimal("10"),
        )
        self._make_stock(
            enough_item,
            quantity=Decimal("8"),
            reserved=Decimal("0"),
            batch_lot="B-001",
            source_document_number="DOC-001",
        )
        self._make_stock(
            enough_item,
            quantity=Decimal("8"),
            reserved=Decimal("0"),
            batch_lot="B-002",
            source_document_number="DOC-002",
        )
        self._make_stock(
            low_item,
            quantity=Decimal("9"),
            reserved=Decimal("0"),
            batch_lot="B-003",
            source_document_number="DOC-003",
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("mobile:stock_list"),
            {"low_stock": "1"},
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["items"].paginator.count, 1)
        self.assertContains(response, "Low Aggregate")
        self.assertNotContains(response, "Enough Aggregate")

    def test_mobile_stock_low_stock_filter_includes_depleted_items(self):
        depleted_item = self._make_item(
            code="ITM-DEPLETED",
            name="Depleted Item",
            minimum_stock=Decimal("10"),
        )
        zero_row_item = self._make_item(
            code="ITM-ZERO",
            name="Zero Row Item",
            minimum_stock=Decimal("10"),
        )
        self._make_stock(
            zero_row_item,
            quantity=Decimal("0"),
            reserved=Decimal("0"),
            batch_lot="B-ZERO",
            source_document_number="DOC-ZERO",
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("mobile:stock_list"),
            {"low_stock": "1"},
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Depleted Item")
        self.assertContains(response, "Zero Row Item")

        rows = {
            row["item__nama_barang"]: row
            for row in response.context["items"].object_list
        }
        self.assertEqual(rows["Depleted Item"]["total_available"], Decimal("0"))
        self.assertEqual(rows["Zero Row Item"]["batch_count"], 0)

    def test_mobile_stock_rejects_null_byte_foreign_key_filter(self):
        item = self._make_item()
        self._make_stock(item)
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("mobile:stock_list"),
            {"location": f"{self.location.pk}\x00"},
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_location"], "")

    def test_mobile_stock_rejects_overlong_filter_values(self):
        program_item = self._make_item(
            code="ITM-PROGRAM",
            name="Program Item",
            minimum_stock=Decimal("10"),
        )
        regular_item = self._make_item(
            code="ITM-REGULAR",
            name="Regular Item",
            program=False,
            minimum_stock=Decimal("1"),
        )
        self._make_stock(
            program_item,
            quantity=Decimal("5"),
            reserved=Decimal("0"),
            source_document_number="DOC-PROGRAM",
        )
        self._make_stock(
            regular_item,
            quantity=Decimal("20"),
            reserved=Decimal("0"),
            source_document_number="DOC-REGULAR",
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("mobile:stock_list"),
            {
                "program": "10",
                "low_stock": "10",
                "expiry_from": "9999-12-31garbage",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["items"].paginator.count, 2)
        self.assertEqual(response.context["selected_program"], "")
        self.assertEqual(response.context["selected_low_stock"], "")
        self.assertIsNone(response.context["expiry_from"])

    def test_mobile_stock_partial_returns_item_cards_and_pagination_headers(self):
        item = self._make_item(name="Partial Item")
        self._make_stock(item)
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("mobile:stock_list"),
            {"partial": "1", "q": "Partial"},
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Partial Item")
        self.assertContains(response, 'href="/mobile/stocks/', html=False)
        self.assertNotContains(response, "??", html=False)
        self.assertEqual(response["X-Result-Count"], "1")
        self.assertEqual(response["X-Entry-Count"], "1")
        self.assertEqual(response["X-Has-Next"], "0")


class MobileStockCardTests(MobileStockTestCase):
    def test_mobile_stock_card_renders_batch_level_stock_data(self):
        item = self._make_item()
        second_location = Location.objects.create(code="KAR", name="Karantina")
        self._make_stock(item, quantity=Decimal("30"), reserved=Decimal("5"))
        self._make_stock(
            item,
            quantity=Decimal("12"),
            reserved=Decimal("0"),
            location=second_location,
            batch_lot="B-002",
            source_document_number="DOC-002",
        )
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
        self.assertContains(response, "Amoxicillin")
        self.assertContains(response, "DAU")
        self.assertContains(response, "30")
        self.assertContains(response, "Karantina")
        self.assertContains(response, "DOC-002")

    def test_mobile_stock_card_back_link_preserves_list_filters(self):
        item = self._make_item()
        self._make_stock(item)
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("mobile:stock_card", args=[item.pk]),
            {
                "q": "Amox",
                "quick": "expired",
                "location": str(self.location.pk),
                "page": "3",
                "partial": "1",
            },
            secure=True,
        )

        expected_url = (
            f"{reverse('mobile:stock_list')}"
            f"?q=Amox&quick=expired&location={self.location.pk}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["stock_list_return_url"], expected_url)
        self.assertContains(
            response,
            f'href="{expected_url.replace("&", "&amp;")}"',
            html=False,
        )
