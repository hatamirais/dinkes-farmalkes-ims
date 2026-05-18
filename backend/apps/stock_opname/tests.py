from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.urls import reverse

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
