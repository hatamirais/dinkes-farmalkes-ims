from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("stock_opname", "0005_backfill_stockopname_completed_by"),
    ]

    operations = [
        migrations.AddField(
            model_name="stockopnameitem",
            name="created_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="stockopnameitem",
            name="updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
