from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("stock_opname", "0007_backfill_stockopnameitem_timestamps"),
    ]

    operations = [
        migrations.AlterField(
            model_name="stockopnameitem",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterField(
            model_name="stockopnameitem",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
    ]
