from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

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
from apps.lplpo.models import LPLPO, LPLPOItem
from apps.puskesmas.models import (
    PuskesmasConsumption,
    PuskesmasConsumptionEntry,
    PuskesmasReceiptConfirmation,
    PuskesmasReceiptConfirmationItem,
    PuskesmasSubunit,
)
from apps.stock.models import Stock
from apps.users.models import User


REPORTING_SETTINGS = {
    "REPORTING_API_ENABLED": True,
    "REPORTING_API_SHARED_SECRET": "test-reporting-secret",
    "REPORTING_API_CACHE_TTL_SECONDS": 21600,
}


class ReportingApiTestCase(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _auth(self, secret="test-reporting-secret"):
        return {"HTTP_AUTHORIZATION": f"Bearer {secret}"}


@override_settings(**REPORTING_SETTINGS)
class ReportingApiAuthTests(ReportingApiTestCase):
    def test_missing_secret_returns_401(self):
        response = self.client.get(reverse("reporting_api:stocks_latest"), secure=True)

        self.assertEqual(response.status_code, 401)

    def test_wrong_secret_returns_401(self):
        response = self.client.get(
            reverse("reporting_api:stocks_latest"),
            secure=True,
            **self._auth("wrong-secret"),
        )

        self.assertEqual(response.status_code, 401)

    def test_bearer_scheme_is_case_insensitive(self):
        response = self.client.get(
            reverse("reporting_api:stocks_latest"),
            secure=True,
            HTTP_AUTHORIZATION="bearer test-reporting-secret",
        )

        self.assertEqual(response.status_code, 200)

    def test_malformed_authorization_bytes_return_401(self):
        response = self.client.get(
            reverse("reporting_api:stocks_latest"),
            secure=True,
            HTTP_AUTHORIZATION="Bearer \xff",
        )

        self.assertEqual(response.status_code, 401)

    @override_settings(REPORTING_API_ENABLED=False)
    def test_disabled_api_returns_403(self):
        response = self.client.get(
            reverse("reporting_api:stocks_latest"),
            secure=True,
            **self._auth(),
        )

        self.assertEqual(response.status_code, 403)


@override_settings(**REPORTING_SETTINGS)
class LatestWarehouseStockApiTests(ReportingApiTestCase):
    def test_latest_stock_includes_zero_items_and_aggregates_layers(self):
        unit = Unit.objects.create(code="TAB", name="Tablet")
        category = Category.objects.create(code="MED", name="Medicine", sort_order=1)
        funding_source = FundingSource.objects.create(code="DAK", name="DAK")
        location = Location.objects.create(code="GUD", name="Gudang")
        program = Program.objects.create(code="CCG", name="Kecacingan")
        therapeutic_class = TherapeuticClass.objects.create(
            code="ANT",
            name="Antelmintik",
        )
        stocked_item = Item.objects.create(
            kode_barang="ITM-001",
            nama_barang="Amoxicillin",
            satuan=unit,
            kategori=category,
            is_program_item=True,
            program=program,
            minimum_stock=Decimal("20"),
        )
        stocked_item.therapeutic_classes.add(therapeutic_class)
        zero_item = Item.objects.create(
            kode_barang="ITM-002",
            nama_barang="Paracetamol",
            satuan=unit,
            kategori=category,
            minimum_stock=Decimal("1"),
        )
        today = timezone.localdate()
        Stock.objects.create(
            item=stocked_item,
            location=location,
            batch_lot="B-OLD",
            expiry_date=today - timedelta(days=1),
            quantity=Decimal("10"),
            reserved=Decimal("2"),
            unit_price=Decimal("1000"),
            sumber_dana=funding_source,
            source_document_number="DOC-1",
        )
        Stock.objects.create(
            item=stocked_item,
            location=location,
            batch_lot="B-SOON",
            expiry_date=today + timedelta(days=30),
            quantity=Decimal("15"),
            reserved=Decimal("3"),
            unit_price=Decimal("1000"),
            sumber_dana=funding_source,
            source_document_number="DOC-2",
        )

        response = self.client.get(
            reverse("reporting_api:stocks_latest"),
            secure=True,
            **self._auth(),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        rows = {row["kode_barang"]: row for row in payload["results"]}
        self.assertEqual(payload["count"], 2)
        self.assertEqual(rows["ITM-001"]["physical_quantity"], "25.00")
        self.assertEqual(rows["ITM-001"]["reserved_quantity"], "5.00")
        self.assertEqual(rows["ITM-001"]["available_quantity"], "20.00")
        self.assertFalse(rows["ITM-001"]["is_low_stock"])
        self.assertTrue(rows["ITM-001"]["is_program_item"])
        self.assertEqual(
            rows["ITM-001"]["program"],
            {"id": program.pk, "code": "CCG", "name": "Kecacingan"},
        )
        self.assertEqual(
            rows["ITM-001"]["therapeutic_classes"],
            [{"id": therapeutic_class.pk, "code": "ANT", "name": "Antelmintik"}],
        )
        self.assertEqual(rows["ITM-001"]["expired_batch_count"], 1)
        self.assertEqual(rows["ITM-001"]["expiring_batch_count"], 1)
        self.assertEqual(rows["ITM-002"]["physical_quantity"], "0.00")
        self.assertEqual(rows["ITM-002"]["available_quantity"], "0.00")
        self.assertTrue(rows["ITM-002"]["is_low_stock"])
        self.assertFalse(rows["ITM-002"]["is_program_item"])
        self.assertIsNone(rows["ITM-002"]["program"])
        self.assertEqual(rows["ITM-002"]["therapeutic_classes"], [])
        self.assertIn("generated_at", payload)
        self.assertEqual(payload["cache_ttl_seconds"], 21600)

    def test_latest_stock_response_is_cached(self):
        unit = Unit.objects.create(code="BTL", name="Bottle")
        category = Category.objects.create(code="SUP", name="Supply", sort_order=1)
        item = Item.objects.create(
            kode_barang="ITM-CACHE",
            nama_barang="Cached Item",
            satuan=unit,
            kategori=category,
        )

        first = self.client.get(
            reverse("reporting_api:stocks_latest"),
            secure=True,
            **self._auth(),
        )
        item.nama_barang = "Changed Item"
        item.save(update_fields=["nama_barang"])
        second = self.client.get(
            reverse("reporting_api:stocks_latest"),
            secure=True,
            **self._auth(),
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json(), second.json())

    def test_latest_stock_serializes_aggregates_larger_than_one_stock_row(self):
        unit = Unit.objects.create(code="AMP", name="Ampoule")
        category = Category.objects.create(code="BIG", name="Large Stock", sort_order=1)
        funding_source = FundingSource.objects.create(code="APBD", name="APBD")
        location = Location.objects.create(code="BIG-GUD", name="Big Gudang")
        item = Item.objects.create(
            kode_barang="ITM-BIG",
            nama_barang="Large Aggregate",
            satuan=unit,
            kategori=category,
        )
        Stock.objects.create(
            item=item,
            location=location,
            batch_lot="BIG-1",
            quantity=Decimal("9999999999.99"),
            reserved=Decimal("1.00"),
            unit_price=Decimal("1000"),
            sumber_dana=funding_source,
            source_document_number="BIG-DOC-1",
        )
        Stock.objects.create(
            item=item,
            location=location,
            batch_lot="BIG-2",
            quantity=Decimal("9999999999.99"),
            reserved=Decimal("2.00"),
            unit_price=Decimal("1000"),
            sumber_dana=funding_source,
            source_document_number="BIG-DOC-2",
        )

        response = self.client.get(
            reverse("reporting_api:stocks_latest"),
            secure=True,
            **self._auth(),
        )

        self.assertEqual(response.status_code, 200)
        row = response.json()["results"][0]
        self.assertEqual(row["physical_quantity"], "19999999999.98")
        self.assertEqual(row["reserved_quantity"], "3.00")
        self.assertEqual(row["available_quantity"], "19999999996.98")


@override_settings(**REPORTING_SETTINGS)
class LatestPuskesmasStockApiTests(ReportingApiTestCase):
    def test_latest_puskesmas_stock_defaults_current_year_and_applies_adjustments(self):
        unit = Unit.objects.create(code="PCS", name="Pieces")
        category = Category.objects.create(code="PKM", name="Puskesmas", sort_order=1)
        facility = Facility.objects.create(
            code="PKM-01",
            name="Puskesmas 01",
            facility_type=Facility.FacilityType.PUSKESMAS,
        )
        user = User.objects.create_user(
            username="puskesmas-api-user",
            password="TestPassword123!",
            role=User.Role.GUDANG,
        )
        program = Program.objects.create(code="TB", name="Tuberkulosis")
        therapeutic_one = TherapeuticClass.objects.create(
            code="ABX",
            name="Antibiotik",
        )
        therapeutic_two = TherapeuticClass.objects.create(
            code="RESP",
            name="Respirasi",
        )
        item = Item.objects.create(
            kode_barang="ITM-PKM",
            nama_barang="ORS",
            satuan=unit,
            kategori=category,
            is_program_item=True,
            program=program,
            minimum_stock=Decimal("10"),
        )
        item.therapeutic_classes.add(therapeutic_one, therapeutic_two)
        year = timezone.localdate().year
        lplpo = LPLPO.objects.create(
            facility=facility,
            bulan=3,
            tahun=year,
            status=LPLPO.Status.SUBMITTED,
            created_by=user,
        )
        LPLPOItem.objects.create(
            lplpo=lplpo,
            item=item,
            stock_awal=100,
            penerimaan=0,
            persediaan=100,
            pemakaian=40,
            stock_keseluruhan=60,
            permintaan_jumlah=0,
            pemberian_jumlah=0,
        )
        confirmation = PuskesmasReceiptConfirmation.objects.create(
            facility=facility,
            distribution=None,
            received_date=date(year, 4, 15),
            status=PuskesmasReceiptConfirmation.ReceiptStatus.CONFIRMED,
            created_by=user,
        )
        PuskesmasReceiptConfirmationItem.objects.create(
            sbbk=confirmation,
            item=item,
            quantity=Decimal("25"),
            unit_price=Decimal("1000"),
        )
        consumption = PuskesmasConsumption.objects.create(
            facility=facility,
            bulan=5,
            tahun=year,
            created_by=user,
        )
        subunit = PuskesmasSubunit.objects.create(
            facility=facility,
            name="Poli Umum",
            subunit_type=PuskesmasSubunit.SubunitType.TREATMENT_ROOM,
        )
        PuskesmasConsumptionEntry.objects.create(
            consumption=consumption,
            item=item,
            subunit=subunit,
            quantity=7,
        )

        response = self.client.get(
            reverse("reporting_api:puskesmas_stocks_latest"),
            secure=True,
            **self._auth(),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["period"], {"year": year})
        self.assertEqual(payload["count"], 1)
        row = payload["results"][0]
        self.assertEqual(row["facility_name"], "Puskesmas 01")
        self.assertEqual(row["item_id"], item.pk)
        self.assertEqual(row["kode_barang"], "ITM-PKM")
        self.assertTrue(row["is_program_item"])
        self.assertEqual(
            row["program"],
            {"id": program.pk, "code": "TB", "name": "Tuberkulosis"},
        )
        self.assertEqual(
            row["therapeutic_classes"],
            [
                {"id": therapeutic_one.pk, "code": "ABX", "name": "Antibiotik"},
                {"id": therapeutic_two.pk, "code": "RESP", "name": "Respirasi"},
            ],
        )
        self.assertEqual(row["stock_current"], 78)
        self.assertEqual(row["base_month"], 3)
        self.assertEqual(row["base_year"], year)
        self.assertEqual(row["receipt_adjustment"], 25)
        self.assertEqual(row["consumption_adjustment"], 7)

    def test_puskesmas_stock_rejects_invalid_year(self):
        response = self.client.get(
            reverse("reporting_api:puskesmas_stocks_latest"),
            {"year": "invalid"},
            secure=True,
            **self._auth(),
        )

        self.assertEqual(response.status_code, 400)

    def test_puskesmas_stock_cache_varies_by_year(self):
        with patch(
            "apps.api.views.build_latest_puskesmas_stock_payload",
            side_effect=lambda year: {
                "generated_at": timezone.now(),
                "cache_ttl_seconds": 21600,
                "period": {"year": year},
                "count": 0,
                "results": [],
            },
        ) as builder:
            first = self.client.get(
                reverse("reporting_api:puskesmas_stocks_latest"),
                {"year": "2025"},
                secure=True,
                **self._auth(),
            )
            second = self.client.get(
                reverse("reporting_api:puskesmas_stocks_latest"),
                {"year": "2026"},
                secure=True,
                **self._auth(),
            )
            third = self.client.get(
                reverse("reporting_api:puskesmas_stocks_latest"),
                {"year": "2025"},
                secure=True,
                **self._auth(),
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(third.status_code, 200)
        self.assertEqual(builder.call_count, 2)
        self.assertEqual(first.json()["period"], {"year": 2025})
        self.assertEqual(second.json()["period"], {"year": 2026})

    def test_puskesmas_stock_returns_all_rows_not_html_page_size(self):
        unit = Unit.objects.create(code="BOX", name="Box")
        category = Category.objects.create(code="MANY", name="Many", sort_order=1)
        facility = Facility.objects.create(
            code="PKM-MANY",
            name="Puskesmas Many",
            facility_type=Facility.FacilityType.PUSKESMAS,
        )
        user = User.objects.create_user(
            username="puskesmas-many-api-user",
            password="TestPassword123!",
            role=User.Role.GUDANG,
        )
        year = timezone.localdate().year
        lplpo = LPLPO.objects.create(
            facility=facility,
            bulan=1,
            tahun=year,
            status=LPLPO.Status.SUBMITTED,
            created_by=user,
        )
        for index in range(30):
            item = Item.objects.create(
                kode_barang=f"ITM-MANY-{index:02d}",
                nama_barang=f"Many Item {index:02d}",
                satuan=unit,
                kategori=category,
            )
            LPLPOItem.objects.create(
                lplpo=lplpo,
                item=item,
                stock_awal=1,
                penerimaan=0,
                pemakaian=0,
            )

        response = self.client.get(
            reverse("reporting_api:puskesmas_stocks_latest"),
            **self._auth(),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 30)


@override_settings(**REPORTING_SETTINGS)
class ReportingApiSchemaTests(ReportingApiTestCase):
    def test_schema_contains_reporting_endpoints(self):
        response = self.client.get(reverse("api_schema"), secure=True)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("/api/v1/reporting/stocks/latest/", content)
        self.assertIn("/api/v1/reporting/puskesmas-stocks/latest/", content)
        self.assertIn("ReportingApiBearerAuth", content)

    def test_swagger_and_redoc_routes_render(self):
        swagger = self.client.get(reverse("api_docs_swagger"), secure=True)
        redoc = self.client.get(reverse("api_docs_redoc"), secure=True)

        self.assertEqual(swagger.status_code, 200)
        self.assertEqual(redoc.status_code, 200)
