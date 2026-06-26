from django.db import migrations


class Migration(migrations.Migration):
    """Compatibility node for databases that applied an older stock_opname branch."""

    dependencies = [
        ("stock_opname", "0003_stockopnameitem_chk_actual_quantity_gte_0"),
    ]

    operations = []
