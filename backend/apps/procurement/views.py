from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.decorators import module_scope_required, perm_required
from apps.core.rate_limits import procurement_mutation_ratelimit
from apps.users.models import ModuleAccess

from .forms import (
    ProcurementAmendmentForm,
    ProcurementAmendmentLineFormSet,
    ProcurementContractForm,
    ProcurementContractLineFormSet,
)
from .models import (
    ProcurementAmendment,
    ProcurementAmendmentLine,
    ProcurementContract,
    ProcurementContractLine,
    ProcurementWorkflowError,
)
from .services import (
    approve_amendment,
    approve_contract,
    build_contract_summary_rows,
    close_contract,
    submit_amendment,
    submit_contract,
)


def _redirect_contract_detail(pk):
    return redirect("procurement:contract_detail", pk=pk)


def _redirect_amendment_detail(pk):
    return redirect("procurement:amendment_detail", pk=pk)


@login_required
@perm_required("procurement.view_procurementcontract")
def contract_list(request):
    queryset = (
        ProcurementContract.objects.select_related(
            "supplier",
            "sumber_dana",
            "created_by",
            "approved_by",
        )
        .annotate(
            line_count=Count("lines", distinct=True),
            amendment_count=Count("amendments", distinct=True),
        )
        .order_by("-contract_date", "-created_at")
    )

    search = request.GET.get("q", "").strip()
    if search:
        queryset = queryset.filter(
            Q(document_number__icontains=search)
            | Q(supplier__name__icontains=search)
            | Q(lines__item__nama_barang__icontains=search)
        ).distinct()

    status = request.GET.get("status", "").strip()
    if status:
        queryset = queryset.filter(status=status)

    contracts = Paginator(queryset, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "procurement/contract_list.html",
        {
            "contracts": contracts,
            "search": search,
            "selected_status": status,
            "status_choices": ProcurementContract.Status.choices,
            "page_title": "SPJ / Pengadaan",
        },
    )


@login_required
@perm_required("procurement.view_procurementcontract")
def contract_detail(request, pk):
    contract = get_object_or_404(
        ProcurementContract.objects.select_related(
            "supplier",
            "sumber_dana",
            "created_by",
            "submitted_by",
            "approved_by",
            "closed_by",
        ).prefetch_related(
            Prefetch(
                "lines",
                queryset=ProcurementContractLine.objects.select_related("item").order_by(
                    "item__nama_barang", "pk"
                ),
            ),
            Prefetch(
                "amendments",
                queryset=ProcurementAmendment.objects.select_related(
                    "created_by", "approved_by"
                ).order_by("-amendment_date", "-created_at"),
            ),
        ),
        pk=pk,
    )
    summary_rows, linked_receiving = build_contract_summary_rows(contract)
    return render(
        request,
        "procurement/contract_detail.html",
        {
            "contract": contract,
            "summary_rows": summary_rows,
            "linked_receiving": linked_receiving,
            "page_title": "Detail SPJ / Pengadaan",
        },
    )


@login_required
@perm_required("procurement.add_procurementcontract")
@procurement_mutation_ratelimit
def contract_create(request):
    if request.method == "POST":
        form = ProcurementContractForm(request.POST)
        formset = ProcurementContractLineFormSet(request.POST, prefix="lines")
        if form.is_valid() and formset.is_valid():
            contract = form.save(commit=False)
            contract.created_by = request.user
            contract.status = ProcurementContract.Status.DRAFT
            contract.save()
            formset.instance = contract
            formset.save()
            messages.success(request, f"Kontrak {contract.document_number} berhasil dibuat.")
            return redirect("procurement:contract_detail", pk=contract.pk)
    else:
        form = ProcurementContractForm(initial={"contract_date": timezone.now().date()})
        formset = ProcurementContractLineFormSet(prefix="lines")

    return render(
        request,
        "procurement/contract_form.html",
        {
            "title": "Buat SPJ / Pengadaan",
            "page_title": "Buat SPJ / Pengadaan",
            "form": form,
            "formset": formset,
            "is_edit": False,
        },
    )


@login_required
@perm_required("procurement.change_procurementcontract")
@procurement_mutation_ratelimit
def contract_edit(request, pk):
    contract = get_object_or_404(ProcurementContract, pk=pk)
    if contract.status != ProcurementContract.Status.DRAFT:
        messages.error(request, "Hanya kontrak Draft yang dapat diubah.")
        return _redirect_contract_detail(pk)

    if request.method == "POST":
        form = ProcurementContractForm(request.POST, instance=contract)
        formset = ProcurementContractLineFormSet(request.POST, instance=contract, prefix="lines")
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, f"Kontrak {contract.document_number} berhasil diperbarui.")
            return _redirect_contract_detail(pk)
    else:
        form = ProcurementContractForm(instance=contract)
        formset = ProcurementContractLineFormSet(instance=contract, prefix="lines")

    return render(
        request,
        "procurement/contract_form.html",
        {
            "title": f"Edit {contract.document_number}",
            "page_title": "Edit SPJ / Pengadaan",
            "form": form,
            "formset": formset,
            "contract": contract,
            "is_edit": True,
        },
    )


@login_required
@perm_required("procurement.change_procurementcontract")
@procurement_mutation_ratelimit
def contract_submit(request, pk):
    contract = get_object_or_404(ProcurementContract, pk=pk)
    if request.method != "POST":
        return _redirect_contract_detail(pk)
    if contract.status != ProcurementContract.Status.DRAFT:
        messages.error(request, "Hanya kontrak Draft yang dapat diajukan.")
        return _redirect_contract_detail(pk)
    try:
        submit_contract(contract, request.user)
    except ProcurementWorkflowError as exc:
        messages.error(request, str(exc))
        return _redirect_contract_detail(pk)
    messages.success(request, f"Kontrak {contract.document_number} berhasil diajukan.")
    return _redirect_contract_detail(pk)


@login_required
@perm_required("procurement.change_procurementcontract")
@module_scope_required(ModuleAccess.Module.PROCUREMENT, ModuleAccess.Scope.APPROVE)
@procurement_mutation_ratelimit
def contract_approve(request, pk):
    contract = get_object_or_404(ProcurementContract, pk=pk)
    if request.method != "POST":
        return _redirect_contract_detail(pk)
    if contract.status != ProcurementContract.Status.SUBMITTED:
        messages.error(request, "Hanya kontrak Diajukan yang dapat disetujui.")
        return _redirect_contract_detail(pk)
    try:
        approve_contract(contract, request.user)
    except ProcurementWorkflowError as exc:
        messages.error(request, str(exc))
        return _redirect_contract_detail(pk)
    messages.success(
        request,
        f"Kontrak {contract.document_number} disetujui dan rencana penerimaan dibuat otomatis.",
    )
    return _redirect_contract_detail(pk)


@login_required
@perm_required("procurement.change_procurementcontract")
@procurement_mutation_ratelimit
def contract_close(request, pk):
    contract = get_object_or_404(ProcurementContract, pk=pk)
    if request.method != "POST":
        return _redirect_contract_detail(pk)
    if contract.status != ProcurementContract.Status.APPROVED:
        messages.error(request, "Hanya kontrak Disetujui yang dapat ditutup.")
        return _redirect_contract_detail(pk)
    try:
        close_contract(contract, request.user)
    except ProcurementWorkflowError as exc:
        messages.error(request, str(exc))
        return _redirect_contract_detail(pk)
    messages.success(request, f"Kontrak {contract.document_number} berhasil ditutup.")
    return _redirect_contract_detail(pk)


@login_required
@perm_required("procurement.add_procurementamendment")
@procurement_mutation_ratelimit
def amendment_create(request, pk):
    contract = get_object_or_404(ProcurementContract, pk=pk)
    if contract.status != ProcurementContract.Status.APPROVED:
        messages.error(request, "Amandemen hanya dapat dibuat untuk kontrak yang sudah disetujui.")
        return _redirect_contract_detail(pk)
    if contract.closed_at is not None:
        messages.error(request, "Kontrak yang sudah ditutup tidak dapat diamandemen.")
        return _redirect_contract_detail(pk)

    if request.method == "POST":
        form = ProcurementAmendmentForm(request.POST)
        formset = ProcurementAmendmentLineFormSet(
            request.POST,
            prefix="lines",
            form_kwargs={"contract": contract},
        )
        if form.is_valid() and formset.is_valid():
            amendment = form.save(commit=False)
            amendment.contract = contract
            amendment.created_by = request.user
            amendment.status = ProcurementAmendment.Status.DRAFT
            amendment.save()
            formset.instance = amendment
            formset.save()
            messages.success(request, f"Amandemen {amendment.document_number} berhasil dibuat.")
            return redirect("procurement:amendment_detail", pk=amendment.pk)
    else:
        form = ProcurementAmendmentForm(initial={"amendment_date": timezone.now().date()})
        formset = ProcurementAmendmentLineFormSet(
            prefix="lines",
            form_kwargs={"contract": contract},
        )

    return render(
        request,
        "procurement/amendment_form.html",
        {
            "title": f"Buat Amandemen untuk {contract.document_number}",
            "page_title": "Buat Amandemen SPJ",
            "form": form,
            "formset": formset,
            "contract": contract,
            "is_edit": False,
        },
    )


@login_required
@perm_required("procurement.view_procurementamendment")
def amendment_detail(request, pk):
    amendment = get_object_or_404(
        ProcurementAmendment.objects.select_related(
            "contract",
            "created_by",
            "submitted_by",
            "approved_by",
        ).prefetch_related(
            Prefetch(
                "lines",
                queryset=ProcurementAmendmentLine.objects.select_related(
                    "contract_line",
                    "contract_line__item",
                ).order_by("contract_line__item__nama_barang", "pk"),
            )
        ),
        pk=pk,
    )
    return render(
        request,
        "procurement/amendment_detail.html",
        {
            "amendment": amendment,
            "contract": amendment.contract,
            "page_title": "Detail Amandemen SPJ",
        },
    )


@login_required
@perm_required("procurement.change_procurementamendment")
@procurement_mutation_ratelimit
def amendment_edit(request, pk):
    amendment = get_object_or_404(ProcurementAmendment.objects.select_related("contract"), pk=pk)
    if amendment.status != ProcurementAmendment.Status.DRAFT:
        messages.error(request, "Hanya amandemen Draft yang dapat diubah.")
        return _redirect_amendment_detail(pk)

    if request.method == "POST":
        form = ProcurementAmendmentForm(request.POST, instance=amendment)
        formset = ProcurementAmendmentLineFormSet(
            request.POST,
            instance=amendment,
            prefix="lines",
            form_kwargs={"contract": amendment.contract},
        )
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, f"Amandemen {amendment.document_number} berhasil diperbarui.")
            return _redirect_amendment_detail(pk)
    else:
        form = ProcurementAmendmentForm(instance=amendment)
        formset = ProcurementAmendmentLineFormSet(
            instance=amendment,
            prefix="lines",
            form_kwargs={"contract": amendment.contract},
        )

    return render(
        request,
        "procurement/amendment_form.html",
        {
            "title": f"Edit {amendment.document_number}",
            "page_title": "Edit Amandemen SPJ",
            "form": form,
            "formset": formset,
            "contract": amendment.contract,
            "amendment": amendment,
            "is_edit": True,
        },
    )


@login_required
@perm_required("procurement.change_procurementamendment")
@procurement_mutation_ratelimit
def amendment_submit(request, pk):
    amendment = get_object_or_404(ProcurementAmendment.objects.select_related("contract"), pk=pk)
    if request.method != "POST":
        return _redirect_amendment_detail(pk)
    if amendment.status != ProcurementAmendment.Status.DRAFT:
        messages.error(request, "Hanya amandemen Draft yang dapat diajukan.")
        return _redirect_amendment_detail(pk)
    try:
        submit_amendment(amendment, request.user)
    except ProcurementWorkflowError as exc:
        messages.error(request, str(exc))
        return _redirect_amendment_detail(pk)
    messages.success(request, f"Amandemen {amendment.document_number} berhasil diajukan.")
    return _redirect_amendment_detail(pk)


@login_required
@perm_required("procurement.change_procurementamendment")
@module_scope_required(ModuleAccess.Module.PROCUREMENT, ModuleAccess.Scope.APPROVE)
@procurement_mutation_ratelimit
def amendment_approve(request, pk):
    amendment = get_object_or_404(ProcurementAmendment.objects.select_related("contract"), pk=pk)
    if request.method != "POST":
        return _redirect_amendment_detail(pk)
    if amendment.status != ProcurementAmendment.Status.SUBMITTED:
        messages.error(request, "Hanya amandemen Diajukan yang dapat disetujui.")
        return _redirect_amendment_detail(pk)
    try:
        approve_amendment(amendment, request.user)
    except ProcurementWorkflowError as exc:
        messages.error(request, str(exc))
        return _redirect_amendment_detail(pk)
    messages.success(
        request,
        f"Amandemen {amendment.document_number} disetujui dan rencana penerimaan diperbarui.",
    )
    return _redirect_amendment_detail(pk)
