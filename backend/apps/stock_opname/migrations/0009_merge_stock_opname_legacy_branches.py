from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("stock_opname", "0008_alter_stockopnameitem_timestamps_non_null"),
        ("stock_opname", "0006_enforce_stock_opname_note_lengths"),
    ]

    operations = []
