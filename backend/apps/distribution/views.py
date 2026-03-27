from decimal import Decimal

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

from .forms import DistributionForm, DistributionItemFormSet
from .models import Distribution, DistributionItem, DistributionStaffAssignment


def sync_distribution_staff_assignments(distribution, staff_users):
    selected_users = list(staff_users)
    selected_ids = {user.id for user in selected_users}

    distribution.staff_assignments.exclude(user_id__in=selected_ids).delete()

    existing_ids = set(
        distribution.staff_assignments.filter(user_id__in=selected_ids).values_list(
            "user_id", flat=True
        )
    )

    DistributionStaffAssignment.objects.bulk_create(
        [
            DistributionStaffAssignment(distribution=distribution, user=user)
            for user in selected_users
            if user.id not in existing_ids
        ]
    )


@login_required
def distribution_list(request):
    queryset = Distribution.objects.select_related("facility", "created_by").order_by(
        "-request_date"
    )

    search = request.GET.get("q", "").strip()
    if search:
        queryset = queryset.filter(
            Q(document_number__icontains=search) | Q(facility__name__icontains=search)
        )

    status = request.GET.get("status")
    if status:
        queryset = queryset.filter(status=status)

    d_type = request.GET.get("type")
    if d_type:
        queryset = queryset.filter(distribution_type=d_type)

    paginator = Paginator(queryset, 25)
    distributions = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "distribution/distribution_list.html",
        {
            "distributions": distributions,
            "search": search,
            "selected_status": status or "",
            "selected_type": d_type or "",
            "status_choices": Distribution.Status.choices,
            "type_choices": Distribution.DistributionType.choices,
        },
    )


@login_required
@perm_required("distribution.add_distribution")
def distribution_create(request):
    if request.method == "POST":
        form = DistributionForm(request.POST)
        formset = DistributionItemFormSet(request.POST, prefix="items")

        if form.is_valid() and formset.is_valid():
            dist = form.save(commit=False)
            dist.created_by = request.user
            dist.status = Distribution.Status.DRAFT
            dist.save()
            sync_distribution_staff_assignments(
                dist, form.cleaned_data.get("assigned_staff", [])
            )

            formset.instance = dist
            formset.save()

            messages.success(
                request, f"Distribusi {dist.document_number} berhasil dibuat."
            )
            return redirect("distribution:distribution_detail", pk=dist.pk)
    else:
        form = DistributionForm()
        formset = DistributionItemFormSet(prefix="items")

    return render(
        request,
        "distribution/distribution_form.html",
        {
            "form": form,
            "formset": formset,
            "title": "Buat Distribusi Baru",
            "is_edit": False,
        },
    )


@login_required
@perm_required("distribution.change_distribution")
def distribution_edit(request, pk):
    dist = get_object_or_404(Distribution, pk=pk)
    if dist.status not in (Distribution.Status.DRAFT, Distribution.Status.SUBMITTED):
        messages.error(request, "Hanya distribusi Draft/Diajukan yang dapat diubah.")
        return redirect("distribution:distribution_detail", pk=dist.pk)

    if request.method == "POST":
        form = DistributionForm(request.POST, instance=dist)
        formset = DistributionItemFormSet(request.POST, instance=dist, prefix="items")

        if form.is_valid() and formset.is_valid():
            form.save()
            sync_distribution_staff_assignments(
                dist, form.cleaned_data.get("assigned_staff", [])
            )
            formset.save()
            messages.success(
                request, f"Distribusi {dist.document_number} berhasil diperbarui."
            )
            return redirect("distribution:distribution_detail", pk=dist.pk)
    else:
        form = DistributionForm(instance=dist)
        formset = DistributionItemFormSet(instance=dist, prefix="items")

    return render(
        request,
        "distribution/distribution_form.html",
        {
            "form": form,
            "formset": formset,
            "title": f"Edit Distribusi {dist.document_number}",
            "is_edit": True,
            "distribution": dist,
        },
    )


@login_required
def distribution_detail(request, pk):
    dist = get_object_or_404(
        Distribution.objects.select_related(
            "facility", "created_by", "verified_by", "approved_by"
        ).prefetch_related("staff_assignments__user"),
        pk=pk,
    )
    items = dist.items.select_related("item", "item__satuan", "stock")
    assigned_staff = [assignment.user for assignment in dist.staff_assignments.all()]
    kepala_instalasi = (
        ModuleAccess.user.field.model.objects.filter(
            role=ModuleAccess.user.field.model.Role.KEPALA,
            is_active=True,
        )
        .order_by("full_name", "username")
        .first()
    )

    printable_items = []
    total_quantity = Decimal("0")
    grand_total = Decimal("0")
    for di in items:
        quantity = (
            di.quantity_approved
            if di.quantity_approved is not None
            else di.quantity_requested
        )
        unit_price = di.stock.unit_price if di.stock else None
        line_total = None
        if quantity is not None and unit_price is not None:
            line_total = quantity * unit_price

        if quantity is not None:
            total_quantity += quantity
        if line_total is not None:
            grand_total += line_total

        printable_items.append(
            {
                "line": di,
                "quantity": quantity,
                "unit_price": unit_price,
                "line_total": line_total,
            }
        )

    return render(
        request,
        "distribution/distribution_detail.html",
        {
            "distribution": dist,
            "items": items,
            "printable_items": printable_items,
            "total_quantity": total_quantity,
            "grand_total": grand_total,
            "assigned_staff": assigned_staff,
            "kepala_instalasi": kepala_instalasi,
        },
    )


# ---------- Workflow transitions ----------


@login_required
@perm_required("distribution.change_distribution")
def distribution_submit(request, pk):
    dist = get_object_or_404(Distribution, pk=pk)
    if request.method != "POST":
        return redirect("distribution:distribution_detail", pk=pk)

    if dist.status != Distribution.Status.DRAFT:
        messages.error(request, "Hanya distribusi Draft yang dapat diajukan.")
        return redirect("distribution:distribution_detail", pk=pk)

    if not dist.items.exists():
        messages.error(
            request, "Tambahkan minimal 1 item sebelum mengajukan distribusi."
        )
        return redirect("distribution:distribution_detail", pk=pk)

    if not dist.staff_assignments.exists():
        messages.error(
            request, "Pilih minimal 1 staf terlibat sebelum mengajukan distribusi."
        )
        return redirect("distribution:distribution_detail", pk=pk)

    dist.status = Distribution.Status.SUBMITTED
    dist.save(update_fields=["status", "updated_at"])
    messages.success(request, f"Distribusi {dist.document_number} berhasil diajukan.")
    return redirect("distribution:distribution_detail", pk=pk)


@login_required
@perm_required("distribution.change_distribution")
@module_scope_required(ModuleAccess.Module.DISTRIBUTION, ModuleAccess.Scope.APPROVE)
def distribution_verify(request, pk):
    dist = get_object_or_404(Distribution, pk=pk)
    if request.method != "POST":
        return redirect("distribution:distribution_detail", pk=pk)

    if dist.status != Distribution.Status.SUBMITTED:
        messages.error(
            request, "Hanya distribusi berstatus Diajukan yang dapat diverifikasi."
        )
        return redirect("distribution:distribution_detail", pk=pk)

    dist_items = list(dist.items.select_related("item", "stock"))
    if not dist_items:
        messages.error(request, "Distribusi tidak memiliki item untuk diverifikasi.")
        return redirect("distribution:distribution_detail", pk=pk)

    # Validate every item has quantity_approved and stock assigned
    for di in dist_items:
        if di.quantity_approved is None or di.quantity_approved <= 0:
            messages.error(
                request,
                f"Item {di.item.nama_barang}: jumlah disetujui harus diisi dan lebih dari 0.",
            )
            return redirect("distribution:distribution_detail", pk=pk)
        if di.stock is None:
            messages.error(
                request,
                f"Item {di.item.nama_barang}: batch stok harus dipilih sebelum verifikasi.",
            )
            return redirect("distribution:distribution_detail", pk=pk)
        # Check stock availability (no deduction yet)
        if di.quantity_approved > di.stock.available_quantity:
            messages.error(
                request,
                f"Stok tidak cukup untuk {di.item.nama_barang}. "
                f"Tersedia {di.stock.available_quantity}, disetujui {di.quantity_approved}.",
            )
            return redirect("distribution:distribution_detail", pk=pk)

    dist.status = Distribution.Status.VERIFIED
    dist.verified_by = request.user
    dist.verified_at = timezone.now()
    dist.save(update_fields=["status", "verified_by", "verified_at", "updated_at"])
    messages.success(
        request, f"Distribusi {dist.document_number} berhasil diverifikasi."
    )
    return redirect("distribution:distribution_detail", pk=pk)


@login_required
@perm_required("distribution.change_distribution")
def distribution_prepare(request, pk):
    dist = get_object_or_404(Distribution, pk=pk)
    if request.method != "POST":
        return redirect("distribution:distribution_detail", pk=pk)

    if dist.status != Distribution.Status.VERIFIED:
        messages.error(request, "Hanya distribusi terverifikasi yang dapat disiapkan.")
        return redirect("distribution:distribution_detail", pk=pk)

    dist.status = Distribution.Status.PREPARED
    dist.save(update_fields=["status", "updated_at"])
    messages.success(request, f"Distribusi {dist.document_number} ditandai disiapkan.")
    return redirect("distribution:distribution_detail", pk=pk)


@login_required
@perm_required("distribution.change_distribution")
def distribution_distribute(request, pk):
    """Final step: deduct stock and create Transaction(OUT) records."""
    dist = get_object_or_404(Distribution, pk=pk)
    if request.method != "POST":
        return redirect("distribution:distribution_detail", pk=pk)

    if dist.status != Distribution.Status.PREPARED:
        messages.error(
            request, "Hanya distribusi berstatus Disiapkan yang dapat didistribusikan."
        )
        return redirect("distribution:distribution_detail", pk=pk)

    dist_items = list(dist.items.select_related("item", "stock"))
    if not dist_items:
        messages.error(request, "Distribusi tidak memiliki item untuk didistribusikan.")
        return redirect("distribution:distribution_detail", pk=pk)

    try:
        with transaction.atomic():
            for di in dist_items:
                stock = Stock.objects.select_for_update().get(pk=di.stock_id)

                if stock.item_id != di.item_id:
                    raise ValueError(
                        f"Batch stok tidak sesuai untuk item {di.item.nama_barang}."
                    )

                qty = di.quantity_approved
                if qty > stock.available_quantity:
                    raise ValueError(
                        f"Stok tidak cukup untuk {di.item.nama_barang}. "
                        f"Tersedia {stock.available_quantity}, disetujui {qty}."
                    )

                stock.quantity = stock.quantity - qty
                stock.save(update_fields=["quantity", "updated_at"])

                Transaction.objects.create(
                    transaction_type=Transaction.TransactionType.OUT,
                    item=di.item,
                    location=stock.location,
                    batch_lot=stock.batch_lot,
                    quantity=qty,
                    unit_price=stock.unit_price,
                    sumber_dana=stock.sumber_dana,
                    reference_type=Transaction.ReferenceType.DISTRIBUTION,
                    reference_id=dist.id,
                    user=request.user,
                    notes=f"Distribusi {dist.document_number} ke {dist.facility}: {di.notes}".strip(),
                )

            dist.status = Distribution.Status.DISTRIBUTED
            dist.approved_by = request.user
            dist.approved_at = timezone.now()
            dist.distributed_date = timezone.now().date()
            dist.save(
                update_fields=[
                    "status",
                    "approved_by",
                    "approved_at",
                    "distributed_date",
                    "updated_at",
                ]
            )

    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("distribution:distribution_detail", pk=pk)

    messages.success(
        request,
        f"Distribusi {dist.document_number} berhasil didistribusikan dan stok diperbarui.",
    )
    return redirect("distribution:distribution_detail", pk=pk)


@login_required
@perm_required("distribution.change_distribution")
@module_scope_required(ModuleAccess.Module.DISTRIBUTION, ModuleAccess.Scope.APPROVE)
def distribution_reject(request, pk):
    dist = get_object_or_404(Distribution, pk=pk)
    if request.method != "POST":
        return redirect("distribution:distribution_detail", pk=pk)

    if dist.status != Distribution.Status.SUBMITTED:
        messages.error(
            request, "Hanya distribusi berstatus Diajukan yang dapat ditolak."
        )
        return redirect("distribution:distribution_detail", pk=pk)

    dist.status = Distribution.Status.REJECTED
    dist.save(update_fields=["status", "updated_at"])
    messages.success(request, f"Distribusi {dist.document_number} ditolak.")
    return redirect("distribution:distribution_detail", pk=pk)


@login_required
@perm_required("distribution.change_distribution")
def distribution_reset_to_draft(request, pk):
    dist = get_object_or_404(Distribution, pk=pk)
    if request.method != "POST":
        return redirect("distribution:distribution_detail", pk=pk)

    resettable_statuses = {
        Distribution.Status.SUBMITTED,
        Distribution.Status.VERIFIED,
        Distribution.Status.PREPARED,
        Distribution.Status.REJECTED,
    }

    if dist.status not in resettable_statuses:
        if dist.status == Distribution.Status.DISTRIBUTED:
            messages.error(
                request,
                "Distribusi yang sudah didistribusikan tidak dapat dikembalikan ke Draft.",
            )
        else:
            messages.error(
                request,
                "Status distribusi saat ini tidak dapat dikembalikan ke Draft.",
            )
        return redirect("distribution:distribution_detail", pk=pk)

    dist.status = Distribution.Status.DRAFT
    dist.verified_by = None
    dist.verified_at = None
    dist.approved_by = None
    dist.approved_at = None
    dist.distributed_date = None
    dist.save(
        update_fields=[
            "status",
            "verified_by",
            "verified_at",
            "approved_by",
            "approved_at",
            "distributed_date",
            "updated_at",
        ]
    )
    messages.success(
        request, f"Distribusi {dist.document_number} dikembalikan ke Draft."
    )
    return redirect("distribution:distribution_detail", pk=pk)


@login_required
@perm_required("distribution.change_distribution")
def distribution_step_back(request, pk):
    dist = get_object_or_404(Distribution, pk=pk)
    if request.method != "POST":
        return redirect("distribution:distribution_detail", pk=pk)

    previous_status_map = {
        Distribution.Status.SUBMITTED: Distribution.Status.DRAFT,
        Distribution.Status.VERIFIED: Distribution.Status.SUBMITTED,
        Distribution.Status.PREPARED: Distribution.Status.VERIFIED,
        Distribution.Status.REJECTED: Distribution.Status.SUBMITTED,
    }

    previous_status = previous_status_map.get(dist.status)
    if previous_status is None:
        if dist.status == Distribution.Status.DISTRIBUTED:
            messages.error(
                request,
                "Distribusi yang sudah didistribusikan tidak dapat dikembalikan ke status sebelumnya.",
            )
        else:
            messages.error(
                request,
                "Status distribusi saat ini tidak memiliki status sebelumnya.",
            )
        return redirect("distribution:distribution_detail", pk=pk)

    dist.status = previous_status

    update_fields = ["status", "updated_at"]

    if previous_status in {Distribution.Status.DRAFT, Distribution.Status.SUBMITTED}:
        dist.verified_by = None
        dist.verified_at = None
        update_fields.extend(["verified_by", "verified_at"])

    dist.save(update_fields=update_fields)
    messages.success(
        request,
        f"Distribusi {dist.document_number} dikembalikan ke status {dist.get_status_display()}.",
    )
    return redirect("distribution:distribution_detail", pk=pk)


@login_required
@perm_required("distribution.delete_distribution")
def distribution_delete(request, pk):
    dist = get_object_or_404(Distribution, pk=pk)
    if request.method != "POST":
        return redirect("distribution:distribution_detail", pk=pk)

    deletable_statuses = {
        Distribution.Status.DRAFT,
        Distribution.Status.REJECTED,
    }

    if dist.status not in deletable_statuses:
        messages.error(
            request,
            "Hanya distribusi berstatus Draft atau Ditolak yang dapat dihapus.",
        )
        return redirect("distribution:distribution_detail", pk=pk)

    document_number = dist.document_number
    dist.delete()
    messages.success(request, f"Distribusi {document_number} berhasil dihapus.")
    return redirect("distribution:distribution_list")
