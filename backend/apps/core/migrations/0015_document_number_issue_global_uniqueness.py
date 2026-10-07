from django.db import migrations, models


OLD_CONSTRAINT = models.UniqueConstraint(
    fields=("rule", "document_number"),
    name="uq_doc_number_issue_rule_number",
)
GLOBAL_CONSTRAINT = models.UniqueConstraint(
    condition=models.Q(is_legacy_duplicate=False),
    fields=("document_number",),
    name="uq_doc_number_issue_number",
)


def _table_constraints(schema_editor, table_name):
    with schema_editor.connection.cursor() as cursor:
        return schema_editor.connection.introspection.get_constraints(
            cursor,
            table_name,
        )


def _table_columns(schema_editor, table_name):
    with schema_editor.connection.cursor() as cursor:
        return {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(
                cursor,
                table_name,
            )
        }


def reconcile_global_uniqueness_schema(apps, schema_editor):
    """Support fresh installs and databases that applied the former 0014."""
    Issue = apps.get_model("core", "DocumentNumberIssue")
    table_name = Issue._meta.db_table
    legacy_field = Issue._meta.get_field("is_legacy_duplicate")

    if legacy_field.column not in _table_columns(schema_editor, table_name):
        schema_editor.add_field(Issue, legacy_field)

    constraints = _table_constraints(schema_editor, table_name)
    if OLD_CONSTRAINT.name in constraints:
        schema_editor.remove_constraint(Issue, OLD_CONSTRAINT)
    if GLOBAL_CONSTRAINT.name in constraints:
        schema_editor.remove_constraint(
            Issue,
            models.UniqueConstraint(
                fields=("document_number",),
                name=GLOBAL_CONSTRAINT.name,
            ),
        )
    schema_editor.add_constraint(Issue, GLOBAL_CONSTRAINT)


def restore_per_rule_uniqueness_schema(apps, schema_editor):
    Issue = apps.get_model("core", "DocumentNumberIssue")
    table_name = Issue._meta.db_table
    constraints = _table_constraints(schema_editor, table_name)

    if GLOBAL_CONSTRAINT.name in constraints:
        schema_editor.remove_constraint(Issue, GLOBAL_CONSTRAINT)
    if OLD_CONSTRAINT.name not in constraints:
        schema_editor.add_constraint(Issue, OLD_CONSTRAINT)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_global_document_number_issue_uniqueness"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    reconcile_global_uniqueness_schema,
                    restore_per_rule_uniqueness_schema,
                ),
            ],
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="documentnumberissue",
                    name="uq_doc_number_issue_rule_number",
                ),
                migrations.AddConstraint(
                    model_name="documentnumberissue",
                    constraint=GLOBAL_CONSTRAINT,
                ),
            ],
        ),
    ]
