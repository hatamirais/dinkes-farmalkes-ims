from datetime import date

from django.db import migrations


def backfill_no_expiry_sentinel(apps, schema_editor):
    DistributionItem = apps.get_model("distribution", "DistributionItem")
    DistributionItem.objects.filter(issued_expiry_date=date(2099, 12, 31)).update(
        issued_expiry_date=None
    )


class Migration(migrations.Migration):

    dependencies = [
        ("distribution", "0007_migrate_generated_to_verified"),
        ("stock", "0007_backfill_no_expiry_sentinel"),
    ]

    operations = [
        migrations.RunPython(backfill_no_expiry_sentinel, migrations.RunPython.noop),
    ]
