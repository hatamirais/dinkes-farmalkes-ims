from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import ProgrammingError
from django.test import TestCase
from django.test import SimpleTestCase
from django.test import RequestFactory
from django.test import override_settings
from django.template import Context, Template
from django.urls import resolve, reverse
from django.utils import timezone

from apps.core.context_processors import nav_notifications
from apps.core.forms import SystemSettingsForm
from apps.core.models import SystemSettings
from apps.core.templatetags.number_format import safe_media_url
from apps.core.views import (
    bad_request,
    maintenance_mode,
    page_not_found_handler,
    permission_denied_handler,
)
from apps.core.versioning import DEFAULT_VERSION, SemanticVersion, read_version, write_version
from apps.distribution.models import Distribution
from apps.items.models import Category, Facility, FundingSource, Item, Location, Unit
from apps.lplpo.models import LPLPO
from apps.puskesmas.models import PuskesmasRequest
from apps.receiving.models import Receiving
from apps.stock.models import Stock, Transaction
from apps.users.models import ModuleAccess, User


class SemanticVersionTests(SimpleTestCase):
    def test_parse_valid_semver(self):
        parsed = SemanticVersion.parse("2.4.9")
        self.assertEqual(parsed.major, 2)
        self.assertEqual(parsed.minor, 4)
        self.assertEqual(parsed.patch, 9)

    def test_parse_rejects_invalid_semver(self):
        with self.assertRaisesMessage(ValueError, "Invalid semantic version"):
            SemanticVersion.parse("1.0")

    def test_bump_rules(self):
        initial = SemanticVersion.parse("3.7.8")
        self.assertEqual(str(initial.bump_major()), "4.0.0")
        self.assertEqual(str(initial.bump_minor()), "3.8.0")
        self.assertEqual(str(initial.bump_patch()), "3.7.9")

    def test_read_missing_file_uses_default(self):
        with TemporaryDirectory() as temp_dir:
            version_file = Path(temp_dir) / "VERSION"
            self.assertEqual(str(read_version(version_file)), DEFAULT_VERSION)

    def test_write_and_read_round_trip(self):
        with TemporaryDirectory() as temp_dir:
            version_file = Path(temp_dir) / "VERSION"
            expected = SemanticVersion.parse("1.2.3")

            write_version(version_file, expected)

            self.assertEqual(str(read_version(version_file)), "1.2.3")


class SafeMediaUrlFilterTests(SimpleTestCase):
    def test_allows_root_relative_url(self):
        self.assertEqual(safe_media_url("/media/settings/logo.png"), "/media/settings/logo.png")

    def test_rejects_https_url(self):
        self.assertEqual(safe_media_url("https://example.com/logo.png"), "")

    def test_rejects_http_url(self):
        self.assertEqual(safe_media_url("http://example.com/logo.png"), "")

    def test_rejects_javascript_scheme(self):
        self.assertEqual(safe_media_url("javascript:alert(1)"), "")

    def test_rejects_protocol_relative_url(self):
        self.assertEqual(safe_media_url("//example.com/logo.png"), "")

    def test_returns_empty_for_none(self):
        self.assertEqual(safe_media_url(None), "")

    def test_returns_empty_for_blank(self):
        self.assertEqual(safe_media_url(""), "")

    def test_returns_empty_for_whitespace(self):
        self.assertEqual(safe_media_url("   "), "")

    def test_returns_empty_for_data_uri(self):
        self.assertEqual(safe_media_url("data:image/png;base64,abc123"), "")

    def test_rejects_ftp_scheme(self):
        self.assertEqual(safe_media_url("ftp://example.com/logo.png"), "")

    def test_root_relative_with_special_chars(self):
        self.assertEqual(
            safe_media_url("/media/settings/my-logo_v2.png"),
            "/media/settings/my-logo_v2.png",
        )


class SystemSettingsFormTests(SimpleTestCase):
    def test_accepts_valid_numbering_templates(self):
        form = SystemSettingsForm(
            data={
                "platform_label": "Healthcare IMS",
                "facility_name": "Instalasi Farmasi",
                "facility_address": "",
                "facility_phone": "",
                "header_title": "Dinas Kesehatan",
                "lplpo_distribution_number_template": "440/{seq}/SBBK.RF/{year}",
                "special_request_distribution_number_template": "PK/{year}/{seq}/KD.F",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_rejects_unknown_numbering_placeholder(self):
        form = SystemSettingsForm(
            data={
                "platform_label": "Healthcare IMS",
                "facility_name": "Instalasi Farmasi",
                "facility_address": "",
                "facility_phone": "",
                "header_title": "Dinas Kesehatan",
                "lplpo_distribution_number_template": "440/{seq}/{month}/SBBK.RF/{year}",
                "special_request_distribution_number_template": "440/{seq}/KD.F/{year}",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("lplpo_distribution_number_template", form.errors)


class SystemSettingsModelTests(TestCase):
    def test_get_settings_exposes_default_numbering_templates(self):
        settings = SystemSettings.get_settings()

        self.assertEqual(settings.lplpo_distribution_number_template, "440/{seq}/SBBK.RF/{year}")
        self.assertEqual(settings.special_request_distribution_number_template, "440/{seq}/KD.F/{year}")


class DashboardViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.facility = Facility.objects.create(
            code="PKM-A",
            name="Puskesmas A",
            facility_type=Facility.FacilityType.PUSKESMAS,
        )
        cls.other_facility = Facility.objects.create(
            code="PKM-B",
            name="Puskesmas B",
            facility_type=Facility.FacilityType.PUSKESMAS,
        )
        cls.puskesmas_user = User.objects.create_user(
            username="operator-a",
            password="TestPassword123!",
            role=User.Role.PUSKESMAS,
            facility=cls.facility,
        )

    def _set_scope(self, user, module, scope):
        ModuleAccess.objects.update_or_create(
            user=user,
            module=module,
            defaults={"scope": scope},
        )

    def test_puskesmas_dashboard_uses_facility_scoped_template(self):
        own_lplpo = LPLPO.objects.create(
            facility=self.facility,
            bulan=3,
            tahun=2026,
            status=LPLPO.Status.DRAFT,
            created_by=self.puskesmas_user,
        )
        other_lplpo = LPLPO.objects.create(
            facility=self.other_facility,
            bulan=3,
            tahun=2026,
            status=LPLPO.Status.SUBMITTED,
            created_by=self.puskesmas_user,
        )
        own_request = PuskesmasRequest.objects.create(
            facility=self.facility,
            created_by=self.puskesmas_user,
            status=PuskesmasRequest.Status.DRAFT,
        )
        other_request = PuskesmasRequest.objects.create(
            facility=self.other_facility,
            created_by=self.puskesmas_user,
            status=PuskesmasRequest.Status.SUBMITTED,
        )

        self.client.force_login(self.puskesmas_user)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard_puskesmas.html")
        self.assertEqual(response.context["facility"], self.facility)
        self.assertEqual(response.context["latest_lplpo"], own_lplpo)
        self.assertEqual(response.context["draft_lplpo_count"], 1)
        self.assertEqual(response.context["submitted_lplpo_count"], 0)
        self.assertEqual(response.context["reviewed_lplpo_count"], 0)
        self.assertEqual(list(response.context["recent_lplpos"]), [own_lplpo])
        self.assertEqual(list(response.context["recent_requests"]), [own_request])
        self.assertNotIn(other_lplpo, response.context["recent_lplpos"])
        self.assertNotIn(other_request, response.context["recent_requests"])

    def test_puskesmas_dashboard_handles_missing_facility(self):
        user = User.objects.create_user(
            username="operator-no-facility",
            password="TestPassword123!",
            role=User.Role.PUSKESMAS,
        )

        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard_puskesmas.html")
        self.assertIsNone(response.context["facility"])
        self.assertEqual(list(response.context["recent_lplpos"]), [])
        self.assertEqual(list(response.context["recent_requests"]), [])

    def test_global_dashboard_requires_stock_view_scope(self):
        user = User.objects.create_user(
            username="dashboard-blocked",
            password="TestPassword123!",
            role=User.Role.ADMIN_UMUM,
        )
        self._set_scope(user, ModuleAccess.Module.STOCK, ModuleAccess.Scope.NONE)

        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 403)
        self.assertContains(
            response,
            "Anda tidak memiliki izin untuk mengakses dashboard inventaris.",
            status_code=403,
        )

    def test_global_dashboard_hides_transaction_user_without_users_scope(self):
        viewer = User.objects.create_user(
            username="dashboard-viewer",
            password="TestPassword123!",
            role=User.Role.ADMIN_UMUM,
        )
        actor = User.objects.create_user(
            username="dashboard-actor",
            password="TestPassword123!",
            role=User.Role.GUDANG,
        )
        self._set_scope(viewer, ModuleAccess.Module.STOCK, ModuleAccess.Scope.VIEW)
        self._set_scope(viewer, ModuleAccess.Module.USERS, ModuleAccess.Scope.NONE)
        self._set_scope(viewer, ModuleAccess.Module.ADMIN_PANEL, ModuleAccess.Scope.NONE)

        unit = Unit.objects.create(code="TAB", name="Tablet")
        category = Category.objects.create(code="OBT", name="Obat")
        funding_source = FundingSource.objects.create(code="DAK", name="Dana Alokasi Khusus")
        location = Location.objects.create(code="GUD", name="Gudang Utama")
        item = Item.objects.create(
            nama_barang="Paracetamol 500mg",
            satuan=unit,
            kategori=category,
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=item,
            location=location,
            batch_lot="BATCH-001",
            quantity="10",
            unit_price="1000",
            sumber_dana=funding_source,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=1,
            user=actor,
        )

        self.client.force_login(viewer)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard.html")
        self.assertContains(response, "Paracetamol 500mg")
        self.assertNotContains(response, "dashboard-actor")
        self.assertNotContains(response, "Pengguna")

    def test_global_dashboard_total_stock_quantity_uses_available_stock(self):
        viewer = User.objects.create_user(
            username="dashboard-available-stock",
            password="TestPassword123!",
            role=User.Role.ADMIN_UMUM,
        )
        self._set_scope(viewer, ModuleAccess.Module.STOCK, ModuleAccess.Scope.VIEW)
        self._set_scope(viewer, ModuleAccess.Module.ITEMS, ModuleAccess.Scope.NONE)
        self._set_scope(viewer, ModuleAccess.Module.EXPIRED, ModuleAccess.Scope.NONE)
        self._set_scope(viewer, ModuleAccess.Module.USERS, ModuleAccess.Scope.NONE)
        self._set_scope(viewer, ModuleAccess.Module.ADMIN_PANEL, ModuleAccess.Scope.NONE)

        unit = Unit.objects.create(code="KPS", name="Kapsul")
        category = Category.objects.create(code="OBT2", name="Obat Uji")
        funding_source = FundingSource.objects.create(code="DAU", name="Dana Alokasi Umum")
        location = Location.objects.create(code="GD2", name="Gudang Cadangan")
        item = Item.objects.create(
            nama_barang="Amoxicillin 500mg",
            satuan=unit,
            kategori=category,
        )
        Stock.objects.create(
            item=item,
            location=location,
            batch_lot="BATCH-AVAILABLE-001",
            expiry_date="2026-12-31",
            quantity=Decimal("100"),
            reserved=Decimal("60"),
            unit_price=Decimal("1000"),
            sumber_dana=funding_source,
        )

        self.client.force_login(viewer)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_stock_quantity"], Decimal("40"))

    def test_global_dashboard_today_transaction_count_includes_return_transactions(self):
        viewer = User.objects.create_user(
            username="dashboard-transaction-count",
            password="TestPassword123!",
            role=User.Role.ADMIN_UMUM,
        )
        actor = User.objects.create_user(
            username="dashboard-return-actor",
            password="TestPassword123!",
            role=User.Role.GUDANG,
        )
        self._set_scope(viewer, ModuleAccess.Module.STOCK, ModuleAccess.Scope.VIEW)
        self._set_scope(viewer, ModuleAccess.Module.EXPIRED, ModuleAccess.Scope.NONE)
        self._set_scope(viewer, ModuleAccess.Module.ITEMS, ModuleAccess.Scope.NONE)
        self._set_scope(viewer, ModuleAccess.Module.USERS, ModuleAccess.Scope.NONE)
        self._set_scope(viewer, ModuleAccess.Module.ADMIN_PANEL, ModuleAccess.Scope.NONE)

        unit = Unit.objects.create(code="RET", name="Retur")
        category = Category.objects.create(code="RET", name="Retur Test")
        funding_source = FundingSource.objects.create(code="RET", name="Retur Funding")
        location = Location.objects.create(code="GDRET", name="Gudang Retur")
        item = Item.objects.create(
            nama_barang="Item Retur Dashboard",
            satuan=unit,
            kategori=category,
        )
        fixed_now = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
        today_transaction = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.RETURN,
            item=item,
            location=location,
            batch_lot="RETURN-001",
            quantity=Decimal("5"),
            unit_price=Decimal("1000"),
            sumber_dana=funding_source,
            reference_type=Transaction.ReferenceType.RECALL,
            reference_id=1,
            user=actor,
        )
        tomorrow_transaction = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.RETURN,
            item=item,
            location=location,
            batch_lot="RETURN-002",
            quantity=Decimal("3"),
            unit_price=Decimal("1000"),
            sumber_dana=funding_source,
            reference_type=Transaction.ReferenceType.RECALL,
            reference_id=2,
            user=actor,
        )
        Transaction.objects.filter(pk=today_transaction.pk).update(created_at=fixed_now)
        Transaction.objects.filter(pk=tomorrow_transaction.pk).update(
            created_at=fixed_now + timedelta(days=1)
        )

        self.client.force_login(viewer)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["today_transaction_count"], 1)
        self.assertContains(response, "Semua jenis transaksi")

    def test_global_dashboard_expiring_soon_excludes_already_expired_batches(self):
        viewer = User.objects.create_user(
            username="dashboard-expiring-soon",
            password="TestPassword123!",
            role=User.Role.ADMIN_UMUM,
        )
        self._set_scope(viewer, ModuleAccess.Module.STOCK, ModuleAccess.Scope.VIEW)
        self._set_scope(viewer, ModuleAccess.Module.EXPIRED, ModuleAccess.Scope.VIEW)
        self._set_scope(viewer, ModuleAccess.Module.ITEMS, ModuleAccess.Scope.NONE)
        self._set_scope(viewer, ModuleAccess.Module.USERS, ModuleAccess.Scope.NONE)
        self._set_scope(viewer, ModuleAccess.Module.ADMIN_PANEL, ModuleAccess.Scope.NONE)

        unit = Unit.objects.create(code="BOT", name="Botol")
        category = Category.objects.create(code="EXP", name="Expiring Test")
        funding_source = FundingSource.objects.create(code="BOK", name="Bantuan Operasional")
        location = Location.objects.create(code="GDEXP", name="Gudang Expired Test")
        expired_item = Item.objects.create(
            nama_barang="Stok Sudah Expired",
            satuan=unit,
            kategori=category,
        )
        near_expiry_item = Item.objects.create(
            nama_barang="Stok Mendekati Expired",
            satuan=unit,
            kategori=category,
        )

        today = timezone.now().date()
        Stock.objects.create(
            item=expired_item,
            location=location,
            batch_lot="EXP-OLD-001",
            expiry_date=today - timedelta(days=5),
            quantity=Decimal("10"),
            reserved=Decimal("0"),
            unit_price=Decimal("1000"),
            sumber_dana=funding_source,
        )
        near_expiry_stock = Stock.objects.create(
            item=near_expiry_item,
            location=location,
            batch_lot="EXP-SOON-001",
            expiry_date=today + timedelta(days=20),
            quantity=Decimal("12"),
            reserved=Decimal("0"),
            unit_price=Decimal("1000"),
            sumber_dana=funding_source,
        )

        self.client.force_login(viewer)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["expiring_soon_count"], 1)
        self.assertEqual(list(response.context["expiring_soon"]), [near_expiry_stock])
        self.assertContains(response, "Stok Mendekati Expired")
        self.assertNotContains(response, "Stok Sudah Expired")

    def test_global_dashboard_hides_unscoped_cards_and_actions(self):
        viewer = User.objects.create_user(
            username="dashboard-stock-only",
            password="TestPassword123!",
            role=User.Role.ADMIN_UMUM,
        )
        self._set_scope(viewer, ModuleAccess.Module.STOCK, ModuleAccess.Scope.VIEW)
        self._set_scope(viewer, ModuleAccess.Module.ITEMS, ModuleAccess.Scope.NONE)
        self._set_scope(viewer, ModuleAccess.Module.EXPIRED, ModuleAccess.Scope.NONE)
        self._set_scope(viewer, ModuleAccess.Module.RECEIVING, ModuleAccess.Scope.NONE)
        self._set_scope(viewer, ModuleAccess.Module.DISTRIBUTION, ModuleAccess.Scope.NONE)
        self._set_scope(viewer, ModuleAccess.Module.USERS, ModuleAccess.Scope.NONE)
        self._set_scope(viewer, ModuleAccess.Module.ADMIN_PANEL, ModuleAccess.Scope.NONE)

        self.client.force_login(viewer)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Total Stok Aktif")
        self.assertContains(response, 'href="/stock/transactions/"', html=False)
        self.assertNotContains(response, "Total Jenis Barang")
        self.assertNotContains(response, "Stok Rendah")
        self.assertNotContains(response, 'href="/expired/alerts/?level=all&amp;pending=1"', html=False)
        self.assertNotContains(response, "Buat Penerimaan")
        self.assertNotContains(response, "Buat Permintaan Khusus")
        self.assertNotContains(response, "Buat Mutasi Lokasi")


class ErrorPageTemplateTests(TestCase):
    def test_404_page_renders_back_and_fallback_actions(self):
        response = self.client.get("/halaman-yang-tidak-ada/")

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Kembali ke Halaman Sebelumnya", status_code=404)
        self.assertContains(response, "Buka Login", status_code=404)

    def test_403_page_keeps_same_error_layout_actions(self):
        user = User.objects.create_user(
            username="forbidden-user",
            password="TestPassword123!",
            role=User.Role.ADMIN_UMUM,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("settings"))

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Kembali ke Halaman Sebelumnya", status_code=403)
        self.assertContains(response, "Buka Dashboard", status_code=403)

    def test_admin_middleware_uses_custom_403_page(self):
        user = User.objects.create_user(
            username="admin-panel-blocked",
            password="TestPassword123!",
            role=User.Role.ADMIN_UMUM,
        )
        self.client.force_login(user)

        response = self.client.get("/admin/")

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Kembali ke Halaman Sebelumnya", status_code=403)
        self.assertContains(response, "Buka Dashboard", status_code=403)



class SystemSettingsAccessTests(TestCase):
    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("settings"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_non_admin_user_is_denied_access(self):
        user = User.objects.create_user(
            username="settings-operator",
            password="TestPassword123!",
            role=User.Role.ADMIN_UMUM,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("settings"))

        self.assertEqual(response.status_code, 403)

    def test_admin_user_sees_numbering_preview_card(self):
        user = User.objects.create_superuser(
            username="settings-admin",
            email="settings-admin@example.com",
            password="TestPassword123!",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Preview Rule")
        self.assertContains(response, "440/12/SBBK.RF/2026")
        self.assertContains(response, "440/12/KD.F/2026")


class AdministrationHistoryAccessTests(TestCase):
    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("administration_receiving_history"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_non_admin_user_is_denied_access(self):
        user = User.objects.create_user(
            username="admin-history-operator",
            password="TestPassword123!",
            role=User.Role.ADMIN_UMUM,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("administration_receiving_history"))

        self.assertEqual(response.status_code, 403)

    def test_admin_user_can_open_receiving_history_placeholder(self):
        user = User.objects.create_superuser(
            username="admin-history-admin",
            email="admin-history-admin@example.com",
            password="TestPassword123!",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("administration_receiving_history"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Riwayat Penerimaan")
        self.assertContains(response, "MVP Placeholder")
        self.assertContains(response, reverse("receiving:receiving_list"))

    def test_admin_user_can_open_distribution_history_placeholder(self):
        user = User.objects.create_superuser(
            username="admin-history-dist-admin",
            email="admin-history-dist-admin@example.com",
            password="TestPassword123!",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("administration_distribution_history"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Riwayat Pengeluaran")
        self.assertContains(response, reverse("distribution:distribution_list"))


class ErrorHandlerTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_maintenance_route_and_error_handlers_are_registered(self):
        from config import urls as root_urls

        self.assertEqual(resolve("/maintenance/").func, maintenance_mode)
        self.assertEqual(root_urls.handler400, "apps.core.views.bad_request")
        self.assertEqual(
            root_urls.handler403, "apps.core.views.permission_denied_handler"
        )
        self.assertEqual(root_urls.handler404, "apps.core.views.page_not_found_handler")
        self.assertEqual(root_urls.handler500, "apps.core.views.server_error_handler")
    def test_maintenance_mode_renders_503_template(self):
        request = self.factory.get("/maintenance/")
        request.user = AnonymousUser()

        response = maintenance_mode(request)

        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "503", status_code=503)
        self.assertContains(response, "Layanan sedang dalam perawatan", status_code=503)

    def test_bad_request_renders_400_template(self):
        request = self.factory.get("/bad-request/")
        request.user = AnonymousUser()

        response = bad_request(request, ValueError("invalid input"))

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "400", status_code=400)
        self.assertContains(response, "Permintaan tidak dapat diproses", status_code=400)

    def test_permission_denied_handler_renders_403_template(self):
        request = self.factory.get("/forbidden/")
        request.user = AnonymousUser()

        response = permission_denied_handler(request, PermissionError("forbidden"))

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "403", status_code=403)
        self.assertContains(
            response,
            "Anda tidak memiliki akses ke halaman ini",
            status_code=403,
        )

    def test_permission_denied_handler_surfaces_specific_exception_message(self):
        request = self.factory.get("/forbidden/")
        request.user = AnonymousUser()

        response = permission_denied_handler(
            request,
            PermissionDenied("Hanya operator Puskesmas yang dapat membuat LPLPO."),
        )

        self.assertContains(
            response,
            "Hanya operator Puskesmas yang dapat membuat LPLPO.",
            status_code=403,
        )

    def test_maintenance_mode_logs_through_core_logger(self):
        request = self.factory.get("/maintenance/")
        request.user = AnonymousUser()
        request.META["REMOTE_ADDR"] = "127.0.0.1"

        with self.assertLogs("core", level="WARNING") as captured:
            maintenance_mode(request)

        self.assertIn("event=service_unavailable", captured.output[0])
        self.assertIn("status_code=503", captured.output[0])
        self.assertIn("path=/maintenance/", captured.output[0])

    def test_page_not_found_handler_logs_contextual_request_details(self):
        request = self.factory.get("/missing-page/")
        request.user = AnonymousUser()
        request.META["REMOTE_ADDR"] = "127.0.0.1"

        with self.assertLogs("core", level="INFO") as captured:
            page_not_found_handler(request, FileNotFoundError("missing"))

        self.assertIn("event=page_not_found", captured.output[0])
        self.assertIn("status_code=404", captured.output[0])
        self.assertIn("exception=FileNotFoundError", captured.output[0])

    @override_settings(DEBUG=True)
    def test_unmatched_route_uses_custom_404_page_in_debug(self):
        # Reload the URLconf module to pick up DEBUG=True setting
        import importlib
        from django.urls import clear_url_caches
        from config import urls
        importlib.reload(urls)
        clear_url_caches()
        
        response = self.client.get("/route-yang-tidak-ada/")

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Halaman yang Anda cari tidak ditemukan", status_code=404)
        self.assertContains(response, "Buka Login", status_code=404)

class NavNotificationsContextProcessorTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _set_scope(self, user, module, scope):
        ModuleAccess.objects.update_or_create(
            user=user,
            module=module,
            defaults={"scope": scope},
        )

    def test_unauthenticated_user_gets_zero_notification_count(self):
        request = self.factory.get("/")
        request.user = type("AnonymousUser", (), {"is_authenticated": False})()

        context = nav_notifications(request)

        self.assertEqual(context["nav_notification_count"], 0)

    def test_puskesmas_user_gets_zero_notification_count_without_rejected_lplpo(self):
        facility = Facility.objects.create(
            code="PKM-NAV",
            name="Puskesmas NAV",
            facility_type=Facility.FacilityType.PUSKESMAS,
        )
        puskesmas_user = User.objects.create_user(
            username="nav-puskesmas",
            password="TestPassword123!",
            role=User.Role.PUSKESMAS,
            facility=facility,
        )
        request = self.factory.get("/")
        request.user = puskesmas_user

        context = nav_notifications(request)

        self.assertEqual(context["nav_notification_count"], 0)
        self.assertEqual(context["nav_notification_items"], [])

    def test_puskesmas_user_gets_rejected_lplpo_notification_for_own_facility(self):
        facility = Facility.objects.create(
            code="PKM-NAV-REJ",
            name="Puskesmas NAV Rejected",
            facility_type=Facility.FacilityType.PUSKESMAS,
        )
        other_facility = Facility.objects.create(
            code="PKM-NAV-OTHER",
            name="Puskesmas NAV Other",
            facility_type=Facility.FacilityType.PUSKESMAS,
        )
        puskesmas_user = User.objects.create_user(
            username="nav-puskesmas-rejected",
            password="TestPassword123!",
            role=User.Role.PUSKESMAS,
            facility=facility,
        )
        LPLPO.objects.create(
            facility=facility,
            bulan=4,
            tahun=2026,
            status=LPLPO.Status.REJECTED,
            created_by=puskesmas_user,
            rejection_reason="Perlu perbaikan.",
        )
        LPLPO.objects.create(
            facility=other_facility,
            bulan=5,
            tahun=2026,
            status=LPLPO.Status.REJECTED,
            created_by=puskesmas_user,
            rejection_reason="Fasilitas lain.",
        )

        request = self.factory.get("/")
        request.user = puskesmas_user

        context = nav_notifications(request)

        self.assertEqual(context["nav_notification_count"], 1)
        self.assertTrue(
            any(
                item["label"] == "LPLPO Ditolak"
                and item["count"] == 1
                and item["url"].endswith("/lplpo/my/?status=REJECTED")
                for item in context["nav_notification_items"]
            )
        )

    def test_admin_user_counts_pending_receiving_documents(self):
        admin_user = User.objects.create_superuser(
            username="nav-admin",
            email="nav-admin@example.com",
            password="TestPassword123!",
        )
        self._set_scope(
            admin_user, ModuleAccess.Module.RECEIVING, ModuleAccess.Scope.MANAGE
        )
        funding_source = FundingSource.objects.create(code="DAK-NAV", name="DAK NAV")
        Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date="2026-04-03",
            sumber_dana=funding_source,
            status=Receiving.Status.SUBMITTED,
            is_planned=True,
            created_by=admin_user,
        )

        request = self.factory.get("/")
        request.user = admin_user
        context = nav_notifications(request)

        self.assertGreaterEqual(context["nav_notification_count"], 1)

    def test_receiving_notifications_for_approve_scope_only_include_submitted(self):
        kepala_user = User.objects.create_user(
            username="nav-kepala",
            password="TestPassword123!",
            role=User.Role.KEPALA,
        )
        self._set_scope(
            kepala_user, ModuleAccess.Module.RECEIVING, ModuleAccess.Scope.APPROVE
        )
        funding_source = FundingSource.objects.create(
            code="DAK-APPROVE", name="DAK Approve"
        )
        Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date="2026-04-03",
            sumber_dana=funding_source,
            status=Receiving.Status.SUBMITTED,
            is_planned=True,
            created_by=kepala_user,
        )
        Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date="2026-04-03",
            sumber_dana=funding_source,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=kepala_user,
        )

        request = self.factory.get("/")
        request.user = kepala_user
        context = nav_notifications(request)

        self.assertEqual(context["nav_notification_count"], 1)

    def test_receiving_notifications_for_operate_scope_exclude_submitted(self):
        operator_user = User.objects.create_user(
            username="nav-operator",
            password="TestPassword123!",
            role=User.Role.ADMIN_UMUM,
        )
        self._set_scope(
            operator_user, ModuleAccess.Module.RECEIVING, ModuleAccess.Scope.OPERATE
        )
        funding_source = FundingSource.objects.create(
            code="DAK-OPERATE", name="DAK Operate"
        )
        Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date="2026-04-03",
            sumber_dana=funding_source,
            status=Receiving.Status.SUBMITTED,
            is_planned=True,
            created_by=operator_user,
        )
        Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date="2026-04-03",
            sumber_dana=funding_source,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=operator_user,
        )

        request = self.factory.get("/")
        request.user = operator_user
        context = nav_notifications(request)

        self.assertEqual(context["nav_notification_count"], 1)

    def test_allocation_notifications_ignore_missing_table(self):
        operator_user = User.objects.create_user(
            username="nav-allocation-operator",
            password="TestPassword123!",
            role=User.Role.ADMIN_UMUM,
        )
        self._set_scope(
            operator_user, ModuleAccess.Module.ALLOCATION, ModuleAccess.Scope.OPERATE
        )
        request = self.factory.get("/")
        request.user = operator_user

        with patch(
            "apps.allocation.models.Allocation.objects.filter",
            side_effect=ProgrammingError('relation "allocations" does not exist'),
        ):
            context = nav_notifications(request)

        self.assertEqual(context["nav_notification_count"], 0)
        self.assertEqual(context["nav_notification_items"], [])

    def test_verified_regular_receiving_does_not_show_when_only_plan_is_actionable(self):
        operator_user = User.objects.create_user(
            username="nav-operator-plan",
            password="TestPassword123!",
            role=User.Role.ADMIN_UMUM,
        )
        self._set_scope(
            operator_user, ModuleAccess.Module.RECEIVING, ModuleAccess.Scope.OPERATE
        )
        funding_source = FundingSource.objects.create(
            code="DAK-PLANONLY", name="DAK Plan Only"
        )
        Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date="2026-04-03",
            sumber_dana=funding_source,
            status=Receiving.Status.VERIFIED,
            is_planned=False,
            created_by=operator_user,
        )
        Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date="2026-04-03",
            sumber_dana=funding_source,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=operator_user,
        )

        request = self.factory.get("/")
        request.user = operator_user
        context = nav_notifications(request)

        self.assertTrue(
            any(
                item["label"] == "Rencana Penerimaan" and item["count"] == 1
                for item in context["nav_notification_items"]
            )
        )
        self.assertFalse(
            any(item["label"] == "Penerimaan" for item in context["nav_notification_items"])
        )

    def test_admin_umum_gets_puskesmas_request_notifications_with_view_scope(self):
        admin_umum = User.objects.create_user(
            username="nav-admin-umum-puskesmas",
            password="TestPassword123!",
            role=User.Role.ADMIN_UMUM,
        )
        self._set_scope(
            admin_umum, ModuleAccess.Module.PUSKESMAS, ModuleAccess.Scope.VIEW
        )
        facility = Facility.objects.create(
            code="PKM-NAV-AU",
            name="Puskesmas Admin Umum",
            facility_type=Facility.FacilityType.PUSKESMAS,
        )
        PuskesmasRequest.objects.create(
            facility=facility,
            created_by=admin_umum,
            status=PuskesmasRequest.Status.SUBMITTED,
        )

        request = self.factory.get("/")
        request.user = admin_umum
        context = nav_notifications(request)

        self.assertTrue(
            any(
                item["label"] == "Permintaan Puskesmas" and item["count"] == 1
                for item in context["nav_notification_items"]
            )
        )

    def test_gudang_gets_puskesmas_request_notifications_with_view_scope(self):
        gudang = User.objects.create_user(
            username="nav-gudang-puskesmas",
            password="TestPassword123!",
            role=User.Role.GUDANG,
        )
        self._set_scope(gudang, ModuleAccess.Module.PUSKESMAS, ModuleAccess.Scope.VIEW)
        facility = Facility.objects.create(
            code="PKM-NAV-GD",
            name="Puskesmas Gudang",
            facility_type=Facility.FacilityType.PUSKESMAS,
        )
        PuskesmasRequest.objects.create(
            facility=facility,
            created_by=gudang,
            status=PuskesmasRequest.Status.SUBMITTED,
        )

        request = self.factory.get("/")
        request.user = gudang
        context = nav_notifications(request)

        self.assertTrue(
            any(
                item["label"] == "Permintaan Puskesmas" and item["count"] == 1
                for item in context["nav_notification_items"]
            )
        )

    def test_explicit_none_scope_hides_puskesmas_request_notifications(self):
        auditor = User.objects.create_user(
            username="nav-auditor-none-puskesmas",
            password="TestPassword123!",
            role=User.Role.AUDITOR,
        )
        self._set_scope(auditor, ModuleAccess.Module.PUSKESMAS, ModuleAccess.Scope.NONE)
        facility = Facility.objects.create(
            code="PKM-NAV-NONE",
            name="Puskesmas None",
            facility_type=Facility.FacilityType.PUSKESMAS,
        )
        PuskesmasRequest.objects.create(
            facility=facility,
            created_by=auditor,
            status=PuskesmasRequest.Status.SUBMITTED,
        )

        request = self.factory.get("/")
        request.user = auditor
        context = nav_notifications(request)

        self.assertFalse(
            any(
                item["label"] == "Permintaan Puskesmas"
                for item in context["nav_notification_items"]
            )
        )

    def test_admin_user_gets_module_summary_items(self):
        admin_user = User.objects.create_superuser(
            username="nav-admin-summary",
            email="nav-admin-summary@example.com",
            password="TestPassword123!",
        )
        facility = Facility.objects.create(
            code="PKM-SUM",
            name="Puskesmas Summary",
            facility_type=Facility.FacilityType.PUSKESMAS,
        )
        Distribution.objects.create(
            distribution_type=Distribution.DistributionType.LPLPO,
            request_date="2026-04-03",
            facility=facility,
            status=Distribution.Status.SUBMITTED,
            created_by=admin_user,
        )

        request = self.factory.get("/")
        request.user = admin_user
        context = nav_notifications(request)

        self.assertIn("nav_notification_items", context)
        self.assertTrue(
            any(
                item["label"] == "Distribusi dari LPLPO" and item["count"] == 1
                for item in context["nav_notification_items"]
            )
        )

    def test_kepala_gets_lplpo_notifications_for_submitted_documents(self):
        kepala_user = User.objects.create_user(
            username="nav-kepala-lplpo",
            password="TestPassword123!",
            role=User.Role.KEPALA,
        )
        self._set_scope(
            kepala_user, ModuleAccess.Module.LPLPO, ModuleAccess.Scope.APPROVE
        )
        facility = Facility.objects.create(
            code="PKM-NAV-LPLPO",
            name="Puskesmas LPLPO",
            facility_type=Facility.FacilityType.PUSKESMAS,
        )
        LPLPO.objects.create(
            facility=facility,
            bulan=4,
            tahun=2026,
            status=LPLPO.Status.SUBMITTED,
            created_by=kepala_user,
        )

        request = self.factory.get("/")
        request.user = kepala_user
        context = nav_notifications(request)

        self.assertTrue(
            any(
                item["label"] == "LPLPO" and item["count"] == 1
                for item in context["nav_notification_items"]
            )
        )


class SafeMediaUrlIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        img = BytesIO()
        from PIL import Image
        Image.new("RGBA", (100, 100), (255, 0, 0, 255)).save(img, format="PNG")
        img.seek(0)
        cls.test_image = SimpleUploadedFile(
            "test_logo.png",
            img.read(),
            "image/png",
        )

    def setUp(self):
        self.settings = SystemSettings.get_settings()

    def test_logo_renders_local_url_in_template(self):
        self.settings.logo = self.test_image
        self.settings.save()

        template = Template(
            "{% load number_format %}"
            "{% if system_settings.logo %}"
            "{% with logo_url=system_settings.logo.url|safe_media_url %}"
            "{% if logo_url %}{{ logo_url }}{% else %}NO_URL{% endif %}"
            "{% endwith %}"
            "{% else %}"
            "FALLBACK"
            "{% endif %}"
        )
        rendered = template.render(Context({"system_settings": self.settings}))

        self.assertTrue(rendered.strip().startswith("/media/settings/"))

    def test_null_logo_renders_fallback_in_template(self):
        self.settings.logo = None
        self.settings.save()

        template = Template(
            "{% load number_format %}"
            "{% if system_settings.logo %}"
            "{% with logo_url=system_settings.logo.url|safe_media_url %}"
            "{% if logo_url %}{{ logo_url }}{% else %}NO_URL{% endif %}"
            "{% endwith %}"
            "{% else %}"
            "FALLBACK"
            "{% endif %}"
        )
        rendered = template.render(Context({"system_settings": self.settings}))

        self.assertEqual(rendered.strip(), "FALLBACK")

    def test_external_url_blocked_in_template(self):
        template = Template(
            "{% load number_format %}"
            '{{ "https://evil.com/malware.png"|safe_media_url }}'
        )
        rendered = template.render(Context({}))

        self.assertEqual(rendered.strip(), "")

    def test_http_url_blocked_in_template(self):
        template = Template(
            "{% load number_format %}"
            '{{ "http://evil.com/malware.png"|safe_media_url }}'
        )
        rendered = template.render(Context({}))

        self.assertEqual(rendered.strip(), "")

    def test_protocol_relative_url_blocked_in_template(self):
        template = Template(
            "{% load number_format %}"
            '{{ "//evil.com/malware.png"|safe_media_url }}'
        )
        rendered = template.render(Context({}))

        self.assertEqual(rendered.strip(), "")

    def test_javascript_scheme_blocked_in_template(self):
        template = Template(
            "{% load number_format %}"
            '{{ "javascript:alert(1)"|safe_media_url }}'
        )
        rendered = template.render(Context({}))

        self.assertEqual(rendered.strip(), "")

    def test_empty_string_blocked_in_template(self):
        template = Template(
            "{% load number_format %}"
            '{{ ""|safe_media_url }}'
        )
        rendered = template.render(Context({}))

        self.assertEqual(rendered.strip(), "")

    def test_root_relative_logo_passes_template_guard_and_renders(self):
        self.settings.logo = self.test_image
        self.settings.save()

        template = Template(
            "{% load number_format %}"
            "{% with logo_url=system_settings.logo.url|safe_media_url %}"
            "{% if logo_url %}"
            '<img src="{{ logo_url }}" alt="Logo">'
            "{% else %}"
            '<i class="bi bi-hospital"></i>'
            "{% endif %}"
            "{% endwith %}"
        )
        rendered = template.render(Context({"system_settings": self.settings}))

        self.assertIn('<img src="/media/settings/', rendered)

    def test_blocked_url_triggers_fallback_icon(self):
        self.settings.logo = self.test_image
        self.settings.save()

        template = Template(
            "{% load number_format %}"
            '{% with logo_url="https://external.com/bad.png"|safe_media_url %}'
            "{% if logo_url %}"
            '<img src="{{ logo_url }}" alt="Logo">'
            "{% else %}"
            '<i class="bi bi-hospital"></i>'
            "{% endif %}"
            "{% endwith %}"
        )
        rendered = template.render(Context({}))

        self.assertIn('<i class="bi bi-hospital"></i>', rendered)
        self.assertNotIn("<img", rendered)
