from django.db import migrations


def backfill_receipt_confirmation_status(apps, schema_editor):
    ReceiptConfirmation = apps.get_model(
        "puskesmas",
        "PuskesmasReceiptConfirmation",
    )
    ReceiptConfirmation.objects.filter(status="DRAFT").update(status="CONFIRMED")


class Migration(migrations.Migration):

    dependencies = [
        ("puskesmas", "0007_puskesmasreceiptconfirmation_status"),
    ]

    operations = [
        migrations.RunPython(
            backfill_receipt_confirmation_status,
            migrations.RunPython.noop,
        ),
    ]
