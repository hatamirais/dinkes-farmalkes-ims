from datetime import timedelta

from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.core.context_processors import nav_notifications
from apps.users.models import AuthorityDelegation, ModuleAccess

from .access import pending_lplpo_queryset
from .models import LPLPO
from .tests import LPLPOTestCase


class LPLPONotificationTests(LPLPOTestCase):
    def report(self, status, month, *, own=False, submitted=True):
        report = self.create_lplpo(
            facility=self.facility if own else self.other_facility,
            created_by=self.puskesmas_user if own else self.other_puskesmas_user,
            status=status,
            bulan=month,
        )
        if submitted:
            self.set_submitted_at(report, 2026, month, 2)
        return report

    def assert_pending(self, user, reports):
        self.assertSetEqual(
            set(pending_lplpo_queryset(user).values_list("pk", flat=True)),
            {report.pk for report in reports},
        )
        request = RequestFactory().get(reverse("lplpo:lplpo_list"))
        request.user = user
        entries = [
            entry for entry in nav_notifications(request)["nav_notification_items"]
            if entry["label"] == "LPLPO"
        ]
        if not reports:
            self.assertEqual(entries, [])
            return
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["count"], len(reports))
        self.client.force_login(user)
        response = self.client.get(entries[0]["url"])
        self.assertEqual(response.status_code, 200)
        visible_ids = {report.pk for report in response.context["lplpos"]}
        self.assertTrue({report.pk for report in reports} <= visible_ids)
        for report in reports:
            with self.subTest(report=report.pk):
                response = self.client.get(reverse("lplpo:lplpo_detail", args=[report.pk]))
                self.assertEqual(response.status_code, 200)

    def delegate(self, user, **overrides):
        values = {
            "module": ModuleAccess.Module.LPLPO,
            "delegate": user,
            "starts_at": timezone.now() - timedelta(hours=2),
            "ends_at": timezone.now() + timedelta(hours=1),
            "reason": "Notification regression test",
            "granted_by": self.kepala_without_facility,
        }
        values.update(overrides)
        return AuthorityDelegation.objects.create(**values)

    def test_kepala_counts_only_legacy_reviewed_work(self):
        self.report(LPLPO.Status.SUBMITTED, 1)
        self.report(LPLPO.Status.PIC_VERIFIED, 2)
        self.report(LPLPO.Status.REJECTED_PIC, 3)
        reviewed = self.report(LPLPO.Status.REVIEWED, 4)
        self.report(LPLPO.Status.APPROVED, 5)
        self.report(LPLPO.Status.CLOSED, 6)
        self.assert_pending(self.kepala_without_facility, [reviewed])

    def test_gudang_counts_active_cross_facility_work_only(self):
        reports = [
            self.report(LPLPO.Status.SUBMITTED, 1),
            self.report(LPLPO.Status.PIC_VERIFIED, 2),
            self.report(LPLPO.Status.REJECTED_PIC, 3),
        ]
        self.report(LPLPO.Status.REVIEWED, 4)
        self.report(LPLPO.Status.APPROVED, 5)
        self.report(LPLPO.Status.SUBMITTED, 6, submitted=False)
        self.assert_pending(self.gudang_without_facility, reports)

    def test_gudang_approve_scope_does_not_expose_cross_facility_reviewed_work(self):
        ModuleAccess.objects.filter(user=self.gudang_user, module=ModuleAccess.Module.LPLPO).update(
            scope=ModuleAccess.Scope.APPROVE
        )
        self.report(LPLPO.Status.REVIEWED, 1)
        self.report(LPLPO.Status.REVIEWED, 2, own=True)
        self.assert_pending(self.gudang_user, [])

    def test_view_scope_delegate_counts_own_legacy_work(self):
        ModuleAccess.objects.filter(user=self.gudang_user, module=ModuleAccess.Module.LPLPO).update(
            scope=ModuleAccess.Scope.VIEW
        )
        own = self.report(LPLPO.Status.REVIEWED, 1, own=True)
        self.report(LPLPO.Status.REVIEWED, 2)
        self.report(LPLPO.Status.SUBMITTED, 3)
        self.delegate(self.gudang_user)
        self.assert_pending(self.gudang_user, [own])

    def test_inactive_delegation_removes_legacy_notification(self):
        self.report(LPLPO.Status.REVIEWED, 1, own=True)
        delegation = self.delegate(self.gudang_user)
        for overrides in (
            {"ends_at": timezone.now() - timedelta(hours=1)},
            {"revoked_at": timezone.now(), "revoked_by": self.kepala_without_facility},
            {"starts_at": timezone.now() + timedelta(minutes=30)},
        ):
            with self.subTest(overrides=overrides):
                delegation.ends_at = timezone.now() + timedelta(hours=1)
                delegation.revoked_at = None
                delegation.revoked_by = None
                for key, value in overrides.items():
                    setattr(delegation, key, value)
                delegation.save()
                self.assert_pending(self.gudang_user, [])

    def test_none_scope_has_no_notification(self):
        self.report(LPLPO.Status.SUBMITTED, 1)
        ModuleAccess.objects.filter(user=self.gudang_user, module=ModuleAccess.Module.LPLPO).update(
            scope=ModuleAccess.Scope.NONE
        )
        self.assert_pending(self.gudang_user, [])

    def test_facility_bound_staff_count_only_own_pending_work(self):
        own = self.report(LPLPO.Status.SUBMITTED, 1, own=True)
        self.report(LPLPO.Status.SUBMITTED, 2)
        self.assert_pending(self.admin_umum_user, [own])
        self.admin_umum_user.facility = None
        self.admin_umum_user.save(update_fields=["facility"])
        self.assert_pending(self.admin_umum_user, [])

    def test_superuser_keeps_all_pending_stages(self):
        reports = [
            self.report(LPLPO.Status.SUBMITTED, 1),
            self.report(LPLPO.Status.PIC_VERIFIED, 2),
            self.report(LPLPO.Status.REJECTED_PIC, 3),
            self.report(LPLPO.Status.REVIEWED, 4),
        ]
        self.assert_pending(self.superuser, reports)
