from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("distribution", "0010_backfill_distributionitem_reserved_quantity"),
    ]

    operations = [
        migrations.AlterField(
            model_name="distributionitem",
            name="reserved_quantity",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text="Jumlah stok yang sedang dibooking untuk dokumen ini.",
                max_digits=12,
            ),
        ),
    ]
