from collections import defaultdict
from decimal import Decimal
from datetime import datetime, timedelta
from itertools import zip_longest
import logging
import unicodedata

from django.contrib import messages
from django.db import transaction as db_transaction
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import (
    Case,
    Count,
    DecimalField,
    ExpressionWrapper,
    Q,
    F,
    OuterRef,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.utils import timezone

from apps.core.decimal_validation import parse_decimal_input
from apps.core.decorators import perm_required
from apps.items.models import Facility, FundingSource, Item, Location
from apps.lplpo.models import LPLPO, LPLPOItem, normalize_whole_number
from apps.puskesmas.models import PuskesmasConsumptionEntry, PuskesmasReceiptConfirmation, PuskesmasReceiptConfirmationItem
from apps.users.models import User

from .forms import PuskesmasStockFilterForm, StockTransferForm
from .models import Stock, StockTransfer, StockTransferItem, Transaction

def _normalize_text_param(value, *, max_length=100):
    normalized = unicodedata.normalize("NFC", value or "")
    normalized = normalized.replace("\x00", "").strip()
    return normalized[:max_length]


def _parse_iso_date_param(value):
    raw_value = _normalize_text_param(value, max_length=10)
    if not raw_value:
        return None

    try:
        parsed = datetime.strptime(raw_value, "%Y-%m-%d").date()
    except ValueError:
        return None

    if parsed.year < 1000 or parsed.year > 9999:
        return None

    return parsed


def _resolve_selected_id(value, allowed_ids):
    raw_value = _normalize_text_param(value, max_length=20)
    if not raw_value.isdigit():
        return ""

    parsed_value = int(raw_value)
    if parsed_value not in allowed_ids:
        return ""

    return str(parsed_value)


def _stock_expiry_badge(expiry_date, today, *, near_expiry_days=90):
    if expiry_date is None:
        return "text-bg-secondary", "Tanpa kedaluwarsa", None

    days_until_expiry = (expiry_date - today).days
    if days_until_expiry <= 0:
        return "text-bg-danger", "Kedaluwarsa", days_until_expiry
    if days_until_expiry <= near_expiry_days:
        return "text-bg-warning", f"≤{near_expiry_days} hari", days_until_expiry
    return "text-bg-success", "Aman", days_until_expiry


def _funding_badge_class(funding_source):
    funding_code = (getattr(funding_source, "code", "") or "").strip().upper()
    if funding_code == "HIBAH":
        return "text-bg-warning"
    if funding_code == "DAU":
        return "text-bg-info"
    if funding_code == "PAD":
        return "text-bg-success"
    return "text-bg-secondary"


logger = logging.getLogger(__name__)


INDONESIAN_MONTH_LABELS = {
    1: "Januari",
    2: "Februari",
    3: "Maret",
    4: "April",
    5: "Mei",
    6: "Juni",
    7: "Juli",
    8: "Agustus",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Desember",
}


def _get_month_label(month_number):
    return INDONESIAN_MONTH_LABELS.get(int(month_number), str(month_number))


SNAPSHOT_BASELINE_LPLPO_STATUSES = frozenset(
    {
        LPLPO.Status.SUBMITTED,
        LPLPO.Status.PIC_VERIFIED,
        LPLPO.Status.REJECTED_PIC,
        LPLPO.Status.REVIEWED,
        LPLPO.Status.APPROVED,
        LPLPO.Status.DISTRIBUTED,
        LPLPO.Status.CLOSED,
    }
)


def _get_latest_lplpo_facilities(year, facility_id=""):
    facilities = Facility.objects.filter(
        facility_type=Facility.FacilityType.PUSKESMAS,
        is_active=True,
    ).order_by("name")
    if facility_id:
        facilities = facilities.filter(pk=int(facility_id))

    latest_lplpo_queryset = (
        LPLPO.objects.filter(
            facility=OuterRef("pk"),
            tahun=year,
            status__in=SNAPSHOT_BASELINE_LPLPO_STATUSES,
        )
        .order_by("-bulan", "-id")
    )
    return list(
        facilities.annotate(
            latest_lplpo_id=Subquery(latest_lplpo_queryset.values("id")[:1]),
            latest_lplpo_month=Subquery(latest_lplpo_queryset.values("bulan")[:1]),
        )
    )


def _build_ledgers_stats(rows, *, quantity_key, quantity_alias=None):
    total_quantity = 0
    visible_facilities = set()
    for row in rows:
        visible_facilities.add(row["facility_id"])
        total_quantity += row[quantity_key]

    stats = {
        "total_facilities": len(visible_facilities),
        "total_rows": len(rows),
        "total_quantity": total_quantity,
    }
    if quantity_alias:
        stats[quantity_alias] = total_quantity
    return stats


def _matches_stock_search(item_obj, search_term):
    if not search_term:
        return True
    normalized_search = search_term.casefold()
    return normalized_search in (item_obj.kode_barang or "").casefold() or normalized_search in (
        item_obj.nama_barang or ""
    ).casefold()


def _default_ledger_stats(*, quantity_alias=None):
    stats = {
        "total_facilities": 0,
        "total_rows": 0,
        "total_quantity": 0,
    }
    if quantity_alias:
        stats[quantity_alias] = 0
    return stats


def _get_receiving_ledger_base_queryset(year, facility_id="", search_term=""):
    queryset = PuskesmasReceiptConfirmationItem.objects.filter(
        sbbk__status=PuskesmasReceiptConfirmation.ReceiptStatus.CONFIRMED,
        sbbk__received_date__year=year,
    )
    if facility_id:
        queryset = queryset.filter(sbbk__facility_id=int(facility_id))
    if search_term:
        queryset = queryset.filter(
            Q(item__kode_barang__icontains=search_term)
            | Q(item__nama_barang__icontains=search_term)
        )
    return queryset


def _get_receiving_ledger_queryset(base_queryset):
    return (
        base_queryset.values(
            "sbbk__facility_id",
            "sbbk__facility__name",
            "item_id",
            "item__kode_barang",
            "item__nama_barang",
            "batch_lot",
            "expiry_date",
            "unit_price",
        )
        .annotate(total_received=Coalesce(Sum("quantity"), Value(Decimal("0"))))
        .order_by(
            "sbbk__facility__name",
            "item__nama_barang",
            "batch_lot",
            "expiry_date",
            "unit_price",
        )
    )


def _build_receiving_ledger_stats(year, facility_id="", search_term=""):
    base_queryset = _get_receiving_ledger_base_queryset(
        year,
        facility_id=facility_id,
        search_term=search_term,
    )
    grouped_queryset = _get_receiving_ledger_queryset(base_queryset)
    aggregates = base_queryset.aggregate(
        total_facilities=Count("sbbk__facility_id", distinct=True),
        total_received=Coalesce(Sum("quantity"), Value(Decimal("0"))),
    )
    return {
        "total_facilities": aggregates["total_facilities"] or 0,
        "total_rows": grouped_queryset.count(),
        "total_quantity": normalize_whole_number(aggregates["total_received"]),
        "total_received": normalize_whole_number(aggregates["total_received"]),
    }


def _build_receiving_ledger_page(year, facility_id="", search_term="", page_number=None):
    base_queryset = _get_receiving_ledger_base_queryset(
        year,
        facility_id=facility_id,
        search_term=search_term,
    )
    grouped_queryset = _get_receiving_ledger_queryset(base_queryset)
    page = _paginate_ledger_rows(grouped_queryset, page_number)
    rows = []
    for row in page.object_list:
        rows.append(
            {
                "facility_id": row["sbbk__facility_id"],
                "facility_name": row["sbbk__facility__name"],
                "item_id": row["item_id"],
                "kode_barang": row["item__kode_barang"],
                "nama_barang": row["item__nama_barang"],
                "batch_lot": row["batch_lot"] or "-",
                "expiry_date": row["expiry_date"],
                "expiry_display": row["expiry_date"].strftime("%d/%m/%Y")
                if row["expiry_date"]
                else "-",
                "unit_price": row["unit_price"] or Decimal("0"),
                "total_received": normalize_whole_number(row["total_received"]),
            }
        )
    page.object_list = rows
    return {
        "rows": rows,
        "page": page,
        "stats": _build_receiving_ledger_stats(
            year,
            facility_id=facility_id,
            search_term=search_term,
        ),
    }


def _get_consumption_ledger_base_queryset(year, facility_id="", search_term=""):
    queryset = PuskesmasConsumptionEntry.objects.filter(consumption__tahun=year)
    if facility_id:
        queryset = queryset.filter(consumption__facility_id=int(facility_id))
    if search_term:
        queryset = queryset.filter(
            Q(item__kode_barang__icontains=search_term)
            | Q(item__nama_barang__icontains=search_term)
        )
    return queryset


def _get_consumption_ledger_queryset(base_queryset):
    return (
        base_queryset.values(
            "consumption__facility_id",
            "consumption__facility__name",
            "item_id",
            "item__kode_barang",
            "item__nama_barang",
            "item__kategori__name",
            "item__satuan__name",
        )
        .annotate(total_consumption=Coalesce(Sum("quantity"), Value(0)))
        .order_by(
            "consumption__facility__name",
            "item__kategori__sort_order",
            "item__nama_barang",
        )
    )


def _build_consumption_ledger_stats(year, facility_id="", search_term=""):
    base_queryset = _get_consumption_ledger_base_queryset(
        year,
        facility_id=facility_id,
        search_term=search_term,
    )
    grouped_queryset = _get_consumption_ledger_queryset(base_queryset)
    aggregates = base_queryset.aggregate(
        total_facilities=Count("consumption__facility_id", distinct=True),
        total_consumption=Coalesce(Sum("quantity"), Value(0)),
    )
    return {
        "total_facilities": aggregates["total_facilities"] or 0,
        "total_rows": grouped_queryset.count(),
        "total_quantity": int(aggregates["total_consumption"] or 0),
        "total_consumption": int(aggregates["total_consumption"] or 0),
    }


def _build_consumption_ledger_page(year, facility_id="", search_term="", page_number=None):
    base_queryset = _get_consumption_ledger_base_queryset(
        year,
        facility_id=facility_id,
        search_term=search_term,
    )
    grouped_queryset = _get_consumption_ledger_queryset(base_queryset)
    page = _paginate_ledger_rows(grouped_queryset, page_number)
    rows = []
    for row in page.object_list:
        rows.append(
            {
                "facility_id": row["consumption__facility_id"],
                "facility_name": row["consumption__facility__name"],
                "item_id": row["item_id"],
                "kode_barang": row["item__kode_barang"],
                "nama_barang": row["item__nama_barang"],
                "kategori": row["item__kategori__name"] or "Lainnya",
                "satuan": row["item__satuan__name"] or "-",
                "total_consumption": int(row["total_consumption"] or 0),
            }
        )
    page.object_list = rows
    return {
        "rows": rows,
        "page": page,
        "stats": _build_consumption_ledger_stats(
            year,
            facility_id=facility_id,
            search_term=search_term,
        ),
    }


def _build_puskesmas_stock_snapshot(year, facility_id="", search_term="", page_number=None, include_rows=True):
    facilities = _get_latest_lplpo_facilities(year, facility_id=facility_id)
    latest_facilities = [facility for facility in facilities if facility.latest_lplpo_id]
    if not latest_facilities:
        return {
            "rows": [],
            "page": _paginate_ledger_rows([], page_number),
            "stats": {
                "total_facilities": 0,
                "total_rows": 0,
                "total_quantity": 0,
                "total_item_rows": 0,
                "total_stock": 0,
            },
        }

    facility_state = {
        facility.pk: {
            "facility_name": facility.name,
            "base_month": int(facility.latest_lplpo_month),
            "latest_lplpo_id": int(facility.latest_lplpo_id),
        }
        for facility in latest_facilities
    }
    facility_ids = list(facility_state.keys())
    latest_lplpo_ids = [state["latest_lplpo_id"] for state in facility_state.values()]

    receipt_adjustments = defaultdict(int)
    receipt_rows = (
        PuskesmasReceiptConfirmationItem.objects.filter(
            sbbk__facility_id__in=facility_ids,
            sbbk__received_date__year=year,
            sbbk__status=PuskesmasReceiptConfirmation.ReceiptStatus.CONFIRMED,
        )
        .values("sbbk__facility_id", "item_id", "sbbk__received_date__month")
        .annotate(total=Coalesce(Sum("quantity"), Value(Decimal("0"))))
    )
    for row in receipt_rows:
        facility_pk = row["sbbk__facility_id"]
        if row["sbbk__received_date__month"] > facility_state[facility_pk]["base_month"]:
            receipt_adjustments[(facility_pk, row["item_id"])] += normalize_whole_number(row["total"])

    consumption_adjustments = defaultdict(int)
    consumption_rows = (
        PuskesmasConsumptionEntry.objects.filter(
            consumption__facility_id__in=facility_ids,
            consumption__tahun=year,
        )
        .values("consumption__facility_id", "item_id", "consumption__bulan")
        .annotate(total=Coalesce(Sum("quantity"), Value(0)))
    )
    for row in consumption_rows:
        facility_pk = row["consumption__facility_id"]
        if row["consumption__bulan"] > facility_state[facility_pk]["base_month"]:
            consumption_adjustments[(facility_pk, row["item_id"])] += int(row["total"] or 0)

    lplpo_items = list(
        LPLPOItem.objects.filter(lplpo_id__in=latest_lplpo_ids)
        .select_related("item", "item__satuan", "item__kategori", "lplpo", "lplpo__facility")
        .order_by("lplpo__facility__name", "item__kategori__sort_order", "item__nama_barang")
    )
    baseline_items = {(row.lplpo.facility_id, row.item_id): row for row in lplpo_items}
    adjustment_keys = set(receipt_adjustments.keys()) | set(consumption_adjustments.keys())
    row_keys = set(baseline_items.keys()) | adjustment_keys

    if not row_keys:
        return {
            "rows": [],
            "page": _paginate_ledger_rows([], page_number),
            "stats": {
                "total_facilities": 0,
                "total_rows": 0,
                "total_quantity": 0,
                "total_item_rows": 0,
                "total_stock": 0,
            },
        }

    baseline_item_ids = {row.item_id for row in lplpo_items}
    missing_item_ids = {item_id for _, item_id in row_keys if item_id not in baseline_item_ids}
    adjustment_items = {
        item.pk: item
        for item in Item.objects.filter(pk__in=missing_item_ids).select_related("satuan", "kategori")
    }

    def _get_snapshot_item_obj(row_key):
        baseline_row = baseline_items.get(row_key)
        if baseline_row is not None:
            return baseline_row.item
        return adjustment_items[row_key[1]]

    stock_rows = []
    total_stock = 0
    total_rows = 0
    visible_facilities = set()
    for facility_pk, item_id in sorted(
        row_keys,
        key=lambda key: (
            facility_state[key[0]]["facility_name"],
            _get_snapshot_item_obj(key).kategori.sort_order
            if _get_snapshot_item_obj(key).kategori
            else 999999,
            _get_snapshot_item_obj(key).nama_barang,
        ),
    ):
        baseline_row = baseline_items.get((facility_pk, item_id))
        item_obj = _get_snapshot_item_obj((facility_pk, item_id))
        if not _matches_stock_search(item_obj, search_term):
            continue

        receipt_adjustment = receipt_adjustments[(facility_pk, item_id)]
        consumption_adjustment = consumption_adjustments[(facility_pk, item_id)]
        baseline_stock = (
            normalize_whole_number(baseline_row.stock_keseluruhan)
            if baseline_row is not None
            else 0
        )
        current_stock = baseline_stock + receipt_adjustment - consumption_adjustment
        total_stock += current_stock
        total_rows += 1
        visible_facilities.add(facility_pk)

        if not include_rows:
            continue

        category_name = item_obj.kategori.name if item_obj.kategori else "Lainnya"
        minimum_stock = normalize_whole_number(item_obj.minimum_stock)
        base_month = facility_state[facility_pk]["base_month"]
        stock_rows.append(
            {
                "facility_id": facility_pk,
                "facility_name": facility_state[facility_pk]["facility_name"],
                "kode_barang": item_obj.kode_barang,
                "nama_barang": item_obj.nama_barang,
                "kategori": category_name,
                "kategori_key": unicodedata.normalize("NFC", category_name).strip().casefold(),
                "satuan": item_obj.satuan.name if item_obj.satuan else "-",
                "stock_current": current_stock,
                "minimum_stock": minimum_stock,
                "is_below_threshold": current_stock < minimum_stock,
                "base_month": base_month,
                "base_month_label": _get_month_label(base_month),
                "receipt_adjustment": receipt_adjustment,
                "consumption_adjustment": consumption_adjustment,
            }
        )

    stats = {
        "total_facilities": len(visible_facilities),
        "total_rows": total_rows,
        "total_quantity": total_stock,
        "total_item_rows": total_rows,
        "total_stock": total_stock,
    }
    if not include_rows:
        return {
            "rows": [],
            "page": _paginate_ledger_rows([], page_number),
            "stats": stats,
        }

    page = _paginate_ledger_rows(stock_rows, page_number)
    page.object_list = list(page.object_list)
    return {
        "rows": list(page.object_list),
        "page": page,
        "stats": stats,
    }


def _paginate_ledger_rows(rows, page_number):
    paginator = Paginator(rows, 25)
    return paginator.get_page(page_number)


@login_required
@perm_required("stock.view_stock")
def puskesmas_stock(request):
    if request.user.role == User.Role.PUSKESMAS:
        raise PermissionDenied("Operator Puskesmas tidak dapat mengakses stok Puskesmas lintas fasilitas.")

    initial = PuskesmasStockFilterForm.get_default_initial()
    effective_get = request.GET.copy()
    for key, value in initial.items():
        if not effective_get.get(key):
            effective_get[key] = str(value)

    filter_form = PuskesmasStockFilterForm(effective_get)
    selected_facility = None
    active_tab = PuskesmasStockFilterForm.TAB_STOCK
    search_term = ""
    selected_year = initial["year"]
    ledger_rows = []
    ledger_page = _paginate_ledger_rows([], request.GET.get("page"))
    ledger_stats = _default_ledger_stats()
    receiving_rows = []
    consumption_rows = []
    stock_rows = []
    receiving_stats = _default_ledger_stats(quantity_alias="total_received")
    consumption_stats = _default_ledger_stats(quantity_alias="total_consumption")
    stock_stats = {
        "total_facilities": 0,
        "total_rows": 0,
        "total_quantity": 0,
        "total_item_rows": 0,
        "total_stock": 0,
    }

    if filter_form.is_valid():
        selected_year = filter_form.cleaned_data["year"]
        selected_facility_id = filter_form.cleaned_data["facility"]
        active_tab = filter_form.cleaned_data["tab"]
        search_term = filter_form.cleaned_data["q"]
        if selected_facility_id:
            selected_facility = Facility.objects.filter(pk=int(selected_facility_id)).first()

        if active_tab == PuskesmasStockFilterForm.TAB_RECEIVING:
            receiving_ledger = _build_receiving_ledger_page(
                selected_year,
                facility_id=selected_facility_id,
                search_term=search_term,
                page_number=request.GET.get("page"),
            )
            receiving_rows = receiving_ledger["rows"]
            receiving_stats = receiving_ledger["stats"]
            ledger_rows = receiving_rows
            ledger_page = receiving_ledger["page"]
            ledger_stats = receiving_stats
            consumption_stats = _build_consumption_ledger_stats(
                selected_year,
                facility_id=selected_facility_id,
                search_term=search_term,
            )
            stock_stats = _build_puskesmas_stock_snapshot(
                selected_year,
                facility_id=selected_facility_id,
                search_term=search_term,
                include_rows=False,
            )["stats"]
        elif active_tab == PuskesmasStockFilterForm.TAB_CONSUMPTION:
            consumption_ledger = _build_consumption_ledger_page(
                selected_year,
                facility_id=selected_facility_id,
                search_term=search_term,
                page_number=request.GET.get("page"),
            )
            consumption_rows = consumption_ledger["rows"]
            consumption_stats = consumption_ledger["stats"]
            ledger_rows = consumption_rows
            ledger_page = consumption_ledger["page"]
            ledger_stats = consumption_stats
            receiving_stats = _build_receiving_ledger_stats(
                selected_year,
                facility_id=selected_facility_id,
                search_term=search_term,
            )
            stock_stats = _build_puskesmas_stock_snapshot(
                selected_year,
                facility_id=selected_facility_id,
                search_term=search_term,
                include_rows=False,
            )["stats"]
        else:
            stock_snapshot = _build_puskesmas_stock_snapshot(
                selected_year,
                facility_id=selected_facility_id,
                search_term=search_term,
                page_number=request.GET.get("page"),
            )
            stock_rows = stock_snapshot["rows"]
            stock_stats = stock_snapshot["stats"]
            ledger_rows = stock_rows
            ledger_page = stock_snapshot["page"]
            ledger_stats = stock_stats
            receiving_stats = _build_receiving_ledger_stats(
                selected_year,
                facility_id=selected_facility_id,
                search_term=search_term,
            )
            consumption_stats = _build_consumption_ledger_stats(
                selected_year,
                facility_id=selected_facility_id,
                search_term=search_term,
            )

        logger.info(
            "puskesmas_stock_viewed",
            extra={
                "username": request.user.username,
                "role": request.user.role,
                "year": selected_year,
                "facility_id": int(selected_facility_id) if selected_facility_id else None,
                "tab": active_tab,
                "has_search_term": bool(search_term),
            },
        )

    tabs = [
        {
            "key": PuskesmasStockFilterForm.TAB_RECEIVING,
            "label": "Penerimaan",
            "count": receiving_stats.get("total_rows", 0),
        },
        {
            "key": PuskesmasStockFilterForm.TAB_CONSUMPTION,
            "label": "Pemakaian",
            "count": consumption_stats.get("total_rows", 0),
        },
        {
            "key": PuskesmasStockFilterForm.TAB_STOCK,
            "label": "Stok Saat Ini",
            "count": stock_stats.get("total_rows", 0),
        },
    ]

    return render(
        request,
        "stock/puskesmas_stock.html",
        {
            "filter_form": filter_form,
            "selected_facility": selected_facility,
            "selected_year": selected_year,
            "search_term": search_term,
            "active_tab": active_tab,
            "tabs": tabs,
            "ledger_page": ledger_page,
            "ledger_rows": ledger_rows,
            "ledger_stats": ledger_stats,
            "receiving_rows": receiving_rows,
            "receiving_stats": receiving_stats,
            "consumption_rows": consumption_rows,
            "consumption_stats": consumption_stats,
            "stock_rows": stock_rows,
            "stock_stats": stock_stats,
        },
    )


@login_required
@perm_required("stock.view_stock")
def stock_list(request):
    today = timezone.localdate()
    near_expiry_days = 90
    warning_threshold = today + timedelta(days=near_expiry_days)
    zero_decimal = Decimal("0")
    available_quantity_expression = ExpressionWrapper(
        F("quantity") - F("reserved"),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )

    active_locations = list(Location.objects.filter(is_active=True).order_by("name"))
    active_funding_sources = list(
        FundingSource.objects.filter(is_active=True).order_by("name")
    )
    active_location_ids = {location.id for location in active_locations}
    active_funding_source_ids = {source.id for source in active_funding_sources}

    queryset = (
        Stock.objects.select_related("item", "item__satuan", "location", "sumber_dana")
        .filter(quantity__gt=0)
        .order_by("item__nama_barang", F("expiry_date").asc(nulls_last=True))
    )

    search = _normalize_text_param(request.GET.get("q", ""), max_length=100)
    if search:
        queryset = queryset.filter(
            Q(item__kode_barang__icontains=search)
            | Q(item__nama_barang__icontains=search)
            | Q(batch_lot__icontains=search)
        )

    location = _resolve_selected_id(request.GET.get("location"), active_location_ids)
    if location:
        queryset = queryset.filter(location_id=int(location))

    sumber_dana = _resolve_selected_id(
        request.GET.get("sumber_dana"), active_funding_source_ids
    )
    if sumber_dana:
        queryset = queryset.filter(sumber_dana_id=int(sumber_dana))

    expiry_from = _parse_iso_date_param(request.GET.get("expiry_from"))
    if expiry_from:
        queryset = queryset.filter(expiry_date__gte=expiry_from)

    expiry_to = _parse_iso_date_param(request.GET.get("expiry_to"))
    if expiry_to:
        queryset = queryset.filter(expiry_date__lte=expiry_to)

    quick = _normalize_text_param(request.GET.get("quick", ""), max_length=20)
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
            Sum(available_quantity_expression),
            Value(zero_decimal),
        ),
        attention_count=Count("pk", filter=Q(expiry_date__lte=warning_threshold)),
    )

    paginator = Paginator(queryset, 25)
    stocks = paginator.get_page(request.GET.get("page"))
    for stock in stocks.object_list:
        (
            stock.expiry_badge_class,
            stock.expiry_badge_label,
            stock.days_until_expiry,
        ) = _stock_expiry_badge(
            stock.expiry_date,
            today,
            near_expiry_days=near_expiry_days,
        )
        stock.source_fund_badge_class = _funding_badge_class(stock.sumber_dana)

    locations = []
    for loc in active_locations:
        locations.append(
            {
                "id": loc.id,
                "name": loc.name,
                "selected": "selected" if location == str(loc.id) else "",
            }
        )

    funding_sources = []
    for sd in active_funding_sources:
        funding_sources.append(
            {
                "id": sd.id,
                "name": sd.name,
                "selected": "selected" if sumber_dana == str(sd.id) else "",
            }
        )

    return render(
        request,
        "stock/stock_list.html",
        {
            "stocks": stocks,
            "stock_stats": stock_stats,
            "quick_counts": quick_counts,
            "locations": locations,
            "funding_sources": funding_sources,
            "search": search,
            "selected_location": location or "",
            "selected_sumber_dana": sumber_dana or "",
            "selected_quick": quick,
            "expiry_from": expiry_from,
            "expiry_to": expiry_to,
        },
    )

@login_required
@perm_required("stock.view_transaction")
def transaction_list(request):
    queryset = Transaction.objects.select_related("item", "user", "location").order_by(
        "-created_at"
    )

    search = request.GET.get("q", "").strip()
    if search:
        queryset = queryset.filter(
            Q(item__kode_barang__icontains=search)
            | Q(item__nama_barang__icontains=search)
            | Q(batch_lot__icontains=search)
            | Q(notes__icontains=search)
        )

    tx_type = request.GET.get("type")
    if tx_type:
        queryset = queryset.filter(transaction_type=tx_type)

    paginator = Paginator(queryset, 25)
    transactions = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "stock/transaction_list.html",
        {
            "transactions": transactions,
            "search": search,
            "selected_type": tx_type or "",
            "type_in": "selected" if tx_type == "IN" else "",
            "type_out": "selected" if tx_type == "OUT" else "",
            "type_adjust": "selected" if tx_type == "ADJUST" else "",
            "type_return": "selected" if tx_type == "RETURN" else "",
        },
    )


@login_required
@perm_required("stock.view_stock")
def stock_card_select(request):
    """Landing page for selecting an item to view its stock card."""
    recent_ids = request.session.get("stock_card_recent_items", [])
    recent_items = []
    if recent_ids:
        items_by_id = {
            item.id: item
            for item in Item.objects.filter(
                id__in=recent_ids, is_active=True
            ).select_related("satuan", "kategori")
        }
        recent_items = [
            items_by_id[item_id] for item_id in recent_ids if item_id in items_by_id
        ]

    return render(
        request,
        "stock/stock_card_select.html",
        {"recent_items": recent_items},
    )


def _parse_filter_date(value):
    """Parse a date string from dd/mm/yyyy or yyyy-mm-dd format."""
    if not value:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _get_stock_card_activity_label(tx):
    if tx.reference_type == Transaction.ReferenceType.TRANSFER:
        if tx.transaction_type == Transaction.TransactionType.IN:
            return "Mutasi Masuk"
        return "Mutasi Keluar"

    activity_labels = {
        Transaction.ReferenceType.RECEIVING: "Penerimaan",
        Transaction.ReferenceType.DISTRIBUTION: "Distribusi",
        Transaction.ReferenceType.RECALL: "Recall",
        Transaction.ReferenceType.EXPIRED: "Kedaluwarsa",
        Transaction.ReferenceType.ALLOCATION: "Alokasi",
        Transaction.ReferenceType.ADJUSTMENT: "Penyesuaian",
        Transaction.ReferenceType.INITIAL_IMPORT: "Import Awal",
    }
    return activity_labels.get(tx.reference_type, tx.get_reference_type_display())


def _get_stock_card_counterparty_label(tx, *, facility_name, receiving_map, distribution_map, recall_map):
    internal_reference_types = {
        Transaction.ReferenceType.RECEIVING,
        Transaction.ReferenceType.TRANSFER,
        Transaction.ReferenceType.EXPIRED,
        Transaction.ReferenceType.ALLOCATION,
        Transaction.ReferenceType.ADJUSTMENT,
        Transaction.ReferenceType.INITIAL_IMPORT,
    }
    if tx.reference_type in internal_reference_types:
        return facility_name
    if tx.reference_type == Transaction.ReferenceType.DISTRIBUTION:
        return distribution_map.get(tx.reference_id, "")
    if tx.reference_type == Transaction.ReferenceType.RECALL:
        return recall_map.get(tx.reference_id, "")
    return receiving_map.get(tx.reference_id, "")


def _build_stock_card_data(item, location_id=None, sumber_dana_id=None,
                           date_from=None, date_to=None):
    """Build per-sumber-dana stock card data for a given item.

    Returns a dict with:
      - funding_source_cards: list of card dicts grouped by sumber_dana
      - locations: available location filter options
      - funding_sources: available sumber_dana filter options
      - date_from / date_to: parsed dates
      - budget_year: current year
    """
    from collections import OrderedDict
    from apps.receiving.models import ReceivingItem
    from apps.core.models import SystemSettings

    queryset = (
        Transaction.objects.filter(item=item)
        .select_related("location", "user", "sumber_dana")
        .order_by("created_at", "id")
    )

    if location_id:
        queryset = queryset.filter(location_id=location_id)
    if sumber_dana_id:
        queryset = queryset.filter(sumber_dana_id=sumber_dana_id)
    if date_from:
        queryset = queryset.filter(created_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(created_at__date__lte=date_to)

    transactions = list(queryset)
    facility_name = SystemSettings.get_settings().facility_name

    # Pre-fetch batch expiry dates keyed by the same stock scope used by transactions.
    batch_expiry_map = {
        (batch_lot, location_id, sumber_dana_id): expiry_date
        for batch_lot, location_id, sumber_dana_id, expiry_date in (
            Stock.objects.filter(item=item)
            .values_list("batch_lot", "location_id", "sumber_dana_id", "expiry_date")
            .distinct()
        )
    }

    # ── Resolve document number labels ───────────────────────────────
    ref_id_sets = {}
    for tx in transactions:
        if tx.reference_id:
            ref_id_sets.setdefault(tx.reference_type, set()).add(tx.reference_id)

    reference_labels = {}
    _ref_model_map = {
        Transaction.ReferenceType.RECEIVING: ("apps.receiving.models", "Receiving"),
        Transaction.ReferenceType.DISTRIBUTION: ("apps.distribution.models", "Distribution"),
        Transaction.ReferenceType.RECALL: ("apps.recall.models", "Recall"),
        Transaction.ReferenceType.EXPIRED: ("apps.expired.models", "Expired"),
        Transaction.ReferenceType.TRANSFER: ("apps.stock.models", "StockTransfer"),
    }
    for ref_type, ids in ref_id_sets.items():
        entry = _ref_model_map.get(ref_type)
        if not entry:
            continue
        module_path, class_name = entry
        import importlib
        mod = importlib.import_module(module_path)
        model_cls = getattr(mod, class_name)
        reference_labels[ref_type] = {
            doc.id: doc.document_number
            for doc in model_cls.objects.filter(id__in=ids).only(
                "id", "document_number"
            )
        }

    # ── Resolve supplier/facility names for DARI/KEPADA ──────────────
    receiving_supplier_map = {}
    distribution_facility_map = {}
    recall_supplier_map = {}

    recv_ids = ref_id_sets.get(Transaction.ReferenceType.RECEIVING, set())
    if recv_ids:
        from apps.receiving.models import Receiving
        for r in Receiving.objects.filter(id__in=recv_ids).select_related(
            "supplier", "facility"
        ).only("id", "supplier__name", "facility__name", "grant_origin"):
            if r.supplier:
                receiving_supplier_map[r.id] = r.supplier.name
            elif r.grant_origin:
                receiving_supplier_map[r.id] = r.grant_origin
            elif r.facility:
                receiving_supplier_map[r.id] = r.facility.name

    dist_ids = ref_id_sets.get(Transaction.ReferenceType.DISTRIBUTION, set())
    if dist_ids:
        from apps.distribution.models import Distribution
        for d in Distribution.objects.filter(id__in=dist_ids).select_related(
            "facility"
        ).only("id", "facility__name"):
            if d.facility:
                distribution_facility_map[d.id] = d.facility.name

    recall_ids = ref_id_sets.get(Transaction.ReferenceType.RECALL, set())
    if recall_ids:
        from apps.recall.models import Recall
        for recall in Recall.objects.filter(id__in=recall_ids).select_related(
            "supplier"
        ).only("id", "supplier__name"):
            recall_supplier_map[recall.id] = recall.supplier.name if recall.supplier else ""

    # ── Group by sumber_dana ─────────────────────────────────────────
    sd_groups = OrderedDict()
    for tx in transactions:
        sd_key = tx.sumber_dana_id or 0
        if sd_key not in sd_groups:
            sd_groups[sd_key] = {
                "sumber_dana": tx.sumber_dana,
                "transactions": [],
            }
        sd_groups[sd_key]["transactions"].append(tx)

    # ── Compute opening balances, running balances, and unit prices ───
    funding_source_cards = []
    for sd_key, group in sd_groups.items():
        sd_txs = group["transactions"]
        sd_obj = group["sumber_dana"]

        # Opening balance for this sumber_dana (aggregate in DB)
        opening_balance = Decimal("0")
        if date_from:
            past_qs = Transaction.objects.filter(
                item=item, created_at__date__lt=date_from
            )
            if location_id:
                past_qs = past_qs.filter(location_id=location_id)
            if sd_key:
                past_qs = past_qs.filter(sumber_dana_id=sd_key)
            agg = past_qs.aggregate(
                balance=Coalesce(
                    Sum(
                        Case(
                            When(
                                transaction_type__in=[
                                    Transaction.TransactionType.IN,
                                    Transaction.TransactionType.RETURN,
                                ],
                                then=F("quantity"),
                            ),
                            default=-F("quantity"),
                        )
                    ),
                    Value(Decimal("0")),
                )
            )
            opening_balance = agg["balance"]

        # Unit price from Receiving module for this item + sumber_dana.
        # Fallback chain:
        #   1. ReceivingItem where the Receiving header matches this sumber_dana
        #   2. Stock.unit_price for this item + sumber_dana (covers initial imports
        #      where the Receiving header sumber_dana differs from Stock sumber_dana)
        #   3. Latest Transaction.unit_price for this item + sumber_dana
        unit_price = Decimal("0")
        if sd_key:
            ri = (
                ReceivingItem.objects.filter(
                    item=item,
                    receiving__sumber_dana_id=sd_key,
                    unit_price__gt=0,
                )
                .order_by("-receiving__receiving_date", "-pk")
                .values_list("unit_price", flat=True)
                .first()
            )
            if ri:
                unit_price = ri

        if not unit_price and sd_key:
            stock_price = (
                Stock.objects.filter(item=item, sumber_dana_id=sd_key)
                .exclude(unit_price=0)
                .order_by("-pk")
                .values_list("unit_price", flat=True)
                .first()
            )
            if stock_price:
                unit_price = stock_price

        if not unit_price:
            tx_price = (
                Transaction.objects.filter(item=item)
                .filter(sumber_dana_id=sd_key if sd_key else None)
                .exclude(unit_price__isnull=True)
                .exclude(unit_price=0)
                .order_by("-created_at")
                .values_list("unit_price", flat=True)
                .first()
            )
            if tx_price:
                unit_price = tx_price

        # Running balance and totals
        current_balance = opening_balance
        total_in = Decimal("0")
        total_out = Decimal("0")

        for tx in sd_txs:
            tx_in = Decimal("0")
            tx_out = Decimal("0")

            if tx.transaction_type in [
                Transaction.TransactionType.IN,
                Transaction.TransactionType.RETURN,
            ]:
                tx_in = tx.quantity
                current_balance += tx_in
                if tx.reference_type != Transaction.ReferenceType.TRANSFER:
                    total_in += tx_in
            else:
                tx_out = tx.quantity
                current_balance -= tx_out
                if tx.reference_type != Transaction.ReferenceType.TRANSFER:
                    total_out += tx_out

            tx.tx_in = tx_in
            tx.tx_out = tx_out
            tx.running_balance = current_balance
            tx.reference_label = reference_labels.get(
                tx.reference_type, {}
            ).get(
                tx.reference_id,
                f"{tx.reference_type}-{tx.reference_id}",
            )
            tx.dari_kepada = _get_stock_card_counterparty_label(
                tx,
                facility_name=facility_name,
                receiving_map=receiving_supplier_map,
                distribution_map=distribution_facility_map,
                recall_map=recall_supplier_map,
            )
            tx.location_label = tx.location.name if tx.location_id else ""

            # Expiry date from batch if available (pre-fetched)
            tx.expiry_display = ""
            if tx.batch_lot:
                batch_scope = (tx.batch_lot, tx.location_id, tx.sumber_dana_id)
                expiry_date = batch_expiry_map.get(batch_scope)
                if expiry_date:
                    tx.expiry_display = expiry_date.strftime("%d/%m/%Y")
                elif batch_scope in batch_expiry_map:
                    tx.expiry_display = "Tanpa kedaluwarsa"

            # Mark transfers for informational display
            tx.is_transfer_transaction = tx.reference_type == Transaction.ReferenceType.TRANSFER
            tx.transfer_quantity = tx.quantity if tx.is_transfer_transaction else None
            tx.activity_label = _get_stock_card_activity_label(tx)

        # Determine Tahun Anggaran from earliest receiving year
        tahun_anggaran = timezone.now().year
        if sd_key:
            from apps.receiving.models import Receiving
            earliest_recv = (
                Receiving.objects.filter(
                    sumber_dana_id=sd_key,
                    items__item=item,
                )
                .order_by("receiving_date")
                .values_list("receiving_date", flat=True)
                .first()
            )
            if earliest_recv:
                tahun_anggaran = earliest_recv.year

        funding_source_cards.append({
            "sumber_dana": sd_obj,
            "unit_price": unit_price,
            "opening_balance": opening_balance,
            "show_opening_balance": bool(date_from),
            "closing_balance": current_balance,
            "total_in": total_in,
            "total_out": total_out,
            "transactions": sd_txs,
            "tahun_anggaran": tahun_anggaran,
        })

    # ── Filter dropdown data ─────────────────────────────────────────
    locations_list = []
    for loc in Location.objects.filter(is_active=True):
        locations_list.append({
            "id": loc.id,
            "name": loc.name,
            "selected": "selected" if location_id == str(loc.id) else "",
        })

    funding_sources_list = []
    for sd in FundingSource.objects.filter(is_active=True):
        funding_sources_list.append({
            "id": sd.id,
            "name": f"{sd.code} - {sd.name}",
            "selected": "selected" if sumber_dana_id == str(sd.id) else "",
        })

    return {
        "funding_source_cards": funding_source_cards,
        "locations": locations_list,
        "funding_sources": funding_sources_list,
        "budget_year": timezone.now().year,
    }


@login_required
@perm_required("stock.view_stock")
def stock_card_detail(request, item_id):
    """View the stock card (running balance) for a specific item, grouped by sumber dana."""
    item = get_object_or_404(Item, pk=item_id)

    recent_ids = request.session.get("stock_card_recent_items", [])
    recent_ids = [rid for rid in recent_ids if rid != item.id]
    recent_ids.insert(0, item.id)
    request.session["stock_card_recent_items"] = recent_ids[:8]

    location_id = request.GET.get("location")
    sumber_dana_id = request.GET.get("sumber_dana")
    date_from_raw = request.GET.get("date_from", "").strip()
    date_to_raw = request.GET.get("date_to", "").strip()
    date_from = _parse_filter_date(date_from_raw)
    date_to = _parse_filter_date(date_to_raw)

    data = _build_stock_card_data(
        item,
        location_id=location_id,
        sumber_dana_id=sumber_dana_id,
        date_from=date_from,
        date_to=date_to,
    )

    context = {
        "item": item,
        **data,
        "date_from": date_from.strftime("%d/%m/%Y")
        if date_from
        else (date_from_raw or ""),
        "date_to": date_to.strftime("%d/%m/%Y") if date_to else (date_to_raw or ""),
        "selected_location": location_id or "",
        "selected_sumber_dana": sumber_dana_id or "",
    }
    return render(request, "stock/stock_card_detail.html", context)


@login_required
@perm_required("stock.view_stock")
def stock_card_print(request, item_id):
    """Standalone print view for government-style Kartu Stok."""
    item = get_object_or_404(Item, pk=item_id)

    location_id = request.GET.get("location")
    sumber_dana_id = request.GET.get("sumber_dana")
    date_from_raw = request.GET.get("date_from", "").strip()
    date_to_raw = request.GET.get("date_to", "").strip()
    date_from = _parse_filter_date(date_from_raw)
    date_to = _parse_filter_date(date_to_raw)

    data = _build_stock_card_data(
        item,
        location_id=location_id,
        sumber_dana_id=sumber_dana_id,
        date_from=date_from,
        date_to=date_to,
    )

    context = {
        "item": item,
        **data,
        "date_from": date_from.strftime("%d/%m/%Y")
        if date_from
        else (date_from_raw or ""),
        "date_to": date_to.strftime("%d/%m/%Y") if date_to else (date_to_raw or ""),
    }
    return render(request, "stock/stock_card_print.html", context)


@login_required
@perm_required("stock.view_stock")
def api_item_search(request):
    """AJAX endpoint for item typeahead."""
    q = request.GET.get("q", "").strip()
    if not q:
        return JsonResponse({"results": []})

    items = (
        Item.objects.filter(is_active=True)
        .filter(Q(kode_barang__icontains=q) | Q(nama_barang__icontains=q))
        .annotate(
            total_stock=Coalesce(
                Sum("stock_entries__quantity"), Value(Decimal("0"))
            )
        )
        .select_related("satuan", "kategori")[:20]
    )

    results = []
    for item in items:
        results.append(
            {
                "id": item.id,
                "text": f"{item.kode_barang} - {item.nama_barang}",
                "satuan": item.satuan.name if item.satuan else "",
                "kategori": item.kategori.name if item.kategori else "",
                "stock": float(item.total_stock.quantize(Decimal("0.01"))),
            }
        )

    return JsonResponse({"results": results})


@login_required
@perm_required("stock.view_stocktransfer")
def transfer_list(request):
    queryset = StockTransfer.objects.select_related(
        "source_location", "destination_location", "created_by", "completed_by"
    ).order_by("-transfer_date", "-created_at")

    search = request.GET.get("q", "").strip()
    if search:
        queryset = queryset.filter(
            Q(document_number__icontains=search)
            | Q(source_location__name__icontains=search)
            | Q(destination_location__name__icontains=search)
        )

    status = request.GET.get("status", "")
    if status:
        queryset = queryset.filter(status=status)

    paginator = Paginator(queryset, 25)
    transfers = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "stock/transfer_list.html",
        {
            "transfers": transfers,
            "search": search,
            "selected_status": status,
            "status_draft": "selected" if status == StockTransfer.Status.DRAFT else "",
            "status_completed": "selected"
            if status == StockTransfer.Status.COMPLETED
            else "",
        },
    )


def _validate_transfer_create_lines(stock_ids, qty_values, source_location_id):
    submitted_lines = []
    row_errors = []
    valid_lines = []
    referenced_stock_ids = set()

    for index, (stock_id_raw, qty_raw) in enumerate(
        zip_longest(stock_ids, qty_values, fillvalue=""),
        start=1,
    ):
        stock_id_text = str(stock_id_raw or "").strip()
        quantity_text = str(qty_raw or "").strip()
        submitted_lines.append(
            {
                "row_number": index,
                "stock_id": stock_id_text,
                "quantity": quantity_text,
                "errors": [],
            }
        )
        if stock_id_text:
            try:
                referenced_stock_ids.add(int(stock_id_text))
            except (TypeError, ValueError):
                continue

    stocks_by_id = (
        Stock.objects.filter(pk__in=referenced_stock_ids)
        .select_related("item", "location")
        .in_bulk()
    )

    for submitted_line in submitted_lines:
        quantity_text = submitted_line["quantity"]
        if not quantity_text:
            continue

        try:
            quantity = parse_decimal_input(
                quantity_text,
                field_label="Jumlah mutasi",
                allow_empty=True,
            )
        except ValidationError as exc:
            submitted_line["errors"].extend(exc.messages)
            row_errors.extend(
                f"Baris {submitted_line['row_number']}: {message}"
                for message in exc.messages
            )
            continue

        if quantity is None or quantity == 0:
            continue

        if quantity < 0:
            error_message = "Jumlah mutasi harus lebih dari 0."
            submitted_line["errors"].append(error_message)
            row_errors.append(f"Baris {submitted_line['row_number']}: {error_message}")
            continue

        stock_id_text = submitted_line["stock_id"]
        try:
            stock_id = int(stock_id_text)
        except (TypeError, ValueError):
            error_message = "Batch stok sumber tidak valid."
            submitted_line["errors"].append(error_message)
            row_errors.append(f"Baris {submitted_line['row_number']}: {error_message}")
            continue

        stock = stocks_by_id.get(stock_id)
        if not stock:
            error_message = "Batch stok sumber tidak ditemukan."
            submitted_line["errors"].append(error_message)
            row_errors.append(f"Baris {submitted_line['row_number']}: {error_message}")
            continue
        if stock.location_id != source_location_id:
            error_message = "Batch stok tidak berada di lokasi asal yang dipilih."
            submitted_line["errors"].append(error_message)
            row_errors.append(f"Baris {submitted_line['row_number']}: {error_message}")
            continue
        if quantity > stock.available_quantity:
            error_message = (
                f"Jumlah mutasi melebihi stok tersedia untuk "
                f"{stock.item.nama_barang} batch {stock.batch_lot}."
            )
            submitted_line["errors"].append(error_message)
            row_errors.append(f"Baris {submitted_line['row_number']}: {error_message}")
            continue

        valid_lines.append({"stock": stock, "quantity": quantity})

    return valid_lines, row_errors, submitted_lines


@login_required
@perm_required("stock.add_stocktransfer")
def transfer_create(request):
    transfer_line_state = []
    if request.method == "POST":
        form = StockTransferForm(request.POST)
        stock_ids = request.POST.getlist("stock_id")
        qty_values = request.POST.getlist("quantity")

        if form.is_valid():
            valid_lines, row_errors, transfer_line_state = _validate_transfer_create_lines(
                stock_ids,
                qty_values,
                form.cleaned_data["source_location"].pk,
            )

            if row_errors:
                form.add_error(
                    None,
                    "Periksa kembali baris mutasi yang tidak valid.",
                )
                for error_message in row_errors:
                    messages.error(request, error_message)
            elif not valid_lines:
                messages.error(
                    request,
                    "Pilih minimal satu item dengan jumlah mutasi valid (> 0).",
                )
            else:
                with db_transaction.atomic():
                    transfer = form.save(commit=False)
                    transfer.created_by = request.user
                    transfer.status = StockTransfer.Status.DRAFT
                    transfer.save()

                    StockTransferItem.objects.bulk_create(
                        [
                            StockTransferItem(
                                transfer=transfer,
                                stock=line["stock"],
                                item=line["stock"].item,
                                quantity=line["quantity"],
                                notes="",
                            )
                            for line in valid_lines
                        ]
                    )

                messages.success(
                    request,
                    f"Mutasi lokasi {transfer.document_number} berhasil dibuat.",
                )
                return redirect("stock:transfer_detail", transfer_id=transfer.pk)
    else:
        form = StockTransferForm()

    return render(
        request,
        "stock/transfer_form.html",
        {
            "form": form,
            "title": "Buat Mutasi Lokasi",
            "transfer_line_state": transfer_line_state,
        },
    )


@login_required
@perm_required("stock.view_stocktransfer")
def transfer_detail(request, transfer_id):
    transfer = get_object_or_404(
        StockTransfer.objects.select_related(
            "source_location", "destination_location", "created_by", "completed_by"
        ),
        pk=transfer_id,
    )
    items = transfer.items.select_related(
        "item", "stock", "stock__sumber_dana"
    ).order_by("id")
    return render(
        request,
        "stock/transfer_detail.html",
        {"transfer": transfer, "items": items},
    )


def _get_locked_transfer_for_completion(transfer_id):
    return StockTransfer.objects.select_for_update().get(pk=transfer_id)


@login_required
@perm_required("stock.change_stocktransfer")
def transfer_complete(request, transfer_id):
    transfer = get_object_or_404(StockTransfer, pk=transfer_id)
    if request.method != "POST":
        return redirect("stock:transfer_detail", transfer_id=transfer.pk)

    try:
        with db_transaction.atomic():
            transfer = _get_locked_transfer_for_completion(transfer_id)
            if transfer.status != StockTransfer.Status.DRAFT:
                raise ValueError("Hanya mutasi Draft yang dapat diselesaikan.")

            transfer_items = list(
                transfer.items.select_related("item", "stock", "stock__sumber_dana")
            )
            if not transfer_items:
                raise ValueError("Mutasi tidak memiliki item.")

            for line in transfer_items:
                source_stock = Stock.objects.select_for_update().get(pk=line.stock_id)

                if source_stock.location_id != transfer.source_location_id:
                    raise ValueError(
                        f"Batch {source_stock.batch_lot} tidak berada di lokasi asal dokumen."
                    )

                if line.quantity > source_stock.available_quantity:
                    raise ValueError(
                        f"Stok tidak cukup untuk {line.item.nama_barang} batch {source_stock.batch_lot}."
                    )

                source_stock.quantity = source_stock.quantity - line.quantity
                source_stock.save(update_fields=["quantity", "updated_at"])

                destination_stock, created = (
                    Stock.objects.select_for_update().get_or_create(
                        item=source_stock.item,
                        location=transfer.destination_location,
                        batch_lot=source_stock.batch_lot,
                        sumber_dana=source_stock.sumber_dana,
                        defaults={
                            "expiry_date": source_stock.expiry_date,
                            "quantity": line.quantity,
                            "reserved": Decimal("0"),
                            "unit_price": source_stock.unit_price,
                            "receiving_ref": source_stock.receiving_ref,
                        },
                    )
                )
                if not created:
                    destination_stock.quantity = (
                        destination_stock.quantity + line.quantity
                    )
                    destination_stock.save(update_fields=["quantity", "updated_at"])

                Transaction.objects.create(
                    transaction_type=Transaction.TransactionType.OUT,
                    item=line.item,
                    location=transfer.source_location,
                    batch_lot=source_stock.batch_lot,
                    quantity=line.quantity,
                    unit_price=source_stock.unit_price,
                    sumber_dana=source_stock.sumber_dana,
                    reference_type=Transaction.ReferenceType.TRANSFER,
                    reference_id=transfer.pk,
                    user=request.user,
                    notes=f"Mutasi lokasi {transfer.document_number} ke {transfer.destination_location.name}",
                )
                Transaction.objects.create(
                    transaction_type=Transaction.TransactionType.IN,
                    item=line.item,
                    location=transfer.destination_location,
                    batch_lot=source_stock.batch_lot,
                    quantity=line.quantity,
                    unit_price=source_stock.unit_price,
                    sumber_dana=source_stock.sumber_dana,
                    reference_type=Transaction.ReferenceType.TRANSFER,
                    reference_id=transfer.pk,
                    user=request.user,
                    notes=f"Mutasi lokasi {transfer.document_number} dari {transfer.source_location.name}",
                )

            transfer.status = StockTransfer.Status.COMPLETED
            transfer.completed_by = request.user
            transfer.completed_at = timezone.now()
            transfer.save(
                update_fields=["status", "completed_by", "completed_at", "updated_at"]
            )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("stock:transfer_detail", transfer_id=transfer.pk)

    messages.success(
        request, f"Mutasi lokasi {transfer.document_number} selesai diproses."
    )
    return redirect("stock:transfer_detail", transfer_id=transfer.pk)


@login_required
@perm_required("stock.add_stocktransfer", "stock.change_stocktransfer")
def api_location_stock_search(request):
    location_id = request.GET.get("location")
    q = request.GET.get("q", "").strip()

    if not location_id:
        return JsonResponse({"results": []})

    queryset = (
        Stock.objects.select_related(
            "item", "item__kategori", "sumber_dana", "location"
        )
        .filter(location_id=location_id)
        .filter(quantity__gt=F("reserved"))
        .order_by(F("expiry_date").asc(nulls_last=True), "item__nama_barang", "batch_lot")
    )
    if q:
        queryset = queryset.filter(
            Q(item__kode_barang__icontains=q)
            | Q(item__nama_barang__icontains=q)
            | Q(item__kategori__name__icontains=q)
            | Q(batch_lot__icontains=q)
        )

    results = []
    for stock in queryset[:200]:
        results.append(
            {
                "stock_id": stock.id,
                "item_id": stock.item_id,
                "kode": stock.item.kode_barang,
                "nama": stock.item.nama_barang,
                "kategori": stock.item.kategori.name if stock.item.kategori else "-",
                "batch": stock.batch_lot,
                "expiry": stock.expiry_date_display,
                "qty": str(stock.quantity),
                "reserved": str(stock.reserved),
                "available": str(stock.available_quantity),
                "funding": stock.sumber_dana.name,
                "unit_price": str(stock.unit_price),
            }
        )

    return JsonResponse({"results": results})
