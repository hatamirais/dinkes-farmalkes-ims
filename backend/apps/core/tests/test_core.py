import json
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from import_export.formats import base_formats
from tablib import Dataset

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
from django_ratelimit.exceptions import Ratelimited
from axes.models import AccessAttempt

from apps.core.admin_mixins import ImportGuideMixin
from apps.core.context_processors import nav_notifications
from apps.core.csv_exports import SanitizedCSV, escape_csv_formula
from apps.core.forms import SystemSettingsForm
from apps.core.models import SystemSettings
from apps.core.xlsx_exports import escape_xlsx_formula
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
from PIL import Image


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


class CsvExportSecurityTests(SimpleTestCase):
    def test_escape_csv_formula_escapes_leading_whitespace_formulae(self):
        for value in (" =SUM(A1:A2)", "\t=SUM(A1:A2)", "\r=SUM(A1:A2)"):
            with self.subTest(value=value):
                self.assertEqual(escape_csv_formula(value), f"'{value}")

    def test_escape_csv_formula_does_not_double_escape_existing_apostrophe(self):
        value = "'=SUM(A1:A2)"

        self.assertEqual(escape_csv_formula(value), value)

    def test_sanitized_csv_export_uses_headers_and_sanitizes_rows(self):
        dataset = Dataset(headers=["Name", "Notes"])
        dataset.append(["Paracetamol", "\t=HYPERLINK(\"http://example.com\")"])

        csv_output = SanitizedCSV().export_data(dataset)

        self.assertIn("Name,Notes", csv_output)
        self.assertIn("'\t=HYPERLINK", csv_output)

    def test_import_guide_mixin_replaces_csv_subclasses_without_instantiating_them(self):
        class NoInitCsvFormat(base_formats.CSV):
            def __init__(self, *args, **kwargs):
                raise AssertionError("CSV format subclasses should not be instantiated here")

        class NonCsvFormat:
            pass

        class ExportFormatsBase:
            def get_export_formats(self):
                return [NoInitCsvFormat, NonCsvFormat]

        class TestAdmin(ImportGuideMixin, ExportFormatsBase):
            pass

        self.assertEqual(TestAdmin().get_export_formats(), [SanitizedCSV, NonCsvFormat])


class XlsxExportSecurityTests(SimpleTestCase):
    def test_escape_xlsx_formula_escapes_leading_whitespace_formulae(self):
        for value in (" =SUM(A1:A2)", "\t=SUM(A1:A2)", "\r=SUM(A1:A2)", " @cmd"):
            with self.subTest(value=value):
                self.assertEqual(escape_xlsx_formula(value), f"'{value}")

    def test_escape_xlsx_formula_does_not_double_escape_existing_apostrophe(self):
        value = "'=SUM(A1:A2)"

        self.assertEqual(escape_xlsx_formula(value), value)

    def test_escape_xlsx_formula_leaves_normal_text_and_non_strings_unchanged(self):
        self.assertEqual(escape_xlsx_formula("Paracetamol"), "Paracetamol")
        self.assertEqual(escape_xlsx_formula(Decimal("12.50")), Decimal("12.50"))


class SystemSettingsFormTests(SimpleTestCase):
    @staticmethod
    def _uploaded_file(name, content, content_type):
        return SimpleUploadedFile(name, content, content_type)

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

    def test_rejects_non_image_logo_with_png_extension(self):
        form = SystemSettingsForm(
            data={
                "platform_label": "Healthcare IMS",
                "facility_name": "Instalasi Farmasi",
                "facility_address": "",
                "facility_phone": "",
                "header_title": "Dinas Kesehatan",
                "lplpo_distribution_number_template": "440/{seq}/SBBK.RF/{year}",
                "special_request_distribution_number_template": "440/{seq}/KD.F/{year}",
            },
            files={
                "logo": self._uploaded_file(
                    "logo.png",
                    b"not-a-real-image",
                    "image/png",
                )
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("logo", form.errors)

    def test_accepts_existing_logo_without_revalidation(self):
        with TemporaryDirectory() as temp_dir:
            logo_path = Path(temp_dir) / "settings" / "logo.png"
            logo_path.parent.mkdir(parents=True, exist_ok=True)
            logo_path.write_bytes(b"existing-logo")

            with override_settings(MEDIA_ROOT=temp_dir):
                form = SystemSettingsForm(
                    data={
                        "platform_label": "Healthcare IMS",
                        "facility_name": "Instalasi Farmasi",
                        "facility_address": "",
                        "facility_phone": "",
                        "header_title": "Dinas Kesehatan",
                        "lplpo_distribution_number_template": "440/{seq}/SBBK.RF/{year}",
                        "special_request_distribution_number_template": "440/{seq}/KD.F/{year}",
                    },
                    instance=SystemSettings(logo="settings/logo.png"),
                )

                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["logo"].name, "settings/logo.png")
                if form.cleaned_data.get("logo"):
                    form.cleaned_data["logo"].close()
                if form.instance and form.instance.logo:
                    form.instance.logo.close()

    @patch("apps.core.upload_validation.Image.open", side_effect=Image.DecompressionBombError("bomb"))
    def test_rejects_decompression_bomb_logo(self, mocked_image_open):
        form = SystemSettingsForm(
            data={
                "platform_label": "Healthcare IMS",
                "facility_name": "Instalasi Farmasi",
                "facility_address": "",
                "facility_phone": "",
                "header_title": "Dinas Kesehatan",
                "lplpo_distribution_number_template": "440/{seq}/SBBK.RF/{year}",
                "special_request_distribution_number_template": "440/{seq}/KD.F/{year}",
            },
            files={
                "logo": self._uploaded_file(
                    "logo.png",
                    b"not-a-real-image",
                    "image/png",
                )
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("logo", form.errors)
        mocked_image_open.assert_called_once()


class SystemSettingsModelTests(TestCase):
    def test_get_settings_exposes_default_numbering_templates(self):
        settings = SystemSettings.get_settings()

        self.assertEqual(settings.lplpo_distribution_number_template, "440/{seq}/SBBK.RF/{year}")
        self.assertEqual(settings.special_request_distribution_number_template, "440/{seq}/KD.F/{year}")


@override_settings(SECURE_SSL_REDIRECT=False)
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

        self.assertEqual(response.status_code, 403)
        self.assertContains(
            response,
            "Akun Anda belum terhubung ke fasilitas puskesmas.",
            status_code=403,
        )

    def test_unlinked_puskesmas_user_sidebar_hides_facility_scoped_navigation(self):
        user = User.objects.create_user(
            username="sidebar-no-facility",
            password="TestPassword123!",
            role=User.Role.PUSKESMAS,
        )

        self.client.force_login(user)
        response = self.client.get(reverse("password_change"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Konfirmasi Penerimaan")
        self.assertNotContains(response, "Poli/Pustu Puskesmas")
        self.assertNotContains(response, "Input Pemakaian")
        self.assertNotContains(response, "Permintaan Barang")
        self.assertNotContains(response, '<span>LPLPO</span>', html=False)

    def test_linked_puskesmas_user_sidebar_keeps_facility_scoped_navigation(self):
        self.client.force_login(self.puskesmas_user)
        response = self.client.get(reverse("password_change"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Konfirmasi Penerimaan")
        self.assertContains(response, "Poli/Pustu Puskesmas")
        self.assertContains(response, "Input Pemakaian")
        self.assertContains(response, "Permintaan Barang")
        self.assertContains(response, '<span>LPLPO</span>', html=False)

    def test_puskesmas_sidebar_lplpo_link_targets_my_list(self):
        self.client.force_login(self.puskesmas_user)
        response = self.client.get(reverse("password_change"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/lplpo/my/"', html=False)

    def test_admin_panel_sidebar_link_uses_noopener_noreferrer(self):
        user = User.objects.create_user(
            username="admin-panel-sidebar-user",
            password="TestPassword123!",
            role=User.Role.ADMIN_UMUM,
        )
        self._set_scope(
            user,
            ModuleAccess.Module.ADMIN_PANEL,
            ModuleAccess.Scope.MANAGE,
        )

        self.client.force_login(user)
        response = self.client.get(reverse("password_change"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'href="/admin/" class="sidebar-link" target="_blank" rel="noopener noreferrer" data-label="Admin Panel" title="Admin Panel"',
            html=False,
        )
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

    def test_global_dashboard_excludes_transfer_transactions_from_kpis(self):
        viewer = User.objects.create_user(
            username="dashboard-transfer-metrics",
            password="TestPassword123!",
            role=User.Role.ADMIN_UMUM,
        )
        actor = User.objects.create_user(
            username="dashboard-transfer-actor",
            password="TestPassword123!",
            role=User.Role.GUDANG,
        )
        self._set_scope(viewer, ModuleAccess.Module.STOCK, ModuleAccess.Scope.VIEW)
        self._set_scope(viewer, ModuleAccess.Module.EXPIRED, ModuleAccess.Scope.NONE)
        self._set_scope(viewer, ModuleAccess.Module.ITEMS, ModuleAccess.Scope.NONE)
        self._set_scope(viewer, ModuleAccess.Module.USERS, ModuleAccess.Scope.NONE)
        self._set_scope(viewer, ModuleAccess.Module.ADMIN_PANEL, ModuleAccess.Scope.NONE)

        unit = Unit.objects.create(code="TRM", name="Transfer Metric")
        category = Category.objects.create(code="TRM", name="Transfer Metric")
        funding_source = FundingSource.objects.create(code="TRM", name="Transfer Metric")
        source_location = Location.objects.create(code="TRSRC", name="Gudang Karantina")
        destination_location = Location.objects.create(code="TRDST", name="Gudang Sirup")
        item = Item.objects.create(
            nama_barang="Item Mutasi Dashboard",
            satuan=unit,
            kategori=category,
        )

        fixed_now = timezone.now().replace(hour=10, minute=0, second=0, microsecond=0)
        inbound = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=item,
            location=source_location,
            batch_lot="IN-001",
            quantity=Decimal("20"),
            unit_price=Decimal("1000"),
            sumber_dana=funding_source,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=10,
            user=actor,
        )
        transfer_out = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=item,
            location=source_location,
            batch_lot="TRF-001",
            quantity=Decimal("5"),
            unit_price=Decimal("1000"),
            sumber_dana=funding_source,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=20,
            user=actor,
        )
        transfer_in = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=item,
            location=destination_location,
            batch_lot="TRF-001",
            quantity=Decimal("5"),
            unit_price=Decimal("1000"),
            sumber_dana=funding_source,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=20,
            user=actor,
        )
        outbound = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=item,
            location=destination_location,
            batch_lot="OUT-001",
            quantity=Decimal("7"),
            unit_price=Decimal("1000"),
            sumber_dana=funding_source,
            reference_type=Transaction.ReferenceType.DISTRIBUTION,
            reference_id=30,
            user=actor,
        )

        for transaction in (inbound, transfer_out, transfer_in, outbound):
            Transaction.objects.filter(pk=transaction.pk).update(created_at=fixed_now)

        self.client.force_login(viewer)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["today_transaction_count"], 2)
        self.assertEqual(response.context["inbound_30_days"], Decimal("20"))
        self.assertEqual(response.context["outbound_30_days"], Decimal("7"))

    def test_global_dashboard_recent_transactions_excludes_transfer_rows(self):
        viewer = User.objects.create_user(
            username="dashboard-transfer-recent",
            password="TestPassword123!",
            role=User.Role.ADMIN_UMUM,
        )
        actor = User.objects.create_user(
            username="dashboard-transfer-recent-actor",
            password="TestPassword123!",
            role=User.Role.GUDANG,
        )
        self._set_scope(viewer, ModuleAccess.Module.STOCK, ModuleAccess.Scope.VIEW)
        self._set_scope(viewer, ModuleAccess.Module.EXPIRED, ModuleAccess.Scope.NONE)
        self._set_scope(viewer, ModuleAccess.Module.ITEMS, ModuleAccess.Scope.NONE)
        self._set_scope(viewer, ModuleAccess.Module.USERS, ModuleAccess.Scope.NONE)
        self._set_scope(viewer, ModuleAccess.Module.ADMIN_PANEL, ModuleAccess.Scope.NONE)

        unit = Unit.objects.create(code="TRR", name="Transfer Recent")
        category = Category.objects.create(code="TRR", name="Transfer Recent")
        funding_source = FundingSource.objects.create(code="TRR", name="Transfer Recent")
        source_location = Location.objects.create(code="TRRSRC", name="Gudang A")
        destination_location = Location.objects.create(code="TRRDST", name="Gudang B")
        item = Item.objects.create(
            nama_barang="Item Recent Dashboard",
            satuan=unit,
            kategori=category,
        )

        normal_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=item,
            location=source_location,
            batch_lot="RCV-001",
            quantity=Decimal("12"),
            unit_price=Decimal("1000"),
            sumber_dana=funding_source,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=1,
            user=actor,
        )
        transfer_tx = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=item,
            location=destination_location,
            batch_lot="TRF-RECENT-001",
            quantity=Decimal("4"),
            unit_price=Decimal("1000"),
            sumber_dana=funding_source,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=2,
            user=actor,
        )
        fixed_now = timezone.now().replace(hour=11, minute=0, second=0, microsecond=0)
        Transaction.objects.filter(pk=normal_tx.pk).update(created_at=fixed_now)
        Transaction.objects.filter(pk=transfer_tx.pk).update(
            created_at=fixed_now + timedelta(minutes=1)
        )

        self.client.force_login(viewer)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        recent_transactions = list(response.context["recent_transactions"])
        self.assertEqual(len(recent_transactions), 1)
        self.assertEqual(recent_transactions[0].reference_type, Transaction.ReferenceType.RECEIVING)

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
        self.assertNotContains(response, "Konfirmasi Penerimaan")
        self.assertNotContains(response, "Poli/Pustu Puskesmas")
        self.assertNotContains(response, "Input Pemakaian")
        self.assertNotContains(response, "Permintaan Barang")

    def test_auditor_sidebar_only_shows_reports_group(self):
        auditor = User.objects.create_user(
            username="auditor-sidebar",
            password="TestPassword123!",
            role=User.Role.AUDITOR,
        )

        self.client.force_login(auditor)
        response = self.client.get(reverse("password_change"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<div class="sidebar-section-title">Laporan</div>', html=False)
        self.assertContains(response, 'href="/reports/"', html=False)
        self.assertContains(response, 'href="/reports/riwayat-penomoran/"', html=False)
        self.assertNotContains(response, '<div class="sidebar-section-title">Menu Utama</div>', html=False)
        self.assertNotContains(response, '<div class="sidebar-section-title">Master Data</div>', html=False)
        self.assertNotContains(response, '<div class="sidebar-section-title">Transaksi</div>', html=False)
        self.assertNotContains(response, '<div class="sidebar-section-title">Transaksi Stok</div>', html=False)
        self.assertNotContains(response, '<div class="sidebar-section-title">Administrasi</div>', html=False)
        self.assertNotContains(response, '<div class="sidebar-section-title">Konfigurasi</div>', html=False)
        self.assertNotContains(response, 'href="/stock/"', html=False)
        self.assertNotContains(response, 'href="/receiving/"', html=False)
        self.assertNotContains(response, 'href="/distribution/"', html=False)

    def test_auditor_dashboard_hides_linked_drill_through_sections(self):
        auditor = User.objects.create_user(
            username="auditor-dashboard",
            password="TestPassword123!",
            role=User.Role.AUDITOR,
        )

        self.client.force_login(auditor)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Total Jenis Barang")
        self.assertContains(response, "Total Stok Aktif")
        self.assertContains(response, "Total Kuantitas Tersedia")
        self.assertContains(response, "Estimasi Nilai Stok")
        self.assertContains(response, "Transaksi Hari Ini")
        self.assertNotContains(response, "Pergerakan Stok")
        self.assertNotContains(response, "Transaksi Terakhir")
        self.assertNotContains(response, "Aksi Cepat")
        self.assertNotContains(response, "Mendekati Kedaluwarsa")
        self.assertNotContains(response, 'href="/stock/transactions/"', html=False)
        self.assertNotContains(response, 'href="/expired/alerts/?level=all&amp;pending=1"', html=False)

    def test_superuser_dashboard_keeps_puskesmas_sidebar_visible(self):
        admin_user = User.objects.create_superuser(
            username="dashboard-admin-puskesmas",
            email="dashboard-admin-puskesmas@example.com",
            password="TestPassword123!",
        )
        self.client.force_login(admin_user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Konfirmasi Penerimaan")
        self.assertContains(response, "Poli/Pustu Puskesmas")
        self.assertContains(response, "Input Pemakaian")
        self.assertContains(response, "Permintaan Barang")

    def test_legacy_admin_role_dashboard_keeps_puskesmas_sidebar_visible(self):
        admin_user = User.objects.create_superuser(
            username="dashboard-legacy-admin-puskesmas",
            email="dashboard-legacy-admin-puskesmas@example.com",
            password="TestPassword123!",
        )
        User.objects.filter(pk=admin_user.pk).update(is_superuser=False, is_staff=False)
        admin_user.refresh_from_db()

        self.client.force_login(admin_user)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Konfirmasi Penerimaan")
        self.assertContains(response, "Poli/Pustu Puskesmas")
        self.assertContains(response, "Input Pemakaian")
        self.assertContains(response, "Permintaan Barang")

@override_settings(SECURE_SSL_REDIRECT=False)
class ErrorPageTemplateTests(TestCase):
    def test_login_page_renders_for_anonymous_user(self):
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/login.html")
        self.assertContains(response, "<form", status_code=200)

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


@override_settings(
    SECURE_SSL_REDIRECT=False,
    AXES_FAILURE_LIMIT=3,
    AXES_COOLOFF_TIME=1,
    AXES_LOCKOUT_PARAMETERS=["username", "ip_address"],
    AXES_RESET_ON_SUCCESS=True,
)
class LoginLockoutTests(TestCase):
    def setUp(self):
        AccessAttempt.objects.all().delete()
        self.user = User.objects.create_user(
            username="spray-target",
            password="TestPassword123!",
        )

    def tearDown(self):
        AccessAttempt.objects.all().delete()

    def _post_login(
        self,
        username,
        password="WrongPassword123!",
        remote_addr="127.0.0.1",
    ):
        return self.client.post(
            reverse("login"),
            {"username": username, "password": password},
            REMOTE_ADDR=remote_addr,
        )

    def test_username_lockout_blocks_distributed_source_ips(self):
        for index in range(2):
            response = self._post_login(
                self.user.username,
                remote_addr=f"10.0.0.{index + 1}",
            )
            self.assertEqual(response.status_code, 200)

        response = self._post_login(self.user.username, remote_addr="10.0.0.3")

        self.assertEqual(response.status_code, 429)
        self.assertTemplateUsed(response, "registration/lockout.html")

    def test_ip_lockout_blocks_multiple_usernames_from_one_source_ip(self):
        for index in range(2):
            response = self._post_login(
                f"unknown-user-{index}",
                remote_addr="10.0.1.10",
            )
            self.assertEqual(response.status_code, 200)

        response = self._post_login("unknown-user-3", remote_addr="10.0.1.10")

        self.assertEqual(response.status_code, 429)
        self.assertTemplateUsed(response, "registration/lockout.html")

    def test_login_page_does_not_disclose_exact_failure_limit(self):
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "terlalu banyak percobaan gagal")
        self.assertNotContains(response, "5 percobaan gagal")



@override_settings(SECURE_SSL_REDIRECT=False)
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

    def test_kepala_user_sees_settings_menu_and_can_open_settings(self):
        user = User.objects.create_user(
            username="settings-kepala",
            password="TestPassword123!",
            role=User.Role.KEPALA,
        )
        self.client.force_login(user)

        sidebar_response = self.client.get(reverse("password_change"))
        self.assertEqual(sidebar_response.status_code, 200)
        self.assertContains(sidebar_response, "Pengaturan")
        self.assertContains(sidebar_response, 'href="/settings/"', html=False)

        settings_response = self.client.get(reverse("settings"))
        self.assertEqual(settings_response.status_code, 200)

    def test_admin_panel_manager_without_admin_or_kepala_role_is_denied_settings(self):
        user = User.objects.create_user(
            username="settings-manager-denied",
            password="TestPassword123!",
            role=User.Role.ADMIN_UMUM,
        )
        ModuleAccess.objects.update_or_create(
            user=user,
            module=ModuleAccess.Module.ADMIN_PANEL,
            defaults={"scope": ModuleAccess.Scope.MANAGE},
        )
        self.client.force_login(user)

        sidebar_response = self.client.get(reverse("password_change"))
        self.assertEqual(sidebar_response.status_code, 200)
        self.assertNotContains(sidebar_response, "Pengaturan")

        settings_response = self.client.get(reverse("settings"))
        self.assertEqual(settings_response.status_code, 403)

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

    def test_admin_user_logo_upload_is_audit_logged(self):
        user = User.objects.create_superuser(
            username="settings-audit-admin",
            email="settings-audit-admin@example.com",
            password="TestPassword123!",
        )
        self.client.force_login(user)

        image_buffer = BytesIO()
        from PIL import Image

        Image.new("RGBA", (16, 16), (255, 0, 0, 255)).save(image_buffer, format="PNG")
        image_buffer.seek(0)

        with self.assertLogs("security", level="INFO") as logs:
            response = self.client.post(
                reverse("settings"),
                {
                    "platform_label": "Healthcare IMS",
                    "facility_name": "Instalasi Farmasi",
                    "facility_address": "",
                    "facility_phone": "",
                    "header_title": "Dinas Kesehatan",
                    "lplpo_distribution_number_template": "440/{seq}/SBBK.RF/{year}",
                    "special_request_distribution_number_template": "440/{seq}/KD.F/{year}",
                    "logo": SimpleUploadedFile(
                        "audit-logo.png",
                        image_buffer.read(),
                        content_type="image/png",
                    ),
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            any("system_settings_logo_upload_succeeded" in message for message in logs.output)
        )

    def test_invalid_logo_upload_is_audit_logged_as_json(self):
        user = User.objects.create_superuser(
            username="settings-audit-fail-admin",
            email="settings-audit-fail-admin@example.com",
        )
        self.client.force_login(user)

        with self.assertLogs("security", level="WARNING") as logs:
            response = self.client.post(
                reverse("settings"),
                {
                    "platform_label": "Healthcare IMS",
                    "facility_name": "Instalasi Farmasi",
                    "facility_address": "",
                    "facility_phone": "",
                    "header_title": "Dinas Kesehatan",
                    "lplpo_distribution_number_template": "440/{seq}/SBBK.RF/{year}",
                    "special_request_distribution_number_template": "440/{seq}/KD.F/{year}",
                    "logo": SimpleUploadedFile(
                        'bad"\nlogo.png',
                        b"not-a-real-image",
                        content_type="image/png",
                    ),
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = json.loads(logs.output[0].split(":", 2)[2])
        self.assertEqual(payload["event"], "system_settings_logo_upload_failed")
        self.assertEqual(payload["filename"], 'bad"logo.png')
        self.assertIn("logo", payload["errors"])


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

    def test_bad_request_handles_request_without_user_attribute(self):
        request = self.factory.get("/bad-request/")
        request.META["REMOTE_ADDR"] = "127.0.0.1"

        with self.assertLogs("security", level="WARNING") as captured:
            response = bad_request(request, ValueError("invalid host"))

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Buka Login", status_code=400)
        self.assertIn("username=anonymous", captured.output[0])
        self.assertIn("event=bad_request", captured.output[0])

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

    def test_permission_denied_handler_returns_429_for_ratelimit_exception(self):
        request = self.factory.post("/users/bulk-action/")
        request.user = AnonymousUser()

        response = permission_denied_handler(request, Ratelimited())

        self.assertEqual(response.status_code, 429)
        self.assertContains(
            response,
            "Terlalu banyak percobaan pada aksi ini",
            status_code=429,
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

    @override_settings(DEBUG=True, SECURE_SSL_REDIRECT=False)
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
            status=LPLPO.Status.REJECTED_PUSKESMAS,
            created_by=puskesmas_user,
            rejection_reason="Perlu perbaikan.",
        )
        LPLPO.objects.create(
            facility=other_facility,
            bulan=5,
            tahun=2026,
            status=LPLPO.Status.REJECTED_PUSKESMAS,
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
                and item["url"].endswith("/lplpo/my/?status=REJECTED_PUSKESMAS")
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

    def test_admin_umum_does_not_get_puskesmas_request_notifications_when_sidebar_is_hidden(self):
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

        self.assertFalse(
            any(item["label"] == "Permintaan Puskesmas" for item in context["nav_notification_items"])
        )

    def test_gudang_does_not_get_puskesmas_request_notifications_when_sidebar_is_hidden(self):
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

        self.assertFalse(
            any(item["label"] == "Permintaan Puskesmas" for item in context["nav_notification_items"])
        )

    def test_legacy_admin_role_keeps_puskesmas_request_notifications(self):
        admin_user = User.objects.create_superuser(
            username="nav-legacy-admin-puskesmas",
            email="nav-legacy-admin-puskesmas@example.com",
            password="TestPassword123!",
        )
        User.objects.filter(pk=admin_user.pk).update(is_superuser=False, is_staff=False)
        admin_user.refresh_from_db()
        self._set_scope(
            admin_user,
            ModuleAccess.Module.PUSKESMAS,
            ModuleAccess.Scope.MANAGE,
        )
        facility = Facility.objects.create(
            code="PKM-NAV-ADM",
            name="Puskesmas Legacy Admin",
            facility_type=Facility.FacilityType.PUSKESMAS,
        )
        PuskesmasRequest.objects.create(
            facility=facility,
            created_by=admin_user,
            status=PuskesmasRequest.Status.SUBMITTED,
        )

        request = self.factory.get("/")
        request.user = admin_user
        context = nav_notifications(request)

        self.assertTrue(
            any(
                item["label"] == "Permintaan Puskesmas"
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
    """
    Integration tests for safe_media_url template filter.

    MEDIA_ROOT is overridden to an isolated temp directory so that logo
    writes do not touch the real backend/media/settings/ path.  This
    prevents PermissionError on Windows-managed workspaces where the
    production media directory may be restricted.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media_temp = TemporaryDirectory()
        cls._override = override_settings(MEDIA_ROOT=cls._media_temp.name)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        cls._media_temp.cleanup()
        super().tearDownClass()

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

