from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, F
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from apps.core.decorators import module_scope_required, perm_required
from apps.items.models import Supplier, FundingSource
from apps.stock.models import Stock, Transaction
from apps.users.models import ModuleAccess
from .models import Receiving, ReceivingItem, ReceivingOrderItem, ReceivingTypeOption
from .forms import (
    ReceivingForm,
    ReceivingItemFormSet,
    PlannedReceivingForm,
    ReceivingOrderItemFormSet,
    ReceivingReceiptItemFormSet,
    ReceivingPlannedReceiptItemFormSet,
    ReceivingCloseForm,
    ReceivingOrderCloseItemFormSet,
)


@login_required
def receiving_list(request):
    queryset = (
        Receiving.objects.select_related("supplier", "sumber_dana", "created_by")
        .filter(is_planned=False)
        .order_by("-receiving_date")
    )

    search = request.GET.get("q", "").strip()
    if search:
        queryset = queryset.filter(
            Q(document_number__icontains=search) | Q(supplier__name__icontains=search)
        )

    status = request.GET.get("status")
    if status:
        queryset = queryset.filter(status=status)

    r_type = request.GET.get("type")
    if r_type:
        queryset = queryset.filter(receiving_type=r_type)

    paginator = Paginator(queryset, 25)
    receivings = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "receiving/receiving_list.html",
        {
            "receivings": receivings,
            "search": search,
            "selected_status": status or "",
            "selected_type": r_type or "",
            "status_draft": "selected" if status == "DRAFT" else "",
            "status_submitted": "selected" if status == "SUBMITTED" else "",
            "status_verified": "selected"
            if status == Receiving.Status.VERIFIED
            else "",
            "type_procurement": "selected" if r_type == "PROCUREMENT" else "",
            "type_grant": "selected" if r_type == "GRANT" else "",
        },
    )


@login_required
def receiving_plan_list(request):
    queryset = (
        Receiving.objects.select_related("supplier", "sumber_dana", "created_by")
        .filter(is_planned=True)
        .order_by("-receiving_date")
    )

    search = request.GET.get("q", "").strip()
    if search:
        queryset = queryset.filter(
            Q(document_number__icontains=search) | Q(supplier__name__icontains=search)
        )

    status = request.GET.get("status")
    if status:
        queryset = queryset.filter(status=status)

    r_type = request.GET.get("type")
    if r_type:
        queryset = queryset.filter(receiving_type=r_type)

    paginator = Paginator(queryset, 25)
    receivings = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "receiving/receiving_plan_list.html",
        {
            "receivings": receivings,
            "search": search,
            "selected_status": status or "",
            "selected_type": r_type or "",
            "status_draft": "selected" if status == Receiving.Status.DRAFT else "",
            "status_submitted": "selected"
            if status == Receiving.Status.SUBMITTED
            else "",
            "status_approved": "selected"
            if status == Receiving.Status.APPROVED
            else "",
            "status_partial": "selected" if status == Receiving.Status.PARTIAL else "",
            "status_received": "selected"
            if status == Receiving.Status.RECEIVED
            else "",
            "status_closed": "selected" if status == Receiving.Status.CLOSED else "",
            "type_procurement": "selected" if r_type == "PROCUREMENT" else "",
            "type_grant": "selected" if r_type == "GRANT" else "",
        },
    )


@login_required
@perm_required("receiving.add_receiving")
def receiving_create(request):
    if request.method == "POST":
        form = ReceivingForm(request.POST)
        formset = ReceivingItemFormSet(request.POST, prefix="items")

        if form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    receiving = form.save(commit=False)
                    receiving.created_by = request.user
                    receiving.status = Receiving.Status.VERIFIED
                    receiving.verified_by = request.user
                    receiving.verified_at = timezone.now()
                    receiving.save()

                    formset.instance = receiving
                    receipt_items = formset.save(commit=False)
                    if not receipt_items:
                        raise ValueError("Tambahkan minimal 1 item penerimaan.")

                    for item in receipt_items:
                        item.receiving = receiving
                        item.received_by = request.user
                        item.received_at = timezone.now()
                        item.save()

                        stock, created = Stock.objects.get_or_create(
                            item=item.item,
                            location=item.location,
                            batch_lot=item.batch_lot,
                            sumber_dana=receiving.sumber_dana,
                            defaults={
                                "expiry_date": item.expiry_date,
                                "quantity": item.quantity,
                                "unit_price": item.unit_price,
                                "receiving_ref": receiving,
                            },
                        )
                        if not created:
                            stock.quantity += item.quantity
                            stock.save(update_fields=["quantity", "updated_at"])

                        Transaction.objects.create(
                            transaction_type=Transaction.TransactionType.IN,
                            item=item.item,
                            location=item.location,
                            batch_lot=item.batch_lot,
                            quantity=item.quantity,
                            unit_price=item.unit_price,
                            sumber_dana=receiving.sumber_dana,
                            reference_type=Transaction.ReferenceType.RECEIVING,
                            reference_id=receiving.pk,
                            user=request.user,
                            notes=f"Penerimaan reguler {receiving.document_number}",
                        )

                    for deleted_form in formset.deleted_forms:
                        if deleted_form.instance.pk:
                            deleted_form.instance.delete()

            except (ValueError, ProtectedError) as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request, f"Penerimaan {receiving.document_number} berhasil dibuat."
                )
                return redirect("receiving:receiving_detail", pk=receiving.pk)
    else:
        form = ReceivingForm()
        formset = ReceivingItemFormSet(prefix="items")

    return render(
        request,
        "receiving/receiving_form.html",
        {
            "form": form,
            "formset": formset,
            "title": "Buat Penerimaan Baru",
        },
    )


@login_required
@perm_required("receiving.add_receiving")
def receiving_plan_create(request):
    if request.method == "POST":
        form = PlannedReceivingForm(request.POST)
        formset = ReceivingOrderItemFormSet(request.POST, prefix="items")

        if form.is_valid() and formset.is_valid():
            receiving = form.save(commit=False)
            receiving.created_by = request.user
            receiving.is_planned = True
            receiving.status = Receiving.Status.DRAFT
            receiving.save()

            formset.instance = receiving
            formset.save()

            messages.success(
                request,
                f"Rencana penerimaan {receiving.document_number} berhasil dibuat.",
            )
            return redirect("receiving:receiving_plan_detail", pk=receiving.pk)
    else:
        form = PlannedReceivingForm()
        formset = ReceivingOrderItemFormSet(prefix="items")

    return render(
        request,
        "receiving/receiving_plan_form.html",
        {
            "form": form,
            "formset": formset,
            "title": "Buat Rencana Penerimaan",
        },
    )


@login_required
def receiving_detail(request, pk):
    receiving = get_object_or_404(
        Receiving.objects.select_related(
            "supplier", "sumber_dana", "created_by", "verified_by"
        ),
        pk=pk,
    )
    items = receiving.items.select_related("item", "item__satuan")

    return render(
        request,
        "receiving/receiving_detail.html",
        {
            "receiving": receiving,
            "items": items,
        },
    )


@login_required
def receiving_plan_detail(request, pk):
    receiving = get_object_or_404(
        Receiving.objects.select_related(
            "supplier", "sumber_dana", "created_by", "approved_by"
        ),
        pk=pk,
        is_planned=True,
    )
    order_items = receiving.order_items.select_related("item", "item__satuan")
    receipt_items = receiving.items.select_related("item", "location")

    return render(
        request,
        "receiving/receiving_plan_detail.html",
        {
            "receiving": receiving,
            "order_items": order_items,
            "receipt_items": receipt_items,
        },
    )


@login_required
@perm_required("receiving.change_receiving")
def receiving_plan_submit(request, pk):
    receiving = get_object_or_404(Receiving, pk=pk, is_planned=True)
    if request.method != "POST":
        return redirect("receiving:receiving_plan_detail", pk=pk)

    if receiving.status != Receiving.Status.DRAFT:
        messages.error(request, "Hanya rencana penerimaan Draft yang dapat diajukan.")
        return redirect("receiving:receiving_plan_detail", pk=pk)

    if not receiving.order_items.exists():
        messages.error(request, "Tambahkan minimal 1 item rencana sebelum diajukan.")
        return redirect("receiving:receiving_plan_detail", pk=pk)

    receiving.status = Receiving.Status.SUBMITTED
    receiving.save(update_fields=["status", "updated_at"])
    messages.success(
        request, f"Rencana penerimaan {receiving.document_number} berhasil diajukan."
    )
    return redirect("receiving:receiving_plan_detail", pk=pk)


@login_required
@perm_required("receiving.change_receiving")
@module_scope_required(ModuleAccess.Module.RECEIVING, ModuleAccess.Scope.APPROVE)
def receiving_plan_approve(request, pk):
    receiving = get_object_or_404(Receiving, pk=pk, is_planned=True)
    if request.method != "POST":
        return redirect("receiving:receiving_plan_detail", pk=pk)

    if receiving.status != Receiving.Status.SUBMITTED:
        messages.error(
            request, "Hanya rencana penerimaan Diajukan yang dapat disetujui."
        )
        return redirect("receiving:receiving_plan_detail", pk=pk)

    receiving.status = Receiving.Status.APPROVED
    receiving.approved_by = request.user
    receiving.approved_at = timezone.now()
    receiving.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    messages.success(
        request, f"Rencana penerimaan {receiving.document_number} disetujui."
    )
    return redirect("receiving:receiving_plan_detail", pk=pk)


@login_required
@perm_required("receiving.change_receiving")
def receiving_plan_close(request, pk):
    receiving = get_object_or_404(Receiving, pk=pk, is_planned=True)
    if request.method != "POST":
        return redirect("receiving:receiving_plan_detail", pk=pk)

    if receiving.status not in [Receiving.Status.APPROVED, Receiving.Status.PARTIAL]:
        messages.error(
            request, "Hanya rencana penerimaan disetujui/parsial yang dapat ditutup."
        )
        return redirect("receiving:receiving_plan_detail", pk=pk)

    return redirect("receiving:receiving_plan_close_items", pk=pk)


@login_required
@perm_required("receiving.change_receiving")
def receiving_plan_close_items(request, pk):
    receiving = get_object_or_404(Receiving, pk=pk, is_planned=True)
    if receiving.status not in [Receiving.Status.APPROVED, Receiving.Status.PARTIAL]:
        messages.error(
            request, "Hanya rencana penerimaan disetujui/parsial yang dapat ditutup."
        )
        return redirect("receiving:receiving_plan_detail", pk=pk)

    if request.method == "POST":
        formset = ReceivingOrderCloseItemFormSet(
            request.POST,
            instance=receiving,
        )
        if formset.is_valid():
            formset.save()
            unresolved = (
                receiving.order_items.filter(is_cancelled=False)
                .exclude(planned_quantity__lte=F("received_quantity"))
                .exists()
            )
            if unresolved:
                messages.error(
                    request,
                    "Masih ada item bersisa yang belum dibatalkan. Tandai item tersebut untuk menutup rencana.",
                )
                return redirect("receiving:receiving_plan_close_items", pk=pk)

            receiving.status = Receiving.Status.CLOSED
            receiving.closed_by = request.user
            receiving.closed_at = timezone.now()
            receiving.closed_reason = "Sisa dibatalkan melalui penutupan rencana"
            receiving.save(
                update_fields=[
                    "status",
                    "closed_by",
                    "closed_at",
                    "closed_reason",
                    "updated_at",
                ]
            )
            messages.success(
                request, f"Rencana penerimaan {receiving.document_number} ditutup."
            )
            return redirect("receiving:receiving_plan_detail", pk=pk)

        messages.error(request, "Periksa isian penutupan sisa.")
    else:
        formset = ReceivingOrderCloseItemFormSet(instance=receiving)

    return render(
        request,
        "receiving/receiving_plan_close_items.html",
        {
            "receiving": receiving,
            "formset": formset,
        },
    )


@login_required
@perm_required("receiving.add_receiving")
def receiving_plan_receive(request, pk):
    receiving = get_object_or_404(Receiving, pk=pk, is_planned=True)
    if receiving.status not in [Receiving.Status.APPROVED, Receiving.Status.PARTIAL]:
        messages.error(
            request, "Rencana penerimaan belum disetujui atau sudah selesai."
        )
        return redirect("receiving:receiving_plan_detail", pk=pk)

    planned_order_items = list(
        receiving.order_items.filter(is_cancelled=False).select_related("item")
    )
    if not planned_order_items:
        messages.error(request, "Rencana tidak memiliki item aktif untuk diterima.")
        return redirect("receiving:receiving_plan_detail", pk=pk)

    initial_rows = []
    for order_item in planned_order_items:
        initial_rows.append(
            {
                "order_item": order_item.pk,
                "quantity": 0,
                "unit_price": order_item.unit_price,
            }
        )

    if request.method == "POST":
        formset = ReceivingPlannedReceiptItemFormSet(
            request.POST,
            prefix="items",
            instance=receiving,
            form_kwargs={"receiving": receiving, "lock_order_item": True},
            queryset=ReceivingItem.objects.none(),
        )
        if not formset.is_valid():
            messages.error(request, "Periksa kembali isian penerimaan.")
            return redirect("receiving:receiving_plan_receive", pk=pk)

        totals = {}
        has_receipt_row = False
        for form in formset.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            order_item = form.cleaned_data.get("order_item")
            quantity = form.cleaned_data.get("quantity")
            if not order_item or quantity is None:
                continue
            has_receipt_row = True
            totals[order_item.pk] = totals.get(order_item.pk, 0) + quantity

        if not has_receipt_row:
            messages.error(request, "Tambahkan minimal 1 item penerimaan.")
            return redirect("receiving:receiving_plan_receive", pk=pk)

        if totals:
            order_items = ReceivingOrderItem.objects.filter(pk__in=totals.keys())
            for order_item in order_items:
                if order_item.remaining_quantity < totals[order_item.pk]:
                    messages.error(
                        request,
                        f"Jumlah penerimaan untuk {order_item.item} melebihi sisa pesanan.",
                    )
                    return redirect("receiving:receiving_plan_receive", pk=pk)

        try:
            with transaction.atomic():
                for form in formset.forms:
                    cleaned = form.cleaned_data
                    if not cleaned:
                        continue
                    item = form.save(commit=False)
                    if item.quantity is None or item.quantity <= 0:
                        continue

                    item.receiving = receiving
                    item.received_by = request.user
                    item.received_at = timezone.now()
                    if item.order_item_id:
                        item.item = item.order_item.item
                    item.save()

                    order_item = ReceivingOrderItem.objects.select_for_update().get(
                        pk=item.order_item_id
                    )
                    order_item.received_quantity = (
                        order_item.received_quantity + item.quantity
                    )
                    order_item.save(update_fields=["received_quantity", "updated_at"])

                    stock, created = Stock.objects.get_or_create(
                        item=item.item,
                        location=item.location,
                        batch_lot=item.batch_lot,
                        sumber_dana=receiving.sumber_dana,
                        defaults={
                            "expiry_date": item.expiry_date,
                            "quantity": item.quantity,
                            "unit_price": item.unit_price,
                            "receiving_ref": receiving,
                        },
                    )
                    if not created:
                        stock.quantity += item.quantity
                        stock.save(update_fields=["quantity", "updated_at"])

                    Transaction.objects.create(
                        transaction_type=Transaction.TransactionType.IN,
                        item=item.item,
                        location=item.location,
                        batch_lot=item.batch_lot,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        sumber_dana=receiving.sumber_dana,
                        reference_type=Transaction.ReferenceType.RECEIVING,
                        reference_id=receiving.pk,
                        user=request.user,
                        notes=f"Penerimaan dari rencana {receiving.document_number}",
                    )

                remaining = (
                    receiving.order_items.filter(is_cancelled=False)
                    .exclude(planned_quantity__lte=F("received_quantity"))
                    .exists()
                )
                receiving.status = (
                    Receiving.Status.PARTIAL if remaining else Receiving.Status.RECEIVED
                )
                receiving.save(update_fields=["status", "updated_at"])

        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("receiving:receiving_plan_receive", pk=pk)

        messages.success(
            request, f"Penerimaan {receiving.document_number} berhasil dicatat."
        )
        return redirect("receiving:receiving_plan_detail", pk=pk)
    else:
        formset = ReceivingPlannedReceiptItemFormSet(
            prefix="items",
            instance=receiving,
            form_kwargs={"receiving": receiving, "lock_order_item": True},
            queryset=ReceivingItem.objects.none(),
            initial=initial_rows,
        )

    return render(
        request,
        "receiving/receiving_plan_receive.html",
        {
            "receiving": receiving,
            "formset": formset,
        },
    )


# ── AJAX Quick-Create Views ────────────────────────────────


@login_required
@require_POST
def quick_create_supplier(request):
    """AJAX endpoint to create a new Supplier."""
    code = request.POST.get("code", "").strip()
    name = request.POST.get("name", "").strip()

    if not code or not name:
        return JsonResponse({"error": "Kode dan Nama wajib diisi."}, status=400)

    if Supplier.objects.filter(code=code).exists():
        return JsonResponse(
            {"error": f'Supplier dengan kode "{code}" sudah ada.'}, status=400
        )

    supplier = Supplier.objects.create(
        code=code,
        name=name,
        address=request.POST.get("address", "").strip(),
        phone=request.POST.get("phone", "").strip(),
        email=request.POST.get("email", "").strip(),
        notes=request.POST.get("notes", "").strip(),
    )
    return JsonResponse({"id": supplier.pk, "text": str(supplier)})


@login_required
@require_POST
def quick_create_funding_source(request):
    """AJAX endpoint to create a new FundingSource."""
    code = request.POST.get("code", "").strip()
    name = request.POST.get("name", "").strip()

    if not code or not name:
        return JsonResponse({"error": "Kode dan Nama wajib diisi."}, status=400)

    if FundingSource.objects.filter(code=code).exists():
        return JsonResponse(
            {"error": f'Sumber dana dengan kode "{code}" sudah ada.'}, status=400
        )

    source = FundingSource.objects.create(
        code=code,
        name=name,
        description=request.POST.get("description", "").strip(),
    )
    return JsonResponse({"id": source.pk, "text": str(source)})


@login_required
@require_POST
def quick_create_receiving_type(request):
    """AJAX endpoint to create a new custom receiving type."""
    code = request.POST.get("code", "").strip().upper()
    name = request.POST.get("name", "").strip()

    if not code or not name:
        return JsonResponse({"error": "Kode dan Nama wajib diisi."}, status=400)

    reserved = {choice[0] for choice in Receiving.ReceivingType.choices}
    if code in reserved:
        return JsonResponse(
            {"error": f'Kode "{code}" sudah digunakan tipe bawaan sistem.'},
            status=400,
        )

    if ReceivingTypeOption.objects.filter(code=code).exists():
        return JsonResponse(
            {"error": f'Tipe penerimaan dengan kode "{code}" sudah ada.'}, status=400
        )

    option = ReceivingTypeOption.objects.create(code=code, name=name)
    return JsonResponse({"id": option.code, "text": option.name})
