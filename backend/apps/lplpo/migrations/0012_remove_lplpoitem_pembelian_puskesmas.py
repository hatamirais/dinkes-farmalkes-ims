from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("lplpo", "0011_allow_negative_lplpo_carry_forward"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="lplpoitem",
            name="pembelian_puskesmas",
        ),
        migrations.AlterField(
            model_name="lplpoitem",
            name="persediaan",
            field=models.IntegerField(
                default=0,
                help_text="stock_awal + penerimaan",
            ),
        ),
    ]
