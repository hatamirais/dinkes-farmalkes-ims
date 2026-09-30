import unicodedata
from datetime import date, datetime

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.models import (
    DocumentNumberIssue,
    DocumentNumberRule,
    DocumentNumberSequence,
    MAX_DOCUMENT_NUMBER_LENGTH,
)


class DocumentNumberingError(ValidationError):
    pass


def _normalize_business_date(value):
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value)
        except ValueError as exc:
            raise DocumentNumberingError("Tanggal bisnis dokumen tidak valid.") from exc
    if isinstance(value, datetime):
        value = timezone.localdate(value) if timezone.is_aware(value) else value.date()
    if not isinstance(value, date):
        raise DocumentNumberingError("Tanggal bisnis dokumen wajib diisi.")
    if not 1000 <= value.year <= 9999:
        raise DocumentNumberingError("Tahun tanggal bisnis harus antara 1000 dan 9999.")
    return value


def _normalize_scope_key(value):
    normalized = unicodedata.normalize("NFC", str(value or "").strip())
    if "\x00" in normalized:
        raise DocumentNumberingError("Scope penomoran tidak valid.")
    if len(normalized) > 191:
        raise DocumentNumberingError("Scope penomoran terlalu panjang.")
    return normalized


def _period_key(rule, business_date):
    if rule.reset_period == DocumentNumberRule.ResetPeriod.MONTHLY:
        return business_date.strftime("%Y%m")
    if rule.reset_period == DocumentNumberRule.ResetPeriod.YEARLY:
        return business_date.strftime("%Y")
    return ""


def render_document_number(rule, sequence, business_date):
    business_date = _normalize_business_date(business_date)
    context = {
        "seq": str(sequence).zfill(rule.padding),
        "year": business_date.strftime("%Y"),
        "month": business_date.strftime("%m"),
    }
    try:
        number = rule.template.format(**context)
    except (KeyError, ValueError) as exc:
        raise DocumentNumberingError(
            f"Template rule {rule.key} tidak dapat dirender."
        ) from exc
    if not number or len(number) > MAX_DOCUMENT_NUMBER_LENGTH:
        raise DocumentNumberingError(
            "Hasil nomor dokumen kosong atau melebihi "
            f"{MAX_DOCUMENT_NUMBER_LENGTH} karakter."
        )
    return number


def _locked_sequence(rule, period_key, scope_key):
    try:
        with transaction.atomic():
            DocumentNumberSequence.objects.create(
                rule=rule,
                period_key=period_key,
                scope_key=scope_key,
                last_value=0,
            )
    except IntegrityError:
        pass
    return DocumentNumberSequence.objects.select_for_update().get(
        rule=rule,
        period_key=period_key,
        scope_key=scope_key,
    )


@transaction.atomic
def issue_document_number(
    rule_key,
    *,
    business_date,
    target,
    actor=None,
    scope_key="",
):
    """Issue once for a saved target and assign its ``document_number`` field."""
    if target.pk is None:
        raise DocumentNumberingError("Dokumen harus disimpan sebelum nomor diterbitkan.")

    business_date = _normalize_business_date(business_date)
    scope_key = _normalize_scope_key(scope_key)
    content_type = ContentType.objects.get_for_model(target, for_concrete_model=False)
    existing = (
        DocumentNumberIssue.objects.select_for_update()
        .filter(content_type=content_type, object_id=target.pk)
        .first()
    )
    if existing:
        if existing.rule.key != rule_key:
            raise DocumentNumberingError(
                "Dokumen ini sudah memakai rule penomoran yang berbeda."
            )
        if existing.business_date != business_date:
            raise DocumentNumberingError(
                "Tanggal bisnis dokumen bernomor tidak boleh diubah."
            )
        if existing.scope_key != scope_key:
            raise DocumentNumberingError(
                "Scope dokumen bernomor tidak boleh diubah."
            )
        if target.document_number != existing.document_number:
            target.document_number = existing.document_number
            update_fields = ["document_number"]
            if hasattr(target, "updated_at"):
                update_fields.append("updated_at")
            target.save(update_fields=update_fields)
        return existing

    if getattr(target, "document_number", None):
        raise DocumentNumberingError(
            "Dokumen sudah memiliki nomor tanpa catatan penerbitan."
        )

    try:
        rule = DocumentNumberRule.objects.select_for_update().get(key=rule_key)
    except DocumentNumberRule.DoesNotExist as exc:
        raise DocumentNumberingError(
            f"Rule penomoran {rule_key} belum dikonfigurasi."
        ) from exc
    rule.full_clean()

    period_key = _period_key(rule, business_date)
    sequence = _locked_sequence(rule, period_key, scope_key)
    sequence.last_value += 1
    while True:
        document_number = render_document_number(
            rule,
            sequence.last_value,
            business_date,
        )
        number_taken = DocumentNumberIssue.objects.filter(
            rule=rule,
            document_number=document_number,
        ).exists()
        if rule_key == DocumentNumberRule.Key.RECEIVING:
            from apps.stock.models import OpeningBalanceImport, SourceDocumentNumberClaim

            number_taken = number_taken or (
                SourceDocumentNumberClaim.objects.filter(
                    document_number=document_number
                ).exists()
                or OpeningBalanceImport.objects.filter(
                    document_number=document_number
                ).exists()
            )
        if not number_taken:
            break
        sequence.last_value += 1
    sequence.save(update_fields=["last_value", "updated_at"])

    issue = DocumentNumberIssue.objects.create(
        rule=rule,
        document_number=document_number,
        sequence_value=sequence.last_value,
        period_key=period_key,
        scope_key=scope_key,
        business_date=business_date,
        content_type=content_type,
        object_id=target.pk,
        target_label=f"{target._meta.label} #{target.pk}",
        rule_label_snapshot=rule.label,
        template_snapshot=rule.template,
        reset_period_snapshot=rule.reset_period,
        padding_snapshot=rule.padding,
        issued_by=actor,
        issued_at=timezone.now(),
    )
    target.document_number = document_number
    update_fields = ["document_number"]
    if hasattr(target, "updated_at"):
        update_fields.append("updated_at")
    target.save(update_fields=update_fields)
    return issue


@transaction.atomic
def void_document_number(target, *, actor=None, reason):
    reason = unicodedata.normalize("NFC", (reason or "").strip())
    if not reason:
        raise DocumentNumberingError("Alasan pembatalan nomor dokumen wajib diisi.")
    content_type = ContentType.objects.get_for_model(target, for_concrete_model=False)
    issue = (
        DocumentNumberIssue.objects.select_for_update()
        .filter(content_type=content_type, object_id=target.pk)
        .first()
    )
    if issue is None or issue.status == DocumentNumberIssue.Status.VOID:
        return issue
    issue.status = DocumentNumberIssue.Status.VOID
    issue.voided_by = actor
    issue.voided_at = timezone.now()
    issue.void_reason = reason
    issue.save(
        update_fields=["status", "voided_by", "voided_at", "void_reason", "updated_at"]
    )
    return issue


def preview_document_number(
    rule_key,
    *,
    business_date,
    scope_key="",
):
    """Return a non-reserving estimate; concurrent issuance may change it."""
    business_date = _normalize_business_date(business_date)
    scope_key = _normalize_scope_key(scope_key)
    rule = DocumentNumberRule.objects.get(key=rule_key)
    period_key = _period_key(rule, business_date)
    last_value = (
        DocumentNumberSequence.objects.filter(
            rule=rule,
            period_key=period_key,
            scope_key=scope_key,
        )
        .values_list("last_value", flat=True)
        .first()
        or 0
    )
    return render_document_number(
        rule,
        last_value + 1,
        business_date,
    )
