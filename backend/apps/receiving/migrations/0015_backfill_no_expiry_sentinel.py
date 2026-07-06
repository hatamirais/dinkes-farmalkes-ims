from datetime import date

from django.db import migrations


def backfill_no_expiry_sentinel(apps, schema_editor):
    ReceivingItem = apps.get_model("receiving", "ReceivingItem")
    ReceivingItem.objects.filter(expiry_date=date(2099, 12, 31)).update(expiry_date=None)


class Migration(migrations.Migration):

    dependencies = [
        ("receiving", "0014_alter_receivingitem_expiry_date"),
    ]

    operations = [
        migrations.RunPython(backfill_no_expiry_sentinel, migrations.RunPython.noop),
    ]
