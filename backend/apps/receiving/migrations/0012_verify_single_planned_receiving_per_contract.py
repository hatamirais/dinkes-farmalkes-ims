from django.db import migrations


def verify_single_planned_receiving_per_contract(apps, schema_editor):
    Receiving = apps.get_model("receiving", "Receiving")
    from django.db.models import Count

    duplicates = list(
        Receiving.objects.filter(is_planned=True, contract__isnull=False)
        .values("contract_id")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )
    if duplicates:
        raise RuntimeError(
            "Duplicate planned receivings linked to the same contract must be fixed before enforcing uniqueness."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("receiving", "0011_receiving_contract_receivingorderitem_contract_line"),
    ]

    operations = [
        migrations.RunPython(
            verify_single_planned_receiving_per_contract,
            migrations.RunPython.noop,
        ),
    ]
