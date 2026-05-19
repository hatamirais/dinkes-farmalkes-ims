from unittest import mock

from django.contrib.auth.models import Permission
from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse

from apps.items.models import Facility
from apps.users.access import (
    ROLE_DEFAULT_SCOPES,
    default_scope_for_role,
    ensure_default_module_access,
    get_user_module_scope,
    has_module_permission,
)
from apps.users.models import ModuleAccess, User
from apps.users.views import _role_defaults_json


class UserManagementViewsTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin_root",
            password="secret12345",
            email="admin@example.com",
            role=User.Role.ADMIN,
        )
        self.target = User.objects.create_user(
            username="petugas1",
            password="secret12345",
            email="petugas1@example.com",
            role=User.Role.GUDANG,
            full_name="Petugas Gudang 1",
            nip="198801012010011001",
            is_active=True,
        )
        self.client.force_login(self.admin)

    def _module_scope_payload(self, scope=ModuleAccess.Scope.NONE):
        payload = {}
        for module_code, _ in ModuleAccess.Module.choices:
            payload[f"module_scope__{module_code}"] = str(scope)
        return payload

    def test_admin_umum_cannot_access_user_management(self):
        admin_umum = User.objects.create_user(
            username="admin_umum_1",
            password="secret12345",
            email="adminumum@example.com",
            role=User.Role.ADMIN_UMUM,
        )
        self.client.force_login(admin_umum)
        response = self.client.get(reverse("users:user_list"))
        self.assertEqual(response.status_code, 403)
        self.assertContains(
            response,
            "Anda tidak memiliki izin untuk membuka manajemen user.",
            status_code=403,
        )

    def test_kepala_can_access_user_management_but_cannot_edit(self):
        kepala = User.objects.create_user(
            username="kepala_1",
            password="secret12345",
            email="kepala@example.com",
            role=User.Role.KEPALA,
        )
        self.client.force_login(kepala)

        list_response = self.client.get(reverse("users:user_list"))
        self.assertEqual(list_response.status_code, 200)

        edit_response = self.client.post(
            reverse("users:user_update", args=[self.target.pk]),
            {
                "username": self.target.username,
                "full_name": "Tidak Boleh",
                "email": self.target.email,
                "role": self.target.role,
                "is_active": "on",
            },
        )
        self.assertEqual(edit_response.status_code, 403)
        self.assertContains(
            edit_response,
            "Anda tidak memiliki izin untuk mengubah user.",
            status_code=403,
        )
        self.target.refresh_from_db()
        self.assertNotEqual(self.target.full_name, "Tidak Boleh")

    def test_kepala_cannot_access_admin_panel(self):
        kepala = User.objects.create_user(
            username="kepala_2",
            password="secret12345",
            email="kepala2@example.com",
            role=User.Role.KEPALA,
            is_staff=True,
        )
        ensure_default_module_access(kepala, overwrite=True)
        self.client.force_login(kepala)
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 403)

    def test_user_list_loads(self):
        response = self.client.get(reverse("users:user_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Manajemen Pengguna")
        self.assertContains(response, self.target.username)

    def test_user_list_filter_by_role(self):
        response = self.client.get(
            reverse("users:user_list"), {"jabatan": User.Role.GUDANG}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.target.username)

    def test_user_list_filter_by_legacy_role_param_still_supported(self):
        response = self.client.get(
            reverse("users:user_list"), {"role": User.Role.GUDANG}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.target.username)

    def test_user_create_success(self):
        payload = {
            "username": "auditor01",
            "full_name": "Auditor Baru",
            "nip": "197912312010011002",
            "email": "auditor01@example.com",
            "role": User.Role.AUDITOR,
            "is_active": "on",
            "password1": "VeryStrongPass123!",
            "password2": "VeryStrongPass123!",
        }
        payload.update(self._module_scope_payload(ModuleAccess.Scope.VIEW))
        response = self.client.post(reverse("users:user_create"), payload)
        self.assertEqual(response.status_code, 302)
        created = User.objects.get(username="auditor01")
        self.assertEqual(created.role, User.Role.AUDITOR)
        self.assertEqual(created.nip, "197912312010011002")
        self.assertTrue(created.check_password("VeryStrongPass123!"))

    def test_user_create_form_hides_admin_cli_notice(self):
        response = self.client.get(reverse("users:user_create"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "createsuperuser")

    def test_user_create_form_shows_role_guide(self):
        response = self.client.get(reverse("users:user_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Panduan Jabatan")
        self.assertContains(response, "Petugas Gudang")
        self.assertContains(response, "Operator Puskesmas")

    def test_user_create_puskesmas_requires_facility(self):
        payload = {
            "username": "operator_pkm_1",
            "full_name": "Operator Puskesmas 1",
            "nip": "197001012010011004",
            "email": "pkm1@example.com",
            "role": User.Role.PUSKESMAS,
            "is_active": "on",
            "password1": "VeryStrongPass123!",
            "password2": "VeryStrongPass123!",
        }
        payload.update(self._module_scope_payload(ModuleAccess.Scope.VIEW))
        response = self.client.post(reverse("users:user_create"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fasilitas wajib dipilih untuk Operator Puskesmas.")
        self.assertFalse(User.objects.filter(username="operator_pkm_1").exists())

    def test_user_create_puskesmas_with_facility_succeeds(self):
        facility = Facility.objects.create(code="PKM-01", name="Puskesmas 01")
        payload = {
            "username": "operator_pkm_2",
            "full_name": "Operator Puskesmas 2",
            "nip": "197001012010011005",
            "email": "pkm2@example.com",
            "role": User.Role.PUSKESMAS,
            "facility": str(facility.pk),
            "is_active": "on",
            "password1": "VeryStrongPass123!",
            "password2": "VeryStrongPass123!",
        }
        payload.update(self._module_scope_payload(ModuleAccess.Scope.VIEW))
        response = self.client.post(reverse("users:user_create"), payload)
        self.assertEqual(response.status_code, 302)
        created = User.objects.get(username="operator_pkm_2")
        self.assertEqual(created.role, User.Role.PUSKESMAS)
        self.assertEqual(created.facility_id, facility.pk)

    def test_dashboard_blocks_admin_role_creation(self):
        """ADMIN role cannot be created from the Dashboard — only via CLI."""
        payload = {
            "username": "sneaky_admin",
            "full_name": "Sneaky Admin",
            "nip": "197001012010011003",
            "email": "sneaky@example.com",
            "role": User.Role.ADMIN,
            "is_active": "on",
            "password1": "VeryStrongPass123!",
            "password2": "VeryStrongPass123!",
        }
        payload.update(self._module_scope_payload(ModuleAccess.Scope.MANAGE))
        response = self.client.post(reverse("users:user_create"), payload)
        # Should re-render the form with an error, not redirect
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="sneaky_admin").exists())

    def test_dashboard_blocks_promoting_user_to_admin(self):
        """Existing user cannot be promoted to ADMIN via the Dashboard."""
        payload = {
            "username": self.target.username,
            "full_name": self.target.full_name,
            "nip": self.target.nip,
            "email": self.target.email,
            "role": User.Role.ADMIN,
            "is_active": "on",
        }
        payload.update(self._module_scope_payload(ModuleAccess.Scope.MANAGE))
        response = self.client.post(
            reverse("users:user_update", args=[self.target.pk]), payload
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertNotEqual(self.target.role, User.Role.ADMIN)

    def test_user_update_success(self):
        payload = {
            "username": self.target.username,
            "full_name": "Nama Baru",
            "nip": "198505052010011004",
            "email": "updated@example.com",
            "role": User.Role.ADMIN_UMUM,
            "is_active": "on",
        }
        payload.update(self._module_scope_payload(ModuleAccess.Scope.VIEW))
        response = self.client.post(
            reverse("users:user_update", args=[self.target.pk]), payload
        )
        self.assertEqual(response.status_code, 302)
        self.target.refresh_from_db()
        self.assertEqual(self.target.full_name, "Nama Baru")
        self.assertEqual(self.target.nip, "198505052010011004")
        self.assertEqual(self.target.email, "updated@example.com")
        self.assertEqual(self.target.role, User.Role.ADMIN_UMUM)

    def test_user_reset_password_success(self):
        response = self.client.post(
            reverse("users:user_reset_password", args=[self.target.pk]),
            {
                "password1": "UpdatedPass123!",
                "password2": "UpdatedPass123!",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password("UpdatedPass123!"))
        self.assertIn(
            f"Password untuk {self.target.username} berhasil direset.",
            [message.message for message in get_messages(response.wsgi_request)],
        )

    def test_user_reset_password_preserves_session_for_self_reset(self):
        response = self.client.post(
            reverse("users:user_reset_password", args=[self.admin.pk]),
            {
                "password1": "AdminReset123!",
                "password2": "AdminReset123!",
            },
        )
        self.assertRedirects(response, reverse("users:user_update", args=[self.admin.pk]))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("AdminReset123!"))
        follow_up = self.client.get(reverse("users:user_list"))
        self.assertEqual(follow_up.status_code, 200)

    def test_user_reset_password_rejects_mismatch(self):
        response = self.client.post(
            reverse("users:user_reset_password", args=[self.target.pk]),
            {
                "password1": "UpdatedPass123!",
                "password2": "DifferentPass123!",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password("secret12345"))
        self.assertIn(
            "Konfirmasi password tidak sama.",
            [message.message for message in get_messages(response.wsgi_request)],
        )

    def test_user_reset_password_rejects_invalid_password(self):
        response = self.client.post(
            reverse("users:user_reset_password", args=[self.target.pk]),
            {
                "password1": "short",
                "password2": "short",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password("secret12345"))
        self.assertTrue(
            any(
                "setidaknya 10 karakter" in message.message
                for message in get_messages(response.wsgi_request)
            )
        )

    def test_user_reset_password_denied_without_manage_scope(self):
        kepala = User.objects.create_user(
            username="kepala_reset",
            password="secret12345",
            email="kepala-reset@example.com",
            role=User.Role.KEPALA,
        )
        self.client.force_login(kepala)

        response = self.client.post(
            reverse("users:user_reset_password", args=[self.target.pk]),
            {
                "password1": "BlockedReset123!",
                "password2": "BlockedReset123!",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password("secret12345"))
        self.assertContains(
            response,
            "Anda tidak memiliki izin untuk mereset password user.",
            status_code=403,
        )

    def test_user_list_shows_nip(self):
        response = self.client.get(reverse("users:user_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "NIP")
        self.assertContains(response, self.target.nip)

    def test_user_list_shows_facility_column_and_values(self):
        facility = Facility.objects.create(code="PKM-LIST", name="Puskesmas List")
        User.objects.create_user(
            username="operator_list",
            password="secret12345",
            email="operator_list@example.com",
            role=User.Role.PUSKESMAS,
            facility=facility,
            full_name="Operator List",
        )

        response = self.client.get(reverse("users:user_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fasilitas")
        self.assertContains(response, "Instalasi Farmasi")
        self.assertContains(response, "Puskesmas List")

    def test_toggle_active_for_target_user(self):
        response = self.client.post(
            reverse("users:user_toggle_active", args=[self.target.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)

    def test_toggle_active_blocks_self_deactivation(self):
        response = self.client.post(
            reverse("users:user_toggle_active", args=[self.admin.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_toggle_active_ajax_returns_json_payload(self):
        response = self.client.post(
            reverse("users:user_toggle_active", args=[self.target.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        self.assertEqual(
            response.json(),
            {
                "success": True,
                "is_active": False,
                "status_text": "Nonaktif",
            },
        )

    def test_toggle_active_ajax_blocks_self_deactivation(self):
        response = self.client.post(
            reverse("users:user_toggle_active", args=[self.admin.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "error": "Tidak dapat menonaktifkan akun sendiri.",
            },
        )

    def test_delete_user_success(self):
        self.target.is_active = False
        self.target.save(update_fields=["is_active"])
        response = self.client.post(reverse("users:user_delete", args=[self.target.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(pk=self.target.pk).exists())

    def test_delete_user_blocks_self_delete(self):
        response = self.client.post(reverse("users:user_delete", args=[self.admin.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_delete_user_blocks_active_user(self):
        response = self.client.post(reverse("users:user_delete", args=[self.target.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(pk=self.target.pk).exists())

    def test_user_detail_hides_edit_button_for_view_only_access(self):
        kepala = User.objects.create_user(
            username="kepala_detail",
            password="secret12345",
            email="kepala.detail@example.com",
            role=User.Role.KEPALA,
        )
        self.client.force_login(kepala)

        response = self.client.get(reverse("users:user_detail", args=[self.target.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.target.full_name)
        self.assertNotContains(
            response,
            reverse("users:user_update", args=[self.target.pk]),
        )

    def test_user_detail_denies_user_without_view_access(self):
        admin_umum = User.objects.create_user(
            username="admin_umum_detail",
            password="secret12345",
            email="adminumum.detail@example.com",
            role=User.Role.ADMIN_UMUM,
        )
        self.client.force_login(admin_umum)

        response = self.client.get(reverse("users:user_detail", args=[self.target.pk]))

        self.assertEqual(response.status_code, 403)
        self.assertContains(
            response,
            "Anda tidak memiliki izin untuk membuka detail user.",
            status_code=403,
        )

    def test_bulk_action_activate_selected_users(self):
        inactive_user = User.objects.create_user(
            username="inactive_user",
            password="secret12345",
            email="inactive@example.com",
            role=User.Role.GUDANG,
            is_active=False,
        )

        response = self.client.post(
            reverse("users:user_bulk_action"),
            {"action": "activate", "selected_users": [inactive_user.pk]},
        )

        self.assertEqual(response.status_code, 302)
        inactive_user.refresh_from_db()
        self.assertTrue(inactive_user.is_active)

    def test_bulk_action_deactivate_selected_users(self):
        response = self.client.post(
            reverse("users:user_bulk_action"),
            {"action": "deactivate", "selected_users": [self.target.pk]},
        )

        self.assertEqual(response.status_code, 302)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)

    def test_bulk_action_delete_skips_active_and_protected_users(self):
        deletable_user = User.objects.create_user(
            username="deletable_user",
            password="secret12345",
            email="deletable@example.com",
            role=User.Role.GUDANG,
            is_active=False,
        )
        protected_user = User.objects.create_user(
            username="protected_user",
            password="secret12345",
            email="protected@example.com",
            role=User.Role.GUDANG,
            is_active=False,
        )

        original_delete = User.delete

        def delete_with_protection(user_obj, *args, **kwargs):
            if user_obj.pk == protected_user.pk:
                raise ProtectedError("protected", [user_obj])
            return original_delete(user_obj, *args, **kwargs)

        with mock.patch.object(User, "delete", autospec=True, side_effect=delete_with_protection):
            response = self.client.post(
                reverse("users:user_bulk_action"),
                {
                    "action": "delete",
                    "selected_users": [
                        self.target.pk,
                        deletable_user.pk,
                        protected_user.pk,
                    ],
                },
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(pk=deletable_user.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.target.pk).exists())
        self.assertTrue(User.objects.filter(pk=protected_user.pk).exists())
        self.assertContains(response, "1 pengguna dihapus.")
        self.assertContains(response, "1 pengguna aktif tidak dapat dihapus.")
        self.assertContains(
            response,
            "1 pengguna memiliki data terkait dan tidak dapat dihapus.",
        )


class StaffFlagSyncTest(TestCase):
    """Verify that is_staff is synced correctly based on role via the post_save signal."""

    def test_create_superuser_forces_admin_role_and_staff(self):
        user = User.objects.create_superuser(
            username="new_admin",
            email="new_admin@example.com",
            password="VeryStrongPass123!",
        )
        user.refresh_from_db()
        self.assertEqual(user.role, User.Role.ADMIN)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

    def test_create_user_blocks_admin_role(self):
        with self.assertRaisesMessage(
            ValueError,
            "Role Admin hanya dapat dibuat melalui perintah createsuperuser.",
        ):
            User.objects.create_user(
                username="blocked_admin",
                password="VeryStrongPass123!",
                role=User.Role.ADMIN,
            )

    def test_non_admin_role_does_not_get_is_staff(self):
        """Non-ADMIN roles should never get is_staff=True through the signal."""
        for role in [
            User.Role.KEPALA,
            User.Role.ADMIN_UMUM,
            User.Role.GUDANG,
            User.Role.AUDITOR,
        ]:
            with self.subTest(role=role):
                user = User.objects.create_user(
                    username=f"user_{role.lower()}",
                    password="VeryStrongPass123!",
                    role=role,
                )
                user.refresh_from_db()
                self.assertFalse(
                    user.is_staff,
                    f"Role {role} should NOT have is_staff=True",
                )

    def test_changing_role_to_admin_is_blocked_for_non_superuser(self):
        user = User.objects.create_user(
            username="promoted_user",
            password="VeryStrongPass123!",
            role=User.Role.GUDANG,
        )
        user.refresh_from_db()
        self.assertFalse(user.is_staff)

        user.role = User.Role.ADMIN
        with self.assertRaises(ValidationError):
            user.save(update_fields=["role"])

        user.refresh_from_db()
        self.assertEqual(user.role, User.Role.GUDANG)
        self.assertFalse(user.is_staff)

    def test_superuser_role_remains_admin_when_saved(self):
        user = User.objects.create_superuser(
            username="demoted_admin",
            email="demoted_admin@example.com",
            password="VeryStrongPass123!",
        )
        user.refresh_from_db()
        self.assertTrue(user.is_staff)

        user.role = User.Role.GUDANG
        user.save(update_fields=["role"])
        user.refresh_from_db()
        self.assertEqual(user.role, User.Role.ADMIN)
        self.assertTrue(user.is_staff)

    def test_admin_panel_save_seeds_module_access(self):
        """
        Users saved via Admin panel (simulated by direct create) must have
        ModuleAccess rows so Dashboard feature-gating works correctly.
        """
        user = User.objects.create_user(
            username="admin_panel_user",
            password="VeryStrongPass123!",
            role=User.Role.GUDANG,
        )
        # Signal should have seeded ModuleAccess rows
        modules_with_access = ModuleAccess.objects.filter(user=user)
        self.assertGreater(
            modules_with_access.count(),
            0,
            "ModuleAccess rows should be seeded after user creation",
        )


class UACRoleMatrixTest(TestCase):
    def _create_user_with_defaults(self, username: str, role: str) -> User:
        if role == User.Role.ADMIN:
            user = User.objects.create_superuser(
                username=username,
                email=f"{username}@example.com",
                password="VeryStrongPass123!",
            )
        else:
            user = User.objects.create_user(
                username=username,
                password="VeryStrongPass123!",
                role=role,
            )
        ensure_default_module_access(user, overwrite=True)
        return user

    def test_default_module_access_seed_matches_role_matrix(self):
        for role, module_scopes in ROLE_DEFAULT_SCOPES.items():
            user = self._create_user_with_defaults(f"matrix_{role.lower()}", role)
            for module, expected_scope in module_scopes.items():
                with self.subTest(role=role, module=module):
                    assignment = ModuleAccess.objects.get(user=user, module=module)
                    self.assertEqual(assignment.scope, expected_scope)

    def test_role_defaults_json_returns_mapping_for_template_json_script(self):
        payload = _role_defaults_json()

        self.assertIsInstance(payload, dict)
        self.assertEqual(payload, ROLE_DEFAULT_SCOPES)
        self.assertIsInstance(payload[User.Role.GUDANG], dict)
        self.assertEqual(
            payload[User.Role.GUDANG][ModuleAccess.Module.STOCK],
            ModuleAccess.Scope.OPERATE,
        )

    def test_petugas_gudang_operational_only_for_change_permissions(self):
        user = self._create_user_with_defaults("gudang_matrix", User.Role.GUDANG)

        self.assertTrue(has_module_permission(user, "receiving.change_receiving"))
        self.assertTrue(has_module_permission(user, "distribution.change_distribution"))
        self.assertTrue(has_module_permission(user, "recall.change_recall"))
        self.assertTrue(has_module_permission(user, "expired.change_expired"))
        self.assertTrue(has_module_permission(user, "stock_opname.change_stockopname"))

        self.assertFalse(
            ModuleAccess.objects.get(
                user=user, module=ModuleAccess.Module.RECEIVING
            ).scope
            >= ModuleAccess.Scope.APPROVE
        )
        self.assertFalse(
            ModuleAccess.objects.get(
                user=user, module=ModuleAccess.Module.DISTRIBUTION
            ).scope
            >= ModuleAccess.Scope.APPROVE
        )
        self.assertFalse(
            ModuleAccess.objects.get(user=user, module=ModuleAccess.Module.RECALL).scope
            >= ModuleAccess.Scope.APPROVE
        )
        self.assertFalse(
            ModuleAccess.objects.get(
                user=user, module=ModuleAccess.Module.EXPIRED
            ).scope
            >= ModuleAccess.Scope.APPROVE
        )
        self.assertFalse(
            ModuleAccess.objects.get(
                user=user, module=ModuleAccess.Module.STOCK_OPNAME
            ).scope
            >= ModuleAccess.Scope.APPROVE
        )

    def test_kepala_has_approval_scope_for_workflow_modules(self):
        user = self._create_user_with_defaults("kepala_matrix", User.Role.KEPALA)

        for module in [
            ModuleAccess.Module.RECEIVING,
            ModuleAccess.Module.DISTRIBUTION,
            ModuleAccess.Module.RECALL,
            ModuleAccess.Module.EXPIRED,
            ModuleAccess.Module.STOCK_OPNAME,
        ]:
            with self.subTest(module=module):
                scope = ModuleAccess.objects.get(user=user, module=module).scope
                self.assertGreaterEqual(scope, ModuleAccess.Scope.APPROVE)

    def test_get_user_module_scope_falls_back_to_role_defaults_without_rows(self):
        user = User.objects.create_user(
            username="legacy_kepala",
            password="VeryStrongPass123!",
            role=User.Role.KEPALA,
        )
        ModuleAccess.objects.filter(user=user).delete()

        self.assertEqual(
            get_user_module_scope(user, ModuleAccess.Module.PUSKESMAS),
            ModuleAccess.Scope.APPROVE,
        )
        self.assertTrue(has_module_permission(user, "puskesmas.view_puskesmasrequest"))


class HybridUserAuthorizationTest(TestCase):
    def setUp(self):
        self.viewer = User.objects.create_user(
            username="viewer_only",
            email="viewer_only@example.com",
            password="VeryStrongPass123!",
            role=User.Role.ADMIN_UMUM,
        )
        ModuleAccess.objects.update_or_create(
            user=self.viewer,
            module=ModuleAccess.Module.USERS,
            defaults={"scope": ModuleAccess.Scope.NONE},
        )
        self.editor = User.objects.create_user(
            username="editor_only",
            email="editor_only@example.com",
            password="VeryStrongPass123!",
            role=User.Role.ADMIN_UMUM,
        )
        ModuleAccess.objects.update_or_create(
            user=self.editor,
            module=ModuleAccess.Module.USERS,
            defaults={"scope": ModuleAccess.Scope.NONE},
        )
        self.target = User.objects.create_user(
            username="target_user",
            email="target_user@example.com",
            password="VeryStrongPass123!",
            role=User.Role.GUDANG,
        )

        self.view_perm = Permission.objects.get(
            content_type__app_label="users",
            codename="view_user",
        )
        self.add_perm = Permission.objects.get(
            content_type__app_label="users",
            codename="add_user",
        )
        self.change_perm = Permission.objects.get(
            content_type__app_label="users",
            codename="change_user",
        )

    def test_direct_django_view_permission_allows_user_list(self):
        self.viewer.user_permissions.add(self.view_perm)
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("users:user_list"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Manajemen Pengguna")

    def test_direct_django_change_permission_allows_user_edit(self):
        self.editor.user_permissions.add(self.change_perm)
        self.client.force_login(self.editor)

        response = self.client.get(
            reverse("users:user_update", args=[self.target.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Edit User {self.target.username}")

    def test_direct_django_add_permission_cannot_assign_custom_module_scopes(self):
        self.viewer.user_permissions.add(self.add_perm)
        self.client.force_login(self.viewer)

        payload = {
            "username": "limited_creator",
            "full_name": "Limited Creator",
            "nip": "197812312010011009",
            "email": "limited_creator@example.com",
            "role": User.Role.AUDITOR,
            "is_active": "on",
            "password1": "VeryStrongPass123!",
            "password2": "VeryStrongPass123!",
        }
        payload.update(
            {
                f"module_scope__{module_code}": str(ModuleAccess.Scope.MANAGE)
                for module_code, _ in ModuleAccess.Module.choices
            }
        )

        response = self.client.post(reverse("users:user_create"), payload, secure=True)

        self.assertEqual(response.status_code, 302)
        created = User.objects.get(username="limited_creator")
        self.assertEqual(
            ModuleAccess.objects.get(
                user=created,
                module=ModuleAccess.Module.USERS,
            ).scope,
            default_scope_for_role(User.Role.AUDITOR, ModuleAccess.Module.USERS),
        )

    def test_direct_django_change_permission_cannot_override_existing_module_scopes(self):
        self.editor.user_permissions.add(self.change_perm)
        self.client.force_login(self.editor)
        ModuleAccess.objects.update_or_create(
            user=self.target,
            module=ModuleAccess.Module.USERS,
            defaults={"scope": ModuleAccess.Scope.VIEW},
        )

        payload = {
            "username": self.target.username,
            "full_name": "Updated Target User",
            "nip": "",
            "email": self.target.email,
            "role": self.target.role,
            "is_active": "on",
        }
        payload.update(
            {
                f"module_scope__{module_code}": str(ModuleAccess.Scope.MANAGE)
                for module_code, _ in ModuleAccess.Module.choices
            }
        )

        response = self.client.post(
            reverse("users:user_update", args=[self.target.pk]),
            payload,
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.target.refresh_from_db()
        self.assertEqual(self.target.full_name, "Updated Target User")
        self.assertEqual(
            ModuleAccess.objects.get(
                user=self.target,
                module=ModuleAccess.Module.USERS,
            ).scope,
            ModuleAccess.Scope.VIEW,
        )

    def test_missing_view_access_raises_403_instead_of_redirect(self):
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("users:user_list"), secure=True)

        self.assertEqual(response.status_code, 403)
        self.assertContains(
            response,
            "Anda tidak memiliki izin untuk membuka manajemen user.",
            status_code=403,
        )

    def test_missing_add_access_raises_403_instead_of_redirect(self):
        self.viewer.user_permissions.add(self.view_perm)
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("users:user_create"), secure=True)

        self.assertEqual(response.status_code, 403)
        self.assertContains(
            response,
            "Anda tidak memiliki izin untuk menambah user.",
            status_code=403,
        )

    def test_missing_change_access_raises_403_for_password_reset(self):
        self.viewer.user_permissions.add(self.view_perm)
        self.client.force_login(self.viewer)

        response = self.client.post(
            reverse("users:user_reset_password", args=[self.target.pk]),
            {
                "password1": "BlockedReset123!",
                "password2": "BlockedReset123!",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 403)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password("VeryStrongPass123!"))
        self.assertContains(
            response,
            "Anda tidak memiliki izin untuk mereset password user.",
            status_code=403,
        )


class ProtectedUserManagementGuardsTest(TestCase):
    def setUp(self):
        self.super_admin = User.objects.create_superuser(
            username="super_admin",
            email="super_admin@example.com",
            password="VeryStrongPass123!",
        )
        self.manager_user = User.objects.create_user(
            username="user_manager",
            email="user_manager@example.com",
            password="VeryStrongPass123!",
            role=User.Role.GUDANG,
        )
        ModuleAccess.objects.update_or_create(
            user=self.manager_user,
            module=ModuleAccess.Module.USERS,
            defaults={"scope": ModuleAccess.Scope.MANAGE},
        )
        self.standard_user = User.objects.create_user(
            username="standard_user",
            email="standard_user@example.com",
            password="VeryStrongPass123!",
            role=User.Role.AUDITOR,
        )
        self.client.force_login(self.manager_user)

    def test_non_superuser_cannot_open_admin_edit_form(self):
        response = self.client.get(
            reverse("users:user_update", args=[self.super_admin.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 403)
        self.assertContains(
            response,
            "Akun admin hanya dapat dikelola oleh superuser.",
            status_code=403,
        )

    def test_non_superuser_cannot_reset_admin_password(self):
        response = self.client.post(
            reverse("users:user_reset_password", args=[self.super_admin.pk]),
            {
                "password1": "ResetBlocked123!",
                "password2": "ResetBlocked123!",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 403)
        self.super_admin.refresh_from_db()
        self.assertTrue(self.super_admin.check_password("VeryStrongPass123!"))
        self.assertContains(
            response,
            "Akun admin hanya dapat dikelola oleh superuser.",
            status_code=403,
        )

    def test_non_superuser_cannot_toggle_admin_active_status_via_ajax(self):
        response = self.client.post(
            reverse("users:user_toggle_active", args=[self.super_admin.pk]),
            secure=True,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 403)
        self.super_admin.refresh_from_db()
        self.assertTrue(self.super_admin.is_active)
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "error": "Akun admin hanya dapat dikelola oleh superuser.",
            },
        )

    def test_non_superuser_cannot_delete_admin_account(self):
        response = self.client.post(
            reverse("users:user_delete", args=[self.super_admin.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(User.objects.filter(pk=self.super_admin.pk).exists())
        self.assertContains(
            response,
            "Akun admin hanya dapat dikelola oleh superuser.",
            status_code=403,
        )

    def test_bulk_action_skips_admin_accounts_for_non_superuser_manager(self):
        response = self.client.post(
            reverse("users:user_bulk_action"),
            {
                "action": "deactivate",
                "selected_users": [self.super_admin.pk, self.standard_user.pk],
            },
            secure=True,
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.super_admin.refresh_from_db()
        self.standard_user.refresh_from_db()
        self.assertTrue(self.super_admin.is_active)
        self.assertFalse(self.standard_user.is_active)
        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertTrue(
            any(
                "1 akun admin dilewati karena hanya dapat dikelola oleh superuser."
                in message
                for message in messages
            )
        )

    def test_bulk_activate_skips_admin_accounts_for_non_superuser_manager(self):
        self.super_admin.is_active = False
        self.super_admin.save(update_fields=["is_active"])
        self.standard_user.is_active = False
        self.standard_user.save(update_fields=["is_active"])

        response = self.client.post(
            reverse("users:user_bulk_action"),
            {
                "action": "activate",
                "selected_users": [self.super_admin.pk, self.standard_user.pk],
            },
            secure=True,
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.super_admin.refresh_from_db()
        self.standard_user.refresh_from_db()
        self.assertFalse(self.super_admin.is_active)
        self.assertTrue(self.standard_user.is_active)
        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertTrue(
            any(
                "1 akun admin dilewati karena hanya dapat dikelola oleh superuser."
                in message
                for message in messages
            )
        )

    def test_bulk_delete_skips_admin_accounts_for_non_superuser_manager(self):
        self.super_admin.is_active = False
        self.super_admin.save(update_fields=["is_active"])
        self.standard_user.is_active = False
        self.standard_user.save(update_fields=["is_active"])

        response = self.client.post(
            reverse("users:user_bulk_action"),
            {
                "action": "delete",
                "selected_users": [self.super_admin.pk, self.standard_user.pk],
            },
            secure=True,
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(pk=self.super_admin.pk).exists())
        self.assertFalse(User.objects.filter(pk=self.standard_user.pk).exists())
        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertTrue(
            any(
                "1 akun admin dilewati karena hanya dapat dikelola oleh superuser."
                in message
                for message in messages
            )
        )
