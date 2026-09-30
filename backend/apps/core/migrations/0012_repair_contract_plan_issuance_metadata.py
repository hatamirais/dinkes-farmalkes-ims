from django.db import migrations


def repair_contract_plan_issuance_metadata(apps, schema_editor):
    database = schema_editor.connection.alias
    Issue = apps.get_model("core", "DocumentNumberIssue")
    ContentType = apps.get_model("contenttypes", "ContentType")
    Receiving = apps.get_model("receiving", "Receiving")

    content_type = ContentType.objects.db_manager(database).get_for_model(Receiving)
    contract_plans = (
        Receiving.objects.using(database)
        .filter(is_planned=True, contract_id__isnull=False)
        .select_related("contract")
    )
    for receiving in contract_plans.iterator():
        Issue.objects.using(database).filter(
            content_type_id=content_type.pk,
            object_id=receiving.pk,
        ).update(
            issued_by_id=receiving.contract.approved_by_id,
            issued_at=receiving.contract.approved_at,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_repair_allocation_child_issuance_metadata"),
    ]

    operations = [
        migrations.RunPython(
            repair_contract_plan_issuance_metadata,
            migrations.RunPython.noop,
        ),
    ]
