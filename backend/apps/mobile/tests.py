from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.core.views import debug_page_not_found
from apps.distribution.models import Distribution, DistributionItem
from apps.expired.models import Expired, ExpiredItem
from apps.items.models import (
    Category,
    Facility,
    FundingSource,
    Item,
    Location,
    Program,
    TherapeuticClass,
    Unit,
)
from apps.stock.models import Stock, Transaction
from apps.users.access import ensure_default_module_access
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
        funding_source=None,
    ):
        return Stock.objects.create(
            item=item,
            location=location or self.location,
            batch_lot=batch_lot,
            expiry_date=timezone.localdate() + timedelta(days=60),
            quantity=quantity,
            reserved=reserved,
            unit_price=Decimal("1000"),
            sumber_dana=funding_source or self.funding_source,
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
        self.assertNotContains(response, "Log Transaksi")
        self.assertNotContains(response, "Mutasi Lokasi")


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


class MobileApprovalTests(MobileStockTestCase):
    def setUp(self):
        super().setUp()
        self.facility = Facility.objects.create(code="PKM-MOB", name="Puskesmas Mobile")
        self.kepala = User.objects.create_user(
            username="kepala-mobile",
            password="TestPassword123!",
            role=User.Role.KEPALA,
        )
        ensure_default_module_access(self.kepala, overwrite=True)
        self.item = self._make_item()
        self.stock = self._make_stock(
            self.item,
            quantity=Decimal("30"),
            reserved=Decimal("0"),
        )

    def _make_distribution(
        self,
        *,
        distribution_type=Distribution.DistributionType.SPECIAL_REQUEST,
    ):
        distribution = Distribution.objects.create(
            distribution_type=distribution_type,
            request_date=timezone.localdate(),
            facility=self.facility,
            status=Distribution.Status.SUBMITTED,
            created_by=self.user,
        )
        DistributionItem.objects.create(
            distribution=distribution,
            item=self.item,
            quantity_requested=Decimal("6"),
            quantity_approved=Decimal("5"),
            stock=self.stock,
        )
        distribution.staff_assignments.create(user=self.user)
        return distribution

    def _make_expired(self):
        expired_document = Expired.objects.create(
            report_date=timezone.localdate(),
            status=Expired.Status.SUBMITTED,
            created_by=self.user,
        )
        ExpiredItem.objects.create(
            expired=expired_document,
            item=self.item,
            stock=self.stock,
            quantity=Decimal("4"),
            notes="Melewati tanggal kedaluwarsa",
        )
        return expired_document

    def _remove_stock_access(self):
        ModuleAccess.objects.update_or_create(
            user=self.kepala,
            module=ModuleAccess.Module.STOCK,
            defaults={"scope": ModuleAccess.Scope.NONE},
        )

    def test_approval_only_kepala_can_discover_and_launch_mobile_inbox(self):
        self._remove_stock_access()
        self.assertFalse(self.kepala.has_perm("stock.view_stock"))
        self.client.force_login(self.kepala)

        desktop = self.client.get(reverse("password_change"), secure=True)
        home = self.client.get(reverse("mobile:home"), secure=True)
        inbox = self.client.get(reverse("mobile:approval_inbox"), secure=True)
        stock = self.client.get(reverse("mobile:stock_list"), secure=True)
        manifest = self.client.get(reverse("mobile:manifest"), secure=True)

        self.assertContains(desktop, 'href="/mobile/"', html=False)
        self.assertContains(desktop, "IMS Mobile tersedia untuk persetujuan")
        self.assertEqual(home.status_code, 302)
        self.assertEqual(home["Location"], reverse("mobile:approval_inbox"))
        self.assertEqual(inbox.status_code, 200)
        self.assertContains(inbox, 'class="mobile-brand" href="/mobile/"', html=False)
        self.assertEqual(stock.status_code, 403)
        self.assertEqual(manifest.json()["start_url"], reverse("mobile:home"))

    def test_expired_only_kepala_uses_approval_entry_point(self):
        self._remove_stock_access()
        ModuleAccess.objects.update_or_create(
            user=self.kepala,
            module=ModuleAccess.Module.DISTRIBUTION,
            defaults={"scope": ModuleAccess.Scope.NONE},
        )
        self.client.force_login(self.kepala)

        home = self.client.get(reverse("mobile:home"), secure=True)
        inbox = self.client.get(reverse("mobile:approval_inbox"), secure=True)

        self.assertEqual(home.status_code, 302)
        self.assertEqual(home["Location"], reverse("mobile:approval_inbox"))
        self.assertEqual(inbox.status_code, 200)
        self.assertTrue(inbox.context["mobile_approval_access"]["expired"])
        self.assertFalse(inbox.context["mobile_approval_access"]["distribution"])

    def test_mobile_home_keeps_stock_as_default_when_user_can_see_both(self):
        self.client.force_login(self.kepala)

        response = self.client.get(reverse("mobile:home"), secure=True)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("mobile:stock_list"))

    def test_mobile_home_denies_user_without_stock_or_approval_access(self):
        user = User.objects.create_user(
            username="mobile-no-access",
            password="TestPassword123!",
            role=User.Role.PUSKESMAS,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("mobile:home"), secure=True)

        self.assertEqual(response.status_code, 403)

    def test_distribution_inbox_query_count_does_not_grow_per_card(self):
        self._make_distribution()
        ModuleAccess.objects.update_or_create(
            user=self.kepala,
            module=ModuleAccess.Module.EXPIRED,
            defaults={"scope": ModuleAccess.Scope.NONE},
        )
        self.client.force_login(self.kepala)

        with CaptureQueriesContext(connection) as one_card_queries:
            one_card = self.client.get(reverse("mobile:approval_inbox"), secure=True)

        for _ in range(19):
            self._make_distribution()

        with CaptureQueriesContext(connection) as twenty_card_queries:
            twenty_cards = self.client.get(reverse("mobile:approval_inbox"), secure=True)

        self.assertEqual(one_card.status_code, 200)
        self.assertEqual(twenty_cards.status_code, 200)
        self.assertEqual(len(one_card_queries), len(twenty_card_queries))
        self.assertContains(twenty_cards, "1 item", count=20)

    def test_approval_inbox_requires_kepala_admin_role_and_approve_scope(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("mobile:approval_inbox"), secure=True)

        self.assertEqual(response.status_code, 403)

    def test_custom_non_kepala_approver_cannot_open_inbox(self):
        ModuleAccess.objects.update_or_create(
            user=self.user,
            module=ModuleAccess.Module.DISTRIBUTION,
            defaults={"scope": ModuleAccess.Scope.APPROVE},
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("mobile:approval_inbox"), secure=True)

        self.assertEqual(response.status_code, 403)

    def test_inbox_groups_actionable_documents_and_excludes_allocation_children(self):
        distribution = self._make_distribution()
        expired_document = self._make_expired()
        allocation = self._make_distribution(
            distribution_type=Distribution.DistributionType.ALLOCATION
        )
        self.client.force_login(self.kepala)

        response = self.client.get(reverse("mobile:approval_inbox"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "mobile/approval_inbox.html")
        self.assertContains(response, distribution.document_number)
        self.assertContains(response, expired_document.document_number)
        self.assertNotContains(response, allocation.document_number)
        self.assertEqual(response.context["mobile_pending_approval_count"], 2)

    def test_inbox_hides_module_when_kepala_scope_is_downgraded(self):
        distribution = self._make_distribution()
        expired_document = self._make_expired()
        ModuleAccess.objects.update_or_create(
            user=self.kepala,
            module=ModuleAccess.Module.EXPIRED,
            defaults={"scope": ModuleAccess.Scope.NONE},
        )
        self.client.force_login(self.kepala)

        response = self.client.get(reverse("mobile:approval_inbox"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, distribution.document_number)
        self.assertNotContains(response, expired_document.document_number)
        self.assertFalse(response.context["mobile_approval_access"]["expired"])

    def test_distribution_approval_detail_preserves_fractional_quantities(self):
        distribution = self._make_distribution()
        line = distribution.items.get()
        line.quantity_requested = Decimal("1.50")
        line.quantity_approved = Decimal("0.40")
        line.save(update_fields=["quantity_requested", "quantity_approved"])
        self.client.force_login(self.kepala)

        response = self.client.get(
            reverse("mobile:distribution_approval_detail", args=[distribution.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1,50")
        self.assertContains(response, "0,40")
        self.assertContains(response, "30,00")

    def test_expired_approval_detail_preserves_fractional_quantities(self):
        expired_document = self._make_expired()
        line = expired_document.items.get()
        line.quantity = Decimal("0.40")
        line.save(update_fields=["quantity"])
        self.client.force_login(self.kepala)

        response = self.client.get(
            reverse("mobile:expired_approval_detail", args=[expired_document.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "0,40", count=2)
        self.assertContains(response, "30,00")

    def test_distribution_approval_shows_and_reserves_selected_source_layer(self):
        other_funding = FundingSource.objects.create(
            code="DAK", name="Dana Alokasi Khusus"
        )
        selected_stock = self._make_stock(
            self.item,
            quantity=Decimal("30"),
            reserved=Decimal("0"),
            source_document_number="DOC-002",
            funding_source=other_funding,
        )
        distribution = self._make_distribution()
        line = distribution.items.get()
        line.stock = selected_stock
        line.save(update_fields=["stock"])
        self.client.force_login(self.kepala)

        detail = self.client.get(
            reverse("mobile:distribution_approval_detail", args=[distribution.pk]),
            secure=True,
        )
        approval = self.client.post(
            reverse("mobile:distribution_approve", args=[distribution.pk]),
            secure=True,
        )

        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Sumber dana: DAK · Dana Alokasi Khusus")
        self.assertContains(detail, "Dokumen asal: DOC-002")
        self.assertNotContains(detail, "Dokumen asal: DOC-001")
        self.assertEqual(approval.status_code, 302)
        selected_stock.refresh_from_db()
        self.stock.refresh_from_db()
        self.assertEqual(selected_stock.reserved, Decimal("5"))
        self.assertEqual(self.stock.reserved, Decimal("0"))

    def test_expired_approval_shows_and_deducts_selected_source_layer(self):
        other_funding = FundingSource.objects.create(
            code="DAK", name="Dana Alokasi Khusus"
        )
        selected_stock = self._make_stock(
            self.item,
            quantity=Decimal("30"),
            reserved=Decimal("0"),
            source_document_number="DOC-002",
            funding_source=other_funding,
        )
        expired_document = self._make_expired()
        line = expired_document.items.get()
        line.stock = selected_stock
        line.save(update_fields=["stock"])
        self.client.force_login(self.kepala)

        detail = self.client.get(
            reverse("mobile:expired_approval_detail", args=[expired_document.pk]),
            secure=True,
        )
        approval = self.client.post(
            reverse("mobile:expired_approve", args=[expired_document.pk]),
            secure=True,
        )

        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Sumber dana: DAK · Dana Alokasi Khusus")
        self.assertContains(detail, "Dokumen asal: DOC-002")
        self.assertNotContains(detail, "Dokumen asal: DOC-001")
        self.assertEqual(approval.status_code, 302)
        selected_stock.refresh_from_db()
        self.stock.refresh_from_db()
        self.assertEqual(selected_stock.quantity, Decimal("26"))
        self.assertEqual(self.stock.quantity, Decimal("30"))

    def test_distribution_approval_reserves_stock_and_records_kepala(self):
        distribution = self._make_distribution()
        self.client.force_login(self.kepala)

        response = self.client.post(
            reverse("mobile:distribution_approve", args=[distribution.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            reverse("mobile:distribution_approval_detail", args=[distribution.pk]),
        )
        distribution.refresh_from_db()
        self.stock.refresh_from_db()
        self.assertEqual(distribution.status, Distribution.Status.VERIFIED)
        self.assertEqual(distribution.verified_by, self.kepala)
        self.assertEqual(self.stock.quantity, Decimal("30"))
        self.assertEqual(self.stock.reserved, Decimal("5"))
        self.assertFalse(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.DISTRIBUTION,
                reference_id=distribution.pk,
            ).exists()
        )

    def test_distribution_rejection_returns_document_to_petugas(self):
        distribution = self._make_distribution()
        self.client.force_login(self.kepala)

        response = self.client.post(
            reverse("mobile:distribution_reject", args=[distribution.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        distribution.refresh_from_db()
        self.assertEqual(distribution.status, Distribution.Status.REJECTED)

    def test_expired_approval_deducts_stock_once_and_creates_out_transaction(self):
        expired_document = self._make_expired()
        self.client.force_login(self.kepala)
        approval_url = reverse("mobile:expired_approve", args=[expired_document.pk])

        first_response = self.client.post(approval_url, secure=True)
        second_response = self.client.post(approval_url, secure=True)

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 302)
        expired_document.refresh_from_db()
        self.stock.refresh_from_db()
        self.assertEqual(expired_document.status, Expired.Status.VERIFIED)
        self.assertEqual(expired_document.verified_by, self.kepala)
        self.assertEqual(self.stock.quantity, Decimal("26"))
        self.assertEqual(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.EXPIRED,
                reference_id=expired_document.pk,
            ).count(),
            1,
        )

    def test_mobile_approval_actions_are_post_only(self):
        distribution = self._make_distribution()
        expired_document = self._make_expired()
        self.client.force_login(self.kepala)

        urls = [
            reverse("mobile:distribution_approve", args=[distribution.pk]),
            reverse("mobile:distribution_reject", args=[distribution.pk]),
            reverse("mobile:expired_approve", args=[expired_document.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url, secure=True)
                self.assertEqual(response.status_code, 405)
