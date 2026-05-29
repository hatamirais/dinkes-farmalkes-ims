import csv
from collections import defaultdict
from decimal import Decimal

from django.http import StreamingHttpResponse
from django.urls import reverse
from django.utils import timezone

from apps.core.csv_exports import sanitize_csv_row
from apps.expired.models import Expired
from apps.stock.models import Transaction


OUTCOME_DESTROY = "DESTROY"


def _safe_decimal(value):
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _get_document_reference(reference_type, reference_id):
    if reference_type == Transaction.ReferenceType.EXPIRED:
        try:
            expired_doc = Expired.objects.only("id", "document_number").get(pk=reference_id)
            return {
                "document_type": "Expired/Disposal",
                "document_reference": expired_doc.document_number,
                "document_url": reverse("expired:expired_detail", args=[expired_doc.pk]),
            }
        except Expired.DoesNotExist:
            return {
                "document_type": "Expired/Disposal",
                "document_reference": f"EXP#{reference_id}",
                "document_url": "",
            }

    if reference_type == Transaction.ReferenceType.DISTRIBUTION:
        from apps.distribution.models import Distribution

        try:
            distribution = Distribution.objects.only("id", "document_number").get(pk=reference_id)
            return {
                "document_type": "Distribution",
                "document_reference": distribution.document_number,
                "document_url": reverse("distribution:distribution_detail", args=[distribution.pk]),
            }
        except Distribution.DoesNotExist:
            return {
                "document_type": "Distribution",
                "document_reference": f"DIST#{reference_id}",
                "document_url": "",
            }

    return {
        "document_type": reference_type.title(),
        "document_reference": str(reference_id),
        "document_url": "",
    }


def _build_destroy_rows(filters):
    queryset = (
        Expired.objects.filter(status=Expired.Status.DISPOSED)
        .select_related("created_by", "verified_by", "disposed_by")
        .prefetch_related(
            "items__item__satuan",
            "items__stock__location",
            "items__stock__sumber_dana",
        )
        .order_by("-disposed_at", "-id")
    )

    start_date = filters.get("start_date")
    end_date = filters.get("end_date")
    date_field = filters.get("date_field") or "disposed_at"
    expired_date_field = {
        "created_at": "created_at__date",
        "verified_at": "verified_at__date",
        "disposed_at": "disposed_at__date",
    }.get(date_field, "disposed_at__date")
    if start_date:
        queryset = queryset.filter(**{f"{expired_date_field}__gte": start_date})
    if end_date:
        queryset = queryset.filter(**{f"{expired_date_field}__lte": end_date})

    location = filters.get("location")
    if location:
        queryset = queryset.filter(items__stock__location=location)

    item = filters.get("item")
    if item:
        queryset = queryset.filter(items__item=item)

    funding_source = filters.get("funding_source")
    if funding_source:
        queryset = queryset.filter(items__stock__sumber_dana=funding_source)

    queryset = queryset.distinct()

    rows = []
    for expired_doc in queryset:
        user_obj = expired_doc.disposed_by or expired_doc.verified_by or expired_doc.created_by
        user_name = getattr(user_obj, "full_name", "") or getattr(user_obj, "username", "") or ""
        for expired_item in expired_doc.items.all():
            if location and expired_item.stock.location_id != location.id:
                continue
            if item and expired_item.item_id != item.id:
                continue
            if funding_source and expired_item.stock.sumber_dana_id != funding_source.id:
                continue
            unit_price = _safe_decimal(expired_item.stock.unit_price)
            total_price = _safe_decimal(expired_item.quantity) * unit_price
            rows.append(
                {
                    "outcome_type": OUTCOME_DESTROY,
                    "document_type": "Expired/Disposal",
                    "document_reference": expired_doc.document_number,
                    "document_url": reverse("expired:expired_detail", args=[expired_doc.pk]),
                    "kode_barang": expired_item.item.kode_barang,
                    "nama_barang": expired_item.item.nama_barang,
                    "item_id": expired_item.item_id,
                    "unit": expired_item.item.satuan.name if expired_item.item.satuan_id else "",
                    "batch_lot": expired_item.stock.batch_lot,
                    "expiry_date": expired_item.stock.expiry_date,
                    "quantity": expired_item.quantity,
                    "unit_price": unit_price,
                    "total_price": total_price,
                    "location": expired_item.stock.location.name,
                    "location_id": expired_item.stock.location_id,
                    "facility": "",
                    "funding_source": expired_item.stock.sumber_dana.name if expired_item.stock.sumber_dana_id else "",
                    "funding_source_id": expired_item.stock.sumber_dana_id,
                    "responsible_user": user_name,
                    "timestamp": expired_doc.disposed_at or expired_doc.verified_at or expired_doc.created_at,
                    "notes": expired_item.notes or expired_doc.notes or "",
                    "reference_code": f"DISP-{expired_item.id}",
                    "reference_id": expired_item.id,
                }
            )
    return rows


def build_expired_audit_report(filters):
    rows = _build_destroy_rows(filters)

    rows.sort(
        key=lambda row: (
            row["timestamp"] or timezone.now(),
            row["document_reference"],
            row["nama_barang"],
            row["batch_lot"],
        ),
        reverse=True,
    )

    totals_by_outcome = {
        OUTCOME_DESTROY: Decimal("0"),
    }
    totals_value_by_outcome = {
        OUTCOME_DESTROY: Decimal("0"),
    }
    totals_by_item = defaultdict(lambda: {OUTCOME_DESTROY: Decimal("0")})
    total_values_by_item = defaultdict(lambda: {OUTCOME_DESTROY: Decimal("0")})

    for row in rows:
        quantity = _safe_decimal(row["quantity"])
        total_price = _safe_decimal(row["total_price"])
        totals_by_outcome[row["outcome_type"]] += quantity
        totals_value_by_outcome[row["outcome_type"]] += total_price
        totals_by_item[row["nama_barang"]][row["outcome_type"]] += quantity
        total_values_by_item[row["nama_barang"]][row["outcome_type"]] += total_price

    summary_rows = []
    for item_name in sorted(totals_by_item.keys()):
        summary_rows.append(
            {
                "item_name": item_name,
                "destroy_total": totals_by_item[item_name][OUTCOME_DESTROY],
                "destroy_total_value": total_values_by_item[item_name][OUTCOME_DESTROY],
            }
        )

    return {
        "rows": rows,
        "totals_by_outcome": totals_by_outcome,
        "totals_value_by_outcome": totals_value_by_outcome,
        "summary_rows": summary_rows,
        "reconciliation_notes": [],
    }


class _Echo:
    def write(self, value):
        return value


def export_expired_audit_report_csv(report_data):
    def generate_rows():
        writer = csv.writer(_Echo())
        yield "\ufeff"
        yield writer.writerow(
            sanitize_csv_row(
                [
                    "Outcome Type",
                    "Document Type",
                    "Document Reference",
                    "Kode Barang",
                    "Nama Barang",
                    "Batch / Lot",
                    "Expiry Date",
                    "Quantity",
                    "Unit Price",
                    "Total Price",
                    "Unit",
                    "Location",
                    "Funding Source",
                    "Responsible User",
                    "Timestamp",
                    "Notes / Reason",
                    "Item Reference",
                ]
            )
        )
        for row in report_data["rows"]:
            yield writer.writerow(
                sanitize_csv_row(
                    [
                        row["outcome_type"],
                        row["document_type"],
                        row["document_reference"],
                        row["kode_barang"],
                        row["nama_barang"],
                        row["batch_lot"],
                        row["expiry_date"].isoformat() if row["expiry_date"] else "",
                        row["quantity"],
                        row["unit_price"],
                        row["total_price"],
                        row["unit"],
                        row["location"],
                        row["funding_source"],
                        row["responsible_user"],
                        row["timestamp"].isoformat() if row["timestamp"] else "",
                        row["notes"],
                        row["reference_code"],
                    ]
                )
            )

    response = StreamingHttpResponse(
        generate_rows(),
        content_type="text/csv; charset=utf-8",
    )
    response["Content-Disposition"] = 'attachment; filename="expired_audit_report.csv"'
    return response

