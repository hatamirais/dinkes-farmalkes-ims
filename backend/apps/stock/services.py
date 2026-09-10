from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import unicodedata

from django.core.paginator import Paginator
from django.db.models import (
    Count,
    DecimalField,
    Exists,
    ExpressionWrapper,
    F,
    OuterRef,
    Q,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.items.models import FundingSource, Item, Location, TherapeuticClass

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


def _build_mobile_stock_queryset(params, *, options):
    today = timezone.localdate()
    warning_threshold = today + timedelta(days=options.near_expiry_days)
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
        .filter(quantity__gt=0)
        .annotate(available_qty=available_quantity_expression)
    )

    search = normalize_text_param(params.get("q", ""), max_length=100)
    if search:
        therapeutic_match = Item.therapeutic_classes.through.objects.filter(
            item_id=OuterRef("item_id"),
        ).filter(
            Q(therapeuticclass__code__icontains=search)
            | Q(therapeuticclass__name__icontains=search)
        )
        queryset = queryset.filter(
            Q(item__kode_barang__icontains=search)
            | Q(item__nama_barang__icontains=search)
            | Q(batch_lot__icontains=search)
            | Q(source_document_number__icontains=search)
            | Q(item__program__code__icontains=search)
            | Q(item__program__name__icontains=search)
            | Q(Exists(therapeutic_match))
        )

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
        selected_therapeutic_match = Item.therapeutic_classes.through.objects.filter(
            item_id=OuterRef("item_id"),
            therapeuticclass_id=int(therapeutic_class),
        )
        queryset = queryset.filter(Exists(selected_therapeutic_match))

    low_stock = normalize_text_param(params.get("low_stock", ""), max_length=1)
    if low_stock != "1":
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

    return {
        "queryset": queryset,
        "search": search,
        "location": location,
        "sumber_dana": sumber_dana,
        "program": program,
        "therapeutic_class": therapeutic_class,
        "low_stock": low_stock,
        "expiry_from": expiry_from,
        "expiry_to": expiry_to,
        "quick": quick,
        "today": today,
        "warning_threshold": warning_threshold,
        "locations": active_locations,
        "funding_sources": active_funding_sources,
        "therapeutic_classes": active_therapeutic_classes,
    }


def _mobile_item_risk_state(row):
    if row["expired_batch_count"]:
        return "expired"
    if row["expiring_batch_count"]:
        return "expiring"
    return "safe"


def _decorate_mobile_item_row(row):
    risk_badges = []
    if row["expired_batch_count"]:
        risk_badges.append(
            {
                "class": "text-bg-danger",
                "label": f"{row['expired_batch_count']} Expired",
            }
        )
    if row["expiring_batch_count"]:
        risk_badges.append(
            {
                "class": "text-bg-warning",
                "label": f"{row['expiring_batch_count']} near 90 hari",
            }
        )

    row["risk_state"] = _mobile_item_risk_state(row)
    row["risk_badges"] = risk_badges
    return row


def _mobile_filter_options(active_rows, selected_id):
    return [
        {
            "id": row.id,
            "name": row.name,
            "selected": "selected" if selected_id == str(row.id) else "",
        }
        for row in active_rows
    ]


def build_mobile_stock_search_context(params, *, options=None):
    options = options or StockListOptions()
    state = _build_mobile_stock_queryset(params, options=options)
    queryset = state["queryset"]
    zero_decimal = Decimal("0")
    preserved_params = params.copy()
    for key in ("page", "partial"):
        if key in preserved_params:
            del preserved_params[key]

    grouped_rows = list(
        queryset.values(
            "item_id",
            "item__kode_barang",
            "item__nama_barang",
            "item__satuan__name",
            "item__kategori__sort_order",
            "item__minimum_stock",
        )
        .annotate(
            total_quantity=Coalesce(Sum("quantity"), Value(zero_decimal)),
            total_reserved=Coalesce(Sum("reserved"), Value(zero_decimal)),
            total_available=Coalesce(Sum("available_qty"), Value(zero_decimal)),
            batch_count=Count("pk"),
            expired_batch_count=Count(
                "pk",
                filter=Q(expiry_date__lte=state["today"]),
            ),
            expiring_batch_count=Count(
                "pk",
                filter=Q(
                    expiry_date__gt=state["today"],
                    expiry_date__lte=state["warning_threshold"],
                ),
            ),
        )
        .order_by(
            "item__kategori__sort_order",
            "item__nama_barang",
            "item__kode_barang",
        )
    )

    if state["low_stock"]:
        grouped_rows = [
            row for row in grouped_rows
            if row["total_available"] < row["item__minimum_stock"]
        ]

    quick_counts = {
        "expired": 0,
        "expiring": 0,
        "safe": 0,
    }
    for row in grouped_rows:
        quick_counts[_mobile_item_risk_state(row)] += 1

    if state["quick"]:
        grouped_rows = [
            row for row in grouped_rows
            if _mobile_item_risk_state(row) == state["quick"]
        ]

    stats_queryset = queryset
    if state["low_stock"] or state["quick"]:
        stats_queryset = queryset.filter(
            item_id__in=[row["item_id"] for row in grouped_rows]
        )

    stock_stats = stats_queryset.aggregate(
        total_entries=Count("pk"),
        total_items=Count("item_id", distinct=True),
        total_quantity=Coalesce(Sum("quantity"), Value(zero_decimal)),
        total_reserved=Coalesce(Sum("reserved"), Value(zero_decimal)),
        total_available=Coalesce(Sum("available_qty"), Value(zero_decimal)),
    )

    paginator = Paginator(grouped_rows, options.page_size)
    items = paginator.get_page(params.get("page"))
    items.object_list = [_decorate_mobile_item_row(row) for row in items.object_list]

    location = state["location"]
    sumber_dana = state["sumber_dana"]
    therapeutic_class = state["therapeutic_class"]

    return {
        "items": items,
        "stock_stats": stock_stats,
        "quick_counts": quick_counts,
        "locations": _mobile_filter_options(state["locations"], location),
        "funding_sources": _mobile_filter_options(
            state["funding_sources"],
            sumber_dana,
        ),
        "therapeutic_classes": _mobile_filter_options(
            state["therapeutic_classes"],
            therapeutic_class,
        ),
        "search": state["search"],
        "selected_location": location or "",
        "selected_sumber_dana": sumber_dana or "",
        "selected_program": state["program"] or "",
        "selected_therapeutic_class": therapeutic_class or "",
        "selected_low_stock": state["low_stock"],
        "selected_quick": state["quick"],
        "expiry_from": state["expiry_from"],
        "expiry_to": state["expiry_to"],
        "near_expiry_days": options.near_expiry_days,
        "mobile_querystring": preserved_params.urlencode(),
    }


def build_mobile_stock_detail_context(item, params, *, options=None):
    options = options or StockListOptions()
    state = _build_mobile_stock_queryset(params, options=options)
    queryset = (
        state["queryset"]
        .filter(item=item)
        .order_by(F("expiry_date").asc(nulls_last=True), "location__name", "batch_lot")
    )

    quick_counts = queryset.aggregate(
        expired=Count("pk", filter=Q(expiry_date__lte=state["today"])),
        expiring=Count(
            "pk",
            filter=Q(
                expiry_date__gt=state["today"],
                expiry_date__lte=state["warning_threshold"],
            ),
        ),
        safe=Count(
            "pk",
            filter=Q(expiry_date__gt=state["warning_threshold"]) | Q(expiry_date__isnull=True),
        ),
    )

    if state["quick"] == "expired":
        queryset = queryset.filter(expiry_date__lte=state["today"])
    elif state["quick"] == "expiring":
        queryset = queryset.filter(
            expiry_date__gt=state["today"],
            expiry_date__lte=state["warning_threshold"],
        )
    elif state["quick"] == "safe":
        queryset = queryset.filter(
            Q(expiry_date__gt=state["warning_threshold"]) | Q(expiry_date__isnull=True)
        )

    batches = list(queryset)
    for stock in batches:
        (
            stock.expiry_badge_class,
            stock.expiry_badge_label,
            stock.days_until_expiry,
        ) = stock_expiry_badge(
            stock.expiry_date,
            state["today"],
            near_expiry_days=options.near_expiry_days,
        )

    stock_stats = queryset.aggregate(
        total_entries=Count("pk"),
        total_quantity=Coalesce(Sum("quantity"), Value(Decimal("0"))),
        total_reserved=Coalesce(Sum("reserved"), Value(Decimal("0"))),
        total_available=Coalesce(Sum("available_qty"), Value(Decimal("0"))),
    )

    return {
        "batches": batches,
        "stock_stats": stock_stats,
        "quick_counts": quick_counts,
        "selected_quick": state["quick"],
        "near_expiry_days": options.near_expiry_days,
    }


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
