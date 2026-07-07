from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("distribution", "0008_backfill_no_expiry_sentinel"),
    ]

    operations = [
        migrations.AddField(
            model_name="distributionitem",
            name="reserved_quantity",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Jumlah stok yang sedang dibooking untuk dokumen ini.",
                max_digits=12,
                null=True,
            ),
        ),
    ]
