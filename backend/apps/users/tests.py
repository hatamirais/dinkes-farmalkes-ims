from django.test import TestCase
from django.urls import reverse

from apps.users.access import ensure_default_module_access
from apps.users.models import ModuleAccess, User


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
        self.assertEqual(response.status_code, 302)

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
        self.assertEqual(edit_response.status_code, 302)
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
        self.assertTrue(created.check_password("VeryStrongPass123!"))

    def test_dashboard_blocks_admin_role_creation(self):
        """ADMIN role cannot be created from the Dashboard — only via CLI."""
        payload = {
            "username": "sneaky_admin",
            "full_name": "Sneaky Admin",
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
        self.assertEqual(self.target.email, "updated@example.com")
        self.assertEqual(self.target.role, User.Role.ADMIN_UMUM)

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


class StaffFlagSyncTest(TestCase):
    """Verify that is_staff is synced correctly based on role via the post_save signal."""

    def test_admin_role_gets_is_staff_true(self):
        """Dashboard-created ADMIN user must have is_staff=True for Admin panel access."""
        user = User.objects.create_user(
            username="new_admin",
            password="VeryStrongPass123!",
            role=User.Role.ADMIN,
        )
        user.refresh_from_db()
        self.assertTrue(user.is_staff, "ADMIN role user should have is_staff=True")

    def test_non_admin_role_does_not_get_is_staff(self):
        """Non-ADMIN roles should never get is_staff=True through the signal."""
        for role in [User.Role.KEPALA, User.Role.ADMIN_UMUM, User.Role.GUDANG, User.Role.AUDITOR]:
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

    def test_changing_role_to_admin_grants_is_staff(self):
        """Promoting an existing user to ADMIN should flip is_staff to True."""
        user = User.objects.create_user(
            username="promoted_user",
            password="VeryStrongPass123!",
            role=User.Role.GUDANG,
        )
        user.refresh_from_db()
        self.assertFalse(user.is_staff)

        # Promote to ADMIN
        user.role = User.Role.ADMIN
        user.save(update_fields=["role"])
        user.refresh_from_db()
        self.assertTrue(user.is_staff, "Promoted ADMIN user should have is_staff=True")

    def test_demoting_admin_removes_is_staff(self):
        """Demoting an ADMIN to another role should flip is_staff back to False."""
        user = User.objects.create_user(
            username="demoted_admin",
            password="VeryStrongPass123!",
            role=User.Role.ADMIN,
        )
        user.refresh_from_db()
        self.assertTrue(user.is_staff)

        # Demote to GUDANG
        user.role = User.Role.GUDANG
        user.save(update_fields=["role"])
        user.refresh_from_db()
        self.assertFalse(user.is_staff, "Demoted user should lose is_staff")

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
