from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import unicodedata

from django.core.paginator import Paginator
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.items.models import FundingSource, Location, TherapeuticClass

from .models import Stock


@dataclass(frozen=True)
class StockListOptions:
    page_size: int = 25
    near_expiry_days: int = 90


def normalize_text_param(value, *, max_length=100):
    normalized = unicodedata.normalize("NFC", value or "")
    normalized = normalized.replace("\x00", "").strip()
    return normalized[:max_length]


def parse_iso_date_param(value):
    raw_value = normalize_text_param(value, max_length=10)
    if not raw_value:
        return None

    try:
        parsed = datetime.strptime(raw_value, "%Y-%m-%d").date()
    except ValueError:
        return None

    if parsed.year < 1000 or parsed.year > 9999:
        return None

    return parsed


def resolve_selected_id(value, allowed_ids):
    raw_value = normalize_text_param(value, max_length=20)
    if not raw_value.isdigit():
        return ""

    parsed_value = int(raw_value)
    if parsed_value not in allowed_ids:
        return ""

    return str(parsed_value)


def stock_expiry_badge(expiry_date, today, *, near_expiry_days=90):
    if expiry_date is None:
        return "text-bg-secondary", "Tanpa kedaluwarsa", None

    days_until_expiry = (expiry_date - today).days
    if days_until_expiry <= 0:
        return "text-bg-danger", "Kedaluwarsa", days_until_expiry
    if days_until_expiry <= near_expiry_days:
        return "text-bg-warning", f"≤{near_expiry_days} hari", days_until_expiry
    return "text-bg-success", "Aman", days_until_expiry


def funding_badge_class(funding_source):
    funding_code = (getattr(funding_source, "code", "") or "").strip().upper()
    if funding_code == "HIBAH":
        return "text-bg-warning"
    if funding_code == "DAU":
        return "text-bg-info"
    if funding_code == "PAD":
        return "text-bg-success"
    return "text-bg-secondary"


def build_stock_list_context(params, *, options=None):
    options = options or StockListOptions()
    today = timezone.localdate()
    warning_threshold = today + timedelta(days=options.near_expiry_days)
    zero_decimal = Decimal("0")
    available_quantity_expression = ExpressionWrapper(
        F("quantity") - F("reserved"),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )

    active_locations = list(Location.objects.filter(is_active=True).order_by("name"))
    active_funding_sources = list(
        FundingSource.objects.filter(is_active=True).order_by("name")
    )
    active_therapeutic_classes = list(
        TherapeuticClass.objects.filter(is_active=True).order_by("name")
    )
    active_location_ids = {location.id for location in active_locations}
    active_funding_source_ids = {source.id for source in active_funding_sources}
    active_therapeutic_class_ids = {
        therapeutic_class.id for therapeutic_class in active_therapeutic_classes
    }

    queryset = (
        Stock.objects.select_related(
            "item",
            "item__satuan",
            "item__kategori",
            "item__program",
            "location",
            "sumber_dana",
        )
        .prefetch_related("item__therapeutic_classes")
        .filter(quantity__gt=0)
        .annotate(available_qty=available_quantity_expression)
        .order_by("item__nama_barang", F("expiry_date").asc(nulls_last=True))
    )

    search = normalize_text_param(params.get("q", ""), max_length=100)
    if search:
        queryset = queryset.filter(
            Q(item__kode_barang__icontains=search)
            | Q(item__nama_barang__icontains=search)
            | Q(batch_lot__icontains=search)
            | Q(source_document_number__icontains=search)
            | Q(item__program__code__icontains=search)
            | Q(item__program__name__icontains=search)
            | Q(item__therapeutic_classes__code__icontains=search)
            | Q(item__therapeutic_classes__name__icontains=search)
        ).distinct()

    location = resolve_selected_id(params.get("location"), active_location_ids)
    if location:
        queryset = queryset.filter(location_id=int(location))

    sumber_dana = resolve_selected_id(
        params.get("sumber_dana"),
        active_funding_source_ids,
    )
    if sumber_dana:
        queryset = queryset.filter(sumber_dana_id=int(sumber_dana))

    program = normalize_text_param(params.get("program", ""), max_length=1)
    if program == "1":
        queryset = queryset.filter(item__is_program_item=True)
    elif program == "0":
        queryset = queryset.filter(item__is_program_item=False)
    else:
        program = ""

    therapeutic_class = resolve_selected_id(
        params.get("therapeutic_class"),
        active_therapeutic_class_ids,
    )
    if therapeutic_class:
        queryset = queryset.filter(item__therapeutic_classes__id=int(therapeutic_class))

    low_stock = normalize_text_param(params.get("low_stock", ""), max_length=1)
    if low_stock == "1":
        queryset = queryset.filter(available_qty__lt=F("item__minimum_stock"))
    else:
        low_stock = ""

    expiry_from = parse_iso_date_param(params.get("expiry_from"))
    if expiry_from:
        queryset = queryset.filter(expiry_date__gte=expiry_from)

    expiry_to = parse_iso_date_param(params.get("expiry_to"))
    if expiry_to:
        queryset = queryset.filter(expiry_date__lte=expiry_to)

    quick = normalize_text_param(params.get("quick", ""), max_length=20)
    allowed_quick_filters = {"expired", "expiring", "safe"}
    if quick not in allowed_quick_filters:
        quick = ""

    quick_counts = queryset.aggregate(
        expired=Count("pk", filter=Q(expiry_date__lte=today)),
        expiring=Count(
            "pk",
            filter=Q(expiry_date__gt=today, expiry_date__lte=warning_threshold),
        ),
        safe=Count("pk", filter=Q(expiry_date__gt=warning_threshold)),
    )

    if quick == "expired":
        queryset = queryset.filter(expiry_date__lte=today)
    elif quick == "expiring":
        queryset = queryset.filter(
            expiry_date__gt=today,
            expiry_date__lte=warning_threshold,
        )
    elif quick == "safe":
        queryset = queryset.filter(expiry_date__gt=warning_threshold)

    stock_stats = queryset.aggregate(
        total_entries=Count("pk"),
        total_quantity=Coalesce(Sum("quantity"), Value(zero_decimal)),
        total_reserved=Coalesce(Sum("reserved"), Value(zero_decimal)),
        total_available=Coalesce(
            Sum("available_qty"),
            Value(zero_decimal),
        ),
        attention_count=Count("pk", filter=Q(expiry_date__lte=warning_threshold)),
    )

    paginator = Paginator(queryset, options.page_size)
    stocks = paginator.get_page(params.get("page"))
    for stock in stocks.object_list:
        (
            stock.expiry_badge_class,
            stock.expiry_badge_label,
            stock.days_until_expiry,
        ) = stock_expiry_badge(
            stock.expiry_date,
            today,
            near_expiry_days=options.near_expiry_days,
        )
        stock.source_fund_badge_class = funding_badge_class(stock.sumber_dana)

    locations = [
        {
            "id": loc.id,
            "name": loc.name,
            "selected": "selected" if location == str(loc.id) else "",
        }
        for loc in active_locations
    ]
    funding_sources = [
        {
            "id": sd.id,
            "name": sd.name,
            "selected": "selected" if sumber_dana == str(sd.id) else "",
        }
        for sd in active_funding_sources
    ]
    therapeutic_classes = [
        {
            "id": therapeutic.id,
            "name": therapeutic.name,
            "selected": "selected"
            if therapeutic_class == str(therapeutic.id)
            else "",
        }
        for therapeutic in active_therapeutic_classes
    ]

    return {
        "stocks": stocks,
        "stock_stats": stock_stats,
        "quick_counts": quick_counts,
        "locations": locations,
        "funding_sources": funding_sources,
        "therapeutic_classes": therapeutic_classes,
        "search": search,
        "selected_location": location or "",
        "selected_sumber_dana": sumber_dana or "",
        "selected_program": program or "",
        "selected_therapeutic_class": therapeutic_class or "",
        "selected_low_stock": low_stock,
        "selected_quick": quick,
        "expiry_from": expiry_from,
        "expiry_to": expiry_to,
        "near_expiry_days": options.near_expiry_days,
    }
