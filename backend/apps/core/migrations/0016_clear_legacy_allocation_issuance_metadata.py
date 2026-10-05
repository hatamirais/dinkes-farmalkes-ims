from django.db import migrations
from django.db.models import F


def clear_legacy_allocation_issuance_metadata(apps, schema_editor):
    """Remove mutable submission metadata copied onto legacy Allocation issues."""
    database = schema_editor.connection.alias
    Issue = apps.get_model("core", "DocumentNumberIssue")
    Allocation = apps.get_model("allocation", "Allocation")
    ContentType = apps.get_model("contenttypes", "ContentType")

    content_type = ContentType.objects.db_manager(database).get_for_model(Allocation)
    allocation_issues = Issue.objects.using(database).filter(
        content_type_id=content_type.pk
    )
    for allocation in Allocation.objects.using(database).all().iterator():
        allocation_issues.filter(
            object_id=allocation.pk,
            issued_by_id=allocation.submitted_by_id,
            issued_at=allocation.submitted_at,
        ).exclude(issued_at=F("created_at")).update(
            issued_by_id=None,
            issued_at=None,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_document_number_issue_global_uniqueness"),
    ]

    operations = [
        migrations.RunPython(
            clear_legacy_allocation_issuance_metadata,
            migrations.RunPython.noop,
        ),
    ]
