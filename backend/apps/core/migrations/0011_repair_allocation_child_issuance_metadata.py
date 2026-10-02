from django.db import migrations


def repair_allocation_child_issuance_metadata(apps, schema_editor):
    database = schema_editor.connection.alias
    Issue = apps.get_model("core", "DocumentNumberIssue")
    Distribution = apps.get_model("distribution", "Distribution")
    ContentType = apps.get_model("contenttypes", "ContentType")

    distribution_content_type = ContentType.objects.db_manager(database).get_for_model(
        Distribution
    )
    allocation_children = Distribution.objects.using(database).filter(
        allocation_id__isnull=False
    )
    for distribution in allocation_children.iterator():
        Issue.objects.using(database).filter(
            content_type_id=distribution_content_type.pk,
            object_id=distribution.pk,
        ).update(
            issued_by_id=distribution.verified_by_id,
            issued_at=distribution.verified_at,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_repair_document_number_sequences"),
    ]

    operations = [
        migrations.RunPython(
            repair_allocation_child_issuance_metadata,
            migrations.RunPython.noop,
        ),
    ]
