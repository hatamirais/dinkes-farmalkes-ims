from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from apps.users.models import AuthorityDelegation, ModuleAccess
from apps.stock.models import Stock

from .models import LPLPO, LPLPOItem
from .tests import LPLPOTestCase


class LPLPORejectionRedirectTests(LPLPOTestCase):
    def reject(self, user, *, status=LPLPO.Status.SUBMITTED, own=False):
        report = self.create_lplpo(
            facility=self.facility if own else self.other_facility,
            created_by=self.puskesmas_user if own else self.other_puskesmas_user,
            status=status,
        )
        self.set_submitted_at(report, 2026, report.bulan, 2)
        self.client.force_login(user)
        response = self.client.post(
            reverse("lplpo:lplpo_reject", args=[report.pk]),
            {"rejection_reason": "Perbaiki data stok."},
        )
        report.refresh_from_db()
        expected_status = (
            LPLPO.Status.REJECTED_PIC
            if status == LPLPO.Status.REVIEWED
            else LPLPO.Status.REJECTED_PUSKESMAS
        )
        self.assertEqual(report.status, expected_status)
        self.assertEqual(report.rejection_reason, "Perbaiki data stok.")
        self.assertContains(
            self.client.get(response.url), "berhasil dikembalikan"
        )
        return report, response

    def test_gudang_without_facility_returns_to_queue_after_rejection(self):
        report, response = self.reject(self.gudang_without_facility)
        self.assertRedirects(response, reverse("lplpo:lplpo_list"))
        self.assertEqual(
            self.client.get(reverse("lplpo:lplpo_detail", args=[report.pk])).status_code,
            403,
        )
        self.client.force_login(self.other_puskesmas_user)
        self.assertContains(
            self.client.get(reverse("lplpo:lplpo_detail", args=[report.pk])),
            "Perbaiki data stok.",
        )

    def test_gudang_rejecting_other_facility_returns_to_queue(self):
        _, response = self.reject(self.gudang_user)
        self.assertRedirects(response, reverse("lplpo:lplpo_list"))

    def test_same_facility_rejection_keeps_detail_destination(self):
        report, response = self.reject(self.gudang_user, own=True)
        self.assertRedirects(response, reverse("lplpo:lplpo_detail", args=[report.pk]))

    def test_kepala_legacy_rejection_returns_to_queue(self):
        report, response = self.reject(
            self.kepala_without_facility, status=LPLPO.Status.REVIEWED
        )
        self.assertRedirects(response, reverse("lplpo:lplpo_list"))
        self.assertEqual(
            self.client.get(reverse("lplpo:lplpo_detail", args=[report.pk])).status_code,
            403,
        )

    def test_delegate_legacy_rejection_keeps_same_facility_detail(self):
        AuthorityDelegation.objects.create(
            module=ModuleAccess.Module.LPLPO,
            delegate=self.gudang_user,
            granted_by=self.kepala_without_facility,
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(hours=1),
            reason="Rejection redirect regression test",
        )
        report, response = self.reject(
            self.gudang_user, status=LPLPO.Status.REVIEWED, own=True
        )
        self.assertRedirects(response, reverse("lplpo:lplpo_detail", args=[report.pk]))

    def test_verify_transition_keeps_detail_access_without_facility(self):
        report = self.create_lplpo(status=LPLPO.Status.SUBMITTED)
        self.client.force_login(self.gudang_without_facility)
        response = self.client.post(reverse("lplpo:lplpo_verify", args=[report.pk]))
        report.refresh_from_db()
        self.assertEqual(report.status, LPLPO.Status.PIC_VERIFIED)
        self.assertRedirects(response, reverse("lplpo:lplpo_detail", args=[report.pk]))

    def test_review_without_facility_reaches_generated_distribution(self):
        report = self.create_lplpo(
            status=LPLPO.Status.PIC_VERIFIED,
            facility=self.other_facility,
            created_by=self.other_puskesmas_user,
        )
        line = LPLPOItem.objects.create(
            lplpo=report, item=self.item_a, permintaan_jumlah=Decimal("5")
        )
        Stock.objects.create(
            item=self.item_a,
            location=self.location,
            batch_lot="REVIEW-REDIRECT",
            expiry_date=timezone.localdate() + timedelta(days=365),
            quantity=Decimal("10"),
            reserved=Decimal("0"),
            unit_price=Decimal("1000"),
            sumber_dana=self.funding_source,
            source_document_number="REVIEW-REDIRECT-TEST",
        )
        self.client.force_login(self.gudang_without_facility)
        response = self.client.post(
            reverse("lplpo:lplpo_review", args=[report.pk]),
            {
                f"review_{line.pk}-pemberian_jumlah": "5",
                f"review_{line.pk}-pemberian_alasan": "Sesuai permintaan.",
            },
        )
        report.refresh_from_db()
        self.assertEqual(report.status, LPLPO.Status.APPROVED)
        self.assertIsNotNone(report.distribution_id)
        self.assertRedirects(
            response,
            reverse("distribution:distribution_detail", args=[report.distribution_id]),
        )
