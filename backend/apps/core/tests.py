from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase
from django.test import SimpleTestCase
from django.test import RequestFactory
from django.urls import reverse

from apps.core.context_processors import nav_notifications
from apps.core.versioning import DEFAULT_VERSION, SemanticVersion, read_version, write_version
from apps.distribution.models import Distribution
from apps.items.models import Facility, FundingSource
from apps.lplpo.models import LPLPO
from apps.puskesmas.models import PuskesmasRequest
from apps.receiving.models import Receiving
from apps.users.models import User


class SemanticVersionTests(SimpleTestCase):
    def test_parse_valid_semver(self):
        parsed = SemanticVersion.parse("2.4.9")
        self.assertEqual(parsed.major, 2)
        self.assertEqual(parsed.minor, 4)
        self.assertEqual(parsed.patch, 9)

    def test_parse_rejects_invalid_semver(self):
        with self.assertRaisesMessage(ValueError, "Invalid semantic version"):
            SemanticVersion.parse("1.0")

    def test_bump_rules(self):
        initial = SemanticVersion.parse("3.7.8")
        self.assertEqual(str(initial.bump_major()), "4.0.0")
        self.assertEqual(str(initial.bump_minor()), "3.8.0")
        self.assertEqual(str(initial.bump_patch()), "3.7.9")

    def test_read_missing_file_uses_default(self):
        with TemporaryDirectory() as temp_dir:
            version_file = Path(temp_dir) / "VERSION"
            self.assertEqual(str(read_version(version_file)), DEFAULT_VERSION)

    def test_write_and_read_round_trip(self):
        with TemporaryDirectory() as temp_dir:
            version_file = Path(temp_dir) / "VERSION"
            expected = SemanticVersion.parse("1.2.3")

            write_version(version_file, expected)

            self.assertEqual(str(read_version(version_file)), "1.2.3")


class DashboardViewTests(TestCase):
    def setUp(self):
        self.facility = Facility.objects.create(
            code="PKM-A",
            name="Puskesmas A",
            facility_type=Facility.FacilityType.PUSKESMAS,
        )
        self.other_facility = Facility.objects.create(
            code="PKM-B",
            name="Puskesmas B",
            facility_type=Facility.FacilityType.PUSKESMAS,
        )
        self.puskesmas_user = User.objects.create_user(
            username="operator-a",
            password="TestPassword123!",
            role=User.Role.PUSKESMAS,
            facility=self.facility,
        )

    def test_puskesmas_dashboard_uses_facility_scoped_template(self):
        own_lplpo = LPLPO.objects.create(
            facility=self.facility,
            bulan=3,
            tahun=2026,
            status=LPLPO.Status.DRAFT,
            created_by=self.puskesmas_user,
        )
        other_lplpo = LPLPO.objects.create(
            facility=self.other_facility,
            bulan=3,
            tahun=2026,
            status=LPLPO.Status.SUBMITTED,
            created_by=self.puskesmas_user,
        )
        own_request = PuskesmasRequest.objects.create(
            facility=self.facility,
            created_by=self.puskesmas_user,
            status=PuskesmasRequest.Status.DRAFT,
        )
        other_request = PuskesmasRequest.objects.create(
            facility=self.other_facility,
            created_by=self.puskesmas_user,
            status=PuskesmasRequest.Status.SUBMITTED,
        )

        self.client.force_login(self.puskesmas_user)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard_puskesmas.html")
        self.assertEqual(response.context["facility"], self.facility)
        self.assertEqual(response.context["latest_lplpo"], own_lplpo)
        self.assertEqual(list(response.context["recent_lplpos"]), [own_lplpo])
        self.assertEqual(list(response.context["recent_requests"]), [own_request])
        self.assertNotIn(other_lplpo, response.context["recent_lplpos"])
        self.assertNotIn(other_request, response.context["recent_requests"])

    def test_puskesmas_dashboard_handles_missing_facility(self):
        user = User.objects.create_user(
            username="operator-no-facility",
            password="TestPassword123!",
            role=User.Role.PUSKESMAS,
        )

        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard_puskesmas.html")
        self.assertIsNone(response.context["facility"])
        self.assertEqual(list(response.context["recent_lplpos"]), [])
        self.assertEqual(list(response.context["recent_requests"]), [])


class NavNotificationsContextProcessorTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_unauthenticated_user_gets_zero_notification_count(self):
        request = self.factory.get("/")
        request.user = type("AnonymousUser", (), {"is_authenticated": False})()

        context = nav_notifications(request)

        self.assertEqual(context["nav_notification_count"], 0)

    def test_puskesmas_user_gets_zero_notification_count(self):
        facility = Facility.objects.create(
            code="PKM-NAV",
            name="Puskesmas NAV",
            facility_type=Facility.FacilityType.PUSKESMAS,
        )
        puskesmas_user = User.objects.create_user(
            username="nav-puskesmas",
            password="TestPassword123!",
            role=User.Role.PUSKESMAS,
            facility=facility,
        )
        request = self.factory.get("/")
        request.user = puskesmas_user

        context = nav_notifications(request)

        self.assertEqual(context["nav_notification_count"], 0)

    def test_admin_user_counts_pending_receiving_documents(self):
        admin_user = User.objects.create_user(
            username="nav-admin",
            password="TestPassword123!",
            role=User.Role.ADMIN,
        )
        funding_source = FundingSource.objects.create(code="DAK-NAV", name="DAK NAV")
        Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date="2026-04-03",
            sumber_dana=funding_source,
            status=Receiving.Status.SUBMITTED,
            created_by=admin_user,
        )

        request = self.factory.get("/")
        request.user = admin_user
        context = nav_notifications(request)

        self.assertGreaterEqual(context["nav_notification_count"], 1)

    def test_admin_user_gets_module_summary_items(self):
        admin_user = User.objects.create_user(
            username="nav-admin-summary",
            password="TestPassword123!",
            role=User.Role.ADMIN,
        )
        facility = Facility.objects.create(
            code="PKM-SUM",
            name="Puskesmas Summary",
            facility_type=Facility.FacilityType.PUSKESMAS,
        )
        Distribution.objects.create(
            distribution_type=Distribution.DistributionType.LPLPO,
            request_date="2026-04-03",
            facility=facility,
            status=Distribution.Status.SUBMITTED,
            created_by=admin_user,
        )

        request = self.factory.get("/")
        request.user = admin_user
        context = nav_notifications(request)

        self.assertIn("nav_notification_items", context)
        self.assertTrue(
            any(
                item["label"] == "Distribusi dari LPLPO" and item["count"] == 1
                for item in context["nav_notification_items"]
            )
        )
