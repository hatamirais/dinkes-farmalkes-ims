from django.db import migrations


FALLBACK_VOID_REASON = "Dokumen sudah dibatalkan sebelum migrasi."


def repair_backfilled_void_metadata(apps, schema_editor):
    database = schema_editor.connection.alias
    Issue = apps.get_model("core", "DocumentNumberIssue")
    ContentType = apps.get_model("contenttypes", "ContentType")
    Contract = apps.get_model("procurement", "ProcurementContract")
    Receiving = apps.get_model("receiving", "Receiving")

    for model in (Contract, Receiving):
        content_type = ContentType.objects.db_manager(database).get_for_model(model)
        cancelled_objects = model.objects.using(database).filter(status="CANCELLED")
        for obj in cancelled_objects.iterator():
            Issue.objects.using(database).filter(
                content_type_id=content_type.pk,
                object_id=obj.pk,
                status="VOID",
            ).update(
                voided_by_id=obj.cancelled_by_id,
                voided_at=obj.cancelled_at,
                void_reason=obj.cancel_reason or FALLBACK_VOID_REASON,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_remove_parent_numbering_token"),
    ]

    operations = [
        migrations.RunPython(repair_backfilled_void_metadata, migrations.RunPython.noop),
    ]
