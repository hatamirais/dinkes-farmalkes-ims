from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.decorators import module_scope_required, perm_required

from .access import (
    can_approve_workflow,
    ensure_default_module_access,
    get_delegated_signature,
    record_authority_exercise,
    resolve_approval_authority,
)
from .models import AuthorityDelegation, AuthorityExercise, ModuleAccess, User


class AuthorityDelegationTestMixin:
    def make_user(self, username, role):
        user = User.objects.create_user(
            username=username,
            password="TestPassword123!",
            role=role,
            full_name=username.replace("_", " ").title(),
            nip=f"NIP-{username}",
        )
        ensure_default_module_access(user, overwrite=True)
        return user

    def make_delegation(self, delegate, module=ModuleAccess.Module.DISTRIBUTION):
        now = timezone.now()
        return AuthorityDelegation.objects.create(
            module=module,
            delegate=delegate,
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(hours=8),
            reason="Kepala Instalasi sedang bertugas di luar kantor.",
            granted_by=self.kepala,
        )


class AuthorityDelegationPolicyTests(AuthorityDelegationTestMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.kepala = self.make_user("kepala_delegasi", User.Role.KEPALA)
        self.delegate = self.make_user("gudang_delegasi", User.Role.GUDANG)

    def test_active_delegation_passes_role_gated_workflow(self):
        self.make_delegation(self.delegate)

        self.assertTrue(
            can_approve_workflow(
                self.delegate,
                ModuleAccess.Module.DISTRIBUTION,
            )
        )
        decision = resolve_approval_authority(
            self.delegate,
            ModuleAccess.Module.DISTRIBUTION,
            role_gated=True,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.basis, "delegation")

    def test_until_revoked_delegation_is_active_until_revoked(self):
        delegation = self.make_delegation(self.delegate)
        delegation.ends_at = None
        delegation.save(update_fields=("ends_at",))

        self.assertTrue(
            can_approve_workflow(
                self.delegate,
                ModuleAccess.Module.DISTRIBUTION,
            )
        )
        decision = resolve_approval_authority(
            self.delegate,
            ModuleAccess.Module.DISTRIBUTION,
            role_gated=True,
        )
        exercise = record_authority_exercise(
            decision,
            actor=self.delegate,
            module=ModuleAccess.Module.DISTRIBUTION,
            action="verify",
            target=self.kepala,
        )
        self.assertIsNone(exercise.delegation_ends_at_snapshot)

        delegation.revoked_at = timezone.now()
        delegation.revoked_by = self.kepala
        delegation.revocation_reason = "Penugasan telah berakhir."
        delegation.save(
            update_fields=("revoked_at", "revoked_by", "revocation_reason")
        )
        self.assertFalse(
            can_approve_workflow(
                self.delegate,
                ModuleAccess.Module.DISTRIBUTION,
            )
        )

    def test_expired_revoked_or_scope_removed_delegation_is_denied(self):
        delegation = self.make_delegation(self.delegate)
        delegation.ends_at = timezone.now() - timedelta(minutes=1)
        delegation.starts_at = delegation.ends_at - timedelta(hours=1)
        delegation.save(update_fields=("starts_at", "ends_at"))
        self.assertFalse(
            can_approve_workflow(
                self.delegate,
                ModuleAccess.Module.DISTRIBUTION,
            )
        )

        delegation.starts_at = timezone.now() - timedelta(hours=1)
        delegation.ends_at = timezone.now() + timedelta(hours=1)
        delegation.revoked_at = timezone.now()
        delegation.revoked_by = self.kepala
        delegation.save(
            update_fields=("starts_at", "ends_at", "revoked_at", "revoked_by")
        )
        self.assertFalse(
            can_approve_workflow(
                self.delegate,
                ModuleAccess.Module.DISTRIBUTION,
            )
        )

        delegation.revoked_at = None
        delegation.revoked_by = None
        delegation.save(update_fields=("revoked_at", "revoked_by"))
        ModuleAccess.objects.update_or_create(
            user=self.delegate,
            module=ModuleAccess.Module.DISTRIBUTION,
            defaults={"scope": ModuleAccess.Scope.NONE},
        )
        self.assertFalse(
            can_approve_workflow(
                self.delegate,
                ModuleAccess.Module.DISTRIBUTION,
            )
        )

    def test_existing_approval_decorator_chain_accepts_only_active_delegation(self):
        @perm_required("distribution.change_distribution")
        @module_scope_required(
            ModuleAccess.Module.DISTRIBUTION,
            ModuleAccess.Scope.APPROVE,
        )
        def approval_view(request):
            return HttpResponse("ok")

        request = self.factory.post("/test/")
        request.user = self.delegate
        with self.assertRaises(PermissionDenied):
            approval_view(request)

        self.make_delegation(self.delegate)
        response = approval_view(request)
        self.assertEqual(response.status_code, 200)

    def test_exercise_keeps_immutable_signature_snapshot(self):
        self.make_delegation(self.delegate)
        decision = resolve_approval_authority(
            self.delegate,
            ModuleAccess.Module.DISTRIBUTION,
            role_gated=True,
        )
        exercise = record_authority_exercise(
            decision,
            actor=self.delegate,
            module=ModuleAccess.Module.DISTRIBUTION,
            action="verify",
            target=self.kepala,
        )
        self.delegate.full_name = "Nama Berubah"
        self.delegate.nip = "NIP-BARU"
        self.delegate.save(update_fields=("full_name", "nip"))

        signature = get_delegated_signature(self.kepala, action="verify")
        self.assertEqual(signature["name"], exercise.actor_name_snapshot)
        self.assertEqual(signature["nip"], exercise.actor_nip_snapshot)
        self.assertEqual(signature["title"], "Plh. Kepala Instalasi")


class AuthorityDelegationViewTests(AuthorityDelegationTestMixin, TestCase):
    def setUp(self):
        self.kepala = self.make_user("kepala_view", User.Role.KEPALA)
        self.delegate = self.make_user("gudang_view", User.Role.GUDANG)
        self.admin_umum = self.make_user("admin_umum_view", User.Role.ADMIN_UMUM)

    def test_only_admin_or_kepala_can_open_delegation_management(self):
        self.client.force_login(self.kepala)
        response = self.client.get(reverse("users:authority_delegation_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Delegasi Wewenang")

        self.client.force_login(self.admin_umum)
        response = self.client.get(reverse("users:authority_delegation_list"))
        self.assertEqual(response.status_code, 403)

    def test_create_form_places_duration_before_dates_and_toggles_end_field(self):
        self.client.force_login(self.kepala)

        response = self.client.get(reverse("users:authority_delegation_create"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertLess(
            content.index('name="duration_mode"'),
            content.index('id="id_starts_at"'),
        )
        self.assertLess(
            content.index('id="id_starts_at"'),
            content.index('id="id_ends_at"'),
        )
        self.assertEqual(content.count('data-datetime-picker="24h"'), 2)
        self.assertContains(response, "/static/vendor/flatpickr/flatpickr.min.css")
        self.assertContains(response, "/static/vendor/flatpickr/flatpickr.min.js")
        self.assertContains(response, "/static/vendor/flatpickr/l10n/id.js")
        self.assertContains(response, "/static/js/authority-delegation-form.js")

    def test_create_and_revoke_delegation(self):
        self.client.force_login(self.kepala)
        starts_at = timezone.localtime(timezone.now() + timedelta(hours=1))
        ends_at = starts_at + timedelta(days=1)
        response = self.client.post(
            reverse("users:authority_delegation_create"),
            {
                "delegate": self.delegate.pk,
                "modules": [
                    ModuleAccess.Module.DISTRIBUTION,
                    ModuleAccess.Module.EXPIRED,
                ],
                "starts_at": starts_at.strftime("%Y-%m-%dT%H:%M"),
                "duration_mode": "FIXED",
                "ends_at": ends_at.strftime("%Y-%m-%dT%H:%M"),
                "reason": "Penugasan resmi selama Kepala berada di luar kantor.",
            },
        )
        self.assertRedirects(response, reverse("users:authority_delegation_list"))
        self.assertEqual(
            AuthorityDelegation.objects.filter(delegate=self.delegate).count(),
            2,
        )

        delegation = AuthorityDelegation.objects.get(
            delegate=self.delegate,
            module=ModuleAccess.Module.DISTRIBUTION,
        )
        response = self.client.post(
            reverse("users:authority_delegation_revoke", args=[delegation.pk]),
            {"revocation_reason": "Kepala sudah kembali bertugas."},
        )
        self.assertRedirects(response, reverse("users:authority_delegation_list"))
        delegation.refresh_from_db()
        self.assertIsNotNone(delegation.revoked_at)
        self.assertEqual(delegation.revoked_by, self.kepala)

    def test_create_until_revoked_delegation_without_end_datetime(self):
        self.client.force_login(self.kepala)
        starts_at = timezone.localtime(timezone.now() + timedelta(hours=1))

        response = self.client.post(
            reverse("users:authority_delegation_create"),
            {
                "delegate": self.delegate.pk,
                "modules": [ModuleAccess.Module.DISTRIBUTION],
                "starts_at": starts_at.strftime("%Y-%m-%dT%H:%M"),
                "duration_mode": "UNTIL_REVOKED",
                "ends_at": "nilai-lama-yang-diabaikan",
                "reason": "Penugasan berlaku sampai dicabut secara resmi.",
            },
        )

        self.assertRedirects(response, reverse("users:authority_delegation_list"))
        delegation = AuthorityDelegation.objects.get(delegate=self.delegate)
        self.assertIsNone(delegation.ends_at)

        response = self.client.get(reverse("users:authority_delegation_list"))
        self.assertContains(response, "Berlaku sampai dicabut")
        self.assertContains(
            response,
            reverse("users:authority_delegation_revoke", args=[delegation.pk]),
        )

    def test_fixed_duration_requires_end_datetime(self):
        self.client.force_login(self.kepala)
        starts_at = timezone.localtime(timezone.now() + timedelta(hours=1))

        response = self.client.post(
            reverse("users:authority_delegation_create"),
            {
                "delegate": self.delegate.pk,
                "modules": [ModuleAccess.Module.DISTRIBUTION],
                "starts_at": starts_at.strftime("%Y-%m-%dT%H:%M"),
                "duration_mode": "FIXED",
                "ends_at": "",
                "reason": "Penugasan dengan periode tertentu.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Waktu berakhir wajib diisi untuk durasi tertentu.",
        )
        self.assertFalse(
            AuthorityDelegation.objects.filter(delegate=self.delegate).exists()
        )


class AuthorityDelegationConstraintTests(
    AuthorityDelegationTestMixin,
    TransactionTestCase,
):
    reset_sequences = True

    def setUp(self):
        self.kepala = self.make_user("kepala_constraint", User.Role.KEPALA)
        self.delegate = self.make_user("gudang_constraint", User.Role.GUDANG)

    def test_overlapping_non_revoked_delegations_are_rejected_by_database(self):
        first = self.make_delegation(self.delegate)
        other_delegate = self.make_user("admin_umum_constraint", User.Role.ADMIN_UMUM)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AuthorityDelegation.objects.create(
                    module=ModuleAccess.Module.DISTRIBUTION,
                    delegate=other_delegate,
                    starts_at=first.starts_at + timedelta(minutes=10),
                    ends_at=first.ends_at - timedelta(minutes=10),
                    reason="Delegasi tumpang tindih yang harus ditolak.",
                    granted_by=self.kepala,
                )

    def test_adjacent_delegation_is_allowed(self):
        first = self.make_delegation(self.delegate)
        other_delegate = self.make_user("admin_umum_adjacent", User.Role.ADMIN_UMUM)
        second = AuthorityDelegation.objects.create(
            module=ModuleAccess.Module.DISTRIBUTION,
            delegate=other_delegate,
            starts_at=first.ends_at,
            ends_at=first.ends_at + timedelta(hours=2),
            reason="Delegasi pengganti setelah periode pertama berakhir.",
            granted_by=self.kepala,
        )
        self.assertIsNotNone(second.pk)

    def test_until_revoked_delegation_blocks_any_later_non_revoked_delegation(self):
        first = self.make_delegation(self.delegate)
        first.ends_at = None
        first.save(update_fields=("ends_at",))
        other_delegate = self.make_user(
            "admin_umum_open_ended",
            User.Role.ADMIN_UMUM,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AuthorityDelegation.objects.create(
                    module=ModuleAccess.Module.DISTRIBUTION,
                    delegate=other_delegate,
                    starts_at=timezone.now() + timedelta(days=30),
                    ends_at=timezone.now() + timedelta(days=31),
                    reason="Delegasi yang harus diblokir oleh periode terbuka.",
                    granted_by=self.kepala,
                )

    def test_fixed_delegation_still_requires_end_after_start_at_database(self):
        starts_at = timezone.now() + timedelta(hours=2)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AuthorityDelegation.objects.create(
                    module=ModuleAccess.Module.DISTRIBUTION,
                    delegate=self.delegate,
                    starts_at=starts_at,
                    ends_at=starts_at,
                    reason="Periode tetap yang tidak valid.",
                    granted_by=self.kepala,
                )

    def test_new_delegation_is_allowed_after_open_ended_delegation_is_revoked(self):
        first = self.make_delegation(self.delegate)
        first.ends_at = None
        first.revoked_at = timezone.now()
        first.revoked_by = self.kepala
        first.revocation_reason = "Diganti dengan pelaksana baru."
        first.save(
            update_fields=(
                "ends_at",
                "revoked_at",
                "revoked_by",
                "revocation_reason",
            )
        )
        other_delegate = self.make_user(
            "admin_umum_after_revoke",
            User.Role.ADMIN_UMUM,
        )

        replacement = AuthorityDelegation.objects.create(
            module=ModuleAccess.Module.DISTRIBUTION,
            delegate=other_delegate,
            starts_at=timezone.now(),
            ends_at=None,
            reason="Pelaksana pengganti berlaku sampai dicabut.",
            granted_by=self.kepala,
        )

        self.assertIsNotNone(replacement.pk)

