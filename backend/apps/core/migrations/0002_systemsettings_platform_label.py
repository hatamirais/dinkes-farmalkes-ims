from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemsettings",
            name="platform_label",
            field=models.CharField(
                default="Healthcare Inventory Platform",
                help_text="Label singkat untuk branding aplikasi, misalnya badge di halaman login.",
                max_length=255,
            ),
        ),
    ]