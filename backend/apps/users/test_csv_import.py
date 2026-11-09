import csv
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from auditlog.models import LogEntry
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.items.models import Facility
from apps.core.upload_validation import sanitize_uploaded_filename, validate_csv_upload
from .access import default_scope_for_role
from .csv_import import HEADERS, finish_import, parse_user_csv, stage_import
from .forms import UserCreateForm
from .models import ModuleAccess, User, UserImportBatch


PASSWORD = "AnInitial!Credential7492"


def csv_file(rows=None, *, delimiter=",", headers=HEADERS, bom=False):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=delimiter)
    writer.writerow(headers)
    for row in rows or [profile()]:
        writer.writerow([row.get(key, "") for key in headers])
    return SimpleUploadedFile("users.csv", (("\ufeff" if bom else "") + stream.getvalue()).encode(), content_type="text/csv")


def profile(**changes):
    return dict(username="new_operator", full_name="New Operator", nip="00123", email="", role="GUDANG", facility_code="", is_active="true", password=PASSWORD) | changes


class UserCSVImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = User.objects.create_superuser("import_admin", "admin@example.com", PASSWORD)
        cls.facility = Facility.objects.create(code="PKM01", name="Puskesmas Satu")

    def setUp(self):
        cache.clear()
        self.client.force_login(self.actor)
        self.url = reverse("users:user_import_csv")

    def test_preview_confirmation_signals_audit_login_and_replay(self):
        response = self.client.post(self.url, {"action": "preview", "file": csv_file()})
        self.assertContains(response, "Konfirmasi Import")
        self.assertNotContains(response, PASSWORD)
        self.assertFalse(User.objects.filter(username="new_operator").exists())
        batch = UserImportBatch.objects.get()
        self.assertNotIn(PASSWORD, str(batch.rows))
        self.assertNotContains(response, batch.rows[0]["password_hash"])
        result = self.client.post(self.url, {"action": "confirm", "batch_id": batch.pk})
        self.assertRedirects(result, reverse("users:user_list"))
        user = User.objects.get(username="new_operator")
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(user.nip, "00123")
        self.assertFalse(user.is_staff)
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["GUDANG"])
        for module, _ in ModuleAccess.Module.choices:
            self.assertEqual(user.module_accesses.get(module=module).scope, default_scope_for_role(user.role, module))
        log = LogEntry.objects.get(content_type=ContentType.objects.get_for_model(User), object_pk=str(user.pk), action=LogEntry.Action.CREATE)
        self.assertEqual(log.actor_id, self.actor.pk)
        self.assertNotIn("password", log.changes)
        self.assertFalse(UserImportBatch.objects.exists())
        self.assertContains(self.client.post(self.url, {"action": "confirm", "batch_id": batch.pk}), "Pratinjau tidak tersedia")
        self.assertEqual(User.objects.filter(username="new_operator").count(), 1)
        other = Client()
        login = other.post(reverse("login"), {"username": user.username, "password": PASSWORD})
        self.assertEqual(login.status_code, 302)
        self.assertEqual(int(other.session["_auth_user_id"]), user.pk)
        self.assertNotIn("password/change", login.url)
        self.assertEqual(other.get(reverse("users:user_import_csv")).status_code, 403)
        response = other.post(reverse("password_change"), {"old_password": PASSWORD, "new_password1": "Another!Credential6283", "new_password2": "Another!Credential6283"})
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertFalse(user.check_password(PASSWORD))
        self.assertTrue(user.check_password("Another!Credential6283"))

    def test_delimiters_bom_quoted_names_all_roles_and_inactive(self):
        for delimiter, bom in [(";", True), (",", False)]:
            rows = [profile(username=f"person_{role}", role=role, full_name='Nama, "Satu"', is_active="false", facility_code="PKM01" if role in {"PUSKESMAS", "GUDANG", "ADMIN_UMUM"} else "") for role in ["KEPALA", "ADMIN_UMUM", "GUDANG", "AUDITOR", "PUSKESMAS"]]
            parsed = parse_user_csv(csv_file(rows, delimiter=delimiter, bom=bom))
            self.assertEqual(len(parsed), 5)
            self.assertFalse(parsed[0]["is_active"])
            self.assertEqual(parsed[0]["full_name"], 'Nama, "Satu"')

    def test_invalid_rows_never_stage_or_create(self):
        invalid = [
            profile(role="ADMIN"), profile(role="UNKNOWN"), profile(password=""), profile(password="123"),
            profile(role="PUSKESMAS"), profile(facility_code="MISSING"),
            profile(role="AUDITOR", facility_code="PKM01"), profile(is_active="1"),
            profile(username="x" * 151), profile(full_name="x" * 256), profile(nip="x" * 31),
            profile(email="invalid"), profile(full_name="bad\x00name"),
            profile(username="similarusername123!", password="similarusername123!"),
        ]
        for row in invalid:
            with self.subTest(fields=[key for key in row if row[key] != profile()[key]]):
                with self.assertRaises(ValidationError):
                    stage_import(self.actor, csv_file([row]))
        self.assertFalse(UserImportBatch.objects.exists())
        self.assertEqual(User.objects.count(), 1)

    def test_duplicate_headers_privilege_columns_bad_rows_and_limits(self):
        for headers in [HEADERS + ("is_superuser",), HEADERS[:-1], HEADERS[:-1] + ("username",)]:
            with self.assertRaises(ValidationError):
                parse_user_csv(csv_file(headers=headers))
        for content in [b"", b"a,b\n", b"\xff,a", (",".join(HEADERS) + '\n"unclosed').encode(), (",".join(HEADERS) + "\na,b\n").encode()]:
            with self.assertRaises(ValidationError):
                parse_user_csv(SimpleUploadedFile("users.csv", content, content_type="text/csv"))
        with self.assertRaises(ValidationError):
            parse_user_csv(csv_file([profile(username=f"u{i}") for i in range(26)]))
        for filename, mime, content in [("users.txt", "text/csv", b"a,b"), ("users.csv", "application/octet-stream", b"a,b"), ("users.csv", "text/csv", b"a" * (1024 * 1024 + 1))]:
            with self.assertRaises(ValidationError):
                parse_user_csv(SimpleUploadedFile(filename, content, content_type=mime))

    def test_full_file_validation_and_utf8_sample_boundary(self):
        # Byte 4096 is the first byte of a valid two-byte UTF-8 character.
        content = b"a,b\n" + b"x" * 4091 + "é".encode() + b"\n"
        upload = SimpleUploadedFile("users.csv", content, content_type="text/csv")
        self.assertIs(validate_csv_upload(upload, max_size_bytes=1024 * 1024), upload)
        for suffix in [b"\x00", b"\xff"]:
            content = csv_file().read() + b"\n" + b"x" * 4096 + suffix
            with self.assertRaises(ValidationError):
                parse_user_csv(SimpleUploadedFile("users.csv", content, content_type="text/csv"))
        for name in ["../users.csv", "C:\\users.csv", "/users.csv"]:
            with self.assertRaises(ValidationError):
                sanitize_uploaded_filename(name)

    def test_case_insensitive_duplicates_and_blank_emails(self):
        for rows in [[profile(), profile(username="NEW_OPERATOR")], [profile(email="a@example.com"), profile(username="other", email="A@example.com")], [profile(username="IMPORT_ADMIN")], [profile(username="ＩＭＰＯＲＴ＿ＡＤＭＩＮ")], [profile(email="ADMIN@example.com")]]:
            with self.assertRaises(ValidationError):
                parse_user_csv(csv_file(rows))
        batch = stage_import(self.actor, csv_file([profile(), profile(username="other")]))
        self.assertEqual(finish_import(self.actor, batch.pk), 2)

    def test_unicode_normalization_password_preservation_and_escaping(self):
        password = " " + PASSWORD + " "
        row = profile(full_name="  Cafe\u0301 <script>  ", password=password)
        response = self.client.post(self.url, {"action": "preview", "file": csv_file([row])})
        self.assertContains(response, "Café &lt;script&gt;")
        batch = UserImportBatch.objects.get()
        finish_import(self.actor, batch.pk)
        user = User.objects.get(username="new_operator")
        self.assertTrue(user.check_password(password))
        self.assertFalse(user.check_password(PASSWORD))

    def test_stale_duplicate_rolls_back_users_groups_and_audit(self):
        batch = stage_import(self.actor, csv_file([profile(), profile(username="last_user")]))
        User.objects.create_user("LAST_USER", password=PASSWORD, role="GUDANG")
        before_logs = LogEntry.objects.count()
        before_scopes = ModuleAccess.objects.count()
        with self.assertRaises(ValidationError):
            finish_import(self.actor, batch.pk)
        self.assertFalse(User.objects.filter(username="new_operator").exists())
        self.assertEqual(LogEntry.objects.count(), before_logs)
        self.assertEqual(ModuleAccess.objects.count(), before_scopes)
        self.assertTrue(UserImportBatch.objects.filter(pk=batch.pk).exists())

    def test_facility_rechecked_and_cancel_scrubs_hash(self):
        batch = stage_import(self.actor, csv_file([profile(role="PUSKESMAS", facility_code="PKM01")]))
        self.facility.is_active = False
        self.facility.save()
        with self.assertRaises(ValidationError):
            finish_import(self.actor, batch.pk)
        self.assertEqual(finish_import(self.actor, batch.pk, cancel=True), 0)
        self.assertFalse(UserImportBatch.objects.exists())

    def test_wrong_actor_expiry_and_cleanup(self):
        batch = stage_import(self.actor, csv_file())
        other = User.objects.create_superuser("other_admin", password=PASSWORD)
        with self.assertRaises(ValidationError):
            finish_import(other, batch.pk)
        UserImportBatch.objects.filter(pk=batch.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        with self.assertRaises(ValidationError):
            finish_import(self.actor, batch.pk)
        call_command("cleanup_user_imports", stdout=io.StringIO())
        self.assertFalse(UserImportBatch.objects.exists())
        for invalid in ["", "not-a-uuid"]:
            response = self.client.post(self.url, {"action": "confirm", "batch_id": invalid})
            self.assertContains(response, "Pratinjau tidak tersedia")
            self.assertFalse(response.context["form"].is_bound)

    @override_settings(USER_MUTATION_RATE_LIMIT="1/m", RATELIMIT_USE_CACHE="locmem")
    def test_upload_and_confirmation_share_mutation_throttle(self):
        first = self.client.post(self.url, {"action": "preview", "file": csv_file()})
        self.assertEqual(first.status_code, 200)
        batch = UserImportBatch.objects.get()
        self.assertEqual(self.client.post(self.url, {"action": "confirm", "batch_id": batch.pk}).status_code, 429)
        self.assertFalse(User.objects.filter(username="new_operator").exists())

    def test_deactivated_actor_cannot_confirm(self):
        batch = stage_import(self.actor, csv_file())
        User.objects.filter(pk=self.actor.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            finish_import(self.actor, batch.pk)

    def test_permissions_template_methods_csrf_and_module_scope(self):
        viewer = User.objects.create_user("viewer", password=PASSWORD, role="AUDITOR")
        self.client.force_login(viewer)
        for url in [self.url, reverse("users:user_import_csv_template")]:
            self.assertEqual(self.client.get(url).status_code, 403)
        viewer.user_permissions.add(Permission.objects.get(codename="add_user", content_type__app_label="users"))
        self.assertEqual(self.client.get(self.url).status_code, 200)
        template = self.client.get(reverse("users:user_import_csv_template"))
        self.assertEqual(template.content.decode("utf-8-sig").strip(), ",".join(HEADERS))
        self.assertEqual(self.client.put(self.url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(viewer)
        self.assertEqual(csrf_client.post(self.url, {"action": "preview"}).status_code, 403)
        batch = stage_import(viewer, csv_file())
        viewer.user_permissions.clear()
        with self.assertRaises(PermissionDenied):
            finish_import(viewer, batch.pk)
        viewer.module_accesses.filter(module="users").update(scope=ModuleAccess.Scope.MANAGE)
        viewer = User.objects.get(pk=viewer.pk)
        self.assertEqual(len(stage_import(viewer, csv_file()).rows), 1)


class UserCSVConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.actor = User.objects.create_superuser("thread_admin", password=PASSWORD)

    def compete(self, functions):
        barrier = Barrier(2)

        def execute(function):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return function()
            except ValidationError:
                return "rejected"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(execute, functions))
        self.assertEqual(results.count("rejected"), 1)
        self.assertEqual(User.objects.filter(username__iexact="new_operator").count(), 1)

    def test_double_confirmation_single_use(self):
        batch = stage_import(self.actor, csv_file())
        self.compete([lambda: finish_import(self.actor, batch.pk)] * 2)

    def test_two_imports_same_identity(self):
        batches = [stage_import(self.actor, csv_file()) for _ in range(2)]
        self.compete([lambda: finish_import(self.actor, batches[0].pk), lambda: finish_import(self.actor, batches[1].pk)])

    def test_import_and_ordinary_form_create(self):
        batch = stage_import(self.actor, csv_file())

        def create():
            form = UserCreateForm({"username": "NEW_OPERATOR", "role": "GUDANG", "password1": PASSWORD, "password2": PASSWORD, "is_active": "on"}, can_manage_module_scopes=False)
            if not form.is_valid():
                raise ValidationError("Duplicate")
            return form.save().pk

        self.compete([lambda: finish_import(self.actor, batch.pk), create])
