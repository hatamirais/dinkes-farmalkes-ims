from datetime import date

from django.db import migrations


def backfill_no_expiry_sentinel(apps, schema_editor):
    PuskesmasReceiptConfirmationItem = apps.get_model(
        "puskesmas", "PuskesmasReceiptConfirmationItem"
    )
    PuskesmasReceiptConfirmationItem.objects.filter(
        expiry_date=date(2099, 12, 31)
    ).update(expiry_date=None)


class Migration(migrations.Migration):

    dependencies = [
        ("puskesmas", "0008_backfill_receipt_confirmation_status"),
        ("distribution", "0008_backfill_no_expiry_sentinel"),
    ]

    operations = [
        migrations.RunPython(backfill_no_expiry_sentinel, migrations.RunPython.noop),
    ]
