"""Real ORM/client checks for inventory integrity; no mock stock or posting services."""
import csv
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connection
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.tests.mixins import SecureClientDefaultsMixin
from apps.core.context_processors import nav_notifications
from apps.distribution.models import Distribution, DistributionItem
from apps.items.models import Category, Facility, Item, Unit
from apps.users.models import ModuleAccess, User
from .inventory import HEADERS, LEGACY_WORKSHEET_HEADERS, WORKSHEET_HEADERS, parse_csv, prepare_opening, submit_opening, cancel_opening, review_opening, post_receipt
from .models import (
    PuskesmasOpeningVerification, PuskesmasInventoryAccount, PuskesmasInventoryPosting,
    PuskesmasInventoryLayer, PuskesmasInventoryMovement, PuskesmasInventoryBalance,
    PuskesmasReceiptConfirmation, PuskesmasReceiptConfirmationItem,
)


class InventoryFixture:
    def setUp(self):
        super().setUp()
        self.facility = Facility.objects.create(code="INV-PKM", name="Inventory Puskesmas", facility_type="PUSKESMAS")
        self.other = Facility.objects.create(code="INV-OTHER", name="Other Puskesmas", facility_type="PUSKESMAS")
        unit = Unit.objects.create(code="INV-TAB", name="Tablet")
        category = Category.objects.create(code="INV-OBT", name="Obat")
        self.item = Item.objects.create(kode_barang="INV-ITEM", nama_barang="Inventory Item", satuan=unit,
                                        kategori=category, requires_expiry_date=False)
        self.operator = User.objects.create_user(username="inventory-operator", role="PUSKESMAS", facility=self.facility)
        self.verifier = User.objects.create_user(username="inventory-verifier", role="GUDANG")
        ModuleAccess.objects.update_or_create(user=self.verifier, module="lplpo", defaults={"scope": ModuleAccess.Scope.OPERATE})
        self.admin = User.objects.create_superuser(username="inventory-admin")

    def row(self, key="a", price="1000.1234567890", quantity="10"):
        return dict(line_key=key, item=self.item, quantity=Decimal(quantity),
                    unit_price=Decimal(price) if price is not None else None, batch_lot="",
                    expiry_date=None, sumber_dana=None, source_document_number="",
                    provenance_note="Jumlah dan harga diverifikasi; provenance historis tidak diketahui.")

    def opening(self, rows=None, submit=True):
        opening = prepare_opening(user=self.operator, facility_id=self.facility.pk, year=2026,
                                  reference="Bukti Januari", notes="", rows=rows if rows is not None else [self.row()])
        if submit:
            opening = submit_opening(user=self.operator, opening_id=opening.pk, digest=opening.digest)
        return opening

    def post(self, opening=None):
        opening = opening or self.opening()
        return review_opening(user=self.verifier, opening_id=opening.pk, digest=opening.digest)

    def receipt(self, price=Decimal("1250.9876543210"), received_date=date(2026, 2, 1), status="CONFIRMED"):
        distribution = Distribution.objects.create(facility=self.facility, status="DISTRIBUTED",
            distribution_type="LPLPO", request_date=received_date, distributed_date=received_date, created_by=self.admin)
        source = DistributionItem.objects.create(distribution=distribution, item=self.item,
            quantity_requested=Decimal("3"), quantity_approved=Decimal("3"), issued_unit_price=price,
            issued_batch_lot="Batch-R")
        receipt = PuskesmasReceiptConfirmation.objects.create(facility=self.facility, distribution=distribution,
            status=status, received_date=received_date, created_by=self.operator)
        line = PuskesmasReceiptConfirmationItem.objects.create(sbbk=receipt, distribution_item=source,
            item=self.item, quantity=Decimal("3"), unit_price=price or Decimal("0"), batch_lot="Batch-R")
        return receipt, line, source


@override_settings(RATELIMIT_ENABLE=False)
class InventoryTests(InventoryFixture, SecureClientDefaultsMixin, TestCase):
    def opening_notifications(self, user):
        request = RequestFactory().get("/")
        request.user = user
        return [entry for entry in nav_notifications(request)["nav_notification_items"]
                if entry["label"] in {"Saldo Awal Puskesmas", "Saldo Awal Menunggu Verifikasi"}]

    def test_opening_notifications_follow_submission_review_and_active_facility(self):
        opening = self.opening(submit=False)
        self.assertEqual(self.opening_notifications(self.verifier), [])
        submit_opening(user=self.operator, opening_id=opening.pk, digest=opening.digest)
        expected = [{"label": "Saldo Awal Puskesmas", "count": 1,
                     "url": reverse("puskesmas:opening_list") + "?status=SUBMITTED",
                     "icon": "bi-journal-check"}]
        for user in [self.verifier, self.admin]:
            with self.subTest(user=user.username):
                self.assertEqual(self.opening_notifications(user), expected)
                self.client.force_login(user)
                response = self.client.get(expected[0]["url"])
                self.assertEqual(list(response.context["openings"]), [opening])
                self.assertContains(response, 'data-label="Saldo Awal Puskesmas"')
                self.assertContains(self.client.get(reverse("puskesmas:opening_detail", args=[opening.pk])),
                                    "Verifikasi dan Posting")
        self.facility.is_active = False
        self.facility.save(update_fields=["is_active"])
        self.assertEqual(self.opening_notifications(self.verifier), [])
        self.facility.is_active = True
        self.facility.save(update_fields=["is_active"])
        review_opening(user=self.verifier, opening_id=opening.pk, digest=opening.digest,
                       reject_reason="Periksa ulang jumlah")
        self.assertEqual(self.opening_notifications(self.verifier), [])
        posted = self.opening()
        self.assertEqual(self.opening_notifications(self.verifier), expected)
        self.post(posted)
        self.assertEqual(self.opening_notifications(self.verifier), [])

    def test_opening_notifications_keep_role_scope_and_independent_review_boundaries(self):
        self.opening()
        kepala = User.objects.create_user(username="inventory-kepala", role="KEPALA")
        self.assertEqual(self.opening_notifications(kepala)[0]["count"], 1)
        self.assertEqual(self.opening_notifications(self.operator), [])
        self.client.force_login(kepala)
        self.assertEqual(self.client.get(reverse("puskesmas:opening_list")).status_code, 200)
        ModuleAccess.objects.filter(user=self.verifier, module="lplpo").update(scope=ModuleAccess.Scope.VIEW)
        self.assertEqual(self.opening_notifications(self.verifier), [])
        self.client.force_login(self.verifier)
        self.assertEqual(self.client.get(reverse("puskesmas:opening_list")).status_code, 403)
        own = prepare_opening(user=self.admin, facility_id=self.other.pk, year=2026,
                              reference="Admin prepares", notes="", rows=[self.row("own")])
        submit_opening(user=self.admin, opening_id=own.pk, digest=own.digest)
        self.admin.role = User.Role.KEPALA
        self.admin.save(update_fields=["role"])
        self.assertEqual(self.opening_notifications(self.admin)[0]["count"], 1)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("puskesmas:opening_list") + "?status=SUBMITTED")
        self.assertNotIn(own, response.context["openings"])
        self.admin.is_active = False
        self.assertEqual(self.opening_notifications(self.admin), [])

    def test_kepala_oversight_reads_only_eligible_statuses_across_active_facilities(self):
        draft = self.opening(submit=False)
        cancelled = self.opening(submit=False)
        cancel_opening(user=self.operator, opening_id=cancelled.pk, digest=cancelled.digest)
        rejected = self.opening()
        review_opening(user=self.verifier, opening_id=rejected.pk, digest=rejected.digest,
                       reject_reason="Periksa bukti")
        submitted = self.opening()
        posted = self.opening()
        self.post(posted)
        other = prepare_opening(user=self.admin, facility_id=self.other.pk, year=2026,
                                reference="Other facility", notes="", rows=[self.row()])
        submit_opening(user=self.admin, opening_id=other.pk, digest=other.digest)
        kepala = User.objects.create_user(username="oversight-kepala", role="KEPALA")
        self.client.force_login(kepala)
        url = reverse("puskesmas:opening_list")
        for scope in [ModuleAccess.Scope.VIEW, ModuleAccess.Scope.OPERATE,
                      ModuleAccess.Scope.APPROVE, ModuleAccess.Scope.MANAGE]:
            with self.subTest(scope=scope):
                ModuleAccess.objects.update_or_create(user=kepala, module="lplpo", defaults={"scope": scope})
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual({obj.pk for obj in response.context["openings"]},
                                 {submitted.pk, rejected.pk, posted.pk, other.pk})
                self.assertContains(response, 'data-label="Saldo Awal Puskesmas"')
                self.assertNotContains(response, "Siapkan Saldo Awal Pertama")
                for obj in [submitted, rejected, posted, other]:
                    detail = self.client.get(reverse("puskesmas:opening_detail", args=[obj.pk]))
                    self.assertEqual(detail.status_code, 200)
                    for action in ["Verifikasi dan Posting", "Ajukan untuk Verifikasi", "Batalkan Pratinjau",
                                   'name="action" value="reject"']:
                        self.assertNotContains(detail, action)
                self.assertEqual(self.opening_notifications(kepala)[0]["count"], 2)
        response = self.client.get(url, {"status": "SUBMITTED"})
        self.assertEqual({obj.pk for obj in response.context["openings"]}, {submitted.pk, other.pk})
        for obj in [draft, cancelled]:
            self.assertEqual(self.client.get(reverse("puskesmas:opening_detail", args=[obj.pk])).status_code, 404)
        self.other.is_active = False
        self.other.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(reverse("puskesmas:opening_detail", args=[other.pk])).status_code, 404)
        self.assertNotIn(other, self.client.get(url).context["openings"])
        ModuleAccess.objects.filter(user=kepala, module="lplpo").update(scope=ModuleAccess.Scope.NONE)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, 'data-label="Saldo Awal Puskesmas"', status_code=403)
        self.assertEqual(self.client.get(reverse("puskesmas:opening_detail", args=[submitted.pk])).status_code, 403)

    def test_kepala_oversight_denies_mutations_even_with_manage_scope(self):
        submitted = self.opening()
        kepala = User.objects.create_user(username="oversight-no-post", role="KEPALA")
        ModuleAccess.objects.update_or_create(user=kepala, module="lplpo", defaults={"scope": ModuleAccess.Scope.MANAGE})
        self.client.force_login(kepala)
        detail_url = reverse("puskesmas:opening_detail", args=[submitted.pk])
        for action in ["post", "reject", "submit", "cancel"]:
            with self.subTest(action=action):
                response = self.client.post(detail_url, {"action": action, "digest": submitted.digest,
                                                        "verified": "yes", "reason": "Forged action"})
                self.assertEqual(response.status_code, 403)
        for route in ["puskesmas:opening_create", "puskesmas:opening_template"]:
            self.assertEqual(self.client.get(reverse(route)).status_code, 403)
        self.assertEqual(self.client.post(reverse("puskesmas:opening_create"), {}).status_code, 403)
        with self.assertRaises(PermissionDenied):
            review_opening(user=kepala, opening_id=submitted.pk, digest=submitted.digest)
        submitted.refresh_from_db()
        self.assertEqual(submitted.status, "SUBMITTED")
        self.assertFalse(PuskesmasInventoryPosting.objects.exists())

    def test_kepala_bell_notice_is_read_only_scoped_and_clears_after_review(self):
        kepala = User.objects.create_user(username="notice-kepala", role="KEPALA")
        ModuleAccess.objects.update_or_create(user=kepala, module="lplpo", defaults={"scope": ModuleAccess.Scope.VIEW})
        opening = self.opening(submit=False)
        self.assertEqual(self.opening_notifications(kepala), [])
        submit_opening(user=self.operator, opening_id=opening.pk, digest=opening.digest)
        notice = self.opening_notifications(kepala)
        self.assertEqual(notice, [{"label": "Saldo Awal Menunggu Verifikasi", "count": 1,
                                  "url": reverse("puskesmas:opening_list") + "?status=SUBMITTED",
                                  "icon": "bi-journal-check"}])
        self.client.force_login(kepala)
        response = self.client.get(notice[0]["url"])
        self.assertEqual(list(response.context["openings"]), [opening])
        self.assertContains(response, "Saldo Awal Menunggu Verifikasi")
        self.assertNotContains(self.client.get(reverse("puskesmas:opening_detail", args=[opening.pk])),
                               "Verifikasi dan Posting")
        self.facility.is_active = False
        self.facility.save(update_fields=["is_active"])
        self.assertEqual(self.opening_notifications(kepala), [])
        self.facility.is_active = True
        self.facility.save(update_fields=["is_active"])
        ModuleAccess.objects.filter(user=kepala, module="lplpo").update(scope=ModuleAccess.Scope.NONE)
        self.assertEqual(self.opening_notifications(kepala), [])
        ModuleAccess.objects.filter(user=kepala, module="lplpo").update(scope=ModuleAccess.Scope.VIEW)
        kepala.is_active = False
        self.assertEqual(self.opening_notifications(kepala), [])
        kepala.is_active = True
        review_opening(user=self.verifier, opening_id=opening.pk, digest=opening.digest,
                       reject_reason="Periksa bukti")
        self.assertEqual(self.opening_notifications(kepala), [])
        posted = self.opening()
        self.assertEqual(self.opening_notifications(kepala)[0]["count"], 1)
        self.post(posted)
        self.assertEqual(self.opening_notifications(kepala), [])

    def test_creator_cancels_expired_preview_preserving_rows_and_idempotent_history(self):
        opening = self.opening(submit=False)
        line_ids = list(opening.lines.values_list("pk", flat=True))
        self.client.force_login(self.operator)
        url = reverse("puskesmas:opening_detail", args=[opening.pk])
        self.assertContains(self.client.get(url), "Batalkan Pratinjau")
        response = self.client.post(url, {"action": "cancel", "digest": "stale"})
        self.assertRedirects(response, url)
        opening.refresh_from_db()
        self.assertEqual(opening.status, "DRAFT")
        opening.expires_at = timezone.now() - timedelta(hours=1)
        opening.save(update_fields=["expires_at"])
        response = self.client.post(url, {"action": "cancel", "digest": opening.digest})
        self.assertRedirects(response, reverse("puskesmas:opening_list"))
        opening.refresh_from_db()
        self.assertEqual(opening.status, "CANCELLED")
        self.assertEqual(opening.cancelled_by, self.operator)
        self.assertIsNotNone(opening.cancelled_at)
        cancelled_at = opening.cancelled_at
        self.assertEqual(list(opening.lines.values_list("pk", flat=True)), line_ids)
        self.assertFalse(PuskesmasInventoryPosting.objects.exists())
        self.assertFalse(PuskesmasInventoryAccount.objects.exists())
        self.assertFalse(PuskesmasInventoryMovement.objects.exists())
        self.assertNotContains(self.client.get(url), "Batalkan Pratinjau")
        self.assertNotContains(self.client.get(url), "Ajukan untuk Verifikasi")
        self.client.post(url, {"action": "cancel", "digest": opening.digest})
        opening.refresh_from_db()
        self.assertEqual(opening.cancelled_at, cancelled_at)
        with self.assertRaises(ValidationError):
            submit_opening(user=self.operator, opening_id=opening.pk, digest=opening.digest)
        with self.assertRaises(ValidationError):
            opening.delete()

    def test_cancel_rechecks_creator_facility_authority_and_live_workflow_status(self):
        opening = self.opening(submit=False)
        same_facility = User.objects.create_user(username="inventory-colleague", role="PUSKESMAS", facility=self.facility)
        other_facility = User.objects.create_user(username="inventory-other", role="PUSKESMAS", facility=self.other)
        for actor in [same_facility, other_facility, self.verifier, self.admin]:
            with self.subTest(actor=actor.username), self.assertRaises(PermissionDenied):
                cancel_opening(user=actor, opening_id=opening.pk, digest=opening.digest)
        self.client.force_login(same_facility)
        response = self.client.post(reverse("puskesmas:opening_detail", args=[opening.pk]),
                                    {"action": "cancel", "digest": opening.digest})
        self.assertEqual(response.status_code, 404)
        self.operator.is_active = False
        self.operator.save(update_fields=["is_active"])
        with self.assertRaises(PermissionDenied):
            cancel_opening(user=self.operator, opening_id=opening.pk, digest=opening.digest)
        self.operator.is_active = True
        self.operator.save(update_fields=["is_active"])
        submit_opening(user=self.operator, opening_id=opening.pk, digest=opening.digest)
        with self.assertRaises(ValidationError):
            cancel_opening(user=self.operator, opening_id=opening.pk, digest=opening.digest)
        self.post(opening)
        with self.assertRaises(ValidationError):
            cancel_opening(user=self.operator, opening_id=opening.pk, digest=opening.digest)

    def test_detail_formats_year_and_money_and_explains_unpriced_subtotal(self):
        opening = self.opening(rows=[self.row(key="priced", price="10.1234567890", quantity="2"),
                                    self.row(key="zero", price="0"), self.row(key="unknown", price=None)], submit=False)
        self.client.force_login(self.operator)
        with override_settings(USE_THOUSAND_SEPARATOR=True):
            response = self.client.get(reverse("puskesmas:opening_detail", args=[opening.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1 Januari 2026")
        self.assertNotContains(response, "1 Januari 2.026")
        self.assertNotContains(response, "Fondasi belum mencakup")
        self.assertContains(response, "Subtotal saldo awal yang dapat dihitung: Rp 20,25")
        self.assertContains(response, "1 baris belum memiliki harga dan belum masuk subtotal")
        self.assertContains(response, "Belum dapat dihitung")
        self.assertEqual(response.context["total"], Decimal("20.2469135780"))
        self.assertEqual(response.context["unpriced_count"], 1)
        self.assertEqual(opening.lines.get(line_key="priced").unit_price, Decimal("10.1234567890"))

    def test_distinct_layers_exact_values_and_idempotent_post(self):
        opening = self.opening([self.row(), self.row("b", "2000.9876543210")])
        self.assertFalse(PuskesmasInventoryAccount.objects.exists())
        self.post(opening)
        self.post(opening)
        self.assertEqual(PuskesmasInventoryLayer.objects.count(), 2)
        self.assertEqual(PuskesmasInventoryMovement.objects.count(), 2)
        self.assertEqual(list(PuskesmasInventoryLayer.objects.order_by("pk").values_list("unit_price", flat=True)),
                         [Decimal("1000.1234567890"), Decimal("2000.9876543210")])
        for layer in PuskesmasInventoryLayer.objects.all():
            self.assertEqual(layer.balance.quantity, sum(m.quantity_delta for m in layer.movements.all()))
        self.assertEqual(PuskesmasInventoryAccount.objects.get().readiness, "FOUNDATION_INCOMPLETE")
        with self.assertRaises(ValidationError):
            self.opening()

    def test_hold_missing_price_or_required_expiry_rolls_back_entire_post(self):
        opening = self.opening([self.row(), self.row("missing", None)])
        with self.assertRaises(ValidationError):
            self.post(opening)
        self.assertFalse(PuskesmasInventoryMovement.objects.exists())
        self.assertFalse(PuskesmasInventoryAccount.objects.exists())
        self.item.requires_expiry_date = True
        self.item.save()
        with self.assertRaises(ValidationError):
            self.post(self.opening())

    def test_empty_stock_is_rejected_and_rejection_does_not_fabricate_layers(self):
        rejected = self.opening()
        review_opening(user=self.verifier, opening_id=rejected.pk, digest=rejected.digest,
                       reject_reason="Bukti perlu dilengkapi")
        rejected.refresh_from_db()
        self.assertEqual(rejected.status, "REJECTED")
        self.assertFalse(PuskesmasInventoryAccount.objects.exists())
        for zero_stock in [False, True]:
            with self.assertRaises(ValidationError):
                prepare_opening(user=self.operator, facility_id=self.facility.pk, year=2026,
                    reference="Kosong", notes="", rows=[], zero_stock=zero_stock)
        self.assertFalse(PuskesmasInventoryAccount.objects.exists())
        self.assertFalse(PuskesmasInventoryLayer.objects.exists())

    def test_verifier_role_scope_separation_and_scope_revocation(self):
        opening = self.opening()
        with self.assertRaises(PermissionDenied):
            review_opening(user=self.operator, opening_id=opening.pk, digest=opening.digest)
        own = prepare_opening(user=self.admin, facility_id=self.other.pk, year=2026,
                              reference="Bukti", notes="", rows=[self.row("own")])
        submit_opening(user=self.admin, opening_id=own.pk, digest=own.digest)
        with self.assertRaises(PermissionDenied):
            review_opening(user=self.admin, opening_id=own.pk, digest=own.digest)
        ModuleAccess.objects.filter(user=self.verifier, module="lplpo").update(scope=ModuleAccess.Scope.VIEW)
        with self.assertRaises(PermissionDenied):
            self.post(opening)

    def test_actor_bound_preview_stale_digest_expiry_and_frozen_details(self):
        opening = self.opening(submit=False)
        with self.assertRaises(ValidationError):
            submit_opening(user=self.operator, opening_id=opening.pk, digest="stale")
        opening.expires_at = timezone.now() - timedelta(seconds=1)
        opening.save()
        with self.assertRaises(ValidationError):
            submit_opening(user=self.operator, opening_id=opening.pk, digest=opening.digest)
        submitted = self.opening()
        with self.assertRaises(ValidationError):
            submitted.lines.create(**self.row("new"))
        with self.assertRaises(ValidationError):
            PuskesmasOpeningVerification.objects.filter(pk=submitted.pk).update(year=2025)

    def test_receipt_catchup_idempotent_and_price_never_revalued(self):
        receipt, line, source = self.receipt()
        self.assertIsNone(post_receipt(receipt=receipt, user=self.operator))
        self.post()
        posting = post_receipt(receipt=receipt, user=self.operator)
        self.assertEqual(posting.receipt_id, receipt.pk)
        source.issued_unit_price = Decimal("9999")
        source.save()
        self.assertEqual(post_receipt(receipt=receipt, user=self.operator).pk, posting.pk)
        self.assertEqual(posting.layers.get().unit_price, Decimal("1250.9876543210"))
        for operation in [lambda: receipt.save(), lambda: receipt.delete(), lambda: line.save(),
                          lambda: receipt.items.all().delete(), lambda: receipt.items.update(unit_price=1)]:
            with self.assertRaises(ValidationError):
                operation()
        with self.assertRaises(ValidationError):
            PuskesmasInventoryMovement.objects.all().update(unit_price=1)
        balance = posting.layers.get().balance
        with self.assertRaises(ValidationError):
            PuskesmasInventoryBalance(pk=balance.pk, layer=balance.layer, quantity=999).save()

    def test_missing_receipt_snapshot_aborts_opening_but_verified_zero_is_valid(self):
        receipt, line, source = self.receipt(price=None)
        opening = self.opening()
        with self.assertRaises(ValidationError):
            self.post(opening)
        self.assertFalse(PuskesmasInventoryAccount.objects.exists())
        source.issued_unit_price = Decimal("0")
        source.save()
        self.post(opening)
        self.assertEqual(PuskesmasInventoryPosting.objects.get(receipt=receipt).layers.get().unit_price, Decimal("0"))

    def test_prior_receipts_not_double_counted_and_cannot_cross_cutover(self):
        receipt, line, source = self.receipt(received_date=date(2025, 12, 31))
        self.post()
        self.assertFalse(PuskesmasInventoryPosting.objects.filter(receipt=receipt).exists())
        receipt.received_date = date(2026, 1, 1)
        with self.assertRaises(ValidationError):
            receipt.save()

    def test_live_confirmation_posts_once_and_preserves_posted_row_ids(self):
        self.post()
        receipt, _, source = self.receipt(status="DRAFT")
        payload = {"action": "confirm", "facility": self.facility.pk, "distribution": receipt.distribution_id,
            "received_date": "2026-02-01", "document_number": receipt.document_number,
            "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "1", "items-MIN_NUM_FORMS": "1",
            "items-MAX_NUM_FORMS": "1000", "items-0-distribution_item": source.pk, "items-0-confirmed": "on"}
        self.client.force_login(self.operator)
        edit_url = reverse("puskesmas:receiving_edit", args=[receipt.pk])
        response = self.client.post(edit_url, payload)
        self.assertEqual(response.status_code, 302, (
            response.context["form"].errors if response.context else None,
            response.context["checklist_formset"].errors if response.context else None,
            response.context["checklist_formset"].non_form_errors() if response.context else None,
        ))
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, "CONFIRMED")
        posted_line = receipt.items.get().pk
        self.assertTrue(receipt.inventory_posting_exists())
        self.assertEqual(self.client.post(edit_url, payload).status_code, 302)
        self.assertEqual(receipt.items.get().pk, posted_line)
        self.assertEqual(PuskesmasInventoryMovement.objects.count(), 2)
        detail = self.client.get(reverse("puskesmas:receiving_detail", args=[receipt.pk]))
        self.assertContains(detail, "Koreksi posting belum tersedia")
        self.assertNotContains(detail, 'id="edit-btn"')

    def test_non_superuser_admin_can_save_and_confirm_receipts_without_opening_authority(self):
        # Legacy ADMIN rows remain supported although new ADMIN creation is restricted.
        administrator = User.objects.create_superuser(username="receipt-admin")
        User.objects.filter(pk=administrator.pk).update(is_superuser=False, is_staff=False)
        administrator.refresh_from_db()
        self.assertFalse(administrator.is_superuser)
        self.assertIsNone(administrator.facility_id)
        self.client.force_login(administrator)
        opening = self.opening()
        with self.assertRaises(PermissionDenied):
            review_opening(user=administrator, opening_id=opening.pk, digest=opening.digest)
        for initialized in [False, True]:
            with self.subTest(initialized=initialized):
                if initialized:
                    self.post(opening)
                seed, _, source = self.receipt(status="DRAFT")
                distribution_id = seed.distribution_id
                seed.delete()
                payload = {"action": "draft", "facility": self.facility.pk, "distribution": distribution_id,
                    "document_number": f"ADMIN-RCV-{int(initialized)}",
                    "received_date": "2026-02-01", "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "1",
                    "items-MIN_NUM_FORMS": "1", "items-MAX_NUM_FORMS": "1000",
                    "items-0-distribution_item": source.pk, "items-0-confirmed": "on"}
                response = self.client.post(reverse("puskesmas:receiving_create"), payload)
                self.assertEqual(response.status_code, 302, (
                    response.context["form"].errors if response.context else None,
                    response.context["checklist_formset"].errors if response.context else None,
                    response.context["checklist_formset"].non_form_errors() if response.context else None,
                ))
                receipt = PuskesmasReceiptConfirmation.objects.get(distribution_id=distribution_id)
                self.assertEqual(receipt.status, "DRAFT")
                self.assertFalse(receipt.inventory_posting_exists())
                edit_url = reverse("puskesmas:receiving_edit", args=[receipt.pk])
                payload["notes"] = "Administrator verifies receipt evidence"
                self.assertEqual(self.client.post(edit_url, payload).status_code, 302)
                receipt.refresh_from_db()
                self.assertEqual(receipt.notes, payload["notes"])
                payload["action"] = "confirm"
                self.assertEqual(self.client.post(edit_url, payload).status_code, 302)
                receipt.refresh_from_db()
                self.assertEqual(receipt.status, "CONFIRMED")
                self.assertEqual(receipt.inventory_posting_exists(), initialized)
                if initialized:
                    posting = PuskesmasInventoryPosting.objects.get(receipt=receipt)
                    self.assertEqual(posting.actor_id, administrator.pk)
                    self.assertEqual(posting.layers.get().unit_price, source.issued_unit_price)
                    self.assertEqual(post_receipt(receipt=receipt, user=administrator), posting)
                    self.assertEqual(PuskesmasInventoryPosting.objects.filter(receipt=receipt).count(), 1)
        ModuleAccess.objects.update_or_create(user=administrator, module="puskesmas",
                                             defaults={"scope": ModuleAccess.Scope.NONE})
        self.assertEqual(self.client.post(reverse("puskesmas:receiving_create"), payload).status_code, 403)
        User.objects.filter(pk=administrator.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            post_receipt(receipt=receipt, user=administrator)

    def test_csv_validation_and_precision(self):
        def csv_text(quantity="10", price="8893,31985", expiry=""):
            output = io.StringIO()
            writer = csv.writer(output, delimiter=";")
            writer.writerow(HEADERS)
            writer.writerow(["a", self.item.kode_barang, quantity, price, "", expiry, "", "", "Verified unknown provenance"])
            return output.getvalue()
        self.assertEqual(parse_csv(csv_text())[0]["unit_price"], Decimal("8893.31985"))
        for quantity, price in [("NaN", "1"), ("Infinity", "1"), ("1.1", "1"), ("1", "-1"), ("1", "0.12345678901")]:
            with self.assertRaises(ValidationError):
                parse_csv(csv_text(quantity, price))
        for value in [csv_text() + "\x00", csv_text(expiry="0999-01-01"), "wrong,header\n"]:
            with self.assertRaises(ValidationError):
                parse_csv(value)

    def test_end_to_end_upload_preview_submit_review_and_facility_isolation(self):
        self.client.force_login(self.operator)
        template = self.client.get(reverse("puskesmas:opening_template"))
        self.assertEqual(template.status_code, 200)
        upload = SimpleUploadedFile("opening.csv", (",".join(HEADERS) + "\na,INV-ITEM,10,1000,,,,,Verified unknown provenance\n").encode(), content_type="text/csv")
        response = self.client.post(reverse("puskesmas:opening_create"), {
            "facility": self.other.pk, "year": 2026, "reference": "Bukti", "csv_file": upload})
        self.assertEqual(response.status_code, 302)
        opening = PuskesmasOpeningVerification.objects.get()
        self.assertEqual(opening.facility_id, self.facility.pk)
        detail_url = reverse("puskesmas:opening_detail", args=[opening.pk])
        self.assertContains(self.client.get(detail_url), "Pengurangan stok karena pemakaian belum dihitung")
        self.client.post(detail_url, {"action": "submit", "digest": opening.digest})
        self.client.force_login(self.verifier)
        self.assertContains(self.client.get(detail_url), "Verifikasi dan Posting")
        self.client.post(detail_url, {"action": "post", "digest": opening.digest, "verified": "yes"})
        opening.refresh_from_db()
        self.assertEqual(opening.status, "POSTED")
        other = User.objects.create_user(username="inventory-other", role="PUSKESMAS", facility=self.other)
        self.client.force_login(other)
        self.assertEqual(self.client.get(detail_url).status_code, 404)

    def download_worksheet(self, *, year=2026, **params):
        self.client.force_login(self.operator)
        response = self.client.get(reverse("puskesmas:opening_template"), {"year": year, **params})
        self.assertEqual(response.status_code, 200)
        return list(csv.DictReader(io.StringIO(response.content.decode("utf-8"))))

    def worksheet_text(self, rows, headers=WORKSHEET_HEADERS):
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()

    def warehouse_stock(self, **overrides):
        from apps.items.models import FundingSource, Location
        from apps.stock.models import Stock
        fund, _ = FundingSource.objects.get_or_create(code="INV-FUND", defaults={"name": "Inventory funding"})
        location, _ = Location.objects.get_or_create(code="INV-WH", defaults={"name": "Inventory warehouse"})
        values = dict(item=self.item, location=location, sumber_dana=fund, batch_lot="WH-BATCH",
            expiry_date=date(2027, 4, 30), source_document_number="WH-SOURCE", quantity=0,
            unit_price=Decimal("321.1234567890"))
        values.update(overrides)
        return Stock.objects.create(**values)

    def test_parser_batches_mixed_references_without_queries_per_selected_row(self):
        stock = self.warehouse_stock()
        _, _, source = self.receipt(received_date=date(2025, 12, 31))
        source.stock = stock
        source.issued_sumber_dana = stock.sumber_dana
        source.save()
        small = self.download_worksheet()
        for row in small:
            row["quantity"] = "2"
        manual = dict(small[0], line_key="MANUAL-extra", provenance_note="Verified historical stock; source document unknown.")
        small.append(manual)
        with self.assertNumQueries(4):
            parsed_small = parse_csv(self.worksheet_text(small), facility_id=self.facility.pk, year=2026)
        self.assertEqual(len(parsed_small), 3)
        for number in range(30):
            self.warehouse_stock(batch_lot=f"BATCH-{number}", source_document_number=f"SOURCE-{number}")
        large = self.download_worksheet()
        for row in large:
            row["quantity"] = "2"
        large.append(manual)
        with self.assertNumQueries(4):
            parsed_large = parse_csv(self.worksheet_text(large), facility_id=self.facility.pk, year=2026)
        self.assertEqual(len(parsed_large), 33)
        self.assertEqual(sum(row["quantity"] for row in parsed_large), Decimal("66"))

    def test_batch_lookup_keeps_row_errors_and_rejects_oversized_files_before_queries(self):
        self.warehouse_stock()
        row = dict(self.download_worksheet()[0], quantity="1")
        invalid = dict(row, line_key="MANUAL-invalid", item_code="UNKNOWN")
        huge_id = dict(row, line_key="STOCK-" + "9" * 90)
        with self.assertRaises(ValidationError) as error:
            parse_csv(self.worksheet_text([row, invalid, huge_id]), facility_id=self.facility.pk, year=2026)
        self.assertIn("Baris 3:", str(error.exception))
        self.assertIn("Baris 4:", str(error.exception))
        malformed = self.worksheet_text([]) + "missing,columns\n"
        with self.assertNumQueries(0), self.assertRaisesMessage(ValidationError, "Baris 2:"):
            parse_csv(malformed, facility_id=self.facility.pk, year=2026)
        oversized = self.worksheet_text([dict(row, quantity="")] * 10001)
        with self.assertNumQueries(0), self.assertRaisesMessage(ValidationError, "Maksimal 10000 baris"):
            parse_csv(oversized, facility_id=self.facility.pk, year=2026)

    def test_batch_lookup_does_not_reuse_source_snapshots_between_uploads(self):
        stock = self.warehouse_stock()
        rows = self.download_worksheet()
        rows[0]["quantity"] = "1"
        content = self.worksheet_text(rows)
        parsed = parse_csv(content, facility_id=self.facility.pk, year=2026)
        self.assertEqual(parsed[0]["unit_price"], stock.unit_price)
        stock.unit_price = Decimal("999")
        stock.save()
        with self.assertRaisesMessage(ValidationError, "unit_price"):
            parse_csv(content, facility_id=self.facility.pk, year=2026)
        with self.assertRaises(ValidationError):
            self.opening(parsed, submit=False)
        self.assertFalse(PuskesmasOpeningVerification.objects.exists())

    def test_warehouse_candidates_without_facility_history_post_only_facility_inventory(self):
        from apps.stock.models import Transaction
        stock = self.warehouse_stock()
        rows = self.download_worksheet()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["line_key"], f"STOCK-{stock.pk}")
        self.assertEqual(rows[0]["quantity"], "")
        for field, expected in {"item_code": self.item.kode_barang, "item_name": self.item.nama_barang,
            "unit": self.item.satuan.name, "unit_price": "'321.1234567890", "batch_lot": "WH-BATCH",
            "expiry_date": "2027-04-30", "sumber_dana_code": "INV-FUND"}.items():
            self.assertEqual(rows[0][field], expected)
        self.assertNotIn("source_document_number", rows[0])
        self.assertEqual(rows[0]["provenance_note"], "")
        rows[0]["quantity"] = "7"
        # Manual historical layers remain available beside prefilled candidates.
        manual = dict(rows[0], line_key="MANUAL-1", batch_lot="Historical batch", quantity="2",
                      provenance_note="Historical stock verified against facility records; source document unknown.")
        parsed = parse_csv(self.worksheet_text(rows + [manual]), facility_id=self.facility.pk, year=2026)
        opening = self.opening(parsed)
        before = Transaction.objects.count()
        self.post(opening)
        self.assertEqual(opening.lines.get(line_key=f"STOCK-{stock.pk}").source_stock_id, stock.pk)
        self.assertEqual(opening.lines.get(source_stock=stock).source_document_number, "WH-SOURCE")
        self.assertIn("Instalasi Farmasi", opening.lines.get(source_stock=stock).provenance_note)
        self.assertEqual(PuskesmasInventoryBalance.objects.count(), 2)
        self.assertEqual(Transaction.objects.count(), before)
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 0)
        stock.unit_price = Decimal("999")
        stock.save()
        self.assertEqual(PuskesmasInventoryLayer.objects.get(opening_line__source_stock=stock).unit_price,
                         Decimal("321.1234567890"))

    def test_warehouse_metadata_tampering_and_stale_source_hold_posting(self):
        stock = self.warehouse_stock()
        rows = self.download_worksheet()
        rows[0]["quantity"] = "4"
        for field, value in [("unit_price", "999"), ("batch_lot", "OTHER"),
                             ("line_key", "STOCK-99999999")]:
            with self.assertRaises(ValidationError):
                parse_csv(self.worksheet_text([dict(rows[0], **{field: value})]),
                          facility_id=self.facility.pk, year=2026)
        opening = self.opening(parse_csv(self.worksheet_text(rows), facility_id=self.facility.pk, year=2026))
        stock.unit_price = Decimal("999")
        stock.save()
        with self.assertRaises(ValidationError):
            self.post(opening)
        self.assertFalse(PuskesmasInventoryAccount.objects.exists())
        self.assertFalse(PuskesmasInventoryMovement.objects.exists())

    def test_legacy_document_column_is_still_validated_and_manual_note_is_required(self):
        stock = self.warehouse_stock()
        rows = self.download_worksheet()
        rows[0]["quantity"] = "2"
        legacy = dict(rows[0], source_document_number=stock.source_document_number)
        parsed = parse_csv(self.worksheet_text([legacy], LEGACY_WORKSHEET_HEADERS),
                           facility_id=self.facility.pk, year=2026)
        self.assertEqual(parsed[0]["source_document_number"], stock.source_document_number)
        legacy["source_document_number"] = "CHANGED"
        with self.assertRaises(ValidationError):
            parse_csv(self.worksheet_text([legacy], LEGACY_WORKSHEET_HEADERS),
                      facility_id=self.facility.pk, year=2026)
        manual = dict(rows[0], line_key="MANUAL-1")
        with self.assertRaises(ValidationError):
            parse_csv(self.worksheet_text([manual]), facility_id=self.facility.pk, year=2026)
        manual["provenance_note"] = "Bukti stok tahun lalu; nomor dokumen asal tidak diketahui."
        parsed = parse_csv(self.worksheet_text([manual]), facility_id=self.facility.pk, year=2026)
        self.assertEqual(parsed[0]["source_document_number"], "")
        self.assertEqual(parsed[0]["provenance_note"], manual["provenance_note"])

    def test_worksheet_deduplicates_warehouse_identity_across_locations_and_distribution(self):
        from apps.items.models import Location
        stock = self.warehouse_stock()
        other_location = Location.objects.create(code="INV-WH2", name="Second warehouse")
        self.warehouse_stock(location=other_location)
        self.assertEqual(len(self.download_worksheet()), 1)
        _, _, source = self.receipt(price=stock.unit_price, received_date=date(2025, 12, 31))
        source.stock = stock
        source.issued_batch_lot = stock.batch_lot
        source.issued_expiry_date = stock.expiry_date
        source.issued_sumber_dana = stock.sumber_dana
        source.save()
        rows = self.download_worksheet()
        self.assertEqual([row["line_key"] for row in rows], [f"DIST-{source.pk}"])

    def test_warehouse_formula_safe_roundtrip_and_blank_quantities(self):
        stock = self.warehouse_stock(batch_lot="=BATCH", source_document_number="+SOURCE")
        rows = self.download_worksheet()
        self.assertEqual(rows[0]["batch_lot"], "'=BATCH")
        self.assertNotIn("source_document_number", rows[0])
        self.assertEqual(rows[0]["provenance_note"], "")
        with self.assertRaises(ValidationError):
            parse_csv(self.worksheet_text(rows), facility_id=self.facility.pk, year=2026)
        rows[0]["quantity"] = "1"
        parsed = parse_csv(self.worksheet_text(rows), facility_id=self.facility.pk, year=2026)
        self.assertEqual(parsed[0]["batch_lot"], stock.batch_lot)
        self.assertEqual(parsed[0]["source_document_number"], stock.source_document_number)

    def test_numeric_identifiers_preserve_leading_zero_and_decimal_batch_text(self):
        from apps.items.models import FundingSource
        funding = FundingSource.objects.create(code="001", name="Numeric code funding")
        self.item.kode_barang = "000012"
        self.item.save()
        stock = self.warehouse_stock(batch_lot="060125.01", sumber_dana=funding)
        for origin in ("STOCK", "DIST"):
            with self.subTest(origin=origin):
                if origin == "DIST":
                    _, _, source = self.receipt(price=stock.unit_price, received_date=date(2025, 12, 31))
                    source.stock = stock
                    source.issued_batch_lot = stock.batch_lot
                    source.issued_expiry_date = stock.expiry_date
                    source.issued_sumber_dana = funding
                    source.save()
                rows = self.download_worksheet()
                self.assertEqual(len(rows), 1)
                self.assertTrue(rows[0]["line_key"].startswith(origin))
                self.assertEqual(rows[0]["item_code"], "'000012")
                self.assertEqual(rows[0]["batch_lot"], "'060125.01")
                self.assertEqual(rows[0]["sumber_dana_code"], "'001")
                rows[0]["quantity"] = "340"
                parsed = parse_csv(self.worksheet_text(rows), facility_id=self.facility.pk, year=2026)
                self.assertEqual(parsed[0]["item"], self.item)
                self.assertEqual(parsed[0]["batch_lot"], "060125.01")
                self.assertEqual(parsed[0]["sumber_dana"], funding)
                changed = [dict(rows[0], batch_lot="60125,01")]
                with self.assertRaises(ValidationError) as error:
                    parse_csv(self.worksheet_text(changed), facility_id=self.facility.pk, year=2026)
                self.assertIn("Baris 2", str(error.exception))
                self.assertIn("batch_lot", str(error.exception))
                self.assertIn("060125.01", str(error.exception))
                self.assertIn("60125,01", str(error.exception))
                # Decimal commas remain supported in monetary fields.
                rows[0]["unit_price"] = rows[0]["unit_price"].replace(".", ",")
                self.assertEqual(parse_csv(self.worksheet_text(rows), facility_id=self.facility.pk, year=2026)[0]["unit_price"], stock.unit_price)

    def test_manual_added_stock_generates_reference_and_requires_quantity_and_provenance(self):
        stock = self.warehouse_stock()
        row = self.download_worksheet()[0]
        manual = dict(row, line_key="", quantity="", batch_lot="WQPITU", unit_price="404,56", sumber_dana_code="")
        row["quantity"] = "1"
        parsed = parse_csv(self.worksheet_text([row, manual]), facility_id=self.facility.pk, year=2026)
        self.assertEqual(len(parsed), 1)
        manual["quantity"] = "10"
        with self.assertRaisesMessage(ValidationError, "Provenance yang tidak diketahui"):
            parse_csv(self.worksheet_text([row, manual]), facility_id=self.facility.pk, year=2026)
        manual["provenance_note"] = "Bukti stok akhir tahun lalu; sumber dana dan dokumen asal tidak diketahui."
        parsed = parse_csv(self.worksheet_text([row, manual]), facility_id=self.facility.pk, year=2026)
        manual_key = parsed[1]["line_key"]
        self.assertTrue(manual_key.startswith("MANUAL-"))
        opening = self.opening(parsed)
        self.post(opening)
        manual_line = opening.lines.get(line_key=manual_key)
        self.assertIsNone(manual_line.source_stock_id)
        self.assertIsNone(manual_line.source_distribution_item_id)
        self.assertEqual(manual_line.batch_lot, "WQPITU")
        self.assertEqual(manual_line.unit_price, Decimal("404.56"))
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 0)

    def test_generated_manual_keys_are_unique_and_explicit_keys_remain_supported(self):
        self.warehouse_stock()
        manual = dict(self.download_worksheet()[0], line_key="", quantity="2",
                      provenance_note="Stok akhir tahun lalu; dokumen asal tidak diketahui.")
        explicit = dict(manual, line_key="MANUAL-13")
        rows = parse_csv(self.worksheet_text([manual, manual, explicit]),
                         facility_id=self.facility.pk, year=2026)
        self.assertEqual(len({row["line_key"] for row in rows}), 3)
        self.assertTrue(all(row["line_key"].startswith("MANUAL-") for row in rows))
        self.assertEqual(rows[2]["line_key"], "MANUAL-13")
        self.assertTrue(all(row["source_stock"] is None and row["source_distribution_item"] is None for row in rows))
        with self.assertRaisesMessage(ValidationError, "line_key tidak boleh duplikat"):
            parse_csv(self.worksheet_text([explicit, explicit]), facility_id=self.facility.pk, year=2026)
        upload = SimpleUploadedFile("manual-opening.csv", self.worksheet_text([manual, manual, explicit]).encode("utf-8"), content_type="text/csv")
        response = self.client.post(reverse("puskesmas:opening_create"), {
            "year": 2026, "reference": "Bukti manual", "csv_file": upload})
        self.assertEqual(response.status_code, 302)
        opening = PuskesmasOpeningVerification.objects.get()
        saved_keys = list(opening.lines.values_list("line_key", flat=True))
        self.assertEqual(len(set(saved_keys)), 3)
        self.assertIn("MANUAL-13", saved_keys)

    def test_prefilled_prices_with_three_decimal_places_remain_exact_text(self):
        stock = self.warehouse_stock()
        for original in ("992.249", "3741.111", "1705.404", "4370.649"):
            with self.subTest(price=original):
                stock.unit_price = Decimal(original)
                stock.save()
                row = self.download_worksheet()[0]
                self.assertEqual(row["unit_price"], "'" + format(Decimal(original), ".10f"))
                row["quantity"] = "1"
                for value in (row["unit_price"], row["unit_price"].replace(".", ","), original):
                    parsed = parse_csv(self.worksheet_text([dict(row, unit_price=value)]),
                                       facility_id=self.facility.pk, year=2026)
                    self.assertEqual(parsed[0]["unit_price"], Decimal(original))
                with self.assertRaisesMessage(ValidationError, "unit_price"):
                    parse_csv(self.worksheet_text([dict(row, unit_price=original.replace(".", ""))]),
                              facility_id=self.facility.pk, year=2026)

    def test_template_prefills_only_facility_pre_cutover_layers_without_quantities(self):
        receipt, _, first = self.receipt(received_date=date(2025, 12, 30))
        second = DistributionItem.objects.create(distribution=first.distribution, item=self.item,
            quantity_requested=3, issued_batch_lot="Batch-R", issued_unit_price=Decimal("2000.1234567890"))
        draft, _, _ = self.receipt(received_date=date(2025, 12, 28))
        draft.distribution.status = "DRAFT"
        draft.distribution.save()
        other, _, _ = self.receipt(received_date=date(2025, 12, 29))
        other.distribution.facility = self.other
        other.distribution.save()
        self.receipt(received_date=date(2026, 1, 1))
        late, _, _ = self.receipt(received_date=date(2026, 1, 2))
        late.distribution.distributed_date = date(2025, 12, 31)
        late.distribution.save()
        rows = self.download_worksheet(facility=self.other.pk)
        self.assertEqual([row["line_key"] for row in rows], [f"DIST-{first.pk}", f"DIST-{second.pk}"])
        self.assertTrue(all(row["quantity"] == "" for row in rows))
        self.assertTrue(all(row["provenance_note"] == "" for row in rows))
        self.assertEqual(rows[0]["item_code"], self.item.kode_barang)
        self.assertEqual(rows[0]["item_name"], self.item.nama_barang)
        self.assertEqual(rows[0]["unit"], self.item.satuan.name)
        self.assertEqual(rows[1]["unit_price"], "'2000.1234567890")
        self.assertEqual(rows[0]["batch_lot"], "Batch-R")

    def test_worksheet_roundtrip_skips_blank_quantities_and_retains_protected_source(self):
        receipt, _, source = self.receipt(received_date=date(2025, 12, 31))
        rows = self.download_worksheet()
        with self.assertRaises(ValidationError):
            parse_csv(self.worksheet_text(rows), facility_id=self.facility.pk, year=2026)
        rows[0]["quantity"] = "5"
        ignored = dict(rows[0], line_key="unused", quantity="", item_code="NOT-A-REAL-ITEM")
        parsed = parse_csv(self.worksheet_text(rows + [ignored]), facility_id=self.facility.pk, year=2026)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["source_distribution_item"].pk, source.pk)
        opening = self.opening(parsed)
        self.post(opening)
        self.assertEqual(opening.lines.get().source_distribution_item_id, source.pk)
        self.assertIn("Tidak tercatat pada sumber:", opening.lines.get().provenance_note)
        self.assertEqual(PuskesmasInventoryLayer.objects.get().unit_price, source.issued_unit_price)

    def test_source_metadata_scope_cutoff_and_post_time_revalidation(self):
        _, _, source = self.receipt(received_date=date(2025, 12, 31))
        rows = self.download_worksheet()
        rows[0]["quantity"] = "5"
        csv_text = self.worksheet_text(rows)
        for facility_id, year in [(self.other.pk, 2026), (self.facility.pk, 2025)]:
            with self.assertRaises(ValidationError):
                parse_csv(csv_text, facility_id=facility_id, year=year)
        changed = [dict(rows[0], unit_price="9999")]
        with self.assertRaises(ValidationError):
            parse_csv(self.worksheet_text(changed), facility_id=self.facility.pk, year=2026)
        parsed = parse_csv(csv_text, facility_id=self.facility.pk, year=2026)
        opening = self.opening(parsed)
        source.issued_unit_price = Decimal("9999")
        source.save()
        with self.assertRaises(ValidationError):
            self.post(opening)
        self.assertFalse(PuskesmasInventoryAccount.objects.exists())

    def test_missing_prices_stay_blank_template_scope_errors_and_no_zero_checkbox(self):
        self.receipt(price=None, received_date=date(2025, 12, 31))
        rows = self.download_worksheet()
        self.assertEqual(rows[0]["unit_price"], "")
        self.assertEqual(rows[0]["quantity"], "")
        response = self.client.get(reverse("puskesmas:opening_create"))
        self.assertNotContains(response, 'name="zero_stock"')
        self.assertNotContains(response, 'name="boundary_attested"')
        self.assertContains(response, "Catat seluruh stok di gudang, ruang tindakan dan Pustu")
        self.assertContains(response, 'id="template_year"')
        self.assertEqual(self.client.get(reverse("puskesmas:opening_template"), {"year": 999}).status_code, 400)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("puskesmas:opening_template"), {"year": 2026}).status_code, 400)


    def test_export_escapes_formula_text_and_import_restores_linked_snapshot(self):
        from apps.items.models import FundingSource, Location
        from apps.stock.models import Stock
        _, _, source = self.receipt(received_date=date(2025, 12, 31))
        fund = FundingSource.objects.create(code="@FUND", name="Test source")
        location = Location.objects.create(code="INV-LOC", name="Test warehouse")
        stock = Stock.objects.create(item=self.item, location=location, sumber_dana=fund,
            batch_lot="=1+1", source_document_number="+SOURCE", quantity=100, unit_price=9999)
        source.stock = stock
        source.issued_batch_lot = stock.batch_lot
        source.issued_sumber_dana = fund
        source.save()
        rows = self.download_worksheet()
        self.assertEqual(rows[0]["batch_lot"], "'=1+1")
        self.assertNotIn("source_document_number", rows[0])
        self.assertEqual(rows[0]["provenance_note"], "")
        self.assertEqual(rows[0]["unit_price"], "'1250.9876543210")
        rows[0]["quantity"] = "2"
        parsed = parse_csv(self.worksheet_text(rows), facility_id=self.facility.pk, year=2026)
        self.assertEqual(parsed[0]["batch_lot"], "=1+1")
        self.assertEqual(parsed[0]["source_document_number"], "+SOURCE")
        self.assertEqual(parsed[0]["sumber_dana"], fund)
        self.assertEqual(stock.quantity, 100)


class InventoryConcurrencyTests(InventoryFixture, TransactionTestCase):
    def test_cancel_and_submit_serialize_to_one_terminal_draft_transition(self):
        opening = self.opening(submit=False)
        def execute(action):
            close_old_connections()
            try:
                actor = User.objects.get(pk=self.operator.pk)
                service = cancel_opening if action == "cancel" else submit_opening
                try:
                    return service(user=actor, opening_id=opening.pk, digest=opening.digest).status
                except ValidationError:
                    return "rejected"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(execute, ["cancel", "submit"]))
        opening.refresh_from_db()
        self.assertEqual(results.count("rejected"), 1)
        self.assertIn(opening.status, ["CANCELLED", "SUBMITTED"])
        self.assertIn(opening.status, results)
        self.assertEqual(opening.cancelled_at is not None, opening.status == "CANCELLED")
        self.assertEqual(opening.submitted_at is not None, opening.status == "SUBMITTED")
        self.assertFalse(PuskesmasInventoryPosting.objects.exists())
        self.assertFalse(PuskesmasInventoryAccount.objects.exists())

    def test_concurrent_opening_post_is_one_event(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL row locks required")
        opening = self.opening()
        def post():
            close_old_connections()
            try:
                return review_opening(user=User.objects.get(pk=self.verifier.pk), opening_id=opening.pk, digest=opening.digest).pk
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: post(), range(2)))
        self.assertEqual(results, [opening.pk, opening.pk])
        self.assertEqual(PuskesmasInventoryPosting.objects.count(), 1)
        self.assertEqual(PuskesmasInventoryMovement.objects.count(), 1)

    def test_concurrent_receipt_post_and_opening_catchup_cannot_duplicate(self):
        opening = self.opening()
        receipt, _, _ = self.receipt()
        def execute(kind):
            close_old_connections()
            try:
                if kind == "opening":
                    return self.post(opening).pk
                return post_receipt(receipt=receipt, user=User.objects.get(pk=self.operator.pk))
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(execute, ["opening", "receipt"]))
        self.assertEqual(PuskesmasInventoryPosting.objects.filter(receipt=receipt).count(), 1)
        self.assertEqual(PuskesmasInventoryMovement.objects.count(), 2)

    @override_settings(RATELIMIT_ENABLE=False)
    def test_receipt_confirmation_and_lplpo_submission_serialize(self):
        from django.test import Client
        from apps.lplpo.models import LPLPO, LPLPOItem
        self.post()
        receipt, _, source = self.receipt(status="DRAFT")
        lplpo = LPLPO.objects.create(facility=self.facility, bulan=2, tahun=2026, created_by=self.operator)
        LPLPOItem.objects.create(lplpo=lplpo, item=self.item, stock_awal=10)
        payload = {"action": "confirm", "facility": self.facility.pk, "distribution": receipt.distribution_id,
            "received_date": "2026-02-01", "document_number": receipt.document_number,
            "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "1", "items-MIN_NUM_FORMS": "1",
            "items-MAX_NUM_FORMS": "1000", "items-0-distribution_item": source.pk, "items-0-confirmed": "on"}
        def execute(kind):
            close_old_connections()
            try:
                client = Client(SERVER_NAME="localhost", HTTP_HOST="localhost", secure=True)
                client.force_login(User.objects.get(pk=self.operator.pk))
                url = reverse("puskesmas:receiving_edit", args=[receipt.pk]) if kind == "receipt" else reverse("lplpo:lplpo_submit", args=[lplpo.pk])
                return client.post(url, payload if kind == "receipt" else {}, secure=True).status_code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(execute, ["receipt", "submit"]))
        self.assertTrue(all(status in [200, 302] for status in statuses), statuses)
        receipt.refresh_from_db()
        lplpo.refresh_from_db()
        self.assertEqual(lplpo.status, "SUBMITTED")
        self.assertEqual(lplpo.items.get().penerimaan, 3 if receipt.status == "CONFIRMED" else 0)
        self.assertEqual(PuskesmasInventoryPosting.objects.filter(receipt=receipt).exists(), receipt.status == "CONFIRMED")
