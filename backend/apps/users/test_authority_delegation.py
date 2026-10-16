import time
from datetime import date, timedelta
from threading import Event, Thread
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, transaction
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.decorators import module_scope_required, perm_required
from apps.distribution.models import Distribution
from apps.items.models import Facility

from . import views as user_views
from .access import (
    can_approve_workflow,
    ensure_default_module_access,
    get_delegated_signature,
    record_authority_exercise,
    resolve_approval_authority,
)
from .forms import AuthorityDelegationCreateForm
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

    def test_puskesmas_role_cannot_resolve_manually_created_delegation(self):
        facility = Facility.objects.create(code="PKM-DELEG", name="Puskesmas Delegasi")
        puskesmas_user = self.make_user("puskesmas_delegate", User.Role.PUSKESMAS)
        puskesmas_user.facility = facility
        puskesmas_user.save(update_fields=("facility",))
        self.make_delegation(puskesmas_user)

        decision = resolve_approval_authority(
            puskesmas_user,
            ModuleAccess.Module.DISTRIBUTION,
            role_gated=True,
        )

        self.assertFalse(decision.allowed)

    def test_exercised_workflow_target_cannot_be_hard_deleted(self):
        self.make_delegation(self.delegate)
        facility = Facility.objects.create(code="PKM-PROTECT", name="Puskesmas Protect")
        decision = resolve_approval_authority(
            self.delegate,
            ModuleAccess.Module.DISTRIBUTION,
            role_gated=True,
        )
        target = Distribution.objects.create(
            distribution_type=Distribution.DistributionType.SPECIAL_REQUEST,
            facility=facility,
            request_date=date(2026, 10, 13),
            created_by=self.delegate,
        )
        record_authority_exercise(
            decision,
            actor=self.delegate,
            module=ModuleAccess.Module.DISTRIBUTION,
            action="verify",
            target=target,
        )

        with self.assertRaises(ProtectedError):
            with transaction.atomic():
                target.delete()
        self.assertTrue(Distribution.objects.filter(pk=target.pk).exists())

        with self.assertRaises(ProtectedError):
            with transaction.atomic():
                Distribution.objects.filter(pk=target.pk).delete()
        self.assertTrue(Distribution.objects.filter(pk=target.pk).exists())

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

        signature = get_delegated_signature(
            self.kepala,
            action="verify",
            actor=self.delegate,
            exercised_at=exercise.exercised_at,
        )
        self.assertEqual(signature["name"], exercise.actor_name_snapshot)
        self.assertEqual(signature["nip"], exercise.actor_nip_snapshot)
        self.assertEqual(signature["title"], "Plh. Kepala Instalasi")

        self.assertIsNone(
            get_delegated_signature(
                self.kepala,
                action="verify",
                actor=self.kepala,
                exercised_at=exercise.exercised_at,
            )
        )
        self.assertIsNone(
            get_delegated_signature(
                self.kepala,
                action="verify",
                actor=self.delegate,
                exercised_at=exercise.exercised_at + timedelta(seconds=1),
            )
        )


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

    def test_puskesmas_user_is_not_offered_as_delegate(self):
        facility = Facility.objects.create(code="PKM-CHOICE", name="Puskesmas Choice")
        puskesmas_user = self.make_user("puskesmas_choice", User.Role.PUSKESMAS)
        puskesmas_user.facility = facility
        puskesmas_user.save(update_fields=("facility",))
        self.client.force_login(self.kepala)

        response = self.client.get(reverse("users:authority_delegation_create"))

        self.assertEqual(response.status_code, 200)
        delegate_queryset = response.context["form"].fields["delegate"].queryset
        self.assertFalse(delegate_queryset.filter(pk=puskesmas_user.pk).exists())
        self.assertTrue(delegate_queryset.filter(pk=self.delegate.pk).exists())

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

    def test_create_revalidates_eligibility_after_initial_form_validation(self):
        cases = (
            "grantor_scope_removed",
            "delegate_deactivated",
            "delegate_role_changed",
            "delegate_scope_removed",
            "delegate_facility_removed",
            "delegate_facility_type_changed",
        )

        for index, case in enumerate(cases):
            with self.subTest(case=case):
                kepala = self.make_user(
                    f"kepala_create_race_{index}",
                    User.Role.KEPALA,
                )
                delegate = self.make_user(
                    f"gudang_create_race_{index}",
                    User.Role.GUDANG,
                )
                module = ModuleAccess.Module.DISTRIBUTION
                if case in {
                    "delegate_facility_removed",
                    "delegate_facility_type_changed",
                }:
                    module = ModuleAccess.Module.PUSKESMAS
                    delegate.facility = Facility.objects.create(
                        code=f"PKM-RACE-{index}",
                        name=f"Puskesmas Race {index}",
                    )
                    delegate.save(update_fields=("facility",))

                starts_at = timezone.localtime(timezone.now() + timedelta(hours=1))
                form = AuthorityDelegationCreateForm(
                    {
                        "delegate": delegate.pk,
                        "modules": [module],
                        "starts_at": starts_at.strftime("%Y-%m-%dT%H:%M"),
                        "duration_mode": "FIXED",
                        "ends_at": (starts_at + timedelta(hours=1)).strftime(
                            "%Y-%m-%dT%H:%M"
                        ),
                        "reason": "Validasi ulang sebelum delegasi disimpan.",
                    },
                    actor=kepala,
                )
                self.assertTrue(form.is_valid(), form.errors)

                if case == "grantor_scope_removed":
                    ModuleAccess.objects.filter(user=kepala, module=module).update(
                        scope=ModuleAccess.Scope.OPERATE
                    )
                elif case == "delegate_deactivated":
                    User.objects.filter(pk=delegate.pk).update(is_active=False)
                elif case == "delegate_role_changed":
                    User.objects.filter(pk=delegate.pk).update(role=User.Role.AUDITOR)
                elif case == "delegate_scope_removed":
                    ModuleAccess.objects.filter(user=delegate, module=module).update(
                        scope=ModuleAccess.Scope.NONE
                    )
                elif case == "delegate_facility_removed":
                    User.objects.filter(pk=delegate.pk).update(facility=None)
                else:
                    Facility.objects.filter(pk=delegate.facility_id).update(
                        facility_type=Facility.FacilityType.RS
                    )

                with self.assertRaises(ValidationError):
                    with transaction.atomic():
                        form.save()

                self.assertFalse(
                    AuthorityDelegation.objects.filter(granted_by=kepala).exists()
                )

    def test_create_renders_save_time_eligibility_error(self):
        self.client.force_login(self.kepala)
        starts_at = timezone.localtime(timezone.now() + timedelta(hours=1))
        original_save = AuthorityDelegationCreateForm.save

        def deactivate_delegate_then_save(form):
            User.objects.filter(pk=form.cleaned_data["delegate"].pk).update(
                is_active=False
            )
            return original_save(form)

        with patch.object(
            AuthorityDelegationCreateForm,
            "save",
            autospec=True,
            side_effect=deactivate_delegate_then_save,
        ):
            response = self.client.post(
                reverse("users:authority_delegation_create"),
                {
                    "delegate": self.delegate.pk,
                    "modules": [ModuleAccess.Module.DISTRIBUTION],
                    "starts_at": starts_at.strftime("%Y-%m-%dT%H:%M"),
                    "duration_mode": "FIXED",
                    "ends_at": (starts_at + timedelta(hours=1)).strftime(
                        "%Y-%m-%dT%H:%M"
                    ),
                    "reason": "Delegasi yang berubah sebelum disimpan.",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Pelaksana Harian harus merupakan Admin Umum atau Petugas Gudang "
            "yang masih aktif.",
        )
        self.assertFalse(
            AuthorityDelegation.objects.filter(delegate=self.delegate).exists()
        )

    def test_kepala_cannot_revoke_module_after_approval_scope_is_removed(self):
        delegation = self.make_delegation(self.delegate)
        ModuleAccess.objects.update_or_create(
            user=self.kepala,
            module=ModuleAccess.Module.DISTRIBUTION,
            defaults={"scope": ModuleAccess.Scope.OPERATE},
        )
        revoke_url = reverse(
            "users:authority_delegation_revoke",
            args=[delegation.pk],
        )
        self.client.force_login(self.kepala)

        list_response = self.client.get(reverse("users:authority_delegation_list"))
        get_response = self.client.get(revoke_url)
        post_response = self.client.post(
            revoke_url,
            {"revocation_reason": "Tidak boleh tersimpan."},
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertNotContains(list_response, revoke_url)
        self.assertEqual(get_response.status_code, 403)
        self.assertEqual(post_response.status_code, 403)
        delegation.refresh_from_db()
        self.assertIsNone(delegation.revoked_at)
        self.assertIsNone(delegation.revoked_by)
        self.assertEqual(delegation.revocation_reason, "")

    def test_revoke_rechecks_module_authority_after_locking(self):
        delegation = self.make_delegation(self.delegate)
        self.client.force_login(self.kepala)

        with patch(
            "apps.users.views.can_delegate_module",
            side_effect=(True, False),
        ):
            response = self.client.post(
                reverse(
                    "users:authority_delegation_revoke",
                    args=[delegation.pk],
                ),
                {"revocation_reason": "Tidak boleh tersimpan."},
            )

        self.assertEqual(response.status_code, 403)
        delegation.refresh_from_db()
        self.assertIsNone(delegation.revoked_at)
        self.assertIsNone(delegation.revoked_by)
        self.assertEqual(delegation.revocation_reason, "")

    def test_revoke_reloads_actor_role_before_authorizing(self):
        delegation = self.make_delegation(self.delegate)
        self.client.force_login(self.kepala)
        original_check = user_views._require_authority_delegation_module_access
        check_count = 0

        def demote_after_initial_check(user, module):
            nonlocal check_count
            original_check(user, module)
            check_count += 1
            if check_count == 1:
                User.objects.filter(pk=self.kepala.pk).update(role=User.Role.GUDANG)

        with patch(
            "apps.users.views._require_authority_delegation_module_access",
            side_effect=demote_after_initial_check,
        ):
            response = self.client.post(
                reverse(
                    "users:authority_delegation_revoke",
                    args=[delegation.pk],
                ),
                {"revocation_reason": "Tidak boleh tersimpan."},
            )

        self.assertEqual(response.status_code, 403)
        delegation.refresh_from_db()
        self.assertIsNone(delegation.revoked_at)
        self.assertIsNone(delegation.revoked_by)
        self.assertEqual(delegation.revocation_reason, "")

    def test_facility_bound_delegation_rejects_non_puskesmas_facility(self):
        self.delegate.facility = Facility.objects.create(
            code="RS-DELEGATE",
            name="Rumah Sakit Delegate",
            facility_type=Facility.FacilityType.RS,
        )
        self.delegate.save(update_fields=("facility",))
        starts_at = timezone.localtime(timezone.now() + timedelta(hours=1))
        form = AuthorityDelegationCreateForm(
            {
                "delegate": self.delegate.pk,
                "modules": [ModuleAccess.Module.PUSKESMAS],
                "starts_at": starts_at.strftime("%Y-%m-%dT%H:%M"),
                "duration_mode": "FIXED",
                "ends_at": (starts_at + timedelta(hours=1)).strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "reason": "Fasilitas yang salah harus ditolak.",
            },
            actor=self.kepala,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("delegate", form.errors)
        self.assertIn("fasilitas Puskesmas", form.errors["delegate"][0])

    def test_expired_delegation_cannot_be_rewritten_as_revoked(self):
        delegation = self.make_delegation(self.delegate)
        delegation.starts_at = timezone.now() - timedelta(hours=2)
        delegation.ends_at = timezone.now() - timedelta(hours=1)
        delegation.save(update_fields=("starts_at", "ends_at"))
        self.client.force_login(self.kepala)

        response = self.client.post(
            reverse("users:authority_delegation_revoke", args=[delegation.pk]),
            {"revocation_reason": "Alasan yang tidak boleh tersimpan."},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        delegation.refresh_from_db()
        self.assertIsNone(delegation.revoked_at)
        self.assertIsNone(delegation.revoked_by)
        self.assertEqual(delegation.revocation_reason, "")
        self.assertContains(
            response,
            "Delegasi ini sudah berakhir dan tidak dapat dicabut.",
        )
        self.assertContains(response, "Berakhir")
        self.assertNotContains(response, "Alasan yang tidak boleh tersimpan.")

    def test_delegation_ending_at_locked_decision_time_cannot_be_revoked(self):
        delegation = self.make_delegation(self.delegate)
        decision_at = timezone.now()
        delegation.starts_at = decision_at - timedelta(hours=1)
        delegation.ends_at = decision_at
        delegation.save(update_fields=("starts_at", "ends_at"))
        self.client.force_login(self.kepala)

        with patch("apps.users.views.timezone.now", return_value=decision_at):
            response = self.client.post(
                reverse("users:authority_delegation_revoke", args=[delegation.pk]),
                {"revocation_reason": "Batas waktu sudah tercapai."},
            )

        self.assertRedirects(response, reverse("users:authority_delegation_list"))
        delegation.refresh_from_db()
        self.assertIsNone(delegation.revoked_at)
        self.assertIsNone(delegation.revoked_by)
        self.assertEqual(delegation.revocation_reason, "")

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


class AuthorityDelegationLockingTests(
    AuthorityDelegationTestMixin,
    TransactionTestCase,
):
    def setUp(self):
        self.kepala = self.make_user("kepala_locking", User.Role.KEPALA)
        self.delegate = self.make_user("gudang_locking", User.Role.GUDANG)

    def test_locked_resolution_reloads_delegate_role(self):
        self.make_delegation(self.delegate)
        stale_delegate = User.objects.get(pk=self.delegate.pk)
        User.objects.filter(pk=self.delegate.pk).update(role=User.Role.AUDITOR)

        with transaction.atomic():
            decision = resolve_approval_authority(
                stale_delegate,
                ModuleAccess.Module.DISTRIBUTION,
                role_gated=True,
                for_update=True,
            )

        self.assertFalse(decision.allowed)

    def test_facility_bound_resolution_rechecks_active_puskesmas_link(self):
        facility = Facility.objects.create(
            code="PKM-RESOLVE",
            name="Puskesmas Resolve",
        )
        self.delegate.facility = facility
        self.delegate.save(update_fields=("facility",))
        self.make_delegation(self.delegate, module=ModuleAccess.Module.PUSKESMAS)
        self.make_delegation(self.delegate, module=ModuleAccess.Module.LPLPO)

        for changes in (
            {"is_active": False},
            {"is_active": True, "facility_type": Facility.FacilityType.RS},
        ):
            with self.subTest(changes=changes):
                Facility.objects.filter(pk=facility.pk).update(**changes)
                for module in (
                    ModuleAccess.Module.PUSKESMAS,
                    ModuleAccess.Module.LPLPO,
                ):
                    self.assertFalse(
                        resolve_approval_authority(
                            self.delegate,
                            module,
                            role_gated=True,
                        ).allowed
                    )
                    with transaction.atomic():
                        decision = resolve_approval_authority(
                            self.delegate,
                            module,
                            role_gated=True,
                            for_update=True,
                        )
                    self.assertFalse(decision.allowed)

    def test_locked_exercise_snapshots_reloaded_actor_profile(self):
        self.make_delegation(self.delegate)
        stale_actor = User.objects.get(pk=self.delegate.pk)
        User.objects.filter(pk=self.delegate.pk).update(
            full_name="Nama Terkini",
            nip="NIP-TERKINI",
        )

        with transaction.atomic():
            decision = resolve_approval_authority(
                stale_actor,
                ModuleAccess.Module.DISTRIBUTION,
                role_gated=True,
                for_update=True,
            )
            self.assertTrue(decision.allowed)
            exercise = record_authority_exercise(
                decision,
                actor=stale_actor,
                module=ModuleAccess.Module.DISTRIBUTION,
                action="verify",
                target=self.kepala,
            )

        self.assertEqual(exercise.actor_name_snapshot, "Nama Terkini")
        self.assertEqual(exercise.actor_nip_snapshot, "NIP-TERKINI")
        self.assertEqual(exercise.actor_id, decision.actor.pk)

    def test_locked_resolution_rechecks_time_after_waiting_for_delegation(self):
        delegation = self.make_delegation(self.delegate)
        delegation.ends_at = timezone.now() + timedelta(seconds=2)
        delegation.save(update_fields=("ends_at",))
        lock_acquired = Event()
        release_lock = Event()
        resolver_started = Event()
        result = {}
        errors = []

        def hold_delegation_lock():
            close_old_connections()
            try:
                with transaction.atomic():
                    AuthorityDelegation.objects.select_for_update().get(
                        pk=delegation.pk
                    )
                    lock_acquired.set()
                    if not release_lock.wait(timeout=10):
                        raise TimeoutError("Timed out waiting to release delegation lock.")
            except Exception as exc:  # pragma: no cover - reported in main thread
                errors.append(exc)
                lock_acquired.set()
            finally:
                close_old_connections()

        def resolve_while_locked():
            close_old_connections()
            try:
                delegate = User.objects.get(pk=self.delegate.pk)
                resolver_started.set()
                with transaction.atomic():
                    result["decision"] = resolve_approval_authority(
                        delegate,
                        ModuleAccess.Module.DISTRIBUTION,
                        role_gated=True,
                        for_update=True,
                    )
            except Exception as exc:  # pragma: no cover - reported in main thread
                errors.append(exc)
            finally:
                close_old_connections()

        locker = Thread(target=hold_delegation_lock)
        resolver = Thread(target=resolve_while_locked)
        locker.start()
        self.assertTrue(lock_acquired.wait(timeout=5))
        resolver.start()
        self.assertTrue(resolver_started.wait(timeout=5))
        time.sleep(0.25)
        self.assertTrue(resolver.is_alive())
        remaining = (delegation.ends_at - timezone.now()).total_seconds()
        if remaining > 0:
            time.sleep(remaining + 0.2)
        release_lock.set()
        locker.join(timeout=5)
        resolver.join(timeout=5)

        self.assertFalse(locker.is_alive())
        self.assertFalse(resolver.is_alive())
        self.assertEqual(errors, [])
        self.assertIn("decision", result)
        self.assertFalse(result["decision"].allowed)

