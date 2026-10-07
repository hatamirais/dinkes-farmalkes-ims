from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import date
from importlib import import_module
from io import StringIO
from types import SimpleNamespace

from django.apps import apps as django_apps
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, connections, transaction
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature

from apps.allocation.models import Allocation
from apps.core.forms import DocumentNumberRuleForm
from apps.core.models import (
    DocumentNumberIssue,
    DocumentNumberRule,
    DocumentNumberSequence,
)
from apps.core.numbering import (
    DocumentNumberingError,
    issue_document_number,
    preview_document_number,
    render_document_number,
    void_document_number,
)
from apps.distribution.models import Distribution
from apps.items.models import Facility
from apps.users.models import User


def _ensure_rule(key, label, template, reset_period, padding):
    return DocumentNumberRule.objects.get_or_create(
        key=key,
        defaults={
            "label": label,
            "template": template,
            "reset_period": reset_period,
            "padding": padding,
        },
    )[0]


class DocumentNumberRuleValidationTests(TestCase):
    def test_rejects_unknown_or_missing_tokens(self):
        rule = DocumentNumberRule(
            key=DocumentNumberRule.Key.ALLOCATION,
            label="Alokasi",
            template="ALK-{unknown}",
            reset_period=DocumentNumberRule.ResetPeriod.YEARLY,
            padding=4,
        )
        with self.assertRaises(ValidationError):
            rule.full_clean()

    def test_monthly_rule_requires_year_and_month(self):
        rule = _ensure_rule(
            DocumentNumberRule.Key.RECALL,
            "Recall",
            "REC-{year}{month}-{seq}",
            DocumentNumberRule.ResetPeriod.MONTHLY,
            5,
        )
        rule.template = "REC-{year}-{seq}"
        with self.assertRaises(ValidationError):
            rule.full_clean()

    def test_parent_placeholder_is_not_supported(self):
        rule = DocumentNumberRule(
            key=DocumentNumberRule.Key.PROCUREMENT_AMENDMENT,
            label="Amandemen SPJ",
            template="{parent}-A{seq}",
            reset_period=DocumentNumberRule.ResetPeriod.NEVER,
            padding=1,
        )

        with self.assertRaisesMessage(
            ValidationError,
            "Placeholder tidak didukung: parent.",
        ):
            rule.full_clean()

    def test_template_reserves_space_for_maximum_sequence_width(self):
        rule = DocumentNumberRule.objects.get(
            key=DocumentNumberRule.Key.PROCUREMENT_AMENDMENT,
        )
        rule.template = ("X" * 81) + "{seq}"
        rule.reset_period = DocumentNumberRule.ResetPeriod.NEVER
        rule.padding = 1
        rule.full_clean()
        rendered = render_document_number(
            rule,
            9223372036854775807,
            date(2026, 1, 1),
        )
        self.assertEqual(len(rendered), 100)

        rule.template = ("X" * 82) + "{seq}"
        with self.assertRaisesMessage(
            ValidationError,
            "Hasil template pada urutan maksimum melebihi batas 100 karakter.",
        ):
            rule.full_clean()

    def test_rule_form_rejects_template_that_only_fits_at_minimum_padding(self):
        rule = DocumentNumberRule.objects.get(
            key=DocumentNumberRule.Key.PROCUREMENT_AMENDMENT,
        )
        form = DocumentNumberRuleForm(
            data={
                "template": ("X" * 99) + "{seq}",
                "reset_period": DocumentNumberRule.ResetPeriod.NEVER,
                "padding": 1,
            },
            instance=rule,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("urutan maksimum", str(form.errors))

    def test_migration_repairs_only_invalid_legacy_distribution_templates(self):
        lplpo_rule = DocumentNumberRule.objects.get(
            key=DocumentNumberRule.Key.DISTRIBUTION_LPLPO,
        )
        special_rule = DocumentNumberRule.objects.get(
            key=DocumentNumberRule.Key.DISTRIBUTION_SPECIAL_REQUEST,
        )
        lplpo_rule.template = "CUSTOM/{year}/{seq}"
        lplpo_rule.save(update_fields=["template", "updated_at"])
        special_rule.template = ("X" * 82) + "{year}{seq}"
        special_rule.save(update_fields=["template", "updated_at"])

        migration = import_module(
            "apps.core.migrations.0013_repair_legacy_templates_and_audit_global_numbers"
        )
        migration.repair_legacy_templates_and_audit_global_numbers(
            django_apps,
            SimpleNamespace(connection=connection),
        )

        lplpo_rule.refresh_from_db()
        special_rule.refresh_from_db()
        self.assertEqual(lplpo_rule.template, "CUSTOM/{year}/{seq}")
        self.assertEqual(special_rule.template, "440/{seq}/KD.F/{year}")
        special_rule.full_clean()

    def test_migration_marks_legacy_cross_rule_duplicates_without_renumbering(self):
        allocation_content_type = ContentType.objects.get_for_model(Allocation)
        allocation_rule = DocumentNumberRule.objects.get(
            key=DocumentNumberRule.Key.ALLOCATION
        )
        recall_rule = DocumentNumberRule.objects.get(key=DocumentNumberRule.Key.RECALL)
        common = {
            "document_number": "LEGACY-CROSS-RULE-001",
            "sequence_value": 1,
            "period_key": "2026",
            "scope_key": "",
            "business_date": date(2026, 1, 1),
            "rule_label_snapshot": "Legacy",
            "template_snapshot": "LEGACY-{seq}",
            "reset_period_snapshot": "YEARLY",
            "padding_snapshot": 1,
            "is_legacy_duplicate": True,
        }
        first = DocumentNumberIssue.objects.create(
            rule=allocation_rule,
            content_type=allocation_content_type,
            object_id=990001,
            **common,
        )
        second = DocumentNumberIssue.objects.create(
            rule=recall_rule,
            content_type=allocation_content_type,
            object_id=990002,
            **common,
        )

        audit_migration = import_module(
            "apps.core.migrations.0013_repair_legacy_templates_and_audit_global_numbers"
        )
        audit_output = StringIO()
        with redirect_stdout(audit_output):
            audit_migration.repair_legacy_templates_and_audit_global_numbers(
                django_apps,
                SimpleNamespace(connection=connection),
            )
        self.assertIn("1 legacy duplicate group(s)", audit_output.getvalue())

        migration = import_module(
            "apps.core.migrations.0014_global_document_number_issue_uniqueness"
        )
        migration.mark_legacy_duplicate_numbers(
            django_apps,
            SimpleNamespace(connection=connection),
        )

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_legacy_duplicate)
        self.assertTrue(second.is_legacy_duplicate)
        self.assertEqual(first.document_number, "LEGACY-CROSS-RULE-001")
        self.assertEqual(second.document_number, "LEGACY-CROSS-RULE-001")

        with self.assertRaises(IntegrityError), transaction.atomic():
            DocumentNumberIssue.objects.create(
                rule=recall_rule,
                content_type=allocation_content_type,
                object_id=990003,
                **{**common, "is_legacy_duplicate": False},
            )


class DocumentNumberIssuanceTests(TestCase):
    def setUp(self):
        _ensure_rule(
            DocumentNumberRule.Key.ALLOCATION,
            "Alokasi",
            "ALK-{year}-{seq}",
            DocumentNumberRule.ResetPeriod.YEARLY,
            4,
        )
        self.user = User.objects.create_superuser(
            username="numbering-admin",
            password="StrongPass123!",
        )

    def _allocation(self, business_date):
        return Allocation.objects.create(
            allocation_date=business_date,
            created_by=self.user,
        )

    def test_draft_does_not_consume_number_and_business_year_controls_period(self):
        first = self._allocation(date(2025, 12, 31))
        second = self._allocation(date(2026, 1, 1))
        self.assertIsNone(first.document_number)
        self.assertEqual(DocumentNumberIssue.objects.count(), 0)

        first_issue = issue_document_number(
            DocumentNumberRule.Key.ALLOCATION,
            business_date=first.allocation_date,
            target=first,
            actor=self.user,
        )
        second_issue = issue_document_number(
            DocumentNumberRule.Key.ALLOCATION,
            business_date=second.allocation_date,
            target=second,
            actor=self.user,
        )

        self.assertEqual(first_issue.document_number, "ALK-2025-0001")
        self.assertEqual(second_issue.document_number, "ALK-2026-0001")
        self.assertIsNotNone(first_issue.issued_at)
        self.assertIsNotNone(second_issue.issued_at)

    def test_issue_is_idempotent_and_voided_number_is_not_reused(self):
        first = self._allocation(date(2026, 4, 1))
        first_issue = issue_document_number(
            DocumentNumberRule.Key.ALLOCATION,
            business_date=first.allocation_date,
            target=first,
            actor=self.user,
        )
        repeated = issue_document_number(
            DocumentNumberRule.Key.ALLOCATION,
            business_date=first.allocation_date,
            target=first,
            actor=self.user,
        )
        void_document_number(first, actor=self.user, reason="Dibatalkan untuk uji")

        second = self._allocation(date(2026, 4, 2))
        second_issue = issue_document_number(
            DocumentNumberRule.Key.ALLOCATION,
            business_date=second.allocation_date,
            target=second,
            actor=self.user,
        )

        first_issue.refresh_from_db()
        self.assertEqual(repeated.pk, first_issue.pk)
        self.assertEqual(first_issue.status, DocumentNumberIssue.Status.VOID)
        self.assertEqual(second_issue.document_number, "ALK-2026-0002")

    def test_different_rules_cannot_issue_the_same_rendered_number(self):
        allocation_rule = DocumentNumberRule.objects.get(
            key=DocumentNumberRule.Key.ALLOCATION,
        )
        contract_rule = DocumentNumberRule.objects.get(
            key=DocumentNumberRule.Key.PROCUREMENT_CONTRACT,
        )
        for rule in (allocation_rule, contract_rule):
            rule.template = "DOC-{year}-{seq}"
            rule.reset_period = DocumentNumberRule.ResetPeriod.YEARLY
            rule.padding = 1
            rule.save(
                update_fields=["template", "reset_period", "padding", "updated_at"]
            )

        first = self._allocation(date(2026, 4, 1))
        second = self._allocation(date(2026, 4, 2))
        first_issue = issue_document_number(
            DocumentNumberRule.Key.ALLOCATION,
            business_date=first.allocation_date,
            target=first,
            actor=self.user,
        )
        second_issue = issue_document_number(
            DocumentNumberRule.Key.PROCUREMENT_CONTRACT,
            business_date=second.allocation_date,
            target=second,
            actor=self.user,
        )

        self.assertEqual(first_issue.document_number, "DOC-2026-1")
        self.assertEqual(second_issue.document_number, "DOC-2026-2")
        self.assertEqual(
            DocumentNumberIssue.objects.values("document_number").distinct().count(),
            2,
        )

    def test_retired_distribution_numbers_remain_globally_reserved(self):
        allocation_rule = DocumentNumberRule.objects.get(
            key=DocumentNumberRule.Key.ALLOCATION,
        )
        allocation_rule.template = "DIST-{year}{month}-{seq}"
        allocation_rule.reset_period = DocumentNumberRule.ResetPeriod.MONTHLY
        allocation_rule.padding = 5
        allocation_rule.save(
            update_fields=["template", "reset_period", "padding", "updated_at"]
        )
        facility = Facility.objects.create(
            code="LEGACY-RS",
            name="Legacy RS",
            facility_type=Facility.FacilityType.RS,
        )
        for sequence_value, distribution_type in enumerate(
            ("BORROW_RS", "SWAP_RS"),
            start=1,
        ):
            Distribution.objects.create(
                document_number=f"DIST-202604-{sequence_value:05d}",
                distribution_type=distribution_type,
                request_date=date(2026, 4, sequence_value),
                facility=facility,
                created_by=self.user,
            )

        preview = preview_document_number(
            DocumentNumberRule.Key.ALLOCATION,
            business_date=date(2026, 4, 3),
        )
        allocation = self._allocation(date(2026, 4, 3))
        issue = issue_document_number(
            DocumentNumberRule.Key.ALLOCATION,
            business_date=allocation.allocation_date,
            target=allocation,
            actor=self.user,
        )

        self.assertEqual(preview, "DIST-202604-00003")
        self.assertEqual(issue.document_number, "DIST-202604-00003")
        self.assertEqual(
            DocumentNumberSequence.objects.get(
                rule=allocation_rule,
                period_key="202604",
                scope_key="",
            ).last_value,
            3,
        )

    def test_existing_issue_rejects_changed_business_date(self):
        allocation = self._allocation(date(2026, 4, 1))
        issue = issue_document_number(
            DocumentNumberRule.Key.ALLOCATION,
            business_date=allocation.allocation_date,
            target=allocation,
            actor=self.user,
        )
        allocation.allocation_date = date(2026, 4, 2)
        allocation.save(update_fields=["allocation_date", "updated_at"])

        with self.assertRaisesMessage(
            DocumentNumberingError,
            "Tanggal bisnis dokumen bernomor tidak boleh diubah.",
        ):
            issue_document_number(
                DocumentNumberRule.Key.ALLOCATION,
                business_date=allocation.allocation_date,
                target=allocation,
                actor=self.user,
            )

        issue.refresh_from_db()
        self.assertEqual(issue.business_date, date(2026, 4, 1))
        self.assertEqual(DocumentNumberIssue.objects.count(), 1)

    def test_existing_issue_rejects_changed_scope(self):
        allocation = self._allocation(date(2026, 4, 1))
        issue_document_number(
            DocumentNumberRule.Key.ALLOCATION,
            business_date=allocation.allocation_date,
            target=allocation,
            actor=self.user,
            scope_key="scope-a",
        )

        with self.assertRaisesMessage(
            DocumentNumberingError,
            "Scope dokumen bernomor tidak boleh diubah.",
        ):
            issue_document_number(
                DocumentNumberRule.Key.ALLOCATION,
                business_date=allocation.allocation_date,
                target=allocation,
                actor=self.user,
                scope_key="scope-b",
            )

        issue = DocumentNumberIssue.objects.get(object_id=allocation.pk)
        self.assertEqual(issue.scope_key, "scope-a")
        self.assertEqual(DocumentNumberIssue.objects.count(), 1)

    def test_outer_transaction_rollback_does_not_publish_number(self):
        allocation = self._allocation(date(2026, 6, 1))
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                issue_document_number(
                    DocumentNumberRule.Key.ALLOCATION,
                    business_date=allocation.allocation_date,
                    target=allocation,
                    actor=self.user,
                )
                raise RuntimeError("rollback")

        allocation.refresh_from_db()
        self.assertIsNone(allocation.document_number)
        self.assertFalse(DocumentNumberIssue.objects.filter(object_id=allocation.pk).exists())
        self.assertFalse(
            DocumentNumberSequence.objects.filter(
                rule__key=DocumentNumberRule.Key.ALLOCATION,
                period_key="2026",
            ).exists()
        )


class DocumentNumberConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        _ensure_rule(
            DocumentNumberRule.Key.ALLOCATION,
            "Alokasi",
            "ALK-{year}-{seq}",
            DocumentNumberRule.ResetPeriod.YEARLY,
            4,
        )
        self.user = User.objects.create_superuser(
            username="numbering-concurrency-admin",
            password="StrongPass123!",
        )
        self.allocations = [
            Allocation.objects.create(
                allocation_date=date(2026, 7, 1),
                created_by=self.user,
            )
            for _ in range(2)
        ]

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_issuance_serializes_one_counter(self):
        def issue(allocation_id):
            connections.close_all()
            allocation = Allocation.objects.get(pk=allocation_id)
            actor = User.objects.get(pk=self.user.pk)
            result = issue_document_number(
                DocumentNumberRule.Key.ALLOCATION,
                business_date=allocation.allocation_date,
                target=allocation,
                actor=actor,
            )
            connections.close_all()
            return result.document_number

        with ThreadPoolExecutor(max_workers=2) as executor:
            numbers = list(executor.map(issue, [row.pk for row in self.allocations]))

        self.assertCountEqual(numbers, ["ALK-2026-0001", "ALK-2026-0002"])
        self.assertEqual(
            DocumentNumberSequence.objects.get(
                rule__key=DocumentNumberRule.Key.ALLOCATION,
                period_key="2026",
                scope_key="",
            ).last_value,
            2,
        )

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_different_rules_retry_global_number_collision(self):
        rule_keys = (
            DocumentNumberRule.Key.ALLOCATION,
            DocumentNumberRule.Key.PROCUREMENT_CONTRACT,
        )
        for rule in DocumentNumberRule.objects.filter(key__in=rule_keys):
            rule.template = "DOC-{year}-{seq}"
            rule.reset_period = DocumentNumberRule.ResetPeriod.YEARLY
            rule.padding = 1
            rule.save(
                update_fields=["template", "reset_period", "padding", "updated_at"]
            )

        def issue(payload):
            allocation_id, rule_key = payload
            connections.close_all()
            allocation = Allocation.objects.get(pk=allocation_id)
            actor = User.objects.get(pk=self.user.pk)
            result = issue_document_number(
                rule_key,
                business_date=allocation.allocation_date,
                target=allocation,
                actor=actor,
            )
            connections.close_all()
            return result.document_number

        payloads = list(zip([row.pk for row in self.allocations], rule_keys, strict=True))
        with ThreadPoolExecutor(max_workers=2) as executor:
            numbers = list(executor.map(issue, payloads))

        self.assertCountEqual(numbers, ["DOC-2026-1", "DOC-2026-2"])
        self.assertEqual(DocumentNumberIssue.objects.count(), 2)
