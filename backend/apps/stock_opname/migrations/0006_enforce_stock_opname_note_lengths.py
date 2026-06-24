from django.db import migrations, models


HEADER_NOTES_LIMIT = 1000
ITEM_NOTES_LIMIT = 255


def validate_stock_opname_note_lengths(apps, schema_editor):
    StockOpname = apps.get_model("stock_opname", "StockOpname")
    StockOpnameItem = apps.get_model("stock_opname", "StockOpnameItem")

    oversized_headers = [
        row.pk
        for row in StockOpname.objects.exclude(notes="").only("pk", "notes")
        if len(row.notes or "") > HEADER_NOTES_LIMIT
    ]
    oversized_items = [
        row.pk
        for row in StockOpnameItem.objects.exclude(notes="").only("pk", "notes")
        if len(row.notes or "") > ITEM_NOTES_LIMIT
    ]

    if oversized_headers or oversized_items:
        details = []
        if oversized_headers:
            details.append(
                "stock_opnames notes > 1000 chars on ids: "
                + ", ".join(str(pk) for pk in oversized_headers[:5])
            )
        if oversized_items:
            details.append(
                "stock_opname_items notes > 255 chars on ids: "
                + ", ".join(str(pk) for pk in oversized_items[:5])
            )
        raise RuntimeError(
            "Cannot enforce stock opname note length limits until oversized legacy rows are cleaned up. "
            + " ; ".join(details)
        )


class Migration(migrations.Migration):

    dependencies = [
        ("stock_opname", "0005_backfill_stockopname_completed_by"),
    ]

    operations = [
        migrations.RunPython(
            validate_stock_opname_note_lengths,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="stockopname",
            name="notes",
            field=models.CharField(
                blank=True,
                help_text="Catatan umum stock opname (maksimal 1000 karakter)",
                max_length=1000,
            ),
        ),
        migrations.AlterField(
            model_name="stockopnameitem",
            name="notes",
            field=models.CharField(
                blank=True,
                help_text="Catatan jika ada selisih (maksimal 255 karakter)",
                max_length=255,
            ),
        ),
    ]
