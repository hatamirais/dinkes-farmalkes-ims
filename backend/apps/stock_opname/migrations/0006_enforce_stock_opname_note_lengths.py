from django.db import migrations


class Migration(migrations.Migration):
    """Compatibility node for a superseded stock_opname validation branch."""

    dependencies = [
        ("stock_opname", "0004_add_completed_by"),
        ("stock_opname", "0004_stockopnameitem_created_at_and_more"),
        ("stock_opname", "0005_backfill_stockopname_completed_by"),
    ]

    operations = []
