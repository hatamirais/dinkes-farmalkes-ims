from decimal import Decimal
from datetime import datetime

from django.contrib import messages
from django.db import transaction as db_transaction
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Case, Q, F, Sum, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.core.decorators import perm_required
from .forms import StockTransferForm
from .models import Stock, Transaction, StockTransfer, StockTransferItem
from apps.items.models import Location, FundingSource, Item
from django.http import JsonResponse


@login_required
@perm_required("stock.view_stock")
def stock_list(request):
    queryset = (
        Stock.objects.select_related("item", "location", "sumber_dana")
        .filter(quantity__gt=0)
        .order_by("item__nama_barang", "expiry_date")
    )

    search = request.GET.get("q", "").strip()
    if search:
        queryset = queryset.filter(
            Q(item__kode_barang__icontains=search)
            | Q(item__nama_barang__icontains=search)
            | Q(batch_lot__icontains=search)
        )

    location = request.GET.get("location")
    if location:
        queryset = queryset.filter(location_id=location)

    sumber_dana = request.GET.get("sumber_dana")
    if sumber_dana:
        queryset = queryset.filter(sumber_dana_id=sumber_dana)

    paginator = Paginator(queryset, 25)
    stocks = paginator.get_page(request.GET.get("page"))

    # Build filter lists with selected state
    locations = []
    for loc in Location.objects.filter(is_active=True):
        locations.append(
            {
                "id": loc.id,
                "name": loc.name,
                "selected": "selected" if location == str(loc.id) else "",
            }
        )

    funding_sources = []
    for sd in FundingSource.objects.filter(is_active=True):
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
            "locations": locations,
            "funding_sources": funding_sources,
            "search": search,
            "selected_location": location or "",
            "selected_sumber_dana": sumber_dana or "",
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

    # ── Pre-fetch batch expiry dates for this item (avoids N+1) ───────
    batch_expiry_map = dict(
        Stock.objects.filter(item=item)
        .exclude(expiry_date__isnull=True)
        .values_list("batch_lot", "expiry_date")
        .distinct()
    )

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
                expiry_date = batch_expiry_map.get(tx.batch_lot)
                if expiry_date:
                    tx.expiry_display = expiry_date.strftime("%d/%m/%Y")

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


@login_required
@perm_required("stock.add_stocktransfer")
def transfer_create(request):
    if request.method == "POST":
        form = StockTransferForm(request.POST)
        stock_ids = request.POST.getlist("stock_id")
        qty_values = request.POST.getlist("quantity")

        if form.is_valid():
            transfer = form.save(commit=False)
            transfer.created_by = request.user
            transfer.status = StockTransfer.Status.DRAFT
            transfer.save()

            created_count = 0
            for idx, stock_id in enumerate(stock_ids):
                qty_raw = (qty_values[idx] if idx < len(qty_values) else "").strip()
                if not qty_raw:
                    continue

                try:
                    qty = Decimal(qty_raw)
                except Exception:
                    continue

                if qty <= 0:
                    continue

                stock = (
                    Stock.objects.filter(pk=stock_id)
                    .select_related("item", "location")
                    .first()
                )
                if not stock:
                    continue
                if stock.location_id != transfer.source_location_id:
                    continue
                if qty > stock.available_quantity:
                    continue

                StockTransferItem.objects.create(
                    transfer=transfer,
                    stock=stock,
                    item=stock.item,
                    quantity=qty,
                    notes="",
                )
                created_count += 1

            if created_count == 0:
                transfer.delete()
                messages.error(
                    request,
                    "Pilih minimal satu item dengan jumlah mutasi valid (> 0).",
                )
            else:
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
        {"form": form, "title": "Buat Mutasi Lokasi"},
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


@login_required
@perm_required("stock.change_stocktransfer")
def transfer_complete(request, transfer_id):
    transfer = get_object_or_404(StockTransfer, pk=transfer_id)
    if request.method != "POST":
        return redirect("stock:transfer_detail", transfer_id=transfer.pk)

    if transfer.status != StockTransfer.Status.DRAFT:
        messages.error(request, "Hanya mutasi Draft yang dapat diselesaikan.")
        return redirect("stock:transfer_detail", transfer_id=transfer.pk)

    transfer_items = list(
        transfer.items.select_related("item", "stock", "stock__sumber_dana")
    )
    if not transfer_items:
        messages.error(request, "Mutasi tidak memiliki item.")
        return redirect("stock:transfer_detail", transfer_id=transfer.pk)

    try:
        with db_transaction.atomic():
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
        .order_by("expiry_date", "item__nama_barang", "batch_lot")
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
                "expiry": stock.expiry_date.strftime("%d/%m/%Y")
                if stock.expiry_date
                else "-",
                "qty": str(stock.quantity),
                "reserved": str(stock.reserved),
                "available": str(stock.available_quantity),
                "funding": stock.sumber_dana.name,
                "unit_price": str(stock.unit_price),
            }
        )

    return JsonResponse({"results": results})
