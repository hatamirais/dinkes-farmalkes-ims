from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.items.models import Category, FundingSource, Item, Location, Unit
from apps.stock.models import Stock
from apps.stock_opname.models import StockOpname, StockOpnameItem
from apps.users.access import ensure_default_module_access
from apps.users.models import User


class StockOpnameApprovalAccessTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin_opname",
            password="secret12345",
        )
        self.gudang = User.objects.create_user(
            username="gudang_only_opname",
            password="secret12345",
            role=User.Role.GUDANG,
        )
        ensure_default_module_access(self.gudang, overwrite=True)

        unit = Unit.objects.create(code="PCS", name="Pieces")
        category = Category.objects.create(code="ALKES", name="Alkes", sort_order=1)
        item = Item.objects.create(
            kode_barang="ITM-OP-001",
            nama_barang="Masker Medis",
            satuan=unit,
            kategori=category,
            minimum_stock=Decimal("0"),
        )
        location = Location.objects.create(code="LOC-OP", name="Gudang Opname")
        funding = FundingSource.objects.create(code="BOK", name="BOK")
        stock = Stock.objects.create(
            item=item,
            location=location,
            batch_lot="BATCH-OP-01",
            expiry_date="2030-01-01",
            quantity=Decimal("100"),
            reserved=Decimal("0"),
            unit_price=Decimal("1000"),
            sumber_dana=funding,
        )

        self.opname = StockOpname.objects.create(
            document_number="SOP-2026-00001",
            period_type=StockOpname.PeriodType.MONTHLY,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            status=StockOpname.Status.IN_PROGRESS,
            created_by=self.admin,
        )
        StockOpnameItem.objects.create(
            stock_opname=self.opname,
            stock=stock,
            system_quantity=Decimal("100"),
            actual_quantity=Decimal("100"),
        )

    def test_gudang_cannot_complete_opname(self):
        self.client.force_login(self.gudang)
        response = self.client.post(
            reverse("stock_opname:opname_complete", args=[self.opname.pk])
        )
        self.assertEqual(response.status_code, 403)
