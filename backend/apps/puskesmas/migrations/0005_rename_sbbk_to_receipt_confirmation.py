import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("distribution", "0007_migrate_generated_to_verified"),
        ("puskesmas", "0004_puskesmasconsumption_puskesmassubunit_and_more"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="PuskesmasSBBK",
            new_name="PuskesmasReceiptConfirmation",
        ),
        migrations.RenameModel(
            old_name="PuskesmasSBBKItem",
            new_name="PuskesmasReceiptConfirmationItem",
        ),
        migrations.AddField(
            model_name="puskesmasreceiptconfirmation",
            name="distribution",
            field=models.OneToOneField(
                blank=True,
                help_text="Dokumen distribusi yang dikonfirmasi diterima oleh Puskesmas.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="receipt_confirmation",
                to="distribution.distribution",
            ),
        ),
        migrations.AddField(
            model_name="puskesmasreceiptconfirmationitem",
            name="batch_lot",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="puskesmasreceiptconfirmationitem",
            name="distribution_item",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="receipt_confirmation_items",
                to="distribution.distributionitem",
            ),
        ),
        migrations.AddField(
            model_name="puskesmasreceiptconfirmationitem",
            name="expiry_date",
            field=models.DateField(blank=True, null=True),
        ),
    ]
