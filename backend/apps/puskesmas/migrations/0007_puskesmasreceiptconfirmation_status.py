from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("puskesmas", "0006_alter_puskesmasreceiptconfirmation_created_by_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="puskesmasreceiptconfirmation",
            name="status",
            field=models.CharField(
                choices=[("DRAFT", "Draft"), ("CONFIRMED", "Terkonfirmasi")],
                default="DRAFT",
                max_length=20,
            ),
        ),
    ]
