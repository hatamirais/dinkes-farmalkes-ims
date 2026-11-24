"""Facility-isolated expiry visibility and deliberate operator postings."""
from datetime import timedelta
from uuid import uuid4

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q, Max
from django.forms import formset_factory, BaseFormSet
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.decorators import perm_required
from apps.core.rate_limits import puskesmas_consumption_mutation_ratelimit
from apps.items.models import Facility, Item, Category
from apps.core.expiry_monitoring import expiry_display, expiry_levels, expiry_level_filter
from apps.core.form_fields import ItemBatchSelect
from apps.core.decimal_validation import format_price_exact
from .inventory import text_value
from apps.users.access import is_super_admin, has_module_permission
from .consumption_inventory import assert_operator
from .expiry import post_expiry, current_revision
from .expiry_models import PuskesmasExpiry, PuskesmasExpiryRevision
from .inventory_models import PuskesmasInventoryLayer


def _facility(request, document=None):
    if document:
        facility = document.facility
    elif is_super_admin(request.user):
        raw = request.POST.get("facility") if request.method == "POST" else request.GET.get("facility")
        form = forms.ModelChoiceField(queryset=Facility.objects.filter(facility_type="PUSKESMAS", is_active=True))
        try:
            facility = form.clean(raw) if raw else None
        except ValidationError as exc:
            raise PermissionDenied from exc
    else:
        facility = request.user.facility
    if facility and (not facility.is_active or facility.facility_type != "PUSKESMAS"):
        raise PermissionDenied
    if not is_super_admin(request.user) and (not facility or facility.pk != request.user.facility_id):
        raise PermissionDenied
    return facility


class ExpiryFilter(forms.Form):
    q = forms.CharField(label="Cari barang / batch / sumber", required=False, max_length=100)
    category = forms.ModelChoiceField(label="Kategori", required=False, queryset=Category.objects.none(), empty_label="Semua kategori")
    level = forms.ChoiceField(label="Status ED", choices=expiry_levels(30), initial="all")
    sort = forms.ChoiceField(label="Urutkan", choices=[("expiry", "Tanggal ED"), ("code", "Kode barang"),
        ("name", "Nama barang"), ("category", "Kategori"), ("batch", "Batch"),
        ("available", "Saldo jurnal"), ("price", "Harga asli"), ("source", "Nomor sumber")], initial="expiry")
    dir = forms.ChoiceField(label="Arah", choices=[("asc", "Naik"), ("desc", "Turun")], initial="asc")
    days = forms.IntegerField(label="Jendela peringatan (hari)", min_value=1, max_value=365, initial=30,
        help_text="Hanya mengatur daftar; tidak menandai atau mengurangi stok otomatis.")
    page_size = forms.TypedChoiceField(label="Baris per halaman", coerce=int,
        choices=[(n, n) for n in (25, 50, 100, 200)], initial=25)

    def __init__(self, *args, layers, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(pk__in=layers.values("item__kategori_id")).order_by("sort_order", "name")

    def clean_q(self):
        return text_value(self.cleaned_data["q"], 100)

    def clean(self):
        data = super().clean()
        if data.get("days"):
            self.fields["level"].choices = expiry_levels(data["days"])
        return data


class LayerChoice(forms.ModelChoiceField):
    def label_from_instance(self, layer):
        price = format_price_exact(layer.unit_price).replace(".", ",")
        return f"Batch {layer.batch_lot or 'tidak diketahui'} · ED {layer.expiry_date} · Sumber {layer.source_document_number or 'tidak diketahui'} · Dana {layer.sumber_dana or 'tidak diketahui'} · Rp {price} · Lapisan #{layer.pk} · Saldo jurnal {layer.balance.quantity}"


class ExpiryLineForm(forms.Form):
    item = forms.ModelChoiceField(queryset=Item.objects.none(), label="Barang",
        widget=forms.Select(attrs={"class": "js-typeahead-select js-item-select"}))
    layer = LayerChoice(queryset=PuskesmasInventoryLayer.objects.none(), label="Batch / lapisan stok",
        widget=ItemBatchSelect(attrs={"class": "js-stock-select"}))
    quantity = forms.IntegerField(min_value=0, max_value=2147483647, label="Jumlah ditarik")

    def __init__(self, *args, facility=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["layer"].queryset = PuskesmasInventoryLayer.objects.filter(posting__facility=facility,
            expiry_date__isnull=False).select_related("item", "balance", "sumber_dana").order_by("item__nama_barang", "expiry_date", "pk")
        self.fields["item"].queryset = Item.objects.filter(pk__in=self.fields["layer"].queryset.values("item_id")).order_by("nama_barang", "pk")
        self.fields["item"].label_from_instance = lambda item: item.picker_label

    def clean(self):
        data = super().clean()
        if data.get("item") and data.get("layer") and data["item"].pk != data["layer"].item_id:
            self.add_error("layer", "Batch stok harus sesuai dengan barang yang dipilih.")
        return data


class ExpiryBaseFormSet(BaseFormSet):
    def add_fields(self, form, index):
        super().add_fields(form, index)
        form.fields["DELETE"].label = "Abaikan baris ini"


ExpiryLines = formset_factory(ExpiryLineForm, formset=ExpiryBaseFormSet, extra=1, max_num=100, validate_max=True, absolute_max=100,
                             can_delete=True)


class ExpiryForm(forms.Form):
    effective_date = forms.DateField(label="Tanggal aktual penarikan dari stok", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    reference = forms.CharField(label="Referensi bukti (opsional)", max_length=100, required=False)
    reason = forms.CharField(label="Alasan penandaan / koreksi", max_length=1000, widget=forms.Textarea(attrs={"rows": 3}))
    confirmed = forms.BooleanField(label="Saya memastikan jumlah ini ditarik dari stok yang boleh digunakan. Penandaan ini bukan bukti pemusnahan atau pengembalian fisik.")
    request_key = forms.UUIDField(widget=forms.HiddenInput)
    expected_digest = forms.CharField(widget=forms.HiddenInput, required=False)


@login_required
@perm_required("puskesmas.view_puskesmasexpiry")
def expiry_list(request):
    facility = _facility(request)
    values = request.GET.copy()
    values.setdefault("days", "30")
    values.setdefault("page_size", "25")
    for key, default in (("level", "all"), ("sort", "expiry"), ("dir", "asc")):
        values.setdefault(key, default)
    layers = PuskesmasInventoryLayer.objects.filter(balance__quantity__gt=0,
        posting__facility__is_active=True, expiry_date__isnull=False)
    if facility:
        layers = layers.filter(posting__facility=facility)
    form = ExpiryFilter(values, layers=layers)
    rows = []
    if form.is_valid():
        today = timezone.localdate()
        data = form.cleaned_data
        layers = layers.filter(expiry_date__lte=today + timedelta(days=data["days"])).filter(
            expiry_level_filter("expiry_date", data["level"], today))
        if data["q"]:
            search = data["q"]
            layers = layers.filter(Q(item__kode_barang__icontains=search) | Q(item__nama_barang__icontains=search) |
                Q(item__kategori__name__icontains=search) | Q(batch_lot__icontains=search) | Q(source_document_number__icontains=search))
        if data["category"]:
            layers = layers.filter(item__kategori=data["category"])
        fields = {"expiry": "expiry_date", "code": "item__kode_barang", "name": "item__nama_barang",
            "category": "item__kategori__name", "batch": "batch_lot", "available": "balance__quantity",
            "price": "unit_price", "source": "source_document_number"}
        field = fields[data["sort"]]
        layers = layers.select_related("item__kategori", "posting__facility", "balance", "sumber_dana").order_by(
            ("-" if data["dir"] == "desc" else "") + field, "expiry_date", "pk")
        for layer in layers:
            rows.append(dict(layer=layer, **expiry_display(layer.expiry_date, today)))
    documents = PuskesmasExpiry.objects.select_related("facility").annotate(last_number=Max("revisions__number"))
    if facility:
        documents = documents.filter(facility=facility)
    elif is_super_admin(request.user):
        documents = documents.filter(facility__is_active=True)
    can_manage = is_super_admin(request.user) or (request.user.role == "PUSKESMAS" and (
        request.user.has_perm("puskesmas.add_puskesmasexpiry") or has_module_permission(request.user, "puskesmas.add_puskesmasexpiry")))
    page = Paginator(rows, form.cleaned_data["page_size"] if form.is_valid() else 25).get_page(request.GET.get("page"))
    params = values.copy()
    params.pop("page", None)
    return render(request, "puskesmas/expiry_list.html", dict(form=form, facility=facility,
        facilities=Facility.objects.filter(facility_type="PUSKESMAS", is_active=True).order_by("name") if is_super_admin(request.user) else [],
        rows=page, pagination_query=params.urlencode(), page_range=page.paginator.get_elided_page_range(page.number),
        documents=documents[:50], can_manage=can_manage))


@login_required
@perm_required("puskesmas.add_puskesmasexpiry")
@puskesmas_consumption_mutation_ratelimit
def expiry_create(request):
    return _expiry_form(request)


@login_required
@perm_required("puskesmas.change_puskesmasexpiry")
@puskesmas_consumption_mutation_ratelimit
def expiry_edit(request, pk):
    document = get_object_or_404(PuskesmasExpiry.objects.select_related("facility"), pk=pk)
    return _expiry_form(request, document)


def _expiry_form(request, document=None):
    facility = _facility(request, document)
    if facility:
        assert_operator(request.user, facility,
            permission="puskesmas.change_puskesmasexpiry" if document else "puskesmas.add_puskesmasexpiry")
    elif not is_super_admin(request.user):
        raise PermissionDenied
    previous = current_revision(document) if document else None
    if previous and previous.void:
        messages.error(request, "Dokumen dibatalkan tetap disimpan; buat dokumen baru.")
        return redirect("puskesmas:expiry_detail", pk=document.pk)
    initial = dict(effective_date=previous.effective_date if previous else timezone.localdate(),
        reference=previous.reference if previous else "", reason="", request_key=document.request_key if document else uuid4(),
        expected_digest=previous.digest if previous else "")
    form = ExpiryForm(request.POST or None, initial=initial)
    if previous:
        form.fields["effective_date"].disabled = True
    initial_lines = [dict(item=line.layer.item_id, layer=line.layer_id, quantity=line.quantity)
        for line in previous.lines.select_related("layer")] if previous else []
    lines = ExpiryLines(request.POST or None, initial=initial_lines, form_kwargs={"facility": facility})
    if request.method == "POST" and form.is_valid() and (request.POST.get("action") == "void" or lines.is_valid()):
        try:
            if not facility:
                raise ValidationError("Pilih fasilitas terlebih dahulu.")
            void = request.POST.get("action") == "void"
            entries = [] if void else [dict(layer_id=line.cleaned_data["layer"].pk,
                quantity=line.cleaned_data["quantity"]) for line in lines if line.cleaned_data and not line.cleaned_data.get("DELETE")]
            revision = post_expiry(user=request.user, facility_id=facility.pk, entries=entries,
                effective_date=form.cleaned_data["effective_date"], reference=form.cleaned_data["reference"],
                reason=form.cleaned_data["reason"], request_key=form.cleaned_data["request_key"],
                expiry_id=document.pk if document else None, expected_digest=form.cleaned_data["expected_digest"], void=void)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Penarikan kedaluwarsa dan laporan terdampak disimpan dengan jejak revisi.")
            return redirect("puskesmas:expiry_detail", pk=revision.expiry_id)
    return render(request, "puskesmas/expiry_form.html", dict(form=form, lines=lines, document=document,
        facility=facility, facilities=Facility.objects.filter(facility_type="PUSKESMAS", is_active=True).order_by("name") if not facility else []))


@login_required
@perm_required("puskesmas.view_puskesmasexpiry")
def expiry_detail(request, pk):
    document = get_object_or_404(PuskesmasExpiry.objects.select_related("facility"), pk=pk)
    _facility(request, document)
    return render(request, "puskesmas/expiry_detail.html", dict(document=document,
        current=current_revision(document), revisions=document.revisions.prefetch_related(
            "lines__layer__item", "lines__layer__sumber_dana", "consumption_revisions__consumption").select_related("actor").order_by("-number"),
        can_manage=is_super_admin(request.user) or (request.user.role == "PUSKESMAS" and (
            request.user.has_perm("puskesmas.change_puskesmasexpiry") or has_module_permission(request.user, "puskesmas.change_puskesmasexpiry")))))
