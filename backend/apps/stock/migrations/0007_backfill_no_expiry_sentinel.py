from datetime import date

from django.db import migrations


def backfill_no_expiry_sentinel(apps, schema_editor):
    Stock = apps.get_model("stock", "Stock")
    Stock.objects.filter(expiry_date=date(2099, 12, 31)).update(expiry_date=None)


class Migration(migrations.Migration):

    dependencies = [
        ("stock", "0006_alter_stock_expiry_date"),
    ]

    operations = [
        migrations.RunPython(backfill_no_expiry_sentinel, migrations.RunPython.noop),
    ]
