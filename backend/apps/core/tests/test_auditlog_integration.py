from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.urls import reverse

from auditlog.context import set_actor
from auditlog.models import LogEntry

from apps.items.models import Category, Facility, FundingSource, Item, Location, Unit
from apps.receiving.models import Receiving
from apps.users.models import ModuleAccess, User


@override_settings(SECURE_SSL_REDIRECT=False)
class AuditlogIntegrationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="audit-admin",
            email="audit-admin@example.com",
            password="StrongPass123!",
        )
        self.operator = User.objects.create_user(
            username="audit-operator",
            email="operator@example.com",
            password="StrongPass123!",
            role=User.Role.GUDANG,
        )
        self.unit = Unit.objects.create(code="TAB", name="Tablet")
        self.category = Category.objects.create(code="OBAT", name="Obat")
        self.funding_source = FundingSource.objects.create(code="DAK", name="DAK")
        self.location = Location.objects.create(code="GUD", name="Gudang")
        self.facility = Facility.objects.create(
            code="PKM01",
            name="Puskesmas 01",
            address="Jalan Rahasia",
            phone="08123456789",
        )

    def _latest_log_for(self, instance):
        content_type = ContentType.objects.get_for_model(instance)
        return (
            LogEntry.objects.filter(
                content_type=content_type,
                object_pk=str(instance.pk),
            )
            .order_by("-timestamp")
            .first()
        )

    def test_admin_webview_exposes_auditlog_entries_to_staff_only(self):
        changelist_url = reverse("admin:auditlog_logentry_changelist")

        self.client.force_login(self.admin)
        response = self.client.get(changelist_url)
        self.assertEqual(response.status_code, 200)

        self.client.force_login(self.operator)
        response = self.client.get(changelist_url)
        self.assertEqual(response.status_code, 403)

    def test_registered_model_create_update_delete_logs_actor_and_changes(self):
        with set_actor(self.admin):
            item = Item.objects.create(
                nama_barang="Paracetamol",
                satuan=self.unit,
                kategori=self.category,
                minimum_stock=10,
            )

        create_log = self._latest_log_for(item)
        self.assertIsNotNone(create_log)
        self.assertEqual(create_log.action, LogEntry.Action.CREATE)
        self.assertEqual(create_log.actor, self.admin)

        with set_actor(self.admin):
            item.nama_barang = "Paracetamol 500 mg"
            item.save(update_fields=["nama_barang", "updated_at"])

        update_log = self._latest_log_for(item)
        self.assertEqual(update_log.action, LogEntry.Action.UPDATE)
        self.assertEqual(update_log.actor, self.admin)
        self.assertIn("nama_barang", update_log.changes)
        self.assertNotIn("updated_at", update_log.changes)

        item_pk = item.pk
        with set_actor(self.admin):
            item.delete()

        delete_log = (
            LogEntry.objects.filter(
                content_type=ContentType.objects.get_for_model(Item),
                object_pk=str(item_pk),
                action=LogEntry.Action.DELETE,
            )
            .order_by("-timestamp")
            .first()
        )
        self.assertIsNotNone(delete_log)
        self.assertEqual(delete_log.actor, self.admin)

    def test_sensitive_fields_are_excluded_or_masked(self):
        with set_actor(self.admin):
            user = User.objects.create_user(
                username="audit-sensitive",
                email="secret@example.com",
                password="StrongPass123!",
                nip="1234567890",
            )

        user_log = self._latest_log_for(user)
        self.assertNotIn("password", user_log.changes)
        self.assertIn("email", user_log.changes)
        self.assertNotIn("secret@example.com", str(user_log.changes))
        self.assertIn("nip", user_log.changes)
        self.assertNotIn("1234567890", str(user_log.changes))

        with set_actor(self.admin):
            facility = Facility.objects.create(
                code="PKM02",
                name="Puskesmas 02",
                address="Alamat Privat",
                phone="08999999999",
            )

        facility_log = self._latest_log_for(facility)
        self.assertIn("address", facility_log.changes)
        self.assertNotIn("Alamat Privat", str(facility_log.changes))
        self.assertIn("phone", facility_log.changes)
        self.assertNotIn("08999999999", str(facility_log.changes))

    def test_operational_header_logging_does_not_replace_stock_transaction(self):
        with set_actor(self.admin):
            receiving = Receiving.objects.create(
                receiving_type=Receiving.ReceivingType.GRANT,
                receiving_date="2026-07-14",
                sumber_dana=self.funding_source,
                created_by=self.admin,
            )

        receiving_log = self._latest_log_for(receiving)
        self.assertIsNotNone(receiving_log)
        self.assertEqual(receiving_log.action, LogEntry.Action.CREATE)
        self.assertEqual(receiving_log.actor, self.admin)
        self.assertEqual(receiving_log.content_type.model, "receiving")

    def test_queryset_update_is_documented_as_not_signal_logged(self):
        access = ModuleAccess.objects.get(
            user=self.operator,
            module=ModuleAccess.Module.ITEMS,
        )

        create_count = LogEntry.objects.filter(
            content_type=ContentType.objects.get_for_model(ModuleAccess),
            object_pk=str(access.pk),
        ).count()

        with set_actor(self.admin):
            ModuleAccess.objects.filter(pk=access.pk).update(
                scope=ModuleAccess.Scope.MANAGE,
            )

        self.assertEqual(
            LogEntry.objects.filter(
                content_type=ContentType.objects.get_for_model(ModuleAccess),
                object_pk=str(access.pk),
            ).count(),
            create_count,
        )
