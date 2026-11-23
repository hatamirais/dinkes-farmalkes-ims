"""Real ledger/ORM verification of the staged FEFO engine; no posting test doubles."""
from datetime import date
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from apps.core.tests.mixins import SecureClientDefaultsMixin
from apps.lplpo.models import LPLPO, LPLPOItem
from .test_inventory import InventoryFixture
from .models import PuskesmasConsumption, PuskesmasConsumptionEntry, PuskesmasSubunit
from .inventory_models import (
    PuskesmasConsumptionRevision, PuskesmasConsumptionAllocation, PuskesmasInventoryBalance,
    PuskesmasInventoryMovement, PuskesmasInventoryPosting, PuskesmasLPLPOInventoryBinding,
)
from .consumption_inventory import (
    _post_revision_locked, finalize_consumption, snapshot, snapshot_digest, assert_operator,
)
from .inventory import locked_actor, lock_facility
from .inventory_reporting import period_rows, adopt_opening, adoption_digest


class ConsumptionFixture(InventoryFixture):
    def setUp(self):
        super().setUp()
        self.subunit = PuskesmasSubunit.objects.create(facility=self.facility, name="Poli", subunit_type="TREATMENT_ROOM")
        self.post(self.opening(rows=[self.row("first", "100.1234567890", "10"), self.row("second", "200", "10")]))
        self.consumption = PuskesmasConsumption.objects.create(facility=self.facility, tahun=2026, bulan=1, created_by=self.operator)
        PuskesmasConsumptionEntry.objects.create(consumption=self.consumption, item=self.item, subunit=self.subunit, quantity=12)

    def engine(self, data=None, reason="", expected_digest=None, user=None):
        # Exercise the actual engine behind the closed operational gate, with the
        # same transaction/locks/authority. No expiry adapter or stock service fake.
        with transaction.atomic():
            actor = locked_actor(user or self.operator)
            facility = lock_facility(self.facility.pk)
            assert_operator(actor, facility)
            consumption = PuskesmasConsumption.objects.select_for_update().get(pk=self.consumption.pk)
            return _post_revision_locked(consumption=consumption, user=actor,
                data=snapshot(consumption) if data is None else data, reason=reason,
                expected_digest=expected_digest)


@override_settings(RATELIMIT_ENABLE=False)
class ConsumptionInventoryTests(ConsumptionFixture, SecureClientDefaultsMixin, TestCase):
    def test_fefo_cost_layers_and_shared_report_identity(self):
        revision = self.engine()
        self.assertEqual(list(revision.allocations.values_list("quantity", "unit_price")),
                         [(10, Decimal("100.1234567890")), (2, Decimal("200"))])
        self.assertEqual(list(PuskesmasInventoryBalance.objects.order_by("pk").values_list("quantity", flat=True)), [0, 8])
        rows, _ = period_rows([self.facility.pk], 2026, 1)
        row = rows[0]
        self.assertEqual(row["opening_value"], Decimal("3001.2345678900"))
        self.assertEqual(row["consumption_value"], Decimal("1401.2345678900"))
        self.assertEqual(row["closing_value"], Decimal("1600"))
        self.assertEqual(row["opening_value"] + row["receipts_value"] - row["consumption_value"], row["closing_value"])
        self.assertEqual(PuskesmasInventoryPosting.objects.filter(consumption_revision=revision).count(), 1)
        self.assertEqual(self.engine().pk, revision.pk)

    def test_shortage_rolls_back_all_effects(self):
        self.consumption.entries.update(quantity=21)
        with self.assertRaisesMessage(ValidationError, "kekurangan 1"):
            self.engine()
        self.assertFalse(PuskesmasConsumptionRevision.objects.exists())
        self.assertEqual(list(PuskesmasInventoryBalance.objects.values_list("quantity", flat=True)), [10, 10])

    def test_dated_fefo_precedes_null_expiry_regardless_of_layer_creation_order(self):
        self.facility = self.other
        self.operator.facility = self.other
        self.operator.save(update_fields=["facility"])
        undated = self.row("undated", "30", "2")
        later = self.row("later", "20", "2")
        later["expiry_date"] = date(2027, 6, 1)
        earlier = self.row("earlier", "10", "2")
        earlier["expiry_date"] = date(2027, 2, 1)
        self.post(self.opening(rows=[undated, later, earlier]))
        self.subunit = PuskesmasSubunit.objects.create(facility=self.other, name="Poli Lain", subunit_type="TREATMENT_ROOM")
        self.consumption = PuskesmasConsumption.objects.create(facility=self.other, tahun=2026, bulan=1, created_by=self.operator)
        PuskesmasConsumptionEntry.objects.create(consumption=self.consumption, item=self.item, subunit=self.subunit, quantity=5)
        revision = self.engine()
        self.assertEqual(list(revision.allocations.order_by("pk").values_list("quantity", "unit_price")),
                         [(2, Decimal("10")), (2, Decimal("20")), (1, Decimal("30"))])

    def test_exact_reversal_replacement_and_failed_correction(self):
        first = self.engine()
        data = snapshot(self.consumption)
        data["entries"][0]["quantity"] = 8
        second = self.engine(data, reason="Koreksi catatan poli")
        self.assertEqual(second.number, 2)
        self.assertEqual(list(first.posting.reversal.movements.order_by("layer_id").values_list("quantity_delta", flat=True)), [10, 2])
        self.assertEqual(list(PuskesmasInventoryBalance.objects.order_by("pk").values_list("quantity", flat=True)), [2, 10])
        self.assertEqual(self.consumption.entries.get().quantity, 8)
        data["entries"][0]["quantity"] = 99
        with self.assertRaises(ValidationError):
            self.engine(data, reason="Belum lengkap")
        self.assertEqual(PuskesmasConsumptionRevision.objects.count(), 2)
        self.assertFalse(hasattr(second.posting, "reversal"))

    def test_posted_sources_are_protected_through_orm(self):
        self.engine()
        for action in [lambda: self.consumption.delete(),
                       lambda: self.consumption.entries.all().delete(),
                       lambda: self.consumption.entries.update(quantity=1),
                       lambda: self.consumption.save(),
                       lambda: PuskesmasConsumptionEntry.objects.create(consumption=self.consumption,
                           item=self.item, subunit=self.subunit, quantity=1)]:
            with self.subTest(action=action), self.assertRaises(ValidationError):
                action()

    def test_public_finalization_and_http_remain_gated(self):
        digest = snapshot_digest(self.consumption, snapshot(self.consumption))
        with self.assertRaisesMessage(ValidationError, "Integrasi modul kedaluwarsa"):
            finalize_consumption(user=self.operator, consumption_id=self.consumption.pk, digest=digest)
        self.client.force_login(self.operator)
        response = self.client.post(reverse("puskesmas:consumption_finalize", args=[self.consumption.pk]), {"digest": digest}, follow=True)
        self.assertContains(response, "Integrasi modul kedaluwarsa")
        self.assertFalse(PuskesmasConsumptionRevision.objects.exists())

    def test_january_adoption_preserves_requests_and_blocks_submission(self):
        lplpo = LPLPO.objects.create(facility=self.facility, tahun=2026, bulan=1, created_by=self.operator)
        line = LPLPOItem.objects.create(lplpo=lplpo, item=self.item, stock_awal=5, harga_satuan=999,
            permintaan_jumlah=7, permintaan_alasan="Untuk pelayanan")
        binding = adopt_opening(user=self.operator, lplpo_id=lplpo.pk, digest=adoption_digest(lplpo))
        line.refresh_from_db()
        self.assertEqual((line.stock_awal, line.pemakaian, line.permintaan_jumlah), (20, 0, 7))
        self.assertEqual(binding.previous_values[0]["stock_awal"], 5)
        self.assertEqual(line.nilai_stok_awal, Decimal("3001.2345678900"))
        self.client.force_login(self.operator)
        response = self.client.post(reverse("lplpo:lplpo_submit", args=[lplpo.pk]), follow=True)
        self.assertContains(response, "Integrasi modul kedaluwarsa")
        lplpo.refresh_from_db()
        self.assertEqual(lplpo.status, "DRAFT")
        response = self.client.get(reverse("lplpo:lplpo_edit", args=[lplpo.pk]))
        self.assertNotContains(response, ">Harga Satuan</th>")

    def test_stale_adoption_and_unauthorized_facility(self):
        lplpo = LPLPO.objects.create(facility=self.facility, tahun=2026, bulan=1, created_by=self.operator)
        digest = adoption_digest(lplpo)
        LPLPOItem.objects.create(lplpo=lplpo, item=self.item)
        with self.assertRaises(ValidationError):
            adopt_opening(user=self.operator, lplpo_id=lplpo.pk, digest=digest)
        with self.assertRaises(PermissionDenied):
            self.engine(user=self.verifier)

    def test_later_month_blocks_earlier_correction_and_missing_zero_month(self):
        self.engine()
        february = PuskesmasConsumption.objects.create(facility=self.facility, tahun=2026, bulan=2, created_by=self.operator)
        original = self.consumption
        self.consumption = february
        self.engine()  # Explicit finalized zero use is retained as a revision.
        self.consumption = original
        data = snapshot(original)
        data["entries"][0]["quantity"] = 11
        with self.assertRaisesMessage(ValidationError, "Bulan berikutnya"):
            self.engine(data, reason="Koreksi Januari")

    def test_report_html_excel_and_facility_boundary(self):
        self.client.force_login(self.operator)
        response = self.client.get(reverse("puskesmas:inventory_report"), {"year": 2026, "month": 1, "facility": self.other.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual({row["facility_id"] for row in response.context["rows"]}, {self.facility.pk})
        self.assertContains(response, "Belum lengkap")
        response = self.client.get(reverse("puskesmas:inventory_report"), {"year": 2026, "month": 1, "format": "excel"})
        from openpyxl import load_workbook
        import io
        workbook = load_workbook(io.BytesIO(response.content))
        self.assertEqual(Decimal(workbook.active.cell(4, 5).value), Decimal("3001.2345678900"))
        self.assertIn("Lapisan Harga Asli", workbook.sheetnames)

    def test_expiry_within_month_is_held_without_silent_accounting_policy(self):
        # New independently verified opening uses real dated layers.
        self.consumption.entries.update(quantity=1)
        # Direct SQL-level economic edits are prohibited; use another genuine
        # opening in an independent facility instead of altering posted history.
        self.facility = self.other
        self.operator.facility = self.other
        self.operator.save(update_fields=["facility"])
        row = self.row("dated", "5", "2")
        row["expiry_date"] = date(2026, 1, 15)
        self.post(self.opening(rows=[row]))
        self.subunit = PuskesmasSubunit.objects.create(facility=self.other, name="Poli Lain", subunit_type="TREATMENT_ROOM")
        self.consumption = PuskesmasConsumption.objects.create(facility=self.other, tahun=2026, bulan=1, created_by=self.operator)
        PuskesmasConsumptionEntry.objects.create(consumption=self.consumption, item=self.item, subunit=self.subunit, quantity=1)
        with self.assertRaisesMessage(ValidationError, "aturan/alur kedaluwarsa"):
            self.engine()

    def test_new_backdated_receipt_cannot_change_finalized_fefo(self):
        self.engine()
        receipt, _, _ = self.receipt(received_date=date(2026, 1, 20))
        from .inventory import post_receipt
        with self.assertRaisesMessage(ValidationError, "sudah difinalisasi"):
            post_receipt(receipt=receipt, user=self.operator)

    def test_correction_syncs_bound_lplpo_from_posted_revision(self):
        lplpo = LPLPO.objects.create(facility=self.facility, tahun=2026, bulan=1, created_by=self.operator)
        adopt_opening(user=self.operator, lplpo_id=lplpo.pk, digest=adoption_digest(lplpo))
        self.engine()
        line = lplpo.items.get(item=self.item)
        self.assertEqual((line.pemakaian, line.stock_keseluruhan), (12, 8))
        data = snapshot(self.consumption)
        data["entries"][0]["quantity"] = 6
        self.engine(data, reason="Hitungan poli diperbaiki")
        line.refresh_from_db()
        self.assertEqual((line.pemakaian, line.stock_keseluruhan), (6, 14))

    def test_future_month_and_missing_prior_zero_month_are_blocked(self):
        self.consumption.bulan = 3
        self.consumption.save(update_fields=["bulan"])
        with self.assertRaisesMessage(ValidationError, "01/2026 belum difinalisasi"):
            self.engine()
        self.consumption.tahun = 9999
        self.consumption.save(update_fields=["tahun"])
        with self.assertRaisesMessage(ValidationError, "sebelum hari terakhir"):
            self.engine()

    def test_multi_subunit_allocations_share_one_movement_per_layer(self):
        second = PuskesmasSubunit.objects.create(facility=self.facility, name="Pustu", subunit_type="HELPER_SITE")
        self.consumption.entries.update(quantity=6)
        PuskesmasConsumptionEntry.objects.create(consumption=self.consumption, item=self.item, subunit=second, quantity=6)
        revision = self.engine()
        self.assertEqual(revision.allocations.count(), 3)
        self.assertEqual(revision.posting.movements.count(), 2)
        self.assertEqual(sum(revision.allocations.values_list("quantity", flat=True)), 12)

    def test_stale_correction_and_foreign_subunit_are_rejected(self):
        self.engine()
        data = snapshot(self.consumption)
        data["entries"][0]["quantity"] = 5
        with self.assertRaisesMessage(ValidationError, "berubah"):
            self.engine(data, reason="Koreksi", expected_digest="stale")
        other_subunit = PuskesmasSubunit.objects.create(facility=self.other, name="Other", subunit_type="HELPER_SITE")
        data["entries"][0]["subunit_id"] = other_subunit.pk
        with self.assertRaises(PermissionDenied):
            self.engine(data, reason="Koreksi")

    def test_posted_lplpo_blocks_consumption_correction(self):
        self.engine()
        LPLPO.objects.create(facility=self.facility, tahun=2026, bulan=1, created_by=self.operator, status="SUBMITTED")
        data = snapshot(self.consumption)
        data["entries"][0]["quantity"] = 5
        with self.assertRaisesMessage(ValidationError, "sudah diajukan"):
            self.engine(data, reason="Koreksi")
        self.assertEqual(PuskesmasConsumptionRevision.objects.count(), 1)

    def test_bound_offline_export_hides_price_and_rejects_override(self):
        import io
        from openpyxl import load_workbook
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.lplpo.xlsx_io import export_lplpo_workbook, apply_lplpo_workbook_import
        lplpo = LPLPO.objects.create(facility=self.facility, tahun=2026, bulan=1, created_by=self.operator)
        adopt_opening(user=self.operator, lplpo_id=lplpo.pk, digest=adoption_digest(lplpo))
        lplpo.refresh_from_db()
        workbook = load_workbook(io.BytesIO(export_lplpo_workbook(lplpo).content))
        self.assertTrue(workbook.active.column_dimensions["G"].hidden)
        workbook.active.cell(12, 5).value = 999
        content = io.BytesIO()
        workbook.save(content)
        upload = SimpleUploadedFile("lplpo.xlsx", content.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with self.assertRaisesMessage(ValidationError, "inventaris dan terkunci"):
            apply_lplpo_workbook_import(uploaded_file=upload, lplpo_obj=lplpo)

    def test_inventory_report_routing_and_range_do_not_use_legacy_price(self):
        self.engine()
        lplpo = LPLPO.objects.create(facility=self.facility, tahun=2026, bulan=1, created_by=self.operator)
        adopt_opening(user=self.operator, lplpo_id=lplpo.pk, digest=adoption_digest(lplpo))
        self.client.force_login(self.operator)
        from .forms import PuskesmasPersediaanFilterForm
        params = PuskesmasPersediaanFilterForm.get_default_initial()
        params["year"] = 2026
        response = self.client.get(reverse("puskesmas:report_rekap_persediaan"), params)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("puskesmas:inventory_report"), response.url)
        rows, _ = period_rows([self.facility.pk], 2026, 2, start_month=1)
        self.assertEqual(rows[0]["closing_value"], Decimal("1600"))

    def test_new_january_lplpo_uses_posted_opening_automatically(self):
        self.client.force_login(self.operator)
        response = self.client.post(reverse("lplpo:lplpo_create"), {"facility": self.facility.pk,
            "tahun": 2026, "bulan": 1, "notes": ""})
        self.assertEqual(response.status_code, 302)
        lplpo = LPLPO.objects.get(facility=self.facility, tahun=2026, bulan=1)
        self.assertTrue(lplpo.inventory_backed)
        self.assertEqual(lplpo.items.get(item=self.item).stock_awal, 20)


class ConsumptionConcurrencyTests(ConsumptionFixture, TransactionTestCase):
    def test_duplicate_finalize_serializes_to_one_revision(self):
        def run():
            close_old_connections()
            try:
                return self.engine().pk
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(lambda _: run(), range(2)))
        self.assertEqual(result[0], result[1])
        self.assertEqual(PuskesmasConsumptionRevision.objects.count(), 1)
        self.assertEqual(list(PuskesmasInventoryBalance.objects.order_by("pk").values_list("quantity", flat=True)), [0, 8])

    def test_receipt_and_consumption_have_one_serial_order(self):
        receipt, _, _ = self.receipt(received_date=date(2026, 1, 20), status="DRAFT")
        def confirm():
            close_old_connections()
            try:
                with transaction.atomic():
                    actor = locked_actor(self.admin)
                    lock_facility(self.facility.pk)
                    receipt.status = "CONFIRMED"
                    receipt.save(update_fields=["status", "updated_at"])
                    from .inventory import post_receipt
                    post_receipt(receipt=receipt, user=actor)
                return "POSTED"
            except ValidationError:
                return "HELD"
            finally:
                close_old_connections()
        def consume():
            close_old_connections()
            try:
                return self.engine().pk
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            confirmed = pool.submit(confirm)
            used = pool.submit(consume)
            result = confirmed.result()
            used.result()
        self.assertEqual(PuskesmasConsumptionRevision.objects.count(), 1)
        self.assertEqual(sum(PuskesmasInventoryBalance.objects.values_list("quantity", flat=True)),
                         11 if result == "POSTED" else 8)
