from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_repair_legacy_templates_and_audit_global_numbers"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="documentnumberissue",
            name="uq_doc_number_issue_rule_number",
        ),
        migrations.AddConstraint(
            model_name="documentnumberissue",
            constraint=models.UniqueConstraint(
                fields=("document_number",),
                name="uq_doc_number_issue_number",
            ),
        ),
    ]
