import string
import unicodedata

from django.db import migrations
from django.db.models import Count


MAX_DOCUMENT_NUMBER_LENGTH = 100
MAX_DOCUMENT_SEQUENCE_VALUE = (2**63) - 1
ALLOWED_TOKENS = {"seq", "year", "month"}
LEGACY_DISTRIBUTION_DEFAULTS = {
    "DISTRIBUTION_LPLPO": "440/{seq}/SBBK.RF/{year}",
    "DISTRIBUTION_SPECIAL_REQUEST": "440/{seq}/KD.F/{year}",
}


def _template_is_valid(template, reset_period, padding):
    template = unicodedata.normalize("NFC", (template or "").strip())
    if not template or "\x00" in template:
        return False
    try:
        parsed = list(string.Formatter().parse(template))
    except ValueError:
        return False

    fields = []
    for _literal, field_name, format_spec, conversion in parsed:
        if field_name is None:
            continue
        if format_spec or conversion:
            return False
        fields.append(field_name)
    if set(fields) - ALLOWED_TOKENS or fields.count("seq") != 1:
        return False
    if reset_period == "YEARLY" and fields.count("year") != 1:
        return False
    if reset_period == "MONTHLY" and (
        fields.count("year") != 1 or fields.count("month") != 1
    ):
        return False

    sequence_width = max(padding, len(str(MAX_DOCUMENT_SEQUENCE_VALUE)))
    try:
        rendered = template.format(
            seq="9" * sequence_width,
            year="2026",
            month="09",
        )
    except (KeyError, ValueError):
        return False
    return len(rendered) <= MAX_DOCUMENT_NUMBER_LENGTH


def repair_legacy_templates_and_audit_global_numbers(apps, schema_editor):
    database = schema_editor.connection.alias
    Rule = apps.get_model("core", "DocumentNumberRule")
    Issue = apps.get_model("core", "DocumentNumberIssue")

    for key, default_template in LEGACY_DISTRIBUTION_DEFAULTS.items():
        rule = Rule.objects.using(database).filter(key=key).first()
        if rule is None or _template_is_valid(
            rule.template,
            rule.reset_period,
            rule.padding,
        ):
            continue
        rule.template = default_template
        rule.reset_period = "YEARLY"
        rule.padding = 1
        rule.save(
            update_fields=["template", "reset_period", "padding", "updated_at"]
        )

    duplicates = list(
        Issue.objects.using(database)
        .values("document_number")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
        .order_by("document_number")[:20]
    )
    if duplicates:
        summary = ", ".join(
            f"{row['document_number']} ({row['total']}x)" for row in duplicates
        )
        raise RuntimeError(
            "Tidak dapat mengaktifkan keunikan global nomor dokumen karena ledger "
            f"memuat nomor duplikat: {summary}. Selesaikan konflik audit sebelum "
            "menjalankan migrasi kembali."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_repair_contract_plan_issuance_metadata"),
    ]

    operations = [
        migrations.RunPython(
            repair_legacy_templates_and_audit_global_numbers,
            migrations.RunPython.noop,
        ),
    ]
