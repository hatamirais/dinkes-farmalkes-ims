import re

from django.db import migrations


def _period_key(reset_period, business_date):
    if reset_period == 'MONTHLY':
        return business_date.strftime('%Y%m')
    if reset_period == 'YEARLY':
        return business_date.strftime('%Y')
    return ''


def _sequence_from_number(template, document_number):
    pattern = re.escape(template)
    pattern = pattern.replace(re.escape('{seq}'), r'(?P<seq>\d+)')
    pattern = pattern.replace(re.escape('{year}'), r'\d{4}')
    pattern = pattern.replace(re.escape('{month}'), r'\d{2}')
    pattern = pattern.replace(re.escape('{parent}'), r'.+?')
    match = re.fullmatch(pattern, document_number or '')
    if not match:
        return None
    try:
        return int(match.group('seq'))
    except (TypeError, ValueError):
        return None


def backfill_document_number_issues(apps, schema_editor):
    database = schema_editor.connection.alias
    Rule = apps.get_model('core', 'DocumentNumberRule')
    Issue = apps.get_model('core', 'DocumentNumberIssue')
    Sequence = apps.get_model('core', 'DocumentNumberSequence')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    SourceClaim = apps.get_model('stock', 'SourceDocumentNumberClaim')

    Allocation = apps.get_model('allocation', 'Allocation')
    Distribution = apps.get_model('distribution', 'Distribution')
    Contract = apps.get_model('procurement', 'ProcurementContract')
    Amendment = apps.get_model('procurement', 'ProcurementAmendment')
    Receiving = apps.get_model('receiving', 'Receiving')
    Recall = apps.get_model('recall', 'Recall')
    Expired = apps.get_model('expired', 'Expired')
    Transfer = apps.get_model('stock', 'StockTransfer')
    Opname = apps.get_model('stock_opname', 'StockOpname')

    Allocation.objects.using(database).filter(status='DRAFT').update(document_number=None)
    Distribution.objects.using(database).filter(
        status__in=['DRAFT', 'PREPARED']
    ).update(document_number=None)
    Contract.objects.using(database).filter(status='DRAFT').update(document_number=None)
    Amendment.objects.using(database).filter(status='DRAFT').update(document_number=None)

    draft_receivings = list(
        Receiving.objects.using(database)
        .filter(status='DRAFT')
        .exclude(document_number__isnull=True)
        .values_list('pk', 'document_number')
    )
    for receiving_id, document_number in draft_receivings:
        SourceClaim.objects.using(database).filter(
            document_number=document_number,
            source_type='RECEIVING',
            source_id=receiving_id,
        ).delete()
    Receiving.objects.using(database).filter(status='DRAFT').update(document_number=None)
    Recall.objects.using(database).filter(status='DRAFT').update(document_number=None)
    Expired.objects.using(database).filter(status='DRAFT').update(document_number=None)
    Transfer.objects.using(database).filter(status='DRAFT').update(document_number=None)
    Opname.objects.using(database).filter(status='DRAFT').update(document_number=None)

    configs = [
        (Allocation, 'ALLOCATION', 'allocation_date', '', 'submitted_by_id', {'SUBMITTED', 'APPROVED', 'PARTIALLY_FULFILLED', 'FULFILLED', 'REJECTED'}, set()),
        (Distribution, 'DISTRIBUTION_LPLPO', 'request_date', '', '', {'SUBMITTED', 'VERIFIED', 'DISTRIBUTED', 'REJECTED'}, set()),
        (Distribution, 'DISTRIBUTION_SPECIAL_REQUEST', 'request_date', '', '', {'SUBMITTED', 'VERIFIED', 'DISTRIBUTED', 'REJECTED'}, set()),
        (Contract, 'PROCUREMENT_CONTRACT', 'contract_date', '', 'submitted_by_id', {'SUBMITTED', 'APPROVED', 'CLOSED', 'CANCELLED'}, {'CANCELLED'}),
        (Amendment, 'PROCUREMENT_AMENDMENT', 'amendment_date', 'contract_id', 'submitted_by_id', {'SUBMITTED', 'APPROVED'}, set()),
        (Receiving, 'RECEIVING', 'receiving_date', '', '', {'SUBMITTED', 'APPROVED', 'PARTIAL', 'RECEIVED', 'CLOSED', 'VERIFIED', 'CANCELLED'}, {'CANCELLED'}),
        (Recall, 'RECALL', 'recall_date', '', '', {'SUBMITTED', 'VERIFIED', 'COMPLETED'}, set()),
        (Expired, 'EXPIRED', 'report_date', '', '', {'SUBMITTED', 'VERIFIED', 'DISPOSED'}, set()),
        (Transfer, 'STOCK_TRANSFER', 'transfer_date', '', 'completed_by_id', {'COMPLETED'}, set()),
        (Opname, 'STOCK_OPNAME', 'period_end', '', '', {'IN_PROGRESS', 'COMPLETED'}, set()),
    ]

    counters = {}
    for model, rule_key, date_field, scope_field, actor_field, issued_statuses, void_statuses in configs:
        rule = Rule.objects.using(database).get(key=rule_key)
        queryset = (
            model.objects.using(database)
            .filter(status__in=issued_statuses)
            .exclude(document_number__isnull=True)
            .exclude(document_number='')
            .order_by(date_field, 'pk')
        )
        if model is Distribution:
            queryset = queryset.filter(distribution_type=(
                'LPLPO' if rule_key == 'DISTRIBUTION_LPLPO' else 'SPECIAL_REQUEST'
            ))

        content_type = ContentType.objects.db_manager(database).get_for_model(model)
        for obj in queryset.iterator():
            business_date = getattr(obj, date_field)
            scope_key = str(getattr(obj, scope_field)) if scope_field else ''
            period_key = _period_key(rule.reset_period, business_date)
            bucket = (rule.pk, period_key, scope_key)
            last_value = counters.get(bucket, 0)
            parsed_value = _sequence_from_number(rule.template, obj.document_number)
            sequence_value = parsed_value if parsed_value and parsed_value > last_value else last_value + 1
            counters[bucket] = sequence_value
            is_void = obj.status in void_statuses
            void_reason = getattr(obj, 'cancel_reason', '') if is_void else ''
            issued_by_id = getattr(obj, actor_field, None) if actor_field else None
            if model is Receiving and not obj.is_planned:
                issued_by_id = obj.verified_by_id
            elif model is Receiving and obj.contract_id:
                issued_by_id = obj.approved_by_id
            Issue.objects.using(database).create(
                rule_id=rule.pk,
                document_number=obj.document_number,
                sequence_value=sequence_value,
                period_key=period_key,
                scope_key=scope_key,
                business_date=business_date,
                status='VOID' if is_void else 'ISSUED',
                content_type_id=content_type.pk,
                object_id=obj.pk,
                target_label=f'{model._meta.label} #{obj.pk}',
                rule_label_snapshot=rule.label,
                template_snapshot=rule.template,
                reset_period_snapshot=rule.reset_period,
                padding_snapshot=rule.padding,
                issued_by_id=issued_by_id,
                voided_by_id=getattr(obj, 'cancelled_by_id', None) if is_void else None,
                voided_at=getattr(obj, 'cancelled_at', None) if is_void else None,
                void_reason=(
                    void_reason or 'Dokumen sudah dibatalkan sebelum migrasi.'
                    if is_void
                    else ''
                ),
            )

    for (rule_id, period_key, scope_key), last_value in counters.items():
        Sequence.objects.using(database).update_or_create(
            rule_id=rule_id,
            period_key=period_key,
            scope_key=scope_key,
            defaults={'last_value': last_value},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_documentnumberrule_and_more'),
        ('allocation', '0004_alter_allocation_document_number'),
        ('distribution', '0014_alter_distribution_distribution_type_and_more'),
        ('procurement', '0005_alter_procurementamendment_document_number_and_more'),
        ('receiving', '0023_receiving_import_group_and_more'),
        ('recall', '0003_alter_recall_document_number'),
        ('expired', '0004_alter_expired_document_number'),
        ('stock', '0014_alter_stocktransfer_document_number'),
        ('stock_opname', '0012_alter_stockopname_document_number'),
    ]

    operations = [
        migrations.RunPython(backfill_document_number_issues),
    ]
