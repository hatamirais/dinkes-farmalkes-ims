from decimal import Decimal

from django.db import migrations


ZERO_DECIMAL = Decimal("0")


def backfill_distribution_item_reserved_quantity(apps, schema_editor):
    DistributionItem = apps.get_model("distribution", "DistributionItem")
    Stock = apps.get_model("stock", "Stock")

    DistributionItem.objects.filter(reserved_quantity__isnull=True).update(
        reserved_quantity=ZERO_DECIMAL
    )

    active_reservation_items = list(
        DistributionItem.objects.filter(
            stock_id__isnull=False,
            quantity_approved__gt=0,
        ).filter(
            distribution__status="VERIFIED",
        )
    )
    active_reservation_items.extend(
        DistributionItem.objects.filter(
            stock_id__isnull=False,
            quantity_approved__gt=0,
            distribution__distribution_type="ALLOCATION",
            distribution__status="PREPARED",
        )
    )

    reserved_totals_by_stock_id = {}
    processed_item_ids = set()
    for item in active_reservation_items:
        if item.pk in processed_item_ids:
            continue
        processed_item_ids.add(item.pk)
        item.reserved_quantity = item.quantity_approved
        item.save(update_fields=["reserved_quantity"])
        reserved_totals_by_stock_id[item.stock_id] = (
            reserved_totals_by_stock_id.get(item.stock_id, ZERO_DECIMAL)
            + item.quantity_approved
        )

    for stock in Stock.objects.filter(pk__in=reserved_totals_by_stock_id.keys()):
        stock.reserved = (stock.reserved or ZERO_DECIMAL) + reserved_totals_by_stock_id[stock.pk]
        stock.save(update_fields=["reserved"])


class Migration(migrations.Migration):
    dependencies = [
        ("distribution", "0009_distributionitem_reserved_quantity"),
        ("stock", "0007_backfill_no_expiry_sentinel"),
    ]

    operations = [
        migrations.RunPython(
            backfill_distribution_item_reserved_quantity,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
