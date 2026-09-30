from concurrent.futures import ThreadPoolExecutor
from datetime import date

from django.core.exceptions import ValidationError
from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature

from apps.allocation.models import Allocation
from apps.core.forms import DocumentNumberRuleForm
from apps.core.models import (
    DocumentNumberIssue,
    DocumentNumberRule,
    DocumentNumberSequence,
)
from apps.core.numbering import (
    issue_document_number,
    render_document_number,
    void_document_number,
)
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
