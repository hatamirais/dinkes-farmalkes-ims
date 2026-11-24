"""Real ORM accounting and workflow verification; no expiry/stock test doubles."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from uuid import uuid4
import io

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from apps.core.tests.mixins import SecureClientDefaultsMixin
from apps.lplpo.models import LPLPO, LPLPOItem
from apps.users.models import User, ModuleAccess
from .test_inventory import InventoryFixture
from .models import PuskesmasConsumption, PuskesmasConsumptionEntry, PuskesmasSubunit
from .expiry import post_expiry
from .expiry_models import PuskesmasExpiry, PuskesmasExpiryRevision
from .inventory import locked_actor, lock_facility
from .inventory_models import PuskesmasInventoryLayer, PuskesmasInventoryBalance, PuskesmasInventoryMovement
from .inventory_reporting import period_rows, adopt_opening, adoption_digest
from .consumption_inventory import _post_revision_locked, snapshot, snapshot_digest, finalize_consumption


class ExpiryFixture(InventoryFixture):
    def setUp(self):
        super().setUp()
        first, second = self.row("early", "100.1234567890", "10"), self.row("later", "200", "10")
        first["expiry_date"], second["expiry_date"] = date(2027, 1, 1), date(2027, 6, 1)
        self.post(self.opening(rows=[first, second]))
        self.layers = list(PuskesmasInventoryLayer.objects.order_by("pk"))
        self.subunit = PuskesmasSubunit.objects.create(facility=self.facility, name="Poli", subunit_type="TREATMENT_ROOM")
        self.consumption = PuskesmasConsumption.objects.create(facility=self.facility, tahun=2026, bulan=1, created_by=self.operator)
        PuskesmasConsumptionEntry.objects.create(consumption=self.consumption, item=self.item, subunit=self.subunit, quantity=12)

    def withdraw(self, quantity=3, **kwargs):
        data = dict(user=self.operator, facility_id=self.facility.pk, effective_date=date(2026, 1, 20),
            reference="Bukti penarikan", reason="Batch ditarik dari stok yang boleh digunakan",
            entries=[dict(layer_id=self.layers[0].pk, quantity=quantity)], request_key=uuid4())
        data.update(kwargs)
        return post_expiry(**data)

    def consume(self):
        with transaction.atomic():
            actor = locked_actor(self.operator)
            lock_facility(self.facility.pk)
            document = PuskesmasConsumption.objects.select_for_update().get(pk=self.consumption.pk)
            return _post_revision_locked(consumption=document, user=actor, data=snapshot(document))

    def balances(self):
        return list(PuskesmasInventoryBalance.objects.order_by("pk").values_list("quantity", flat=True))


@override_settings(RATELIMIT_ENABLE=False)
class ExpiryTests(ExpiryFixture, SecureClientDefaultsMixin, TestCase):
    def test_expiry_is_separate_costed_outflow_and_idempotent(self):
        token = uuid4()
        rev = self.withdraw(request_key=token)
        self.assertEqual(self.withdraw(request_key=token).pk, rev.pk)
        self.assertEqual(rev.lines.get().cost, Decimal("300.3703703670"))
        self.assertEqual(self.balances(), [7, 10])
        row = period_rows([self.facility.pk], 2026, 1)[0][0]
        self.assertEqual((row["expiry_quantity"], row["consumption_quantity"], row["closing_quantity"]), (3, 0, 17))
        self.assertEqual(row["opening_value"] + row["receipts_value"] - row["consumption_value"] - row["expiry_value"], row["closing_value"])

    def test_expiry_precedes_monthly_fefo(self):
        self.withdraw()
        rev = self.consume()
        self.assertEqual(list(rev.allocations.values_list("quantity", flat=True)), [7, 5])
        self.assertEqual(self.balances(), [0, 5])

    def test_public_consumption_and_bound_submission_work_after_expiry(self):
        lplpo = LPLPO.objects.create(facility=self.facility, tahun=2026, bulan=1, created_by=self.operator)
        adopt_opening(user=self.operator, lplpo_id=lplpo.pk, digest=adoption_digest(lplpo))
        self.withdraw()
        finalize_consumption(user=self.operator, consumption_id=self.consumption.pk,
            digest=snapshot_digest(self.consumption, snapshot(self.consumption)))
        self.client.force_login(self.operator)
        response = self.client.post(reverse("lplpo:lplpo_submit", args=[lplpo.pk]), follow=True)
        self.assertEqual(response.status_code, 200)
        lplpo.refresh_from_db()
        self.assertEqual(lplpo.status, "SUBMITTED")
        self.assertEqual(lplpo.items.get().kedaluwarsa, 3)

    def _expired_opening(self):
        self.facility = self.other
        self.operator.facility = self.other
        self.operator.save(update_fields=["facility"])
        expired, usable = self.row("expired", "50", "2"), self.row("usable", "100", "10")
        expired["expiry_date"], usable["expiry_date"] = date(2026, 1, 15), date(2027, 1, 1)
        self.post(self.opening(rows=[expired, usable]))
        self.layers = list(PuskesmasInventoryLayer.objects.filter(posting__facility=self.facility).order_by("pk"))
        subunit = PuskesmasSubunit.objects.create(facility=self.facility, name="Poli Lain", subunit_type="TREATMENT_ROOM")
        self.consumption = PuskesmasConsumption.objects.create(facility=self.facility, tahun=2026, bulan=1, created_by=self.operator)
        PuskesmasConsumptionEntry.objects.create(consumption=self.consumption, item=self.item, subunit=subunit, quantity=5)

    def test_unrecorded_expiry_holds_even_zero_use_without_deduction(self):
        self._expired_opening()
        self.consumption.entries.all().delete()
        before = PuskesmasInventoryMovement.objects.count()
        with self.assertRaisesMessage(ValidationError, "mencatat jumlah penarikan"):
            finalize_consumption(user=self.operator, consumption_id=self.consumption.pk,
                digest=snapshot_digest(self.consumption, snapshot(self.consumption)))
        self.assertEqual(PuskesmasInventoryMovement.objects.count(), before)
        self.withdraw(2)
        revision = finalize_consumption(user=self.operator, consumption_id=self.consumption.pk,
            digest=snapshot_digest(self.consumption, snapshot(self.consumption)))
        self.assertFalse(revision.allocations.exists())

    def test_later_dated_expiry_does_not_satisfy_earlier_month(self):
        self._expired_opening()
        self.withdraw(2, effective_date=date(2026, 2, 1))
        with self.assertRaisesMessage(ValidationError, "mencatat jumlah penarikan"):
            finalize_consumption(user=self.operator, consumption_id=self.consumption.pk,
                digest=snapshot_digest(self.consumption, snapshot(self.consumption)))

    def test_late_expiry_reverses_and_reallocates_same_month(self):
        original = self.consume()
        expiry = self.withdraw()
        replacement = self.consumption.inventory_revisions.latest("number")
        self.assertEqual(replacement.number, 2)
        self.assertEqual(replacement.expiry_revision_id, expiry.pk)
        self.assertEqual(original.posting.reversal.movements.count(), 2)
        self.assertEqual(list(replacement.allocations.values_list("quantity", flat=True)), [7, 5])
        self.assertEqual(self.balances(), [0, 5])

    def test_expiry_correction_and_void_keep_history_and_reallocate(self):
        first = self.withdraw()
        self.consume()
        second = self.withdraw(5, expiry_id=first.expiry_id, expected_digest=first.digest, reason="Koreksi hitungan")
        self.assertEqual(self.balances(), [0, 3])
        self.assertEqual(first.posting.reversal.movements.get().quantity_delta, 3)
        cancelled = self.withdraw(entries=[], expiry_id=first.expiry_id, expected_digest=second.digest,
            reason="Penarikan salah dicatat", void=True)
        self.assertTrue(cancelled.void)
        self.assertEqual(self.balances(), [0, 8])
        self.assertEqual(first.expiry.revisions.count(), 3)
        self.assertEqual(self.consumption.inventory_revisions.count(), 3)
        row = period_rows([self.facility.pk], 2026, 1)[0][0]
        self.assertEqual(row["expiry_quantity"], 0)
        self.assertEqual(row["consumption_quantity"], 12)

    def test_failed_reallocation_rolls_back_expiry_and_reversal(self):
        original = self.consume()
        before = PuskesmasInventoryMovement.objects.count()
        with self.assertRaisesMessage(ValidationError, "kekurangan"):
            self.withdraw(10)
        self.assertFalse(PuskesmasExpiry.objects.exists())
        self.assertEqual(PuskesmasInventoryMovement.objects.count(), before)
        self.assertFalse(hasattr(original.posting, "reversal"))
        self.assertEqual(self.balances(), [0, 8])

    def test_stale_and_invalid_corrections_do_not_mutate(self):
        first = self.withdraw()
        for changes in [dict(expected_digest="stale"), dict(effective_date=date(2026, 1, 21), expected_digest=first.digest),
                        dict(expected_digest=first.digest, entries=[dict(layer_id=self.layers[0].pk, quantity=11)])]:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.withdraw(4, expiry_id=first.expiry_id, reason="Koreksi", **changes)
        self.assertEqual(first.expiry.revisions.count(), 1)
        self.assertEqual(self.balances(), [7, 10])

    def test_submitted_lplpo_or_later_finalization_blocks_expiry(self):
        lplpo = LPLPO.objects.create(facility=self.facility, tahun=2026, bulan=1, created_by=self.operator, status="SUBMITTED")
        with self.assertRaisesMessage(ValidationError, "diajukan"):
            self.withdraw()
        lplpo.status = "DRAFT"
        lplpo.save(update_fields=["status"])
        self.consume()
        february = PuskesmasConsumption.objects.create(facility=self.facility, tahun=2026, bulan=2, created_by=self.operator)
        with transaction.atomic():
            locked_actor(self.operator)
            lock_facility(self.facility.pk)
            _post_revision_locked(consumption=february, user=self.operator, data=snapshot(february))
        with self.assertRaisesMessage(ValidationError, "berikutnya"):
            self.withdraw()

    def test_bound_lplpo_keeps_expiry_separate_and_offline_cannot_override_it(self):
        from apps.lplpo.xlsx_io import export_lplpo_workbook, apply_lplpo_workbook_import
        lplpo = LPLPO.objects.create(facility=self.facility, tahun=2026, bulan=1, created_by=self.operator)
        adopt_opening(user=self.operator, lplpo_id=lplpo.pk, digest=adoption_digest(lplpo))
        self.consume()
        self.withdraw()
        line = lplpo.items.get(item=self.item)
        self.assertEqual((line.pemakaian, line.kedaluwarsa, line.stock_keseluruhan), (12, 3, 5))
        lplpo.refresh_from_db()
        workbook = load_workbook(io.BytesIO(export_lplpo_workbook(lplpo).content))
        self.assertEqual(workbook.active["Q12"].value, 3)
        workbook.active["Q12"] = 999
        stream = io.BytesIO()
        workbook.save(stream)
        stream.seek(0)
        with transaction.atomic():
            lock_facility(self.facility.pk)
            apply_lplpo_workbook_import(uploaded_file=stream, lplpo_obj=lplpo)
        line.refresh_from_db()
        self.assertEqual((line.kedaluwarsa, line.stock_keseluruhan), (3, 5))
        self.client.force_login(self.operator)
        self.assertContains(self.client.get(reverse("lplpo:lplpo_detail", args=[lplpo.pk])), "Kedaluwarsa")
        self.assertContains(self.client.get(reverse("lplpo:lplpo_print", args=[lplpo.pk])), "Kedaluwarsa")

    def test_reports_and_excel_show_expiry_separately(self):
        self.withdraw()
        self.consume()
        self.client.force_login(self.operator)
        for name in ("inventory_report", "report_rekap_persediaan", "report_persediaan"):
            params = dict(year=2026, month=1, period="custom", start_month=1, end_month=1)
            response = self.client.get(reverse(f"puskesmas:{name}"), params)
            self.assertEqual(response.status_code, 200)
            if name == "report_rekap_persediaan":
                self.assertEqual(response.context["totals"]["nilai_kedaluwarsa"], Decimal("300.3703703670"))
            exported = self.client.get(reverse(f"puskesmas:{name}"), {**params, "format": "excel"})
            workbook = load_workbook(io.BytesIO(exported.content))
            if name == "inventory_report":
                self.assertEqual(Decimal(workbook.active["L4"].value), 3)
            elif name == "report_rekap_persediaan":
                self.assertEqual(Decimal(workbook.active["G5"].value), Decimal("300.3703703670"))

    def test_authority_scope_and_immutable_history(self):
        staff = User.objects.create_user(username="expiry-admin-umum", role="ADMIN_UMUM", facility=self.facility)
        ModuleAccess.objects.update_or_create(user=staff, module="puskesmas", defaults={"scope": ModuleAccess.Scope.MANAGE})
        for user, facility_id in [(staff, self.facility.pk), (self.verifier, self.facility.pk), (self.operator, self.other.pk)]:
            with self.subTest(user=user), self.assertRaises(PermissionDenied):
                self.withdraw(user=user, facility_id=facility_id)
        revision = self.withdraw()
        for action in (lambda: revision.save(), lambda: revision.delete(),
                       lambda: revision.lines.update(quantity=99), lambda: revision.expiry.delete()):
            with self.assertRaises(ValidationError):
                action()

    def test_invalid_quantities_dates_and_missing_expiry_are_held(self):
        for changes in [dict(effective_date=date(9999, 1, 1)), dict(effective_date=date(2025, 12, 31)),
                        dict(entries=[dict(layer_id=self.layers[0].pk, quantity=-1)]),
                        dict(entries=[dict(layer_id=self.layers[0].pk, quantity=Decimal("NaN"))]),
                        dict(reason="bad\x00reason"), dict(request_key="bad")]:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.withdraw(**changes)
        self.assertFalse(PuskesmasExpiry.objects.exists())
        self.facility = self.other
        self.operator.facility = self.other
        self.operator.save(update_fields=["facility"])
        self.post(self.opening(rows=[self.row("undated", "100", "10")]))
        layer = PuskesmasInventoryLayer.objects.get(posting__facility=self.facility)
        with self.assertRaisesMessage(ValidationError, "tanpa tanggal kedaluwarsa"):
            self.withdraw(entries=[dict(layer_id=layer.pk, quantity=1)])

    def test_document_read_and_correction_cannot_cross_facility(self):
        rev = self.withdraw()
        outsider = User.objects.create_user(username="expiry-outsider", role="PUSKESMAS", facility=self.other)
        self.client.force_login(outsider)
        for name in ("expiry_detail", "expiry_edit"):
            self.assertEqual(self.client.get(reverse(f"puskesmas:{name}", args=[rev.expiry_id])).status_code, 403)
        with self.assertRaises(PermissionDenied):
            self.withdraw(user=outsider, facility_id=self.other.pk, expiry_id=rev.expiry_id,
                expected_digest=rev.digest)

    def test_alerts_are_read_only_and_form_post_has_explicit_confirmation(self):
        self.client.force_login(self.operator)
        before = PuskesmasInventoryMovement.objects.count()
        response = self.client.get(reverse("puskesmas:expiry_list"), {"days": 365, "facility": self.other.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual({row["layer"].posting.facility_id for row in response.context["rows"]}, {self.facility.pk})
        self.assertEqual(PuskesmasInventoryMovement.objects.count(), before)
        data = dict(facility=self.facility.pk, effective_date="2026-01-20", reason="Ditarik", request_key=uuid4(),
            **{"form-TOTAL_FORMS": 1, "form-INITIAL_FORMS": 0, "form-0-item": self.item.pk, "form-0-layer": self.layers[0].pk, "form-0-quantity": 3})
        response = self.client.post(reverse("puskesmas:expiry_create"), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PuskesmasExpiry.objects.exists())
        data["confirmed"] = "on"
        response = self.client.post(reverse("puskesmas:expiry_create"), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PuskesmasExpiry.objects.count(), 1)


@override_settings(RATELIMIT_ENABLE=False)
class SharedExpiryPresentationTests(ExpiryFixture, SecureClientDefaultsMixin, TestCase):
    def test_item_batch_widget_is_shared_with_if_and_rejects_mismatch(self):
        from apps.core.form_fields import ItemBatchSelect
        from apps.expired.forms import StockByItemSelect
        from apps.items.models import Item
        from .expiry_views import ExpiryLineForm
        self.assertIs(StockByItemSelect, ItemBatchSelect)
        self.facility = self.other
        self.operator.facility = self.other
        self.operator.save(update_fields=["facility"])
        other_item = Item.objects.create(kode_barang="OTHER-ITEM", nama_barang="Other Item",
            satuan=self.item.satuan, kategori=self.item.kategori, requires_expiry_date=False)
        first, second = self.row("first"), self.row("second")
        first["expiry_date"] = second["expiry_date"] = date(2027, 1, 1)
        second["item"] = other_item
        self.post(self.opening(rows=[first, second]))
        layer = PuskesmasInventoryLayer.objects.get(posting__facility=self.facility, item=self.item)
        form = ExpiryLineForm({"item": other_item.pk, "layer": layer.pk, "quantity": 1}, facility=self.facility)
        self.assertFalse(form.is_valid())
        self.assertIn("layer", form.errors)
        valid = ExpiryLineForm({"item": self.item.pk, "layer": layer.pk, "quantity": 1}, facility=self.facility)
        self.assertTrue(valid.is_valid(), valid.errors)
        self.assertIn(f'data-item-id="{self.item.pk}"', str(valid["layer"]))
        self.assertIsInstance(valid.fields["layer"].widget, ItemBatchSelect)

    def test_monitoring_search_sort_and_invalid_scope_filters_do_not_write(self):
        from apps.items.models import Category
        self.client.force_login(self.operator)
        before = PuskesmasInventoryMovement.objects.count()
        url = reverse("puskesmas:expiry_list")
        response = self.client.get(url, {"days": 365, "q": self.item.kode_barang, "sort": "price", "dir": "desc"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["layer"].unit_price for row in response.context["rows"]], [Decimal("200"), Decimal("100.1234567890")])
        self.assertContains(response, "Status ED")
        foreign_category = Category.objects.create(code="FOREIGN-CAT", name="Foreign category")
        invalid = self.client.get(url, {"days": 365, "category": foreign_category.pk})
        self.assertTrue(invalid.context["form"].errors)
        self.assertEqual(invalid.context["rows"].paginator.count, 0)
        invalid_sort = self.client.get(url, {"days": 365, "sort": "posting__facility_id"})
        self.assertTrue(invalid_sort.context["form"].errors)
        self.assertEqual(PuskesmasInventoryMovement.objects.count(), before)

    def test_correction_initial_values_keep_item_and_batch_without_rewriting(self):
        revision = self.withdraw()
        self.client.force_login(self.operator)
        before = PuskesmasInventoryMovement.objects.count()
        response = self.client.get(reverse("puskesmas:expiry_edit", args=[revision.expiry_id]))
        line = response.context["lines"].forms[0]
        self.assertEqual(line.initial["item"], self.item.pk)
        self.assertEqual(line.initial["layer"], self.layers[0].pk)
        self.assertContains(response, "js-item-select")
        self.assertContains(response, "data-item-batch-row")
        self.assertEqual(PuskesmasInventoryMovement.objects.count(), before)

    def test_shared_critical_filter_includes_ed_day_without_stock_changes(self):
        from datetime import timedelta
        from django.utils import timezone
        today = timezone.localdate()
        self.facility = self.other
        self.operator.facility = self.other
        self.operator.save(update_fields=["facility"])
        rows = []
        for days in (-1, 0, 30, 31):
            row = self.row(str(days), "100", "1")
            row["expiry_date"] = today + timedelta(days=days)
            rows.append(row)
        self.post(self.opening(rows=rows))
        self.client.force_login(self.operator)
        before = PuskesmasInventoryMovement.objects.count()
        url = reverse("puskesmas:expiry_list")
        response = self.client.get(url, {"days": 90, "level": "critical"})
        self.assertEqual([row["days_to_expiry"] for row in response.context["rows"]], [0, 30])
        self.assertContains(response, "Hari ED")
        expired = self.client.get(url, {"days": 90, "level": "expired"})
        self.assertEqual([row["days_to_expiry"] for row in expired.context["rows"]], [-1])
        self.assertEqual(PuskesmasInventoryMovement.objects.count(), before)


class ExpiryConcurrencyTests(ExpiryFixture, TransactionTestCase):
    def test_expiry_and_consumption_serialize_with_correct_final_allocations(self):
        def run(kind):
            close_old_connections()
            try:
                if kind == "expiry":
                    return self.withdraw().pk
                return finalize_consumption(user=self.admin, consumption_id=self.consumption.pk,
                    digest=snapshot_digest(self.consumption, snapshot(self.consumption))).pk
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(run, ["expiry", "consumption"]))
        self.assertEqual(self.balances(), [0, 5])
        row = period_rows([self.facility.pk], 2026, 1)[0][0]
        self.assertEqual((row["expiry_quantity"], row["consumption_quantity"], row["closing_quantity"]), (3, 12, 5))

    def test_duplicate_request_posts_once(self):
        token = uuid4()
        def run():
            close_old_connections()
            try:
                return self.withdraw(request_key=token).pk
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(lambda _: run(), range(2)))
        self.assertEqual(result[0], result[1])
        self.assertEqual(PuskesmasExpiryRevision.objects.count(), 1)
        self.assertEqual(self.balances(), [7, 10])
