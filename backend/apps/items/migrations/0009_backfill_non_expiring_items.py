from django.db import migrations


def backfill_non_expiring_items(apps, schema_editor):
    Item = apps.get_model("items", "Item")
    Stock = apps.get_model("stock", "Stock")
    ReceivingItem = apps.get_model("receiving", "ReceivingItem")

    affected_item_ids = set(
        Stock.objects.filter(expiry_date__isnull=True).values_list("item_id", flat=True)
    )
    affected_item_ids.update(
        ReceivingItem.objects.filter(expiry_date__isnull=True).values_list("item_id", flat=True)
    )
    if affected_item_ids:
        Item.objects.filter(pk__in=affected_item_ids).update(requires_expiry_date=False)


class Migration(migrations.Migration):

    dependencies = [
        ("items", "0008_item_requires_expiry_date"),
        ("stock", "0007_backfill_no_expiry_sentinel"),
        ("receiving", "0015_backfill_no_expiry_sentinel"),
    ]

    operations = [
        migrations.RunPython(backfill_non_expiring_items, migrations.RunPython.noop),
    ]
