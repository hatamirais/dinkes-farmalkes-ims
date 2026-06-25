from django.db import migrations
from django.db.models import Q



def backfill_stockopnameitem_timestamps(apps, schema_editor):
    StockOpnameItem = apps.get_model("stock_opname", "StockOpnameItem")
    db_alias = schema_editor.connection.alias

    queryset = (
        StockOpnameItem.objects.using(db_alias)
        .select_related("stock_opname")
        .filter(Q(created_at__isnull=True) | Q(updated_at__isnull=True))
    )

    for item in queryset.iterator(chunk_size=500):
        header_created_at = item.stock_opname.created_at
        header_updated_at = item.stock_opname.updated_at
        if item.created_at is None:
            item.created_at = header_created_at
        if item.updated_at is None:
            item.updated_at = header_updated_at
        item.save(update_fields=["created_at", "updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("stock_opname", "0006_stockopnameitem_timestamps_nullable"),
    ]

    operations = [
        migrations.RunPython(
            backfill_stockopnameitem_timestamps,
            migrations.RunPython.noop,
        ),
    ]
