import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def _completed_by_field(*, to_model):
    return models.ForeignKey(
        blank=True,
        null=True,
        on_delete=django.db.models.deletion.PROTECT,
        related_name="completed_stock_opnames",
        to=to_model,
    )


def add_completed_by_if_missing(apps, schema_editor):
    StockOpname = apps.get_model("stock_opname", "StockOpname")
    user_app_label, user_model_name = settings.AUTH_USER_MODEL.split(".")
    User = apps.get_model(user_app_label, user_model_name)
    table_name = StockOpname._meta.db_table
    with schema_editor.connection.cursor() as cursor:
        columns = {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(
                cursor,
                table_name,
            )
        }

    if "completed_by_id" in columns:
        return

    field = _completed_by_field(to_model=User)
    field.set_attributes_from_name("completed_by")
    schema_editor.add_field(StockOpname, field)


class Migration(migrations.Migration):

    dependencies = [
        ("stock_opname", "0003_stockopnameitem_chk_actual_quantity_gte_0"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    add_completed_by_if_missing,
                    reverse_code=migrations.RunPython.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="stockopname",
                    name="completed_by",
                    field=_completed_by_field(to_model=settings.AUTH_USER_MODEL),
                ),
            ],
        ),
    ]
