from django.db import migrations


def repair_receiving_issuance_metadata(apps, schema_editor):
    database = schema_editor.connection.alias
    Issue = apps.get_model("core", "DocumentNumberIssue")
    ContentType = apps.get_model("contenttypes", "ContentType")
    Receiving = apps.get_model("receiving", "Receiving")

    content_type = ContentType.objects.db_manager(database).get_for_model(Receiving)
    receiving_issues = Issue.objects.using(database).filter(
        content_type_id=content_type.pk
    )
    receiving_issues.update(issued_by_id=None, issued_at=None)
    for receiving in Receiving.objects.using(database).filter(is_planned=False).iterator():
        receiving_issues.filter(object_id=receiving.pk).update(
            issued_by_id=receiving.verified_by_id,
            issued_at=receiving.verified_at,
        )
    contract_plans = Receiving.objects.using(database).filter(
        is_planned=True,
        contract_id__isnull=False,
    )
    for receiving in contract_plans.iterator():
        receiving_issues.filter(object_id=receiving.pk).update(
            issued_by_id=receiving.approved_by_id,
            issued_at=receiving.approved_at,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0008_document_number_issue_issued_at"),
    ]

    operations = [
        migrations.RunPython(
            repair_receiving_issuance_metadata,
            migrations.RunPython.noop,
        ),
    ]
