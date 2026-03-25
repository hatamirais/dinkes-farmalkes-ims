from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.decorators import module_scope_required, perm_required
from apps.stock.models import Stock, Transaction
from apps.users.models import ModuleAccess

from .forms import RecallForm, RecallItemFormSet
from .models import Recall


@login_required
def recall_list(request):
    queryset = Recall.objects.select_related("supplier", "created_by").order_by(
        "-recall_date"
    )

    search = request.GET.get("q", "").strip()
    if search:
        queryset = queryset.filter(
            Q(document_number__icontains=search) | Q(supplier__name__icontains=search)
        )

    status = request.GET.get("status")
    if status:
        queryset = queryset.filter(status=status)

    paginator = Paginator(queryset, 25)
    recalls = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "recall/recall_list.html",
        {
            "recalls": recalls,
            "search": search,
            "selected_status": status or "",
            "status_draft": "selected" if status == Recall.Status.DRAFT else "",
            "status_submitted": "selected" if status == Recall.Status.SUBMITTED else "",
            "status_verified": "selected" if status == Recall.Status.VERIFIED else "",
            "status_completed": "selected" if status == Recall.Status.COMPLETED else "",
        },
    )


@login_required
@perm_required("recall.add_recall")
def recall_create(request):
    if request.method == "POST":
        form = RecallForm(request.POST)
        formset = RecallItemFormSet(request.POST, prefix="items")

        if form.is_valid() and formset.is_valid():
            recall = form.save(commit=False)
            recall.created_by = request.user
            recall.status = Recall.Status.DRAFT
            recall.save()

            formset.instance = recall
            formset.save()

            messages.success(
                request, f"Recall {recall.document_number} berhasil dibuat."
            )
            return redirect("recall:recall_detail", pk=recall.pk)
    else:
        form = RecallForm()
        formset = RecallItemFormSet(prefix="items")

    return render(
        request,
        "recall/recall_form.html",
        {
            "form": form,
            "formset": formset,
            "title": "Buat Recall Baru",
            "is_edit": False,
        },
    )


@login_required
@perm_required("recall.change_recall")
def recall_edit(request, pk):
    recall = get_object_or_404(Recall, pk=pk)
    if recall.status not in (Recall.Status.DRAFT, Recall.Status.SUBMITTED):
        messages.error(request, "Hanya recall Draft/Diajukan yang dapat diubah.")
        return redirect("recall:recall_detail", pk=recall.pk)

    if request.method == "POST":
        form = RecallForm(request.POST, instance=recall)
        formset = RecallItemFormSet(request.POST, instance=recall, prefix="items")

        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(
                request, f"Recall {recall.document_number} berhasil diperbarui."
            )
            return redirect("recall:recall_detail", pk=recall.pk)
    else:
        form = RecallForm(instance=recall)
        formset = RecallItemFormSet(instance=recall, prefix="items")

    return render(
        request,
        "recall/recall_form.html",
        {
            "form": form,
            "formset": formset,
            "title": f"Edit Recall {recall.document_number}",
            "is_edit": True,
            "recall": recall,
        },
    )


@login_required
def recall_detail(request, pk):
    recall = get_object_or_404(
        Recall.objects.select_related("supplier", "created_by", "verified_by"),
        pk=pk,
    )
    items = recall.items.select_related(
        "item",
        "item__satuan",
        "stock",
        "stock__location",
        "stock__sumber_dana",
    )

    return render(
        request,
        "recall/recall_detail.html",
        {
            "recall": recall,
            "items": items,
        },
    )


@login_required
@perm_required("recall.change_recall")
def recall_submit(request, pk):
    recall = get_object_or_404(Recall, pk=pk)
    if request.method != "POST":
        return redirect("recall:recall_detail", pk=pk)

    if recall.status != Recall.Status.DRAFT:
        messages.error(request, "Hanya recall Draft yang dapat diajukan.")
        return redirect("recall:recall_detail", pk=pk)

    if not recall.items.exists():
        messages.error(request, "Tambahkan minimal 1 item sebelum mengajukan recall.")
        return redirect("recall:recall_detail", pk=pk)

    recall.status = Recall.Status.SUBMITTED
    recall.save(update_fields=["status", "updated_at"])
    messages.success(request, f"Recall {recall.document_number} berhasil diajukan.")
    return redirect("recall:recall_detail", pk=pk)


@login_required
@perm_required("recall.change_recall")
@module_scope_required(ModuleAccess.Module.RECALL, ModuleAccess.Scope.APPROVE)
def recall_verify(request, pk):
    recall = get_object_or_404(Recall, pk=pk)
    if request.method != "POST":
        return redirect("recall:recall_detail", pk=pk)

    if recall.status != Recall.Status.SUBMITTED:
        messages.error(
            request, "Hanya recall berstatus Diajukan yang dapat diverifikasi."
        )
        return redirect("recall:recall_detail", pk=pk)

    recall_items = list(recall.items.select_related("item", "stock"))
    if not recall_items:
        messages.error(request, "Recall tidak memiliki item untuk diverifikasi.")
        return redirect("recall:recall_detail", pk=pk)

    try:
        with transaction.atomic():
            for recall_item in recall_items:
                stock = Stock.objects.select_for_update().get(pk=recall_item.stock_id)

                if stock.item_id != recall_item.item_id:
                    raise ValueError(
                        f"Batch stok tidak sesuai untuk item {recall_item.item.nama_barang}."
                    )

                if recall_item.quantity > stock.available_quantity:
                    raise ValueError(
                        f"Stok tidak cukup untuk {recall_item.item.nama_barang}. "
                        f"Tersedia {stock.available_quantity}, diminta {recall_item.quantity}."
                    )

                stock.quantity = stock.quantity - recall_item.quantity
                stock.save(update_fields=["quantity", "updated_at"])

                Transaction.objects.create(
                    transaction_type=Transaction.TransactionType.OUT,
                    item=recall_item.item,
                    location=stock.location,
                    batch_lot=stock.batch_lot,
                    quantity=recall_item.quantity,
                    unit_price=stock.unit_price,
                    sumber_dana=stock.sumber_dana,
                    reference_type=Transaction.ReferenceType.RECALL,
                    reference_id=recall.id,
                    user=request.user,
                    notes=f"Recall {recall.document_number}: {recall_item.notes}".strip(),
                )

            recall.status = Recall.Status.VERIFIED
            recall.verified_by = request.user
            recall.verified_at = timezone.now()
            recall.save(
                update_fields=["status", "verified_by", "verified_at", "updated_at"]
            )

    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("recall:recall_detail", pk=pk)

    messages.success(
        request,
        f"Recall {recall.document_number} berhasil diverifikasi dan stok diperbarui.",
    )
    return redirect("recall:recall_detail", pk=pk)


@login_required
@perm_required("recall.change_recall")
@module_scope_required(ModuleAccess.Module.RECALL, ModuleAccess.Scope.APPROVE)
def recall_complete(request, pk):
    recall = get_object_or_404(Recall, pk=pk)
    if request.method != "POST":
        return redirect("recall:recall_detail", pk=pk)

    if recall.status != Recall.Status.VERIFIED:
        messages.error(
            request, "Hanya recall terverifikasi yang dapat ditandai selesai."
        )
        return redirect("recall:recall_detail", pk=pk)

    recall.status = Recall.Status.COMPLETED
    recall.completed_by = request.user
    recall.completed_at = timezone.now()
    recall.save(update_fields=["status", "completed_by", "completed_at", "updated_at"])
    messages.success(request, f"Recall {recall.document_number} ditandai selesai.")
    return redirect("recall:recall_detail", pk=pk)


@login_required
@perm_required("recall.delete_recall")
def recall_delete(request, pk):
    recall = get_object_or_404(Recall, pk=pk)
    if request.method != "POST":
        return redirect("recall:recall_detail", pk=pk)

    if recall.status != Recall.Status.DRAFT:
        messages.error(request, "Hanya recall Draft yang dapat dihapus.")
        return redirect("recall:recall_detail", pk=pk)

    doc_number = recall.document_number
    recall.delete()
    messages.success(request, f"Recall {doc_number} berhasil dihapus.")
    return redirect("recall:recall_list")
