from django.db import migrations, models
from django.db.models import Count


def mark_legacy_duplicate_numbers(apps, schema_editor):
    database = schema_editor.connection.alias
    Issue = apps.get_model("core", "DocumentNumberIssue")

    duplicate_numbers = (
        Issue.objects.using(database)
        .values("document_number")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
        .order_by("document_number")
    )
    for duplicate in duplicate_numbers.iterator():
        issue_ids = list(
            Issue.objects.using(database)
            .filter(document_number=duplicate["document_number"])
            .order_by("id")
            .values_list("id", flat=True)
        )
        Issue.objects.using(database).filter(id=issue_ids[0]).update(
            is_legacy_duplicate=False
        )
        Issue.objects.using(database).filter(id__in=issue_ids[1:]).update(
            is_legacy_duplicate=True
        )


def unmark_legacy_duplicate_numbers(apps, schema_editor):
    database = schema_editor.connection.alias
    Issue = apps.get_model("core", "DocumentNumberIssue")
    Issue.objects.using(database).filter(is_legacy_duplicate=True).update(
        is_legacy_duplicate=False
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_repair_legacy_templates_and_audit_global_numbers"),
    ]

    operations = [
        migrations.AddField(
            model_name="documentnumberissue",
            name="is_legacy_duplicate",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Menandai konflik lintas workflow yang sudah ada sebelum "
                    "keunikan nomor global diberlakukan."
                ),
            ),
        ),
        migrations.RunPython(
            mark_legacy_duplicate_numbers,
            unmark_legacy_duplicate_numbers,
        ),
    ]
