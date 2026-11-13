"""Opening-stock preparation and independent verification; no current-stock UI."""
import csv

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django_ratelimit.decorators import ratelimit

from apps.core.upload_validation import validate_csv_upload
from apps.core.csv_exports import sanitize_csv_row
from apps.core.decimal_validation import multiply_decimals, sum_decimals
from apps.items.models import Facility
from .inventory import (
    WORKSHEET_HEADERS, MAX_BYTES, MAX_ROWS, can_prepare, can_verify, parse_csv, prepare_opening,
    submit_opening, review_opening, line_errors,
    worksheet_rows,
)
from .models import PuskesmasOpeningVerification, PuskesmasInventoryPosting

inventory_ratelimit = ratelimit(key="user_or_ip", method="POST", rate="10/m", block=True,
                               group="puskesmas.inventory_opening")


class OpeningScopeForm(forms.Form):
    facility = forms.ModelChoiceField(label="Puskesmas", queryset=Facility.objects.none())
    year = forms.IntegerField(label="Tahun saldo awal (1 Januari)", min_value=1000)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["year"].max_value = timezone.localdate().year
        facilities = Facility.objects.filter(is_active=True, facility_type="PUSKESMAS")
        if not user.is_superuser:
            facilities = facilities.filter(pk=user.facility_id)
            self.fields["facility"].initial = user.facility_id
            self.fields["facility"].disabled = True
        self.fields["facility"].queryset = facilities.order_by("name")

    def clean_year(self):
        year = self.cleaned_data["year"]
        if year > timezone.localdate().year:
            raise forms.ValidationError("Tahun saldo awal tidak boleh berada di masa depan.")
        return year


class OpeningForm(OpeningScopeForm):
    reference = forms.CharField(label="Referensi bukti verifikasi", max_length=100)
    notes = forms.CharField(label="Catatan", max_length=1000, required=False, widget=forms.Textarea(attrs={"rows": 3}))
    csv_file = forms.FileField(label="CSV saldo awal")
    boundary_attested = forms.BooleanField(label="Saldo mencakup gudang, ruang tindakan dan Pustu sebelum mutasi 1 Januari; penerimaan sejak tanggal itu tidak dimasukkan kembali.")

    def clean(self):
        data = super().clean()
        upload = data.get("csv_file")
        data["rows"] = []
        if upload and data.get("facility") and data.get("year"):
            validate_csv_upload(upload, max_size_bytes=MAX_BYTES)
            try:
                data["rows"] = parse_csv(upload.read().decode("utf-8-sig"),
                    facility_id=data["facility"].pk, year=data["year"])
            except UnicodeDecodeError as exc:
                raise forms.ValidationError("CSV harus UTF-8.") from exc
        return data


def scoped_openings(request):
    user = request.user
    qs = PuskesmasOpeningVerification.objects.select_related("facility", "created_by", "reviewed_by")
    if can_verify(user):
        if user.is_superuser:
            return qs
        return qs.filter(status__in=["SUBMITTED", "POSTED", "REJECTED"])
    if can_prepare(user):
        return qs.filter(facility_id=user.facility_id).filter(~Q(status="DRAFT") | Q(created_by=user))
    from .views import _resolve_report_facility
    from apps.users.access import puskesmas_report_access
    if not puskesmas_report_access(user).allowed:
        raise PermissionDenied
    facility, error = _resolve_report_facility(request)
    if error:
        raise PermissionDenied
    qs = qs.exclude(status="DRAFT")
    return qs.filter(facility=facility) if facility else qs


@login_required
def opening_list(request):
    return render(request, "puskesmas/inventory_list.html", {
        "openings": scoped_openings(request)[:100], "can_prepare": can_prepare(request.user)})


@login_required
def opening_template(request):
    if not can_prepare(request.user):
        raise PermissionDenied
    scope_data = request.GET.copy()
    if not scope_data.get("year"):
        scope_data["year"] = timezone.localdate().year
    scope = OpeningScopeForm(scope_data, user=request.user, auto_id="template_%s", initial={"year": timezone.localdate().year})
    rows = []
    if scope.is_valid():
        from itertools import islice
        rows = list(islice(worksheet_rows(facility_id=scope.cleaned_data["facility"].pk,
            year=scope.cleaned_data["year"]), MAX_ROWS + 1))
        if len(rows) > MAX_ROWS:
            scope.add_error(None, f"Lebih dari {MAX_ROWS} lapisan sumber; hubungi Instalasi Farmasi untuk menyiapkan file dalam batas impor.")
    if not scope.is_valid():
        return render(request, "puskesmas/inventory_form.html", {
            "form": OpeningForm(user=request.user, initial={"year": timezone.localdate().year}),
            "template_form": scope, "template_open": True,
        }, status=400)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="puskesmas_opening_template.csv"'
    writer = csv.writer(response)
    writer.writerow(WORKSHEET_HEADERS)
    for row in rows:
        writer.writerow(sanitize_csv_row(row))
    return response


@login_required
@inventory_ratelimit
def opening_create(request):
    if not can_prepare(request.user):
        raise PermissionDenied
    form = OpeningForm(request.POST or None, request.FILES or None, user=request.user,
                       initial={"year": timezone.localdate().year})
    if request.method == "POST" and form.is_valid():
        try:
            data = form.cleaned_data
            opening = prepare_opening(user=request.user, facility_id=data["facility"].pk,
                year=data["year"], reference=data["reference"], notes=data["notes"],
                rows=data["rows"])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("puskesmas:opening_detail", pk=opening.pk)
    return render(request, "puskesmas/inventory_form.html", {"form": form,
        "template_form": OpeningScopeForm(user=request.user, auto_id="template_%s", initial={"year": timezone.localdate().year})})


@login_required
@inventory_ratelimit
def opening_detail(request, pk):
    opening = get_object_or_404(scoped_openings(request), pk=pk)
    if request.method == "POST":
        try:
            action = request.POST.get("action")
            if action == "submit":
                submit_opening(user=request.user, opening_id=pk, digest=request.POST.get("digest", ""))
            elif action in {"post", "reject"}:
                if action == "post" and request.POST.get("verified") != "yes":
                    raise ValidationError("Konfirmasi pemeriksaan bukti dan batas saldo awal wajib diisi.")
                review_opening(user=request.user, opening_id=pk, digest=request.POST.get("digest", ""),
                    reject_reason=request.POST.get("reason", "") if action == "reject" else None)
            else:
                raise ValidationError("Tindakan tidak valid.")
        except ValidationError as exc:
            for error in exc.messages:
                messages.error(request, error)
        else:
            messages.success(request, "Tindakan saldo awal berhasil disimpan.")
        return redirect("puskesmas:opening_detail", pk=pk)
    lines = list(opening.lines.select_related("item", "sumber_dana"))
    rows = [{"line": line, "errors": line_errors(line),
             "value": multiply_decimals(line.quantity, line.unit_price) if line.unit_price is not None else None}
            for line in lines]
    receipt_postings = PuskesmasInventoryPosting.objects.filter(facility=opening.facility, receipt__isnull=False).select_related("receipt")
    return render(request, "puskesmas/inventory_detail.html", {
        "opening": opening, "rows": rows, "total": sum_decimals(row["value"] for row in rows if row["value"] is not None),
        "has_holds": any(row["errors"] for row in rows),
        "can_submit": can_prepare(request.user) and opening.created_by_id == request.user.pk and opening.status == "DRAFT",
        "can_review": can_verify(request.user) and opening.created_by_id != request.user.pk and opening.status == "SUBMITTED",
        "receipt_postings": receipt_postings if opening.status == "POSTED" else [],
    })
