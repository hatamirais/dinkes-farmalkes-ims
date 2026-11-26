from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from apps.core.tests.mixins import SecureClientDefaultsMixin
from apps.lplpo.models import LPLPO, get_next_required_lplpo_period
from apps.lplpo.xlsx_io import apply_lplpo_workbook_import, export_lplpo_workbook
from apps.users.models import User

from .consumption_inventory import finalize_consumption, latest_revision, snapshot, snapshot_digest
from .inventory import post_receipt
from .inventory_models import PuskesmasInventoryLayer, PuskesmasInventoryPosting
from .inventory_reporting import period_rows
from .models import PuskesmasConsumption, PuskesmasConsumptionEntry, PuskesmasSubunit
from .opname import close_count, compare_revision, current_revision, revision_roster, save_location, start_count
from .opname_actions import decide_action, request_action
from .opname_lplpo import activate
from .opname_models import OpnameActivation, OpnameAuthority, OpnameRevision
from .test_consumption_inventory import ConsumptionFixture


class OpnameFixture(ConsumptionFixture):
    def setUp(self):
        super().setUp()
        self.pustu = PuskesmasSubunit.objects.create(facility=self.facility, name="Pustu", subunit_type="PUSTU")
        OpnameAuthority.objects.create(facility=self.facility, user=self.verifier,
            review_count=True, approve_adjustment=True, correct_receipt=True, reopen_count=True)
        self.engine()

    def observation(self, quantity, **values):
        return {"item": self.item.pk, "observed": quantity, **values}

    def count(self, warehouse, *, month=1, pustu=None):
        count = start_count(user=self.operator, year=2026, month=month)
        entries = {"warehouse": warehouse}
        if pustu is not None:
            entries[str(self.pustu.pk)] = pustu
        for location in count.roster:
            self.location(count, location["key"], entries.get(location["key"], []))
        return count

    def location(self, count, key, lines, evidence="Buku mutasi: tidak ada mutasi tambahan"):
        return save_location(user=self.operator, count_id=count.pk, expected_revision=current_revision(count).pk,
            location_key=key, counted_at=timezone.make_aware(datetime(2026, count.cutoff.month, 28, 12)),
            evidence=evidence, lines=lines, confirmed=True)

    def close(self, count, actor=None):
        revision = current_revision(count)
        return close_count(user=actor or self.operator, count_id=count.pk, expected_revision=revision.pk,
            expected_journal=compare_revision(count, revision)["digest"])

    def request(self, count, kind, **kwargs):
        return request_action(user=self.operator, count_id=count.pk, expected_revision=current_revision(count).pk,
            key=uuid4(), kind=kind, reason="Berita acara diperiksa", reference="Rujukan pengujian", **kwargs)

    def approve(self, count, action):
        return decide_action(user=self.verifier, count_id=count.pk, action_id=action.pk, approve=True)


@override_settings(RATELIMIT_ENABLE=False)
class OpnameTests(OpnameFixture, SecureClientDefaultsMixin, TestCase):
    def test_count_and_lplpo_creation_require_current_reconciliation(self):
        activate(user=self.admin, facility_id=self.facility.pk, year=2026, month=1)
        self.client.force_login(self.operator)
        create_url = reverse("lplpo:lplpo_create")
        form = {"tahun": 2026, "bulan": 1}
        response = self.client.post(create_url, form)
        self.assertContains(response, "Buat dan rekonsiliasi Stock Opname")
        self.assertFalse(LPLPO.objects.exists())
        count = self.count([self.observation(5)], pustu=[self.observation(3)])
        closed = self.close(count)
        self.assertEqual(closed.state, OpnameRevision.State.RECONCILED)
        self.assertEqual(closed.comparison["warehouse"][str(self.item.pk)], 5)
        self.assertEqual(self.client.post(create_url, form).status_code, 302)
        lplpo = LPLPO.objects.get()
        self.assertTrue(lplpo.inventory_backed)
        self.assertEqual(lplpo.opname_links.get().revision, closed)
        self.assertEqual(lplpo.items.get().stock_gudang_puskesmas, 5)
        book = load_workbook(BytesIO(export_lplpo_workbook(lplpo).content))
        book.active["M12"] = 9
        workbook = BytesIO()
        book.save(workbook)
        workbook.seek(0)
        with self.assertRaisesMessage(ValidationError, "berasal dari Stock Opname"):
            apply_lplpo_workbook_import(uploaded_file=workbook, lplpo_obj=lplpo)
        self.assertEqual(self.client.post(reverse("lplpo:lplpo_submit", args=[lplpo.pk])).status_code, 302)
        lplpo.refresh_from_db()
        self.assertEqual(lplpo.status, LPLPO.Status.SUBMITTED)
        reopen = self.request(count, "REOPEN", expected_change="Hitung ulang gudang")
        with self.assertRaisesMessage(ValidationError, "sudah diajukan"):
            self.approve(count, reopen)

    def test_adjustment_and_reversal_preserve_print_and_exact_value(self):
        count = self.count([self.observation(7)])
        with self.assertRaises(PermissionDenied):
            self.close(count)
        frozen = self.close(count, self.verifier)
        self.assertEqual(frozen.state, OpnameRevision.State.CLOSED_OPEN)
        with self.assertRaises(PermissionDenied):
            self.close(count, self.admin)
        layer = PuskesmasInventoryLayer.objects.order_by("pk").last()
        action = self.request(count, "ADJUST", case_key=frozen.comparison["rows"][0]["key"],
                              layer_id=layer.pk, quantity=1, incident_date=date(2026, 1, 14))
        with self.assertRaises(PermissionDenied):
            decide_action(user=self.operator, count_id=count.pk, action_id=action.pk, approve=True)
        decision = self.approve(count, action)
        self.assertEqual(decision.posting.effective_date, date(2026, 1, 31))
        self.assertEqual(decision.posting.movements.get().unit_price, Decimal(200))
        self.assertEqual(self.approve(count, action).pk, decision.pk)
        after = self.close(count)
        self.assertEqual(after.state, OpnameRevision.State.RECONCILED)
        rows, _ = period_rows([self.facility.pk], 2026, 1)
        self.assertEqual((rows[0]["consumption_quantity"], rows[0]["adjustment_value"], rows[0]["closing_quantity"]),
                         (12, 200, 7))
        reversal = self.request(count, "REVERSE", reverse_id=action.pk)
        self.assertEqual(self.approve(count, reversal).posting.reversal_of, decision.posting)
        self.client.force_login(self.operator)
        print_url = reverse("puskesmas:opname_print", args=[count.pk, frozen.number])
        self.assertContains(self.client.get(print_url), "Selisih terbuka")
        self.assertContains(self.client.get(reverse("puskesmas:opname_detail", args=[count.pk])), "Jurnal berubah")
        outsider = User.objects.create_user(username="outside-opname", role="PUSKESMAS", facility=self.other)
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(print_url).status_code, 404)

    def test_receipt_reduction_replays_usage_and_retains_original_receipt(self):
        receipt, line, source = self.receipt()
        source.issued_expiry_date = line.expiry_date = date(2026, 9, 30)
        source.save(update_fields=["issued_expiry_date"])
        line.save(update_fields=["expiry_date"])
        post_receipt(receipt=receipt, user=self.operator)
        february = PuskesmasConsumption.objects.create(facility=self.facility, tahun=2026, bulan=2, created_by=self.operator)
        PuskesmasConsumptionEntry.objects.create(consumption=february, item=self.item, subunit=self.subunit, quantity=4)
        before = finalize_consumption(user=self.operator, consumption_id=february.pk,
                                     digest=snapshot_digest(february, snapshot(february)))
        count = self.count([self.observation(6)], month=2)
        closed = self.close(count, self.verifier)
        case = next(row for row in closed.comparison["rows"] if row["open"])
        layer = PuskesmasInventoryLayer.objects.get(receipt_line=line)
        action = self.request(count, "RECEIPT", case_key=case["key"], layer_id=layer.pk, quantity=1)
        decision = self.approve(count, action)
        after = latest_revision(february)
        self.assertEqual(after.snapshot, before.snapshot)
        self.assertEqual(before.allocations.get(layer=layer).quantity, 3)
        self.assertEqual(after.allocations.get(layer=layer).quantity, 2)
        self.assertEqual(after.receipt_correction_id, action.pk)
        self.assertEqual(before.posting.reversal.effective_date, date(2026, 2, 28))
        self.assertEqual(decision.posting.effective_date, receipt.received_date)
        line.refresh_from_db()
        self.assertEqual(line.quantity, 3)
        rows, _ = period_rows([self.facility.pk], 2026, 2)
        self.assertEqual((rows[0]["receipts_quantity"], rows[0]["consumption_quantity"], rows[0]["adjustment_quantity"]),
                         (2, 4, 0))
        self.assertEqual(self.close(count).state, OpnameRevision.State.RECONCILED)

    def test_reopen_can_expand_roster_without_changing_old_print(self):
        count = self.count([self.observation(8)])
        old = self.close(count)
        missed = PuskesmasSubunit.objects.create(facility=self.facility, name="Poli Nonaktif",
            subunit_type="TREATMENT_ROOM", is_active=False)
        request = self.request(count, "REOPEN", expected_change="Hitung stok Poli Nonaktif",
                               add_location_id=missed.pk)
        self.approve(count, request)
        self.assertNotIn(str(missed.pk), {row["key"] for row in revision_roster(count, old)})
        self.assertIn(str(missed.pk), {row["key"] for row in revision_roster(count, current_revision(count))})
        with self.assertRaisesMessage(ValidationError, "Poli Nonaktif"):
            self.close(count)
        self.location(count, str(missed.pk), [])
        self.assertEqual(self.close(count).state, OpnameRevision.State.RECONCILED)

    def test_damage_still_held_keeps_evidence_after_adjustment(self):
        layer = PuskesmasInventoryLayer.objects.order_by("pk").last()
        damage = self.observation(1, layer=layer.pk, condition="DAMAGED")
        count = self.count([self.observation(7), damage])
        comparison = current_revision(count).comparison
        action = self.request(count, "ADJUST", case_key=comparison["rows"][0]["key"],
                              layer_id=layer.pk, quantity=1)
        posting = self.approve(count, action).posting
        self.location(count, "warehouse", [self.observation(7), {**damage, "excluded_posting": posting.pk}])
        closed = self.close(count)
        self.assertEqual(closed.comparison["warehouse"][str(self.item.pk)], 7)
        self.assertEqual(closed.observations["warehouse"]["lines"][-1]["cutoff_quantity"], 1)

    def test_consumption_correction_rolls_back_when_approved_reduction_no_longer_fits(self):
        count = self.count([self.observation(7)])
        closed = self.close(count, self.verifier)
        layer = PuskesmasInventoryLayer.objects.order_by("pk").last()
        action = self.request(count, "ADJUST", case_key=closed.comparison["rows"][0]["key"],
                              layer_id=layer.pk, quantity=1)
        posting = self.approve(count, action).posting
        before = latest_revision(self.consumption)
        correction = snapshot(self.consumption)
        correction["entries"][0]["quantity"] = 20
        with self.assertRaisesMessage(ValidationError, "tidak menyisakan saldo"):
            finalize_consumption(user=self.operator, consumption_id=self.consumption.pk,
                                 digest=before.digest, data=correction, reason="Periksa pemakaian")
        self.assertEqual(latest_revision(self.consumption), before)
        self.assertEqual(layer.balance.quantity, 7)
        self.assertEqual(posting.movements.get().quantity_delta, -1)

    def test_provisional_evidence_and_stale_confirmation(self):
        count = start_count(user=self.operator, year=2026, month=1)
        original_revision = current_revision(count)
        with self.assertRaisesMessage(ValidationError, "bukti penyesuaian mutasi"):
            self.location(count, "warehouse", [self.observation(8)], evidence="")
        self.location(count, "warehouse", [self.observation(4, factor=Decimal(2),
            observed_unit="Kotak", conversion="Kemasan 2 tablet per kotak")])
        self.assertEqual(current_revision(count).comparison["warehouse"][str(self.item.pk)], 8)
        with self.assertRaisesMessage(ValidationError, "Lokasi belum dikonfirmasi"):
            self.close(count)
        with self.assertRaisesMessage(ValidationError, "Hitungan telah berubah"):
            close_count(user=self.operator, count_id=count.pk, expected_revision=original_revision.pk,
                        expected_journal=original_revision.comparison["digest"])
        self.client.force_login(self.operator)
        self.assertContains(self.client.get(reverse("puskesmas:opname_location", args=[count.pk, "warehouse"])), "Kotak")
        self.assertContains(self.client.get(reverse("puskesmas:opname_observation", args=[count.pk, "warehouse"])), "Jumlah terhitung")

    def test_gated_december_can_be_created_after_year_rollover(self):
        activate(user=self.admin, facility_id=self.facility.pk, year=2026, month=1)
        for month in range(1, 12):
            LPLPO.objects.create(facility=self.facility, bulan=month, tahun=2026, created_by=self.operator)
        self.assertEqual(get_next_required_lplpo_period(self.facility, server_date=date(2027, 1, 1)), (2026, 12))
        self.assertEqual(get_next_required_lplpo_period(self.other, server_date=date(2027, 1, 1)), (2027, 1))
        self.assertEqual(OpnameActivation.objects.count(), 1)


class OpnameConcurrencyTests(OpnameFixture, TransactionTestCase):
    def test_repeat_approval_writes_one_movement(self):
        count = self.count([self.observation(7)])
        revision = self.close(count, self.verifier)
        action = self.request(count, "ADJUST", case_key=revision.comparison["rows"][0]["key"],
                              layer_id=PuskesmasInventoryLayer.objects.order_by("pk").last().pk, quantity=1)

        def approve():
            close_old_connections()
            try:
                return self.approve(count, action).pk
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: approve(), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(PuskesmasInventoryPosting.objects.filter(opname_action=action).count(), 1)
