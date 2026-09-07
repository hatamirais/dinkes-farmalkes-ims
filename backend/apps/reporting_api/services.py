from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.items.models import Item
from apps.stock.models import Stock
from apps.stock.views import _build_puskesmas_stock_snapshot


def _metadata(*, period):
    return {
        "generated_at": timezone.now(),
        "cache_ttl_seconds": settings.REPORTING_API_CACHE_TTL_SECONDS,
        "period": period,
    }


def build_latest_warehouse_stock_payload():
    today = timezone.localdate()
    warning_threshold = today + timedelta(days=90)
    zero = Decimal("0")
    available_expression = ExpressionWrapper(
        F("quantity") - F("reserved"),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )

    stock_summaries = {
        row["item_id"]: row
        for row in Stock.objects.filter(quantity__gt=0)
        .values("item_id")
        .annotate(
            physical_quantity=Coalesce(Sum("quantity"), Value(zero)),
            reserved_quantity=Coalesce(Sum("reserved"), Value(zero)),
            available_quantity=Coalesce(Sum(available_expression), Value(zero)),
            expired_batch_count=Count("pk", filter=Q(expiry_date__lte=today)),
            expiring_batch_count=Count(
                "pk",
                filter=Q(expiry_date__gt=today, expiry_date__lte=warning_threshold),
            ),
        )
    }

    results = []
    items = Item.objects.filter(is_active=True).select_related("kategori", "satuan").order_by(
        "kategori__sort_order",
        "nama_barang",
        "kode_barang",
    )
    for item in items:
        summary = stock_summaries.get(item.pk, {})
        physical_quantity = summary.get("physical_quantity") or zero
        reserved_quantity = summary.get("reserved_quantity") or zero
        available_quantity = summary.get("available_quantity") or zero
        minimum_stock = item.minimum_stock or zero
        results.append(
            {
                "item_id": item.pk,
                "kode_barang": item.kode_barang,
                "nama_barang": item.nama_barang,
                "kategori": item.kategori.name if item.kategori_id else "Lainnya",
                "satuan": item.satuan.name if item.satuan_id else "-",
                "minimum_stock": minimum_stock,
                "physical_quantity": physical_quantity,
                "reserved_quantity": reserved_quantity,
                "available_quantity": available_quantity,
                "is_low_stock": available_quantity < minimum_stock,
                "expired_batch_count": summary.get("expired_batch_count") or 0,
                "expiring_batch_count": summary.get("expiring_batch_count") or 0,
            }
        )

    return {
        **_metadata(period={"as_of_date": today.isoformat()}),
        "count": len(results),
        "results": results,
    }


def build_latest_puskesmas_stock_payload(*, year):
    snapshot = _build_puskesmas_stock_snapshot(
        year,
        page_number=None,
        include_rows=True,
        paginate=False,
    )
    results = []
    for row in snapshot["rows"]:
        results.append(
            {
                "facility_id": row["facility_id"],
                "facility_name": row["facility_name"],
                "kode_barang": row["kode_barang"],
                "nama_barang": row["nama_barang"],
                "kategori": row["kategori"],
                "satuan": row["satuan"],
                "stock_current": row["stock_current"],
                "minimum_stock": row["minimum_stock"],
                "is_below_threshold": row["is_below_threshold"],
                "base_month": row["base_month"],
                "base_month_label": row["base_month_label"],
                "base_year": year,
                "receipt_adjustment": row["receipt_adjustment"],
                "consumption_adjustment": row["consumption_adjustment"],
            }
        )

    return {
        **_metadata(period={"year": year}),
        "count": len(results),
        "results": results,
    }
