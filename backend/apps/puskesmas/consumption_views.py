"""Inventory-facing actions and shared report output; no implicit postings on GET."""
from datetime import date
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.decorators import perm_required, module_scope_required
from apps.core.rate_limits import puskesmas_consumption_mutation_ratelimit
from apps.lplpo.models import LPLPO
from apps.users.models import ModuleAccess
from .consumption_inventory import finalize_consumption, month_end
from .inventory_locking import serialize_facility_document
from .inventory_reporting import adoption_digest, adopt_opening, period_rows
from .models import PuskesmasConsumption
from .stock_reports import stock_report_snapshot, report_links, report_category_totals


@login_required
@perm_required("puskesmas.change_puskesmasconsumption")
@puskesmas_consumption_mutation_ratelimit
@require_POST
def consumption_finalize(request, pk):
    from .views import _check_puskesmas_consumption_creator_access, _check_consumption_facility_access
    _check_puskesmas_consumption_creator_access(request)
    consumption = get_object_or_404(PuskesmasConsumption, pk=pk)
    _check_consumption_facility_access(request, consumption)
    try:
        finalize_consumption(user=request.user, consumption_id=pk, digest=request.POST.get("digest", ""))
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "Pemakaian difinalisasi dengan alokasi harga asli.")
    return redirect("puskesmas:consumption_detail", pk=pk)


@login_required
@perm_required("lplpo.change_lplpo")
@module_scope_required(ModuleAccess.Module.LPLPO, ModuleAccess.Scope.OPERATE)
@puskesmas_consumption_mutation_ratelimit
@serialize_facility_document("lplpo.LPLPO")
def opening_adoption(request, pk):
    from apps.lplpo.views import _check_puskesmas_draft_action_access, _check_facility_access
    _check_puskesmas_draft_action_access(request)
    lplpo = get_object_or_404(LPLPO.objects.select_related("facility"), pk=pk)
    _check_facility_access(request, lplpo, route_kind="draft_mutation")
    if request.method == "POST":
        try:
            adopt_opening(user=request.user, lplpo_id=pk, digest=request.POST.get("digest", ""))
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.success(request, "Saldo awal terverifikasi diadopsi; nilai sebelumnya dipertahankan dalam riwayat.")
            return redirect("lplpo:lplpo_detail", pk=pk)
    projected, accounts = period_rows([lplpo.facility_id], lplpo.tahun, lplpo.bulan)
    existing = {line.item_id: line for line in lplpo.items.select_related("item")}
    comparison = [{"item": row["item"], "previous": existing[row["item"].pk].stock_awal
                   if row["item"].pk in existing else 0, "verified": row["opening_quantity"]} for row in projected]
    projected_ids = {row["item"].pk for row in projected}
    comparison.extend({"item": line.item, "previous": line.stock_awal, "verified": 0}
                      for item_id, line in existing.items() if item_id not in projected_ids)
    return render(request, "puskesmas/inventory_adoption.html", {"lplpo": lplpo,
        "can_adopt": bool(accounts) and lplpo.bulan == 1 and lplpo.status in {LPLPO.Status.DRAFT, LPLPO.Status.REJECTED_PUSKESMAS},
        "comparison": comparison, "accounts": accounts, "digest": adoption_digest(lplpo)})


class InventoryPeriodForm(forms.Form):
    year = forms.IntegerField(min_value=1000, max_value=9999, label="Tahun")
    month = forms.IntegerField(min_value=1, max_value=12, label="Bulan")
    start_month = forms.IntegerField(min_value=1, max_value=12, required=False, label="Bulan awal (opsional)")

    def clean(self):
        data = super().clean()
        if data.get("start_month") and data.get("month") and data["start_month"] > data["month"]:
            self.add_error("start_month", "Bulan awal harus sebelum atau sama dengan bulan batas.")
        return data


@login_required
def inventory_report(request):
    from .views import _resolve_report_facility
    from apps.items.models import Facility
    facility, denied = _resolve_report_facility(request)
    if denied:
        return denied
    today = timezone.localdate()
    values = request.GET.copy()
    values.setdefault("year", str(today.year))
    values.setdefault("month", str(today.month))
    form = InventoryPeriodForm(values)
    from apps.users.access import puskesmas_report_access
    access = puskesmas_report_access(request.user)
    if access.can_select_facility:
        form.fields["facility"] = forms.ModelChoiceField(
            queryset=Facility.objects.filter(facility_type="PUSKESMAS", is_active=True).order_by("name"),
            required=False, label="Puskesmas",
            empty_label="Semua fasilitas" if access.can_aggregate else None)
        if facility:
            form.initial["facility"] = facility.pk
    rows, accounts, end = [], [], None
    metadata, links = None, {}
    facilities = Facility.objects.filter(facility_type="PUSKESMAS", is_active=True)
    if facility:
        facilities = facilities.filter(pk=facility.pk)
    if form.is_valid():
        year, month = form.cleaned_data["year"], form.cleaned_data["month"]
        end = month_end(year, month)
        start_month = form.cleaned_data.get("start_month") or month
        snapshot = stock_report_snapshot(facilities.order_by("name", "pk"), year, start_month, month,
                                         is_aggregate=facility is None)
        rows, accounts, metadata = snapshot["rows"], snapshot["accounts"], snapshot["metadata"]
        links = report_links(year, start_month, month, facility.pk if facility else None)
        if request.GET.get("format") == "excel":
            return inventory_workbook(rows, accounts, end, metadata["missing_baseline_count"],
                                      start=date(year, start_month, 1), report_metadata=metadata)
    params = values.copy()
    params.pop("page", None)
    params.pop("format", None)
    page = Paginator(rows, 25).get_page(request.GET.get("page"))
    print_mode = request.GET.get("format") == "print"
    return render(request, "puskesmas/inventory_report.html", {"form": form, "rows": rows if print_mode else page,
        "accounts": accounts, "cutoff": end, "facility": facility,
        "report_metadata": metadata, "selected_facility_name": facility.name if facility else "Semua Fasilitas",
        "period_label": "Rentang bulan", **links,
        "page_obj": page, "pagination_query": params.urlencode(), "print_mode": print_mode,
        "category_totals": report_category_totals(rows), "can_select_facility": access.can_select_facility,
        "excluded_count": metadata["missing_baseline_count"] if metadata else 0})


def inventory_workbook(rows, accounts, end, excluded_count, *, start=None, report_metadata=None):
    from openpyxl import Workbook
    from django.http import HttpResponse
    from apps.core.xlsx_exports import escape_xlsx_formula
    wb = Workbook()
    ws = wb.active
    ws.title = "Persediaan Puskesmas"
    ws.append(["Batas laporan", str(end), "BELUM LENGKAP — hanya mutasi tercatat; bukan hasil hitung fisik"])
    ws.append(["Fasilitas tanpa sumber saldo", excluded_count, "Awal interval", str(start or "")])
    ws.append(["Fasilitas", "Kode", "Barang", "Awal qty", "Awal nilai", "Terima qty", "Terima nilai",
               "Pakai qty", "Pakai nilai", "Akhir qty", "Akhir nilai", "Kedaluwarsa qty", "Kedaluwarsa nilai"])
    for row in rows:
        ws.append([escape_xlsx_formula(row["facility_name"]), escape_xlsx_formula(row["item"].kode_barang),
            escape_xlsx_formula(row["item"].nama_barang)] + [format(row[f"{kind}_{unit}"], "f") if row[f"{kind}_{unit}"] is not None else "—"
            for kind in ("opening", "receipts", "consumption", "closing", "expiry") for unit in ("quantity", "value")])
    detail = wb.create_sheet("Lapisan Harga Asli")
    detail.append(["Fasilitas", "Barang", "Lapisan", "Batch", "Kedaluwarsa", "Sumber", "Qty", "Harga asli", "Nilai"])
    for row in rows:
        for entry in row["layers"]:
            layer = entry["layer"]
            detail.append([escape_xlsx_formula(row["facility_name"]), escape_xlsx_formula(row["item"].kode_barang),
                layer.pk, escape_xlsx_formula(layer.batch_lot), str(layer.expiry_date or ""),
                escape_xlsx_formula(layer.source_document_number), format(entry["quantity"], "f"),
                format(layer.unit_price, "f"), format(entry["value"], "f")])
    ws.freeze_panes = "D4"
    detail.freeze_panes = "D2"
    recap = wb.create_sheet("Rekap Nilai")
    recap.append(["Kategori", "Saldo awal", "Penerimaan", "Pemakaian", "Saldo akhir", "Kedaluwarsa"])
    for entry in report_category_totals(rows):
        recap.append([escape_xlsx_formula(entry["name"])] + [format(entry[f"{kind}_value"], "f")
            for kind in ("opening", "receipts", "consumption", "closing", "expiry")])
    if report_metadata:
        from .exports import add_persediaan_source_sheet
        add_persediaan_source_sheet(wb, report_metadata, "Persediaan Puskesmas", end.year, "Rentang bulan")
    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="persediaan-puskesmas.xlsx"'
    wb.save(response)
    return response
