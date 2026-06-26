from django.db import migrations, models


def _timestamp_field():
    return models.DateTimeField(blank=True, null=True)


def add_stockopnameitem_timestamps_if_missing(apps, schema_editor):
    StockOpnameItem = apps.get_model("stock_opname", "StockOpnameItem")
    table_name = StockOpnameItem._meta.db_table

    with schema_editor.connection.cursor() as cursor:
        columns = {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(
                cursor,
                table_name,
            )
        }

    for field_name in ("created_at", "updated_at"):
        if field_name in columns:
            continue
        field = _timestamp_field()
        field.set_attributes_from_name(field_name)
        schema_editor.add_field(StockOpnameItem, field)


class Migration(migrations.Migration):

    dependencies = [
        ("stock_opname", "0005_backfill_stockopname_completed_by"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    add_stockopnameitem_timestamps_if_missing,
                    reverse_code=migrations.RunPython.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="stockopnameitem",
                    name="created_at",
                    field=_timestamp_field(),
                ),
                migrations.AddField(
                    model_name="stockopnameitem",
                    name="updated_at",
                    field=_timestamp_field(),
                ),
            ],
        ),
    ]
