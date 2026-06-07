from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("lplpo", "0010_lplpoitem_harga_satuan"),
    ]

    operations = [
        migrations.AlterField(
            model_name="lplpoitem",
            name="persediaan",
            field=models.IntegerField(
                default=0,
                help_text="stock_awal + penerimaan + pembelian_puskesmas",
            ),
        ),
        migrations.AlterField(
            model_name="lplpoitem",
            name="stock_awal",
            field=models.IntegerField(
                default=0,
                help_text=(
                    "Manual on first LPLPO, auto-filled from previous month Stock "
                    "Keseluruhan and may be negative when the prior month closed below zero"
                ),
            ),
        ),
    ]
