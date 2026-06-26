from django.db import migrations


class Migration(migrations.Migration):
    """Compatibility node for older timestamp rollout history."""

    dependencies = [
        ("stock_opname", "0003_stockopnameitem_chk_actual_quantity_gte_0"),
    ]

    operations = []
