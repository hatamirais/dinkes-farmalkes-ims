from django.db import migrations


AMENDMENT_RULE_KEY = "PROCUREMENT_AMENDMENT"
NEW_TEMPLATE = "SPJ/{year}/{month}/{seq}"
LEGACY_TEMPLATE = "{parent}-A{seq}"


def remove_parent_token(apps, schema_editor):
    DocumentNumberRule = apps.get_model("core", "DocumentNumberRule")
    rule = DocumentNumberRule.objects.filter(key=AMENDMENT_RULE_KEY).first()
    if rule is None or "{parent}" not in rule.template:
        return
    rule.template = NEW_TEMPLATE
    rule.reset_period = "MONTHLY"
    rule.save(update_fields=["template", "reset_period", "updated_at"])


def restore_parent_token(apps, schema_editor):
    DocumentNumberRule = apps.get_model("core", "DocumentNumberRule")
    rule = DocumentNumberRule.objects.filter(
        key=AMENDMENT_RULE_KEY,
        template=NEW_TEMPLATE,
        reset_period="MONTHLY",
    ).first()
    if rule is None:
        return
    rule.template = LEGACY_TEMPLATE
    rule.reset_period = "NEVER"
    rule.save(update_fields=["template", "reset_period", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0005_backfill_document_number_issues"),
    ]

    operations = [
        migrations.RunPython(remove_parent_token, restore_parent_token),
    ]
