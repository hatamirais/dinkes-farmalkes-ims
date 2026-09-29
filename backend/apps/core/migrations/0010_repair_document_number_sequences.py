import re

from django.db import migrations


def _sequence_from_number(template, document_number):
    pattern = re.escape(template)
    pattern = pattern.replace(re.escape("{seq}"), r"(?P<seq>\d+)")
    pattern = pattern.replace(re.escape("{year}"), r"\d{4}")
    pattern = pattern.replace(re.escape("{month}"), r"\d{2}")
    pattern = pattern.replace(re.escape("{parent}"), r".+?")
    match = re.fullmatch(pattern, document_number or "")
    if not match:
        return None
    try:
        return int(match.group("seq"))
    except (TypeError, ValueError):
        return None


def repair_document_number_sequences(apps, schema_editor):
    database = schema_editor.connection.alias
    Issue = apps.get_model("core", "DocumentNumberIssue")
    Sequence = apps.get_model("core", "DocumentNumberSequence")

    bucket_maxima = {}
    for issue in Issue.objects.using(database).all().iterator():
        parsed_value = _sequence_from_number(
            issue.template_snapshot,
            issue.document_number,
        )
        sequence_value = issue.sequence_value
        if parsed_value and parsed_value > 0:
            sequence_value = parsed_value
            if issue.sequence_value != parsed_value:
                Issue.objects.using(database).filter(pk=issue.pk).update(
                    sequence_value=parsed_value,
                )

        bucket = (issue.rule_id, issue.period_key, issue.scope_key)
        bucket_maxima[bucket] = max(
            bucket_maxima.get(bucket, 0),
            sequence_value,
        )

    for (rule_id, period_key, scope_key), last_value in bucket_maxima.items():
        Sequence.objects.using(database).update_or_create(
            rule_id=rule_id,
            period_key=period_key,
            scope_key=scope_key,
            defaults={"last_value": last_value},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0009_repair_receiving_issuance_metadata"),
    ]

    operations = [
        migrations.RunPython(
            repair_document_number_sequences,
            migrations.RunPython.noop,
        ),
    ]
