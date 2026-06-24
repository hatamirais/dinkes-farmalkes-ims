from datetime import date
from decimal import Decimal
from unittest import mock

from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.models import TimeStampedModel
from apps.items.models import Category, FundingSource, Item, Location, Unit
from apps.stock.models import Stock
from apps.stock_opname.models import StockOpname, StockOpnameItem
from apps.users.access import ensure_default_module_access
from apps.users.models import User


class StockOpnameTestMixin:
    def setUp(self):
        super().setUp()
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
        opname = StockOpname.objects.create(
            document_number=document_number or "",
            period_type=StockOpname.PeriodType.MONTHLY,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            status=status,
            created_by=self.admin,
        )
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
        snapshot = StockOpnameItem.objects.get(stock_opname=opname, stock=self.stock)
        self.assertEqual(snapshot.system_quantity, Decimal("100"))

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

    def test_location_filter_is_preserved_after_post(self):
        self.client.force_login(self.gudang)
        input_url = reverse("stock_opname:opname_input", args=[self.opname.pk])

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
        self.assertEqual(
            response.headers["Location"],
            f"{input_url}?location={self.location.pk}",
        )

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


    def test_input_rejects_null_byte_notes(self):
        self.client.force_login(self.gudang)

        response = self.client.post(
            reverse("stock_opname:opname_input", args=[self.opname.pk]),
            {
                f"qty_{self.opname_item.pk}": "95",
                f"notes_{self.opname_item.pk}": "bad\x00note",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.opname_item.refresh_from_db()
        self.assertIsNone(self.opname_item.actual_quantity)
        self.assertContains(
            response,
            "Karakter null tidak diizinkan.",
            status_code=400,
        )

    def test_input_rejects_invalid_location_filter_on_get(self):
        self.client.force_login(self.gudang)

        response = self.client.get(
            reverse("stock_opname:opname_input", args=[self.opname.pk]),
            {"location": "not-an-integer"},
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Permintaan tidak dapat diproses", status_code=400)

    def test_input_rejects_invalid_location_filter_on_post(self):
        self.client.force_login(self.gudang)

        response = self.client.post(
            reverse("stock_opname:opname_input", args=[self.opname.pk]),
            {
                "location": "not-an-integer",
                f"qty_{self.opname_item.pk}": "90",
                f"notes_{self.opname_item.pk}": "Rak depan",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Permintaan tidak dapat diproses", status_code=400)


    def test_input_page_shows_row_note_limit_help_text(self):
        self.client.force_login(self.gudang)

        response = self.client.get(
            reverse("stock_opname:opname_input", args=[self.opname.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Maksimal 255 karakter.")


class StockOpnameListAndFormValidationTests(StockOpnameTestMixin, TestCase):
    def test_list_rejects_invalid_status_filter(self):
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("stock_opname:opname_list"),
            {"status": "INVALID"},
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Permintaan tidak dapat diproses", status_code=400)

    def test_list_rejects_invalid_period_filter(self):
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("stock_opname:opname_list"),
            {"period": "INVALID"},
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Permintaan tidak dapat diproses", status_code=400)

    def test_create_rejects_null_byte_notes(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("stock_opname:opname_create"),
            {
                "period_type": StockOpname.PeriodType.MONTHLY,
                "period_start": "2026-03-01",
                "period_end": "2026-03-31",
                "categories": [str(self.category.pk)],
                "assigned_to": [str(self.gudang.pk)],
                "notes": "catatan\x00rusak",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Karakter null tidak diizinkan.")
        self.assertEqual(StockOpname.objects.count(), 0)

    def test_create_rejects_out_of_range_period_year(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("stock_opname:opname_create"),
            {
                "period_type": StockOpname.PeriodType.MONTHLY,
                "period_start": "0999-03-01",
                "period_end": "2026-03-31",
                "categories": [str(self.category.pk)],
                "assigned_to": [str(self.gudang.pk)],
                "notes": "ok",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tahun tanggal mulai tidak valid.")
        self.assertEqual(StockOpname.objects.count(), 0)


    def test_create_form_shows_header_note_limit_help_text(self):
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("stock_opname:opname_create"),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Maksimal 1000 karakter.")


@override_settings(
    STOCK_OPNAME_FORM_RATE_LIMIT="1/m",
    STOCK_OPNAME_INPUT_RATE_LIMIT="1/m",
    STOCK_OPNAME_WORKFLOW_RATE_LIMIT="1/m",
    RATELIMIT_USE_CACHE="locmem",
)
class StockOpnameMutationRateLimitTests(StockOpnameTestMixin, TestCase):
    def test_create_returns_429_when_form_rate_limited(self):
        self.client.force_login(self.admin)
        payload = {
            "period_type": StockOpname.PeriodType.MONTHLY,
            "period_start": "2026-03-01",
            "period_end": "2026-03-31",
            "categories": [str(self.category.pk)],
            "assigned_to": [str(self.gudang.pk)],
            "notes": "Sesi pertama",
        }

        first = self.client.post(
            reverse("stock_opname:opname_create"),
            payload,
            secure=True,
        )
        payload["period_start"] = "2026-04-01"
        payload["period_end"] = "2026-04-30"
        payload["notes"] = "Sesi kedua"
        second = self.client.post(
            reverse("stock_opname:opname_create"),
            payload,
            secure=True,
        )

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 429)
        self.assertContains(second, "Terlalu banyak percobaan pada aksi ini", status_code=429)

    def test_workflow_bucket_can_rate_limit_complete(self):
        warmup = self.create_opname()
        target = self.create_opname(status=StockOpname.Status.IN_PROGRESS)
        StockOpnameItem.objects.create(
            stock_opname=target,
            stock=self.stock,
            system_quantity=Decimal("100"),
            actual_quantity=Decimal("100"),
        )
        self.client.force_login(self.admin)

        started = self.client.post(
            reverse("stock_opname:opname_start", args=[warmup.pk]),
            secure=True,
        )
        throttled = self.client.post(
            reverse("stock_opname:opname_complete", args=[target.pk]),
            secure=True,
        )

        self.assertEqual(started.status_code, 302)
        self.assertEqual(throttled.status_code, 429)
        self.assertContains(throttled, "Terlalu banyak percobaan pada aksi ini", status_code=429)


@override_settings(
    STOCK_OPNAME_FORM_RATE_LIMIT="10/m",
    STOCK_OPNAME_INPUT_RATE_LIMIT="1/m",
    STOCK_OPNAME_WORKFLOW_RATE_LIMIT="10/m",
    RATELIMIT_USE_CACHE="locmem",
)
class StockOpnameRateLimitSeparationTests(StockOpnameTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.opname = self.create_opname(status=StockOpname.Status.IN_PROGRESS)
        self.opname_item = StockOpnameItem.objects.create(
            stock_opname=self.opname,
            stock=self.stock,
            system_quantity=Decimal("100"),
        )

    def test_input_rate_limit_does_not_block_complete(self):
        self.client.force_login(self.admin)
        input_url = reverse("stock_opname:opname_input", args=[self.opname.pk])

        first = self.client.post(
            input_url,
            {
                f"qty_{self.opname_item.pk}": "100",
                f"notes_{self.opname_item.pk}": "Hitung pertama",
            },
            secure=True,
        )
        throttled = self.client.post(
            input_url,
            {
                f"qty_{self.opname_item.pk}": "100",
                f"notes_{self.opname_item.pk}": "Hitung kedua",
            },
            secure=True,
        )
        completed = self.client.post(
            reverse("stock_opname:opname_complete", args=[self.opname.pk]),
            secure=True,
        )

        self.assertEqual(first.status_code, 302)
        self.assertEqual(throttled.status_code, 429)
        self.assertEqual(completed.status_code, 302)
        self.opname.refresh_from_db()
        self.assertEqual(self.opname.status, StockOpname.Status.COMPLETED)

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

    def test_gudang_cannot_complete_opname(self):
        self.client.force_login(self.gudang)
        response = self.client.post(
            reverse("stock_opname:opname_complete", args=[self.opname.pk]),
            secure=True,
        )
        self.assertEqual(response.status_code, 403)


class StockOpnameModelTests(StockOpnameTestMixin, TestCase):
    def test_document_number_retries_on_unique_conflict(self):
        self.create_opname(document_number="SO-202605-00001")

        with mock.patch.object(
            StockOpname,
            "generate_document_number",
            side_effect=["SO-202605-00001", "SO-202605-00002"],
        ):
            opname = StockOpname(
                period_type=StockOpname.PeriodType.MONTHLY,
                period_start=date(2026, 4, 1),
                period_end=date(2026, 4, 30),
                created_by=self.admin,
            )
            opname.save()

        self.assertEqual(opname.document_number, "SO-202605-00002")

    def test_document_number_retry_does_not_swallow_unrelated_integrity_error(self):
        with mock.patch.object(
            StockOpname,
            "generate_document_number",
            return_value="SO-202605-99999",
        ) as generate_mock, mock.patch.object(
            TimeStampedModel,
            "save",
            side_effect=IntegrityError(
                'duplicate key value violates unique constraint "stock_opnames_period_type_key"'
            ),
        ):
            opname = StockOpname(
                period_type=StockOpname.PeriodType.MONTHLY,
                period_start=date(2026, 4, 1),
                period_end=date(2026, 4, 30),
                created_by=self.admin,
            )
            with self.assertRaises(IntegrityError):
                opname.save()

        self.assertEqual(generate_mock.call_count, 1)
