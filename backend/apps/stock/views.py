from decimal import Decimal
from datetime import datetime

from django.contrib import messages
from django.db import transaction as db_transaction
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, F
from django.utils import timezone

from apps.core.decorators import perm_required
from .forms import StockTransferForm
from .models import Stock, Transaction, StockTransfer, StockTransferItem
from apps.items.models import Location, FundingSource, Item
from django.http import JsonResponse


@login_required
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


@login_required
def stock_card_detail(request, item_id):
    """View the stock card (running balance) for a specific item."""
    from decimal import Decimal

    item = get_object_or_404(Item, pk=item_id)

    recent_ids = request.session.get("stock_card_recent_items", [])
    recent_ids = [rid for rid in recent_ids if rid != item.id]
    recent_ids.insert(0, item.id)
    request.session["stock_card_recent_items"] = recent_ids[:8]

    # Query all transactions for this item, sorted chronologically
    queryset = (
        Transaction.objects.filter(item=item)
        .select_related("location", "user")
        .order_by("created_at", "id")
    )

    location_id = request.GET.get("location")
    if location_id:
        queryset = queryset.filter(location_id=location_id)

    date_from_raw = request.GET.get("date_from", "").strip()
    date_to_raw = request.GET.get("date_to", "").strip()

    def _parse_filter_date(value):
        if not value:
            return None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None

    date_from = _parse_filter_date(date_from_raw)
    date_to = _parse_filter_date(date_to_raw)

    # Optional date filters
    if date_from:
        queryset = queryset.filter(created_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(created_at__date__lte=date_to)

    # Before paginating or rendering, we need the opening balance
    # Opening balance is the sum of transactions before date_from (if date_from is provided)
    opening_balance = Decimal("0")
    if date_from:
        past_txs = Transaction.objects.filter(item=item, created_at__date__lt=date_from)
        if location_id:
            past_txs = past_txs.filter(location_id=location_id)

        for tx in past_txs:
            if tx.transaction_type in [
                Transaction.TransactionType.IN,
                Transaction.TransactionType.RETURN,
            ]:
                opening_balance += tx.quantity
            elif tx.transaction_type in [
                Transaction.TransactionType.OUT,
                Transaction.TransactionType.ADJUST,
            ]:
                # Assume ADJUST is negative or positive, but we'll subtract OUT.
                # Standard convention for this app seems to be OUT is positive quantity, deducted.
                opening_balance -= tx.quantity

    # Fetch all matching transactions to calculate running balances
    transactions = list(queryset)

    # Resolve human-friendly document numbers for reference labels
    receiving_ids = [
        tx.reference_id
        for tx in transactions
        if tx.reference_type == Transaction.ReferenceType.RECEIVING and tx.reference_id
    ]
    distribution_ids = [
        tx.reference_id
        for tx in transactions
        if tx.reference_type == Transaction.ReferenceType.DISTRIBUTION
        and tx.reference_id
    ]
    recall_ids = [
        tx.reference_id
        for tx in transactions
        if tx.reference_type == Transaction.ReferenceType.RECALL and tx.reference_id
    ]
    expired_ids = [
        tx.reference_id
        for tx in transactions
        if tx.reference_type == Transaction.ReferenceType.EXPIRED and tx.reference_id
    ]
    transfer_ids = [
        tx.reference_id
        for tx in transactions
        if tx.reference_type == Transaction.ReferenceType.TRANSFER and tx.reference_id
    ]

    reference_labels = {}
    if receiving_ids:
        from apps.receiving.models import Receiving

        reference_labels[Transaction.ReferenceType.RECEIVING] = {
            doc.id: doc.document_number
            for doc in Receiving.objects.filter(id__in=receiving_ids).only(
                "id", "document_number"
            )
        }
    if distribution_ids:
        from apps.distribution.models import Distribution

        reference_labels[Transaction.ReferenceType.DISTRIBUTION] = {
            doc.id: doc.document_number
            for doc in Distribution.objects.filter(id__in=distribution_ids).only(
                "id", "document_number"
            )
        }
    if recall_ids:
        from apps.recall.models import Recall

        reference_labels[Transaction.ReferenceType.RECALL] = {
            doc.id: doc.document_number
            for doc in Recall.objects.filter(id__in=recall_ids).only(
                "id", "document_number"
            )
        }
    if expired_ids:
        from apps.expired.models import Expired

        reference_labels[Transaction.ReferenceType.EXPIRED] = {
            doc.id: doc.document_number
            for doc in Expired.objects.filter(id__in=expired_ids).only(
                "id", "document_number"
            )
        }
    if transfer_ids:
        reference_labels[Transaction.ReferenceType.TRANSFER] = {
            doc.id: doc.document_number
            for doc in StockTransfer.objects.filter(id__in=transfer_ids).only(
                "id", "document_number"
            )
        }

    funding_labels = []
    for tx in transactions:
        if tx.sumber_dana_id and tx.sumber_dana:
            label = f"{tx.sumber_dana.code}/{tx.sumber_dana.name}"
            if label not in funding_labels:
                funding_labels.append(label)

    funding_display = ", ".join(funding_labels[:4]) if funding_labels else "-"

    current_balance = opening_balance
    total_in = Decimal("0")
    total_out = Decimal("0")
    include_transfer_in_totals = bool(location_id)

    for tx in transactions:
        tx_in = Decimal("0")
        tx_out = Decimal("0")

        if tx.transaction_type in [
            Transaction.TransactionType.IN,
            Transaction.TransactionType.RETURN,
        ]:
            tx_in = tx.quantity
            current_balance += tx_in
            if (
                include_transfer_in_totals
                or tx.reference_type != Transaction.ReferenceType.TRANSFER
            ):
                total_in += tx_in
        else:
            tx_out = tx.quantity
            current_balance -= tx_out
            if (
                include_transfer_in_totals
                or tx.reference_type != Transaction.ReferenceType.TRANSFER
            ):
                total_out += tx_out

        # Attach dynamic attributes
        tx.tx_in = tx_in
        tx.tx_out = tx_out
        tx.running_balance = current_balance
        tx.reference_label = reference_labels.get(tx.reference_type, {}).get(
            tx.reference_id,
            f"{tx.reference_type}-{tx.reference_id}",
        )

    # Pagination
    paginator = Paginator(transactions, 50)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Prepare locations for filter dropdown
    locations = []
    for loc in Location.objects.filter(is_active=True):
        locations.append(
            {
                "id": loc.id,
                "name": loc.name,
                "selected": "selected" if location_id == str(loc.id) else "",
            }
        )

    context = {
        "item": item,
        "transactions": page_obj,
        "opening_balance": opening_balance,
        "closing_balance": current_balance,
        "total_in": total_in,
        "total_out": total_out,
        "total_label": "TOTAL MUTASI (Periode/Filter ini)"
        if location_id
        else "TOTAL MASUK/KELUAR EKSTERNAL (Mutasi internal dikecualikan)",
        "funding_display": funding_display,
        "budget_year": timezone.now().year,
        "date_from": date_from.strftime("%d/%m/%Y")
        if date_from
        else (date_from_raw or ""),
        "date_to": date_to.strftime("%d/%m/%Y") if date_to else (date_to_raw or ""),
        "locations": locations,
        "selected_location": location_id or "",
    }
    return render(request, "stock/stock_card_detail.html", context)


@login_required
def api_item_search(request):
    """AJAX endpoint for item typeahead."""
    q = request.GET.get("q", "").strip()
    if not q:
        return JsonResponse({"results": []})

    items = (
        Item.objects.filter(is_active=True)
        .filter(Q(kode_barang__icontains=q) | Q(nama_barang__icontains=q))
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
                "stock": sum(
                    [s.quantity for s in item.stock_entries.all()]
                ),  # Quick stock sum
            }
        )

    return JsonResponse({"results": results})


@login_required
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
