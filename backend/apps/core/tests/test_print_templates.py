from datetime import date

from django.test import TestCase
from django.urls import reverse

from apps.expired.models import Expired
from apps.items.models import Category, Facility, Item, Unit
from apps.lplpo.models import LPLPO
from apps.stock_opname.models import StockOpname
from apps.users.models import User


class PrintAndAdminStylesheetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser(
            username="print-style-review", password="PrintStyleTest123!"
        )
        unit = Unit.objects.create(code="PRN", name="Print unit")
        category = Category.objects.create(code="PRN", name="Print category")
        cls.item = Item.objects.create(
            kode_barang="PRINT-STYLE-001", nama_barang="Print item",
            satuan=unit, kategori=category,
        )
        cls.opname = StockOpname.objects.create(
            period_type=StockOpname.PeriodType.MONTHLY,
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
            created_by=cls.user,
        )
        cls.expired = Expired.objects.create(
            report_date=date(2026, 1, 1), created_by=cls.user,
        )
        facility = Facility.objects.create(code="PRN", name="Print facility")
        cls.lplpo = LPLPO.objects.create(
            facility=facility, bulan=1, tahun=2026, created_by=cls.user,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_standalone_documents_load_scoped_print_styles_without_desktop_shell(self):
        routes = (
            ("stock:stock_card_print", [self.item.pk], {}),
            ("stock_opname:opname_print", [self.opname.pk], {}),
            ("stock_opname:opname_report_print", [self.opname.pk], {}),
            ("expired:expired_print", [self.expired.pk], {}),
            ("expired:expired_audit_report", [], {
                "format": "print", "start_date": "2026-01-01",
                "end_date": "2026-12-31", "date_field": "disposed_at",
                "outcome_type": "BOTH",
            }),
            ("lplpo:lplpo_print", [self.lplpo.pk], {}),
            ("lplpo:lplpo_print_report", [], {}),
        )
        for name, args, params in routes:
            with self.subTest(route=name):
                response = self.client.get(reverse(name, args=args), params, secure=True)
                self.assertContains(response, "css/app.tailwind.css")
                self.assertContains(response, 'class="ims-print-document ims-print-')
                self.assertNotContains(response, "vendor/bootstrap/css/")
                self.assertNotContains(response, 'class="sidebar')

    def test_lplpo_report_print_uses_the_csp_compatible_external_handler(self):
        response = self.client.get(reverse("lplpo:lplpo_print_report"), secure=True)
        self.assertContains(response, 'data-action="print"')
        self.assertContains(response, "js/confirm-actions.js")
        self.assertNotContains(response, "onclick=")
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])

    def test_admin_import_styles_do_not_load_application_preflight(self):
        for name in ("admin:stock_opening_balance_import_csv", "admin:items_unit_import"):
            with self.subTest(route=name):
                response = self.client.get(reverse(name), secure=True)
                self.assertContains(response, "admin/css/ims-import.css")
                self.assertContains(response, "admin/css/base.css")
                self.assertNotContains(response, "css/app.tailwind.css")
                self.assertNotContains(response, "vendor/bootstrap/css/")
