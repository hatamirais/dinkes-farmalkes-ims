import importlib
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.apps import apps as django_apps
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import DocumentNumberIssue, DocumentNumberRule, SystemSettings
from apps.items.models import Category, FundingSource, Item, Location, Unit
from apps.stock.models import Stock, Transaction
from apps.stock_opname.models import StockOpname, StockOpnameItem
from apps.users.access import ensure_default_module_access
from apps.users.models import User


class StockOpnameTestMixin:
    def setUp(self):
        super().setUp()
        DocumentNumberRule.objects.get_or_create(
            key=DocumentNumberRule.Key.STOCK_OPNAME,
            defaults={
                "label": "Stock Opname",
                "template": "SO-{year}{month}-{seq}",
                "reset_period": DocumentNumberRule.ResetPeriod.MONTHLY,
                "padding": 5,
            },
        )
        self.admin = User.objects.create_superuser(
            username="admin_opname",
            password="secret12345",
        )
        self.gudang = User.objects.create_user(
            username="gudang_opname",
            password="secret12345",
            role=User.Role.GUDANG,
        )
        self.admin_umum = User.objects.create_user(
            username="admin_umum_opname",
            password="secret12345",
            role=User.Role.ADMIN_UMUM,
        )
        ensure_default_module_access(self.gudang, overwrite=True)
        ensure_default_module_access(self.admin_umum, overwrite=True)

        self.unit = Unit.objects.create(code="PCS", name="Pieces")
        self.category = Category.objects.create(
            code="ALKES", name="Alkes", sort_order=1
        )
        self.item = Item.objects.create(
            kode_barang="ITM-OP-001",
            nama_barang="Masker Medis",
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal("0"),
        )
        self.location = Location.objects.create(code="LOC-OP", name="Gudang Opname")
        self.funding = FundingSource.objects.create(code="BOK", name="BOK")
        self.stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="BATCH-OP-01",
            expiry_date="2030-01-01",
            quantity=Decimal("100"),
            reserved=Decimal("0"),
            unit_price=Decimal("1000"),
            sumber_dana=self.funding,
        )

    def create_opname(self, *, status=StockOpname.Status.DRAFT, document_number=None):
        kwargs = {
            "period_type": StockOpname.PeriodType.MONTHLY,
            "period_start": date(2026, 3, 1),
            "period_end": date(2026, 3, 31),
            "status": status,
            "created_by": self.admin,
        }
        if document_number is not None:
            kwargs["document_number"] = document_number
        opname = StockOpname.objects.create(**kwargs)
        opname.categories.add(self.category)
        return opname


class StockOpnameAccessAndWorkflowTests(StockOpnameTestMixin, TestCase):
    def test_detail_shows_missing_categories_for_legacy_rows(self):
        draft = self.create_opname()
        draft.categories.clear()

        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("stock_opname:opname_detail", args=[draft.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Semua kategori")
        self.assertNotContains(response, "Tidak ada kategori")

        started = self.create_opname(status=StockOpname.Status.IN_PROGRESS)
        started.categories.clear()

        response = self.client.get(
            reverse("stock_opname:opname_detail", args=[started.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tidak ada kategori")
        self.assertNotContains(response, "Semua kategori")

    def test_read_endpoints_require_view_permission(self):
        opname = self.create_opname(status=StockOpname.Status.IN_PROGRESS)
        StockOpnameItem.objects.create(
            stock_opname=opname,
            stock=self.stock,
            system_quantity=Decimal("100"),
            actual_quantity=Decimal("100"),
        )

        self.client.force_login(self.admin_umum)

        urls = [
            reverse("stock_opname:opname_list"),
            reverse("stock_opname:opname_detail", args=[opname.pk]),
            reverse("stock_opname:opname_report_print", args=[opname.pk]),
            reverse("stock_opname:opname_print", args=[opname.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url, secure=True)
                self.assertEqual(response.status_code, 403)

    def test_start_snapshots_stock_and_updates_status(self):
        opname = self.create_opname()

        self.client.force_login(self.gudang)
        response = self.client.post(
            reverse("stock_opname:opname_start", args=[opname.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        opname.refresh_from_db()
        self.assertEqual(opname.status, StockOpname.Status.IN_PROGRESS)
        self.assertEqual(opname.document_number, "SO-202603-00001")
        snapshot = StockOpnameItem.objects.get(stock_opname=opname, stock=self.stock)
        self.assertEqual(snapshot.system_quantity, Decimal("100"))
        self.assertIsNotNone(snapshot.created_at)
        self.assertIsNotNone(snapshot.updated_at)

    def test_start_rejects_non_draft_session_without_creating_new_rows(self):
        opname = self.create_opname(status=StockOpname.Status.IN_PROGRESS)
        existing_item = StockOpnameItem.objects.create(
            stock_opname=opname,
            stock=self.stock,
            system_quantity=Decimal("100"),
        )

        self.client.force_login(self.gudang)
        response = self.client.post(
            reverse("stock_opname:opname_start", args=[opname.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            StockOpnameItem.objects.filter(stock_opname=opname).count(),
            1,
        )
        self.assertEqual(
            StockOpnameItem.objects.get(pk=existing_item.pk).system_quantity,
            Decimal("100"),
        )


class StockOpnameInputValidationTests(StockOpnameTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.opname = self.create_opname(status=StockOpname.Status.IN_PROGRESS)
        self.opname_item = StockOpnameItem.objects.create(
            stock_opname=self.opname,
            stock=self.stock,
            system_quantity=Decimal("100"),
        )

    def test_negative_actual_quantity_returns_400_and_does_not_save(self):
        self.client.force_login(self.gudang)

        response = self.client.post(
            reverse("stock_opname:opname_input", args=[self.opname.pk]),
            {f"qty_{self.opname_item.pk}": "-1", f"notes_{self.opname_item.pk}": "bad"},
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.opname_item.refresh_from_db()
        self.assertIsNone(self.opname_item.actual_quantity)
        self.assertContains(
            response,
            "Jumlah aktual tidak boleh kurang dari 0.",
            status_code=400,
        )

    def test_non_numeric_actual_quantity_returns_400_and_does_not_save(self):
        self.client.force_login(self.gudang)

        response = self.client.post(
            reverse("stock_opname:opname_input", args=[self.opname.pk]),
            {f"qty_{self.opname_item.pk}": "abc", f"notes_{self.opname_item.pk}": "bad"},
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.opname_item.refresh_from_db()
        self.assertIsNone(self.opname_item.actual_quantity)
        self.assertContains(
            response,
            "Jumlah aktual harus berupa angka yang valid.",
            status_code=400,
        )

    def test_nan_actual_quantity_returns_400_and_does_not_save(self):
        self.client.force_login(self.gudang)

        response = self.client.post(
            reverse("stock_opname:opname_input", args=[self.opname.pk]),
            {f"qty_{self.opname_item.pk}": "NaN", f"notes_{self.opname_item.pk}": "bad"},
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.opname_item.refresh_from_db()
        self.assertIsNone(self.opname_item.actual_quantity)
        self.assertContains(
            response,
            "Jumlah aktual harus berupa angka yang valid.",
            status_code=400,
        )

    def test_valid_actual_quantity_updates_item(self):
        self.client.force_login(self.gudang)

        response = self.client.post(
            reverse("stock_opname:opname_input", args=[self.opname.pk]),
            {
                f"qty_{self.opname_item.pk}": "95.50",
                f"notes_{self.opname_item.pk}": "Disesuaikan",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.opname_item.refresh_from_db()
        self.assertEqual(self.opname_item.actual_quantity, Decimal("95.50"))
        self.assertEqual(self.opname_item.notes, "Disesuaikan")

    def test_input_form_prefills_saved_actual_quantity_without_localized_separator(self):
        self.opname_item.actual_quantity = Decimal("1000.00")
        self.opname_item.notes = "Sudah dihitung"
        self.opname_item.save(update_fields=["actual_quantity", "notes", "updated_at"])
        self.client.force_login(self.gudang)

        response = self.client.get(
            reverse("stock_opname:opname_input", args=[self.opname.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            (
                f'<input type="number" name="qty_{self.opname_item.pk}" '
                'class="form-control form-control-sm " step="0.01" min="0" '
                'value="1000.00">'
            ),
            html=True,
        )
        self.assertNotContains(response, f'value="1.000,00"')
        self.assertContains(
            response,
            (
                f'<input type="text" name="notes_{self.opname_item.pk}" '
                'class="form-control form-control-sm" value="Sudah dihitung">'
            ),
            html=True,
        )

    def test_valid_actual_quantity_updates_item_timestamp(self):
        self.client.force_login(self.gudang)
        earlier = timezone.now() - timedelta(days=1)
        StockOpnameItem.objects.filter(pk=self.opname_item.pk).update(updated_at=earlier)

        response = self.client.post(
            reverse("stock_opname:opname_input", args=[self.opname.pk]),
            {
                f"qty_{self.opname_item.pk}": "94",
                f"notes_{self.opname_item.pk}": "Koreksi hitung",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.opname_item.refresh_from_db()
        self.assertGreater(self.opname_item.updated_at, earlier)

    def test_input_post_redirects_to_detail_after_save(self):
        self.client.force_login(self.gudang)
        input_url = reverse("stock_opname:opname_input", args=[self.opname.pk])
        detail_url = reverse("stock_opname:opname_detail", args=[self.opname.pk])

        get_response = self.client.get(
            f"{input_url}?location={self.location.pk}",
            secure=True,
        )

        self.assertEqual(get_response.status_code, 200)
        self.assertContains(
            get_response,
            f'<input type="hidden" name="location" value="{self.location.pk}">',
            html=True,
        )

        response = self.client.post(
            f"{input_url}?location={self.location.pk}",
            {
                f"qty_{self.opname_item.pk}": "90",
                f"notes_{self.opname_item.pk}": "Rak depan",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], detail_url)

    def test_input_post_rejects_when_opname_was_completed_before_submit(self):
        self.client.force_login(self.gudang)
        input_url = reverse("stock_opname:opname_input", args=[self.opname.pk])

        get_response = self.client.get(input_url, secure=True)
        self.assertEqual(get_response.status_code, 200)

        self.opname.status = StockOpname.Status.COMPLETED
        self.opname.completed_by = self.admin
        self.opname.completed_at = self.opname.created_at
        self.opname.save(
            update_fields=["status", "completed_by", "completed_at", "updated_at"]
        )

        response = self.client.post(
            input_url,
            {
                f"qty_{self.opname_item.pk}": "90",
                f"notes_{self.opname_item.pk}": "Terlambat disimpan",
            },
            secure=True,
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.opname_item.refresh_from_db()
        self.assertIsNone(self.opname_item.actual_quantity)
        messages = list(response.context["messages"])
        self.assertTrue(
            any(
                "sudah diselesaikan atau belum dimulai" in str(message)
                for message in messages
            )
        )


class StockOpnameApprovalAccessTest(StockOpnameTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.opname = self.create_opname(
            status=StockOpname.Status.IN_PROGRESS,
            document_number="SO-2026-00001",
        )
        StockOpnameItem.objects.create(
            stock_opname=self.opname,
            stock=self.stock,
            system_quantity=Decimal("100"),
            actual_quantity=Decimal("100"),
        )

    def test_admin_can_complete_in_progress_opname(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("stock_opname:opname_complete", args=[self.opname.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.opname.refresh_from_db()
        self.assertEqual(self.opname.status, StockOpname.Status.COMPLETED)
        self.assertEqual(self.opname.completed_by, self.admin)
        self.assertIsNotNone(self.opname.completed_at)
        item = StockOpnameItem.objects.get(stock_opname=self.opname, stock=self.stock)
        self.assertEqual(item.completion_stock_quantity, Decimal("100"))

    def test_complete_rejects_when_no_items_have_been_counted(self):
        self.opname_item = StockOpnameItem.objects.get(stock_opname=self.opname, stock=self.stock)
        self.opname_item.actual_quantity = None
        self.opname_item.save(update_fields=["actual_quantity"])

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("stock_opname:opname_complete", args=[self.opname.pk]),
            secure=True,
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.opname.refresh_from_db()
        self.assertEqual(self.opname.status, StockOpname.Status.IN_PROGRESS)
        self.assertIsNone(self.opname.completed_by)
        self.assertIsNone(self.opname.completed_at)
        messages = list(response.context["messages"])
        self.assertTrue(
            any(
                "belum ada item yang dihitung" in str(message)
                for message in messages
            )
        )

    def test_complete_rejects_when_any_snapshot_item_is_uncounted(self):
        second_stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="BATCH-OP-02",
            expiry_date="2030-02-01",
            quantity=Decimal("50"),
            reserved=Decimal("0"),
            unit_price=Decimal("1000"),
            sumber_dana=self.funding,
        )
        StockOpnameItem.objects.create(
            stock_opname=self.opname,
            stock=second_stock,
            system_quantity=Decimal("50"),
            actual_quantity=None,
        )

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("stock_opname:opname_complete", args=[self.opname.pk]),
            secure=True,
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.opname.refresh_from_db()
        self.assertEqual(self.opname.status, StockOpname.Status.IN_PROGRESS)
        self.assertIsNone(self.opname.completed_by)
        self.assertIsNone(self.opname.completed_at)
        messages = list(response.context["messages"])
        self.assertTrue(
            any(
                "masih ada item yang belum dihitung" in str(message)
                for message in messages
            )
        )

    def test_second_completion_attempt_is_rejected_after_status_changes(self):
        self.opname.status = StockOpname.Status.COMPLETED
        self.opname.completed_at = self.opname.created_at
        self.opname.save(update_fields=["status", "completed_at", "updated_at"])

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("stock_opname:opname_complete", args=[self.opname.pk]),
            secure=True,
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.opname.refresh_from_db()
        self.assertEqual(self.opname.status, StockOpname.Status.COMPLETED)
        messages = list(response.context["messages"])
        self.assertTrue(
            any(
                "sudah diselesaikan atau belum dimulai" in str(message)
                for message in messages
            )
        )

    def test_gudang_can_complete_opname_without_current_discrepancy(self):
        self.client.force_login(self.gudang)
        response = self.client.post(
            reverse("stock_opname:opname_complete", args=[self.opname.pk]),
            secure=True,
        )
        self.assertEqual(response.status_code, 302)
        self.opname.refresh_from_db()
        self.assertEqual(self.opname.status, StockOpname.Status.COMPLETED)
        self.assertEqual(self.opname.completed_by, self.gudang)

    def test_gudang_cannot_complete_opname_with_current_discrepancy(self):
        self.stock.quantity = Decimal("90")
        self.stock.save(update_fields=["quantity", "updated_at"])

        self.client.force_login(self.gudang)
        response = self.client.post(
            reverse("stock_opname:opname_complete", args=[self.opname.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 403)
        self.opname.refresh_from_db()
        self.assertEqual(self.opname.status, StockOpname.Status.IN_PROGRESS)
        self.assertIsNone(self.opname.completed_by)

    def test_django_permission_user_can_complete_without_current_discrepancy(self):
        permission_user = User.objects.create_user(
            username="django_perm_opname",
            password="secret12345",
            role=User.Role.ADMIN_UMUM,
        )
        ensure_default_module_access(permission_user, overwrite=True)
        permission_user.user_permissions.add(
            Permission.objects.get(codename="view_stockopname"),
            Permission.objects.get(codename="change_stockopname"),
        )
        self.client.force_login(permission_user)

        detail_response = self.client.get(
            reverse("stock_opname:opname_detail", args=[self.opname.pk]),
            secure=True,
        )
        post_response = self.client.post(
            reverse("stock_opname:opname_complete", args=[self.opname.pk]),
            secure=True,
        )

        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "Selesaikan")
        self.assertEqual(post_response.status_code, 302)
        self.opname.refresh_from_db()
        self.assertEqual(self.opname.status, StockOpname.Status.COMPLETED)
        self.assertEqual(self.opname.completed_by, permission_user)

    def test_django_permission_user_cannot_complete_with_current_discrepancy(self):
        self.stock.quantity = Decimal("90")
        self.stock.save(update_fields=["quantity", "updated_at"])
        permission_user = User.objects.create_user(
            username="django_perm_opname_discrepancy",
            password="secret12345",
            role=User.Role.ADMIN_UMUM,
        )
        ensure_default_module_access(permission_user, overwrite=True)
        permission_user.user_permissions.add(
            Permission.objects.get(codename="view_stockopname"),
            Permission.objects.get(codename="change_stockopname"),
        )
        self.client.force_login(permission_user)

        detail_response = self.client.get(
            reverse("stock_opname:opname_detail", args=[self.opname.pk]),
            secure=True,
        )
        post_response = self.client.post(
            reverse("stock_opname:opname_complete", args=[self.opname.pk]),
            secure=True,
        )

        self.assertEqual(detail_response.status_code, 200)
        self.assertNotContains(detail_response, "Selesaikan")
        self.assertEqual(post_response.status_code, 403)
        self.opname.refresh_from_db()
        self.assertEqual(self.opname.status, StockOpname.Status.IN_PROGRESS)
        self.assertIsNone(self.opname.completed_by)

    def test_complete_button_visible_for_gudang_operator_without_current_discrepancy(self):
        self.client.force_login(self.gudang)
        response = self.client.get(
            reverse("stock_opname:opname_detail", args=[self.opname.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Input Hitung")
        self.assertContains(response, "Selesaikan")

    def test_complete_button_hidden_for_gudang_operator_with_current_discrepancy(self):
        self.stock.quantity = Decimal("90")
        self.stock.save(update_fields=["quantity", "updated_at"])

        self.client.force_login(self.gudang)
        response = self.client.get(
            reverse("stock_opname:opname_detail", args=[self.opname.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Input Hitung")
        self.assertNotContains(response, "Selesaikan")
        self.assertContains(response, "Cetak Selisih")

    def test_kepala_can_complete_opname(self):
        kepala = User.objects.create_user(
            username="kepala_opname",
            password="secret12345",
            role=User.Role.KEPALA,
        )
        ensure_default_module_access(kepala, overwrite=True)
        self.client.force_login(kepala)

        response = self.client.post(
            reverse("stock_opname:opname_complete", args=[self.opname.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.opname.refresh_from_db()
        self.assertEqual(self.opname.status, StockOpname.Status.COMPLETED)
        self.assertEqual(self.opname.completed_by, kepala)

    def test_kepala_can_complete_opname_with_current_discrepancy(self):
        self.stock.quantity = Decimal("90")
        self.stock.save(update_fields=["quantity", "updated_at"])
        kepala = User.objects.create_user(
            username="kepala_opname_discrepancy",
            password="secret12345",
            role=User.Role.KEPALA,
        )
        ensure_default_module_access(kepala, overwrite=True)
        self.client.force_login(kepala)

        response = self.client.post(
            reverse("stock_opname:opname_complete", args=[self.opname.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.opname.refresh_from_db()
        self.assertEqual(self.opname.status, StockOpname.Status.COMPLETED)
        self.assertEqual(self.opname.completed_by, kepala)
        item = StockOpnameItem.objects.get(stock_opname=self.opname, stock=self.stock)
        self.assertEqual(item.completion_stock_quantity, Decimal("90"))

    def test_complete_button_visible_for_kepala_approver(self):
        kepala = User.objects.create_user(
            username="kepala_opname_button",
            password="secret12345",
            role=User.Role.KEPALA,
        )
        ensure_default_module_access(kepala, overwrite=True)
        self.client.force_login(kepala)

        response = self.client.get(
            reverse("stock_opname:opname_detail", args=[self.opname.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Selesaikan")


class StockOpnameModelTests(StockOpnameTestMixin, TestCase):
    def test_draft_save_does_not_issue_document_number(self):
        opname = self.create_opname()
        self.assertIsNone(opname.document_number)


class StockOpnamePresentationAndAuditTests(StockOpnameTestMixin, TestCase):
    def test_detail_renders_notes_with_line_breaks(self):
        opname = self.create_opname()
        opname.notes = "Baris pertama\nBaris kedua"
        opname.save(update_fields=["notes", "updated_at"])

        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("stock_opname:opname_detail", args=[opname.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Baris pertama<br>Baris kedua", html=True)

    def test_print_uses_system_settings_header_context(self):
        opname = self.create_opname(status=StockOpname.Status.IN_PROGRESS)
        StockOpnameItem.objects.create(
            stock_opname=opname,
            stock=self.stock,
            system_quantity=Decimal("100"),
            actual_quantity=Decimal("95"),
            notes="Selisih lima",
        )
        settings_obj = SystemSettings.get_settings()
        settings_obj.header_title = "DINAS KESEHATAN KABUPATEN"
        settings_obj.facility_name = "Instalasi Farmasi Daerah"
        settings_obj.save()

        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("stock_opname:opname_print", args=[opname.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "DINAS KESEHATAN KABUPATEN")
        self.assertContains(response, "Instalasi Farmasi Daerah")

    def test_detail_shows_full_stock_opname_report_button_for_gudang(self):
        opname = self.create_opname(status=StockOpname.Status.IN_PROGRESS)
        StockOpnameItem.objects.create(
            stock_opname=opname,
            stock=self.stock,
            system_quantity=Decimal("100"),
            actual_quantity=Decimal("100"),
        )

        self.client.force_login(self.gudang)
        response = self.client.get(
            reverse("stock_opname:opname_detail", args=[opname.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cetak Opname")
        self.assertContains(
            response,
            reverse("stock_opname:opname_report_print", args=[opname.pk]),
        )

    def test_detail_hides_refresh_stock_update_for_completed_opname(self):
        opname = self.create_opname(status=StockOpname.Status.COMPLETED)
        StockOpnameItem.objects.create(
            stock_opname=opname,
            stock=self.stock,
            system_quantity=Decimal("100"),
            actual_quantity=Decimal("100"),
        )

        self.client.force_login(self.gudang)
        response = self.client.get(
            reverse("stock_opname:opname_detail", args=[opname.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Refresh Stok Update")
        self.assertContains(response, "Cetak Opname")

    def test_full_stock_opname_report_prints_assignee_signatures(self):
        opname = self.create_opname(status=StockOpname.Status.IN_PROGRESS)
        self.gudang.full_name = "Petugas Gudang Satu"
        self.gudang.nip = "198001012006041001"
        self.gudang.save(update_fields=["full_name", "nip"])
        second_assignee = User.objects.create_user(
            username="gudang_opname_report",
            password="secret12345",
            role=User.Role.GUDANG,
            full_name="Petugas Gudang Dua",
            nip="198201012006041002",
        )
        opname.assigned_to.add(self.gudang, second_assignee)
        StockOpnameItem.objects.create(
            stock_opname=opname,
            stock=self.stock,
            system_quantity=Decimal("100"),
            actual_quantity=Decimal("100"),
            notes="Cocok",
        )

        self.client.force_login(self.gudang)
        response = self.client.get(
            reverse("stock_opname:opname_report_print", args=[opname.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Laporan Stock Opname")
        self.assertContains(response, "Masker Medis")
        self.assertContains(response, "Stok Sistem")
        self.assertContains(response, "Stok Update")
        self.assertContains(response, "Stok Fisik")
        self.assertContains(response, "Sumber Dana")
        self.assertContains(response, "BOK")
        self.assertContains(response, "Mengetahui")
        self.assertContains(response, "Kepala")
        self.assertContains(response, "Petugas Gudang Satu")
        self.assertContains(response, "198001012006041001")
        self.assertContains(response, "Petugas Gudang Dua")
        self.assertContains(response, "198201012006041002")
        self.assertContains(response, "Cocok")

    def test_opname_surfaces_show_stock_update_and_compact_columns(self):
        self.stock.source_document_number = "RCV-OPNAME-LAYER"
        self.stock.quantity = Decimal("95")
        self.stock.unit_price = Decimal("1234.1234567890")
        self.stock.save(
            update_fields=[
                "source_document_number",
                "quantity",
                "unit_price",
                "updated_at",
            ]
        )
        opname = self.create_opname(status=StockOpname.Status.IN_PROGRESS)
        StockOpnameItem.objects.create(
            stock_opname=opname,
            stock=self.stock,
            system_quantity=Decimal("100"),
            actual_quantity=Decimal("95"),
        )

        self.client.force_login(self.admin)
        for url_name in ["opname_detail", "opname_input"]:
            with self.subTest(url_name=url_name):
                response = self.client.get(
                    reverse(f"stock_opname:{url_name}", args=[opname.pk]),
                    secure=True,
                )

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Stok Update")
                self.assertContains(response, "Stok Fisik")
                self.assertContains(response, "Sumber Dana")
                self.assertContains(response, "BOK")
                self.assertContains(response, "95")
                self.assertContains(response, "1.234,123456789")
                self.assertContains(response, "Dok: RCV-OPNAME-LAYER")
                self.assertNotContains(response, "<th>Dokumen Sumber</th>", html=True)
                self.assertNotContains(
                    response,
                    '<td class="text-end">1.234,12</td>',
                    html=True,
                )
        detail_response = self.client.get(
            reverse("stock_opname:opname_detail", args=[opname.pk]),
            secure=True,
        )
        self.assertContains(
            detail_response,
            '<span class="text-danger"><strong>0</strong> selisih</span>',
            html=True,
        )

        print_response = self.client.get(
            reverse("stock_opname:opname_print", args=[opname.pk]),
            secure=True,
        )
        self.assertEqual(print_response.status_code, 200)
        self.assertContains(print_response, "Tidak ada item dengan selisih.")
        self.assertNotContains(print_response, "Masker Medis")

    def test_completed_opname_uses_frozen_stock_update_after_later_stock_change(self):
        opname = self.create_opname(status=StockOpname.Status.IN_PROGRESS)
        StockOpnameItem.objects.create(
            stock_opname=opname,
            stock=self.stock,
            system_quantity=Decimal("100"),
            actual_quantity=Decimal("100"),
        )
        self.client.force_login(self.admin)
        complete_response = self.client.post(
            reverse("stock_opname:opname_complete", args=[opname.pk]),
            secure=True,
        )
        self.assertEqual(complete_response.status_code, 302)

        self.stock.quantity = Decimal("75")
        self.stock.save(update_fields=["quantity", "updated_at"])

        detail_response = self.client.get(
            reverse("stock_opname:opname_detail", args=[opname.pk]),
            secure=True,
        )
        detail_item = next(
            item
            for loc_data in detail_response.context["locations"]
            for item in loc_data["items"]
        )
        self.assertEqual(detail_response.context["discrepancy_count"], 0)
        self.assertEqual(detail_item.stock_update_quantity, Decimal("100"))
        self.assertEqual(detail_item.current_difference, Decimal("0"))

        report_response = self.client.get(
            reverse("stock_opname:opname_report_print", args=[opname.pk]),
            secure=True,
        )
        report_item = next(
            item
            for loc_data in report_response.context["locations"]
            for item in loc_data["items"]
        )
        self.assertEqual(report_response.context["discrepancy_count"], 0)
        self.assertEqual(report_item.stock_update_quantity, Decimal("100"))
        self.assertEqual(report_item.current_difference, Decimal("0"))

        print_response = self.client.get(
            reverse("stock_opname:opname_print", args=[opname.pk]),
            secure=True,
        )
        self.assertEqual(print_response.context["total_discrepancies"], 0)
        self.assertContains(print_response, "Tidak ada item dengan selisih.")

    def test_completed_discrepancy_print_uses_frozen_stock_update(self):
        opname = self.create_opname(status=StockOpname.Status.IN_PROGRESS)
        StockOpnameItem.objects.create(
            stock_opname=opname,
            stock=self.stock,
            system_quantity=Decimal("100"),
            actual_quantity=Decimal("90"),
        )
        self.client.force_login(self.admin)
        complete_response = self.client.post(
            reverse("stock_opname:opname_complete", args=[opname.pk]),
            secure=True,
        )
        self.assertEqual(complete_response.status_code, 302)

        self.stock.quantity = Decimal("90")
        self.stock.save(update_fields=["quantity", "updated_at"])

        print_response = self.client.get(
            reverse("stock_opname:opname_print", args=[opname.pk]),
            secure=True,
        )
        print_item = next(
            item
            for loc_data in print_response.context["locations"]
            for item in loc_data["items"]
        )
        self.assertEqual(print_response.context["total_discrepancies"], 1)
        self.assertEqual(print_item.stock_update_quantity, Decimal("100"))
        self.assertEqual(print_item.current_difference, Decimal("-10"))
        self.assertContains(print_response, "Masker Medis")

    def test_delete_completed_opname_returns_404(self):
        opname = self.create_opname(status=StockOpname.Status.COMPLETED)
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("stock_opname:opname_delete", args=[opname.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 404)

    def test_delete_in_progress_opname_voids_issued_number(self):
        opname = self.create_opname()
        self.client.force_login(self.admin)
        start_response = self.client.post(
            reverse("stock_opname:opname_start", args=[opname.pk]),
            secure=True,
        )
        self.assertEqual(start_response.status_code, 302)
        opname.refresh_from_db()
        self.assertEqual(opname.status, StockOpname.Status.IN_PROGRESS)
        issue = DocumentNumberIssue.objects.get(object_id=opname.pk)

        response = self.client.post(
            reverse("stock_opname:opname_delete", args=[opname.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(StockOpname.objects.filter(pk=opname.pk).exists())
        issue.refresh_from_db()
        self.assertEqual(issue.status, DocumentNumberIssue.Status.VOID)
        self.assertEqual(issue.voided_by, self.admin)
        self.assertIsNotNone(issue.voided_at)

    def test_stock_opname_item_has_timestamps(self):
        opname = self.create_opname(status=StockOpname.Status.IN_PROGRESS)
        item = StockOpnameItem.objects.create(
            stock_opname=opname,
            stock=self.stock,
            system_quantity=Decimal("100"),
        )

        self.assertIsNotNone(item.created_at)
        self.assertIsNotNone(item.updated_at)


class StockOpnameCompletionBackfillMigrationTests(StockOpnameTestMixin, TestCase):
    def _run_backfill(self):
        migration = importlib.import_module(
            "apps.stock_opname.migrations.0011_backfill_completion_stock_quantity"
        )
        schema_editor = SimpleNamespace(connection=connection)
        migration.backfill_completion_stock_quantity(django_apps, schema_editor)

    def test_backfill_preserves_system_snapshot_despite_later_transactions(self):
        snapshot_at = timezone.now() - timedelta(days=3)
        completed_at = timezone.now() - timedelta(days=2)
        opname = self.create_opname(status=StockOpname.Status.COMPLETED)
        opname.completed_by = self.admin
        opname.completed_at = completed_at
        opname.save(update_fields=["completed_by", "completed_at", "updated_at"])
        item = StockOpnameItem.objects.create(
            stock_opname=opname,
            stock=self.stock,
            system_quantity=Decimal("80"),
            actual_quantity=Decimal("50"),
        )
        StockOpnameItem.objects.filter(pk=item.pk).update(created_at=snapshot_at)
        self.stock.quantity = Decimal("5")
        self.stock.save(update_fields=["quantity", "updated_at"])
        in_period_transaction = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.stock.item,
            location=self.stock.location,
            batch_lot=self.stock.batch_lot,
            source_document_number=self.stock.source_document_number,
            quantity=Decimal("30"),
            unit_price=self.stock.unit_price,
            sumber_dana=self.stock.sumber_dana,
            reference_type=Transaction.ReferenceType.DISTRIBUTION,
            reference_id=2,
            user=self.admin,
        )
        Transaction.objects.filter(pk=in_period_transaction.pk).update(
            created_at=snapshot_at + timedelta(days=1)
        )
        self._run_backfill()

        item.refresh_from_db()
        self.assertEqual(item.completion_stock_quantity, Decimal("80"))

    def test_backfill_preserves_system_snapshot_without_completion_timestamp(self):
        opname = self.create_opname(status=StockOpname.Status.COMPLETED)
        item = StockOpnameItem.objects.create(
            stock_opname=opname,
            stock=self.stock,
            system_quantity=Decimal("100"),
            actual_quantity=Decimal("70"),
        )
        self.stock.quantity = Decimal("70")
        self.stock.save(update_fields=["quantity", "updated_at"])

        self._run_backfill()

        item.refresh_from_db()
        self.assertEqual(item.completion_stock_quantity, Decimal("100"))

    def test_backfill_preserves_system_snapshot_for_synthetic_legacy_item_timestamp(self):
        draft_created_at = timezone.now() - timedelta(days=4)
        completed_at = timezone.now() - timedelta(days=2)
        opname = self.create_opname(status=StockOpname.Status.COMPLETED)
        opname.completed_by = self.admin
        opname.completed_at = completed_at
        opname.save(update_fields=["completed_by", "completed_at", "updated_at"])
        StockOpname.objects.filter(pk=opname.pk).update(created_at=draft_created_at)
        item = StockOpnameItem.objects.create(
            stock_opname=opname,
            stock=self.stock,
            system_quantity=Decimal("80"),
            actual_quantity=Decimal("50"),
        )
        StockOpnameItem.objects.filter(pk=item.pk).update(created_at=draft_created_at)
        self.stock.quantity = Decimal("5")
        self.stock.save(update_fields=["quantity", "updated_at"])
        transaction = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.stock.item,
            location=self.stock.location,
            batch_lot=self.stock.batch_lot,
            source_document_number=self.stock.source_document_number,
            quantity=Decimal("30"),
            unit_price=self.stock.unit_price,
            sumber_dana=self.stock.sumber_dana,
            reference_type=Transaction.ReferenceType.DISTRIBUTION,
            reference_id=1,
            user=self.admin,
        )
        Transaction.objects.filter(pk=transaction.pk).update(
            created_at=draft_created_at + timedelta(days=1)
        )

        self._run_backfill()

        item.refresh_from_db()
        self.assertEqual(item.completion_stock_quantity, Decimal("80"))

class StockOpnameQualityTests(StockOpnameTestMixin, TestCase):
    """Tests for F9–F15 quality / convention fixes."""

    # ------------------------------------------------------------------
    # F10 — assigned_to must exclude inactive users
    # ------------------------------------------------------------------
    def test_form_excludes_inactive_users_from_assigned_to(self):
        inactive = User.objects.create_user(
            username="inactive_gudang_q",
            password="secret12345",
            role=User.Role.GUDANG,
            is_active=False,
        )
        from apps.stock_opname.forms import StockOpnameForm

        # Create form: inactive user must NOT appear.
        form = StockOpnameForm()
        qs = form.fields["assigned_to"].queryset
        self.assertIn(self.gudang, qs)
        self.assertNotIn(inactive, qs)

    def test_edit_form_preserves_deactivated_assignee_in_queryset(self):
        """Reviewer concern: deactivating an assigned user must not silently
        drop them when a staff member later saves an unrelated edit on the
        same draft opname."""
        inactive = User.objects.create_user(
            username="inactive_was_assigned_q",
            password="secret12345",
            role=User.Role.GUDANG,
            is_active=True,  # active at assignment time
        )
        from apps.stock_opname.forms import StockOpnameForm

        draft = self.create_opname(status=StockOpname.Status.DRAFT)
        draft.assigned_to.add(inactive)

        # Now deactivate the user (simulating real-world deactivation after assignment)
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])

        # The edit form must still include the now-inactive user in the queryset
        # so the M2M relation is not silently cleared on save.
        edit_form = StockOpnameForm(instance=draft)
        qs = edit_form.fields["assigned_to"].queryset
        self.assertIn(inactive, qs, "Deactivated current assignee must remain in edit queryset")
        self.assertIn(self.gudang, qs, "Active users must still appear")

    def test_create_form_excludes_deactivated_user_even_if_previously_assigned(self):
        """A deactivated user must never appear on a fresh create form."""
        inactive = User.objects.create_user(
            username="inactive_create_check_q",
            password="secret12345",
            role=User.Role.GUDANG,
            is_active=False,
        )
        from apps.stock_opname.forms import StockOpnameForm

        form = StockOpnameForm()  # no instance
        qs = form.fields["assigned_to"].queryset
        self.assertNotIn(inactive, qs)


    # ------------------------------------------------------------------
    # F9 — FormHelper must be configured (crispy-forms)
    # ------------------------------------------------------------------
    def test_form_has_crispy_helper(self):
        from apps.stock_opname.forms import StockOpnameForm
        from crispy_forms.helper import FormHelper

        form = StockOpnameForm()
        self.assertIsInstance(form.helper, FormHelper)
        self.assertFalse(form.helper.form_tag)

    # ------------------------------------------------------------------
    # F14 — edit blocked for IN_PROGRESS and COMPLETED opnames
    # ------------------------------------------------------------------
    def test_edit_redirects_for_in_progress_opname(self):
        in_progress = self.create_opname(status=StockOpname.Status.IN_PROGRESS)
        self.client.force_login(self.admin)

        for method in ("get", "post"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    reverse("stock_opname:opname_edit", args=[in_progress.pk]),
                    secure=True,
                )
                self.assertEqual(response.status_code, 302)
                self.assertEqual(
                    response.headers["Location"],
                    reverse("stock_opname:opname_detail", args=[in_progress.pk]),
                )

    def test_edit_redirects_for_completed_opname(self):
        completed = self.create_opname(status=StockOpname.Status.COMPLETED)
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("stock_opname:opname_edit", args=[completed.pk]),
            secure=True,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["Location"],
            reverse("stock_opname:opname_detail", args=[completed.pk]),
        )

    def test_edit_allowed_for_draft_opname(self):
        draft = self.create_opname(status=StockOpname.Status.DRAFT)
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("stock_opname:opname_edit", args=[draft.pk]),
            secure=True,
        )
        self.assertEqual(response.status_code, 200)

    def test_edit_reloads_row_after_concurrent_start(self):
        draft = self.create_opname(status=StockOpname.Status.DRAFT)
        stale_draft = StockOpname.objects.get(pk=draft.pk)
        self.client.force_login(self.admin)

        self.client.post(
            reverse("stock_opname:opname_start", args=[draft.pk]),
            secure=True,
        )
        draft.refresh_from_db()
        issued_number = draft.document_number

        with mock.patch(
            "apps.stock_opname.views.get_object_or_404", return_value=stale_draft
        ):
            response = self.client.post(
                reverse("stock_opname:opname_edit", args=[draft.pk]),
                {
                    "period_type": StockOpname.PeriodType.MONTHLY,
                    "period_start": "2026-04-01",
                    "period_end": "2026-04-30",
                    "categories": [str(self.category.pk)],
                    "assigned_to": [str(self.gudang.pk)],
                    "notes": "Tidak boleh tersimpan",
                },
                secure=True,
            )

        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(draft.status, StockOpname.Status.IN_PROGRESS)
        self.assertEqual(draft.document_number, issued_number)
        self.assertEqual(draft.period_end, date(2026, 3, 31))
        self.assertEqual(draft.notes, "")

    # ------------------------------------------------------------------
    # F13 — pagination must preserve query filters
    # ------------------------------------------------------------------
    def test_pagination_links_preserve_filters(self):
        # Create 25 DRAFT opnames so pagination kicks in (page_size=20)
        for i in range(25):
            self.create_opname(document_number=f"SO-FILT-{i:04d}")

        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("stock_opname:opname_list") + "?q=FILT&status=DRAFT",
            secure=True,
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # The querystring tag should embed existing params in pagination hrefs
        self.assertIn("q=FILT", content)
        self.assertIn("status=DRAFT", content)

    # ------------------------------------------------------------------
    # F15 — admin get_queryset must use select_related + prefetch_related
    # ------------------------------------------------------------------
    def test_admin_get_queryset_uses_prefetch_and_select_related(self):
        from django.contrib.admin.sites import AdminSite
        from apps.stock_opname.admin import StockOpnameAdmin

        ma = StockOpnameAdmin(StockOpname, AdminSite())
        qs = ma.get_queryset(mock.Mock())
        # select_related stores a dict of joined tables
        self.assertIn("created_by", qs.query.select_related)
        # prefetch_related stores a list of lookups
        self.assertIn("assigned_to", qs._prefetch_related_lookups)

    def test_admin_existing_opname_makes_workflow_fields_read_only(self):
        from django.contrib.admin.sites import AdminSite
        from apps.stock_opname.admin import StockOpnameAdmin

        ma = StockOpnameAdmin(StockOpname, AdminSite())
        opname = self.create_opname(
            status=StockOpname.Status.IN_PROGRESS,
            document_number="SO-202603-00001",
        )

        readonly_fields = ma.get_readonly_fields(mock.Mock(), opname)

        self.assertIn("status", readonly_fields)
        self.assertIn("created_by", readonly_fields)
        self.assertIn("completed_by", readonly_fields)
        self.assertIn("completed_at", readonly_fields)
        self.assertIn("period_end", readonly_fields)

    def test_admin_locks_entire_header_after_draft(self):
        from django.contrib.admin.sites import AdminSite
        from apps.stock_opname.admin import StockOpnameAdmin

        ma = StockOpnameAdmin(StockOpname, AdminSite())
        request = mock.Mock(user=self.admin)
        draft = self.create_opname(status=StockOpname.Status.DRAFT)
        in_progress = self.create_opname(status=StockOpname.Status.IN_PROGRESS)
        completed = self.create_opname(status=StockOpname.Status.COMPLETED)

        self.assertTrue(ma.has_change_permission(request, draft))
        self.assertFalse(ma.has_change_permission(request, in_progress))
        self.assertFalse(ma.has_change_permission(request, completed))

    def test_numbered_form_ignores_changed_period_end(self):
        from apps.stock_opname.forms import StockOpnameForm

        opname = self.create_opname(
            status=StockOpname.Status.DRAFT,
            document_number="SO-202603-00001",
        )
        original_period_end = opname.period_end
        form = StockOpnameForm(
            data={
                "period_type": StockOpname.PeriodType.MONTHLY,
                "period_start": "2026-03-01",
                "period_end": "2026-04-30",
                "categories": [self.category.pk],
                "assigned_to": [self.gudang.pk],
                "notes": "Catatan diperbarui",
            },
            instance=opname,
        )

        self.assertTrue(form.fields["period_end"].disabled)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        opname.refresh_from_db()
        self.assertEqual(opname.period_end, original_period_end)

        draft_form = StockOpnameForm(instance=self.create_opname())
        self.assertFalse(draft_form.fields["period_end"].disabled)

    def test_admin_disables_object_and_bulk_deletion(self):
        from django.contrib.admin.sites import AdminSite
        from apps.stock_opname.admin import StockOpnameAdmin

        ma = StockOpnameAdmin(StockOpname, AdminSite())
        request = mock.Mock(user=self.admin)
        draft = self.create_opname()

        self.assertFalse(ma.has_delete_permission(request))
        self.assertFalse(ma.has_delete_permission(request, draft))
        self.assertNotIn("delete_selected", ma.get_actions(request))

    def test_admin_new_opname_forces_draft_workflow_state(self):
        from django.contrib.admin.sites import AdminSite
        from apps.stock_opname.admin import StockOpnameAdmin

        ma = StockOpnameAdmin(StockOpname, AdminSite())
        request = mock.Mock(user=self.admin)
        readonly_fields = ma.get_readonly_fields(request, None)
        opname = StockOpname(
            period_type=StockOpname.PeriodType.MONTHLY,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
            status=StockOpname.Status.COMPLETED,
            completed_by=self.gudang,
            completed_at=timezone.now(),
        )

        ma.save_model(request, opname, mock.Mock(), change=False)

        opname.refresh_from_db()
        self.assertIn("status", readonly_fields)
        self.assertIn("created_by", readonly_fields)
        self.assertIn("completed_by", readonly_fields)
        self.assertIn("completed_at", readonly_fields)
        self.assertEqual(opname.status, StockOpname.Status.DRAFT)
        self.assertEqual(opname.created_by, self.admin)
        self.assertIsNone(opname.completed_by)
        self.assertIsNone(opname.completed_at)

