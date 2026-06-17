import unicodedata

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Div, Layout
from django import forms
from django.db.models import Q
from django.forms import inlineformset_factory
from django.utils import timezone

from apps.core.decimal_validation import validate_finite_decimal
from apps.distribution.models import Distribution, DistributionItem
from apps.items.models import Facility, Item
from apps.users.models import User

from .models import (
    PuskesmasConsumption,
    PuskesmasConsumptionEntry,
    PuskesmasReceiptConfirmation,
    PuskesmasReceiptConfirmationItem,
    PuskesmasRequest,
    PuskesmasRequestItem,
    PuskesmasSubunit,
)


def _normalize_text_value(value, *, field_label, max_length=None):
    if value in (None, ""):
        return ""

    normalized = unicodedata.normalize("NFC", str(value)).strip()
    if "\x00" in normalized:
        raise forms.ValidationError(f"{field_label} tidak boleh mengandung null byte.")
    if max_length is not None and len(normalized) > max_length:
        raise forms.ValidationError(
            f"{field_label} tidak boleh lebih dari {max_length} karakter."
        )
    return normalized


class PuskesmasRequestForm(forms.ModelForm):
    class Meta:
        model = PuskesmasRequest
        fields = ["document_number", "facility", "request_date", "notes"]
        widgets = {
            "document_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Kosongkan untuk auto-generate",
                }
            ),
            "facility": forms.Select(attrs={"class": "form-select"}),
            "request_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.fields["document_number"].required = False
        self.fields["notes"].required = False
        # Only show active puskesmas facilities
        self.fields["facility"].queryset = Facility.objects.filter(
            facility_type=Facility.FacilityType.PUSKESMAS, is_active=True
        ).order_by("name")
        if self.user and getattr(self.user, "role", None) == User.Role.PUSKESMAS:
            self.fields["facility"].widget = forms.HiddenInput()
            self.fields["facility"].required = False
            if self.user.facility_id:
                self.fields["facility"].initial = self.user.facility_id

    def clean_facility(self):
        if self.user and getattr(self.user, "role", None) == User.Role.PUSKESMAS:
            if not self.user.facility_id:
                raise forms.ValidationError(
                    "Akun operator belum terhubung ke fasilitas puskesmas."
                )
            return self.user.facility
        return self.cleaned_data.get("facility")

    def clean_document_number(self):
        return _normalize_text_value(
            self.cleaned_data.get("document_number"),
            field_label="Nomor dokumen",
            max_length=100,
        )

    def clean_notes(self):
        return _normalize_text_value(
            self.cleaned_data.get("notes"),
            field_label="Catatan",
            max_length=1000,
        )


class PuskesmasRequestItemForm(forms.ModelForm):
    class Meta:
        model = PuskesmasRequestItem
        fields = ["item", "quantity_requested", "notes"]
        widgets = {
            "item": forms.Select(
                attrs={
                    "class": "form-select form-select-sm js-typeahead-select js-item-select"
                }
            ),
            "quantity_requested": forms.NumberInput(
                attrs={"class": "form-control form-control-sm", "min": "1", "step": "1"}
            ),
            "notes": forms.TextInput(
                attrs={"class": "form-control form-control-sm", "placeholder": "Keterangan (opsional)"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["notes"].required = False
        # Prefer program items first in the dropdown
        self.fields["item"].queryset = (
            Item.objects.select_related("satuan", "kategori", "program")
            .filter(is_active=True)
            .order_by("-is_program_item", "kode_barang")
        )
        self.fields["item"].label_from_instance = lambda obj: obj.picker_label

    def clean_quantity_requested(self):
        qty = self.cleaned_data.get("quantity_requested")
        qty = validate_finite_decimal(qty, field_label="Jumlah")
        if qty is not None and qty <= 0:
            raise forms.ValidationError("Jumlah harus lebih dari 0.")
        return qty

    def clean_notes(self):
        return _normalize_text_value(
            self.cleaned_data.get("notes"),
            field_label="Keterangan",
            max_length=255,
        )


class ApprovalItemForm(forms.ModelForm):
    """Inline form for approving/adjusting quantity per item during the approval step."""

    class Meta:
        model = PuskesmasRequestItem
        fields = ["quantity_approved"]
        widgets = {
            "quantity_approved": forms.NumberInput(
                attrs={"class": "form-control form-control-sm", "min": "0", "step": "1"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["quantity_approved"].required = False


PuskesmasRequestItemFormSet = inlineformset_factory(
    PuskesmasRequest,
    PuskesmasRequestItem,
    form=PuskesmasRequestItemForm,
    extra=3,
    can_delete=True,
    min_num=1,
    validate_min=True,
)


class PuskesmasReceiptConfirmationForm(forms.ModelForm):
    class Meta:
        model = PuskesmasReceiptConfirmation
        fields = ["document_number", "facility", "distribution", "received_date", "notes"]
        widgets = {
            "document_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Kosongkan untuk auto-generate",
                }
            ),
            "facility": forms.Select(attrs={"class": "form-select"}),
            "distribution": forms.Select(
                attrs={"class": "form-select js-typeahead-select"}
            ),
            "received_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        self.lock_distribution = kwargs.pop("lock_distribution", False)
        super().__init__(*args, **kwargs)
        self.is_legacy_unlinked_edit = bool(
            self.instance.pk and self.instance.distribution_id is None
        )
        self.fields["document_number"].required = False
        self.fields["notes"].required = False
        self.fields["distribution"].required = not self.is_legacy_unlinked_edit
        self.fields["facility"].queryset = Facility.objects.filter(
            facility_type=Facility.FacilityType.PUSKESMAS, is_active=True
        ).order_by("name")
        distribution_qs = Distribution.objects.select_related("facility").filter(
            facility__facility_type=Facility.FacilityType.PUSKESMAS,
            facility__is_active=True,
            status=Distribution.Status.DISTRIBUTED,
        )
        if self.instance.pk and self.instance.distribution_id:
            distribution_qs = distribution_qs.filter(
                Q(receipt_confirmation__isnull=True)
                | Q(pk=self.instance.distribution_id)
            )
        else:
            distribution_qs = distribution_qs.filter(receipt_confirmation__isnull=True)

        if self.user and getattr(self.user, "role", None) == User.Role.PUSKESMAS:
            self.fields["facility"].widget = forms.HiddenInput()
            self.fields["facility"].required = False
            if self.user.facility_id:
                self.fields["facility"].initial = self.user.facility_id
                distribution_qs = distribution_qs.filter(facility_id=self.user.facility_id)

        self.fields["distribution"].queryset = distribution_qs.order_by(
            "-distributed_date", "-request_date", "-created_at"
        )
        self.fields["distribution"].label_from_instance = lambda obj: (
            f"{obj.document_number} - {obj.facility.name} - "
            f"{(obj.distributed_date or obj.request_date).strftime('%d/%m/%Y')}"
        )

        if self.is_legacy_unlinked_edit:
            self.fields["distribution"].widget = forms.HiddenInput()

        if self.lock_distribution and self.instance.pk:
            self.fields["distribution"].widget = forms.HiddenInput()
            self.fields["facility"].widget = forms.HiddenInput()
            self.fields["distribution"].initial = self.instance.distribution_id
            self.fields["facility"].initial = self.instance.facility_id

    def clean_facility(self):
        distribution = self.cleaned_data.get("distribution")
        if self.user and getattr(self.user, "role", None) == User.Role.PUSKESMAS:
            if not self.user.facility_id:
                raise forms.ValidationError(
                    "Akun operator belum terhubung ke fasilitas puskesmas."
                )
            if distribution and distribution.facility_id != self.user.facility_id:
                raise forms.ValidationError(
                    "Distribusi harus berasal dari fasilitas akun Anda."
                )
            return self.user.facility
        facility = self.cleaned_data.get("facility")
        if distribution and facility and distribution.facility_id != facility.pk:
            raise forms.ValidationError(
                "Puskesmas harus sama dengan tujuan distribusi yang dipilih."
            )
        return facility or getattr(distribution, "facility", None)

    def clean_distribution(self):
        distribution = self.cleaned_data.get("distribution")
        if self.is_legacy_unlinked_edit:
            if distribution is not None:
                raise forms.ValidationError(
                    "Dokumen lama tidak boleh ditautkan ulang ke distribusi sumber baru."
                )
            return None
        if distribution is None:
            raise forms.ValidationError("Distribusi sumber wajib dipilih.")
        if distribution.status != Distribution.Status.DISTRIBUTED:
            raise forms.ValidationError(
                "Hanya distribusi berstatus terdistribusi yang dapat dikonfirmasi."
            )
        try:
            existing = distribution.receipt_confirmation
        except PuskesmasReceiptConfirmation.DoesNotExist:
            existing = None
        if existing and existing.pk != self.instance.pk:
            raise forms.ValidationError(
                "Distribusi ini sudah memiliki konfirmasi penerimaan."
            )
        return distribution

    def clean_document_number(self):
        return _normalize_text_value(
            self.cleaned_data.get("document_number"),
            field_label="Nomor dokumen",
            max_length=100,
        )

    def clean_received_date(self):
        value = self.cleaned_data.get("received_date")
        if value and not (1000 <= value.year <= 9999):
            raise forms.ValidationError("Tahun tanggal tidak valid.")
        return value

    def clean_notes(self):
        return _normalize_text_value(
            self.cleaned_data.get("notes"),
            field_label="Catatan",
            max_length=1000,
        )


class PuskesmasReceiptConfirmationItemForm(forms.ModelForm):
    class Meta:
        model = PuskesmasReceiptConfirmationItem
        fields = [
            "distribution_item",
            "item",
            "quantity",
            "unit_price",
            "batch_lot",
            "expiry_date",
            "notes",
        ]
        widgets = {
            "distribution_item": forms.Select(
                attrs={"class": "form-select form-select-sm js-typeahead-select"}
            ),
            "item": forms.Select(
                attrs={
                    "class": "form-select form-select-sm js-typeahead-select js-item-select"
                }
            ),
            "quantity": forms.NumberInput(
                attrs={"class": "form-control form-control-sm", "min": "1", "step": "1"}
            ),
            "unit_price": forms.NumberInput(
                attrs={"class": "form-control form-control-sm", "min": "0", "step": "0.01"}
            ),
            "batch_lot": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "placeholder": "Batch/Lot",
                }
            ),
            "expiry_date": forms.DateInput(
                attrs={"class": "form-control form-control-sm", "type": "date"}
            ),
            "notes": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "placeholder": "Keterangan penyesuaian (opsional)",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        self.distribution = kwargs.pop("distribution", None)
        super().__init__(*args, **kwargs)
        self.fields["notes"].required = False
        self.fields["batch_lot"].required = False
        self.fields["expiry_date"].required = False
        self.fields["item"].queryset = (
            Item.objects.select_related("satuan", "kategori", "program")
            .filter(is_active=True)
            .order_by("-is_program_item", "kode_barang")
        )
        self.fields["item"].label_from_instance = lambda obj: obj.picker_label
        if self.distribution is None and self.instance.pk and self.instance.sbbk_id:
            self.distribution = self.instance.sbbk.distribution
        distribution_item_qs = DistributionItem.objects.none()
        if self.distribution is not None:
            distribution_item_qs = self.distribution.items.select_related("item").order_by(
                "item__kategori__sort_order", "item__nama_barang", "id"
            )
        elif self.instance.pk and self.instance.distribution_item_id:
            distribution_item_qs = DistributionItem.objects.filter(
                pk=self.instance.distribution_item_id
            ).select_related("item")
        self.fields["distribution_item"].queryset = distribution_item_qs
        self.fields["distribution_item"].label_from_instance = lambda obj: (
            f"{obj.item.nama_barang} | qty "
            f"{obj.quantity_approved if obj.quantity_approved is not None else obj.quantity_requested} "
            f"| batch {obj.issued_batch_lot or '-'}"
        )

    def clean_quantity(self):
        quantity = self.cleaned_data.get("quantity")
        quantity = validate_finite_decimal(quantity, field_label="Jumlah")
        if quantity is not None and quantity <= 0:
            raise forms.ValidationError("Jumlah harus lebih dari 0.")
        if quantity is not None and quantity != quantity.to_integral_value():
            raise forms.ValidationError(
                "Jumlah penerimaan harus berupa bilangan bulat agar sinkron dengan LPLPO."
            )
        return quantity

    def clean_distribution_item(self):
        distribution_item = self.cleaned_data.get("distribution_item")
        if distribution_item is None and self.distribution is None:
            return None
        if distribution_item is None:
            raise forms.ValidationError("Baris distribusi sumber wajib dipilih.")
        if self.distribution and distribution_item.distribution_id != self.distribution.pk:
            raise forms.ValidationError(
                "Baris distribusi harus berasal dari distribusi yang dipilih."
            )
        return distribution_item

    def clean_item(self):
        distribution_item = self.cleaned_data.get("distribution_item")
        if distribution_item is not None:
            return distribution_item.item
        return self.cleaned_data.get("item")

    def clean_unit_price(self):
        unit_price = self.cleaned_data.get("unit_price")
        unit_price = validate_finite_decimal(unit_price, field_label="Harga satuan")
        if unit_price is None or unit_price < 0:
            raise forms.ValidationError("Harga satuan tidak boleh kurang dari 0.")
        return unit_price

    def clean_batch_lot(self):
        return _normalize_text_value(
            self.cleaned_data.get("batch_lot"),
            field_label="Batch/Lot",
            max_length=100,
        )

    def clean_expiry_date(self):
        value = self.cleaned_data.get("expiry_date")
        if value and not (1000 <= value.year <= 9999):
            raise forms.ValidationError("Tahun tanggal kedaluwarsa tidak valid.")
        return value

    def clean_notes(self):
        return _normalize_text_value(
            self.cleaned_data.get("notes"),
            field_label="Keterangan",
            max_length=255,
        )


PuskesmasReceiptConfirmationItemFormSet = inlineformset_factory(
    PuskesmasReceiptConfirmation,
    PuskesmasReceiptConfirmationItem,
    form=PuskesmasReceiptConfirmationItemForm,
    extra=3,
    can_delete=True,
    min_num=1,
    validate_min=True,
)


PuskesmasSBBKForm = PuskesmasReceiptConfirmationForm
PuskesmasSBBKItemForm = PuskesmasReceiptConfirmationItemForm
PuskesmasSBBKItemFormSet = PuskesmasReceiptConfirmationItemFormSet


class PuskesmasSubunitForm(forms.ModelForm):
    class Meta:
        model = PuskesmasSubunit
        fields = ["facility", "name", "subunit_type", "is_active"]
        widgets = {
            "facility": forms.Select(attrs={"class": "form-select"}),
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Contoh: Poli Umum"}
            ),
            "subunit_type": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.disable_csrf = True
        self.helper.layout = Layout(
            Div("facility", css_class="mb-3"),
            Div("name", css_class="mb-3"),
            Div("subunit_type", css_class="mb-3"),
            Div("is_active", css_class="form-check mb-0"),
        )

        self.fields["facility"].label = "Puskesmas"
        self.fields["facility"].widget.attrs["title"] = (
            "Pilih puskesmas yang memiliki poli atau pustu ini."
        )
        self.fields["name"].label = "Nama Poli/Pustu"
        self.fields["name"].widget.attrs["title"] = (
            "Isi nama poli atau pustu sesuai penamaan yang digunakan di puskesmas."
        )
        self.fields["subunit_type"].label = "Jenis Poli/Pustu"
        self.fields["subunit_type"].widget.attrs["title"] = (
            "Pilih Poli untuk layanan di dalam puskesmas atau Pustu untuk layanan di luar gedung utama."
        )
        self.fields["is_active"].label = "Aktif"
        self.fields["is_active"].widget.attrs["title"] = (
            "Matikan jika poli atau pustu ini tidak lagi dipakai sebagai kolom input."
        )

        self.fields["facility"].queryset = Facility.objects.filter(
            facility_type=Facility.FacilityType.PUSKESMAS,
            is_active=True,
        ).order_by("name")

        if self.user and getattr(self.user, "role", None) == User.Role.PUSKESMAS:
            self.fields["facility"].widget = forms.HiddenInput()
            self.fields["facility"].required = False
            if self.user.facility_id:
                self.fields["facility"].initial = self.user.facility_id

    def clean_facility(self):
        if self.user and getattr(self.user, "role", None) == User.Role.PUSKESMAS:
            if not self.user.facility_id:
                raise forms.ValidationError(
                    "Akun operator belum terhubung ke fasilitas puskesmas."
                )
            return self.user.facility
        facility = self.cleaned_data.get("facility")
        if (
            facility
            and self.instance
            and self.instance.pk
            and self.instance.consumption_entries.exists()
            and facility.pk != self.instance.facility_id
        ):
            raise forms.ValidationError(
                "Fasilitas tidak dapat diubah karena subunit sudah dipakai pada data pemakaian."
            )
        return facility

    def clean_name(self):
        return _normalize_text_value(
            self.cleaned_data.get("name"),
            field_label="Nama Poli/Pustu",
            max_length=120,
        )


class PuskesmasConsumptionMatrixForm(forms.ModelForm):
    """Monthly consumption form with dynamic per-subunit quantity cells."""

    class Meta:
        model = PuskesmasConsumption
        fields = ["facility", "bulan", "tahun", "notes"]
        widgets = {
            "facility": forms.Select(attrs={"class": "form-select"}),
            "bulan": forms.NumberInput(
                attrs={"class": "form-control", "min": "1", "max": "12", "step": "1"}
            ),
            "tahun": forms.NumberInput(
                attrs={"class": "form-control", "min": "1000", "max": "9999", "step": "1"}
            ),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(
        self,
        *args,
        user=None,
        subunits=None,
        items=None,
        existing_entries=None,
        lock_period=False,
        **kwargs,
    ):
        self.user = user
        self.subunits = list(subunits or [])
        self.items = list(items or [])
        self.existing_entries = existing_entries or {}
        self.lock_period = lock_period
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.disable_csrf = True
        self.helper.layout = Layout(
            Div("facility", css_class="mb-3"),
            Div("bulan", css_class="mb-3"),
            Div("tahun", css_class="mb-3"),
            Div("notes", css_class="mb-0"),
        )

        self.fields["facility"].label = "Puskesmas"
        self.fields["facility"].widget.attrs["title"] = (
            "Pilih puskesmas yang akan mengisi pemakaian rinci."
        )
        self.fields["bulan"].label = "Bulan"
        self.fields["bulan"].widget.attrs["title"] = (
            "Masukkan bulan periode pemakaian yang sedang dilaporkan."
        )
        self.fields["tahun"].label = "Tahun"
        self.fields["tahun"].widget.attrs["title"] = (
            "Masukkan tahun periode pemakaian yang sedang dilaporkan."
        )
        self.fields["notes"].label = "Catatan"
        self.fields["notes"].widget.attrs["title"] = (
            "Isi catatan tambahan bila ada kondisi khusus pada periode pemakaian ini."
        )

        self.fields["facility"].queryset = Facility.objects.filter(
            facility_type=Facility.FacilityType.PUSKESMAS,
            is_active=True,
        ).order_by("name")

        if self.user and getattr(self.user, "role", None) == User.Role.PUSKESMAS:
            self.fields["facility"].widget = forms.HiddenInput()
            self.fields["facility"].required = False
            if self.user.facility_id:
                self.fields["facility"].initial = self.user.facility_id

        if self.instance and self.instance.pk and self.lock_period:
            self.fields["facility"].widget = forms.HiddenInput()
            self.fields["bulan"].widget = forms.HiddenInput()
            self.fields["tahun"].widget = forms.HiddenInput()
            self.fields["facility"].initial = self.instance.facility_id
            self.fields["bulan"].initial = self.instance.bulan
            self.fields["tahun"].initial = self.instance.tahun

        for item in self.items:
            for subunit in self.subunits:
                field_name = self.get_matrix_field_name(item.pk, subunit.pk)
                self.fields[field_name] = forms.IntegerField(
                    required=False,
                    min_value=0,
                    initial=self.existing_entries.get((item.pk, subunit.pk), 0),
                    widget=forms.NumberInput(
                        attrs={
                            "class": "form-control form-control-sm text-end",
                            "min": "0",
                            "step": "1",
                            "placeholder": "0",
                            "title": (
                                f"Isi jumlah pemakaian {item.nama_barang} yang digunakan di "
                                f"{subunit.name} pada periode ini."
                            ),
                            "aria-label": (
                                f"Pemakaian {item.nama_barang} untuk {subunit.name}"
                            ),
                        }
                    ),
                    label=f"{item.picker_label} / {subunit.name}",
                )

    @staticmethod
    def get_matrix_field_name(item_id, subunit_id):
        return f"qty_{item_id}_{subunit_id}"

    def clean_facility(self):
        if self.user and getattr(self.user, "role", None) == User.Role.PUSKESMAS:
            if not self.user.facility_id:
                raise forms.ValidationError(
                    "Akun operator belum terhubung ke fasilitas puskesmas."
                )
            return self.user.facility
        return self.cleaned_data.get("facility")

    def clean_bulan(self):
        value = self.cleaned_data.get("bulan")
        if value and not 1 <= value <= 12:
            raise forms.ValidationError("Bulan harus berada pada rentang 1-12.")
        return value

    def clean_tahun(self):
        value = self.cleaned_data.get("tahun")
        if value and not 1000 <= value <= 9999:
            raise forms.ValidationError("Tahun harus berada pada rentang 1000-9999.")
        return value

    def clean_notes(self):
        return _normalize_text_value(
            self.cleaned_data.get("notes"),
            field_label="Catatan",
            max_length=1000,
        )

    def clean(self):
        cleaned_data = super().clean()
        matrix_values = {}

        for item in self.items:
            for subunit in self.subunits:
                field_name = self.get_matrix_field_name(item.pk, subunit.pk)
                raw_value = self.data.get(self.add_prefix(field_name), "")
                decimal_value = validate_finite_decimal(
                    raw_value,
                    field_label=f"Jumlah {item.picker_label} / {subunit.name}",
                )
                if decimal_value in (None, ""):
                    quantity = 0
                else:
                    try:
                        quantity = int(decimal_value)
                    except (TypeError, ValueError):
                        self.add_error(field_name, "Jumlah pemakaian harus berupa angka.")
                        continue
                    if decimal_value != int(decimal_value):
                        self.add_error(
                            field_name,
                            "Jumlah pemakaian harus berupa bilangan bulat.",
                        )
                        continue
                    if quantity < 0:
                        self.add_error(
                            field_name,
                            "Jumlah pemakaian tidak boleh negatif.",
                        )
                        continue
                matrix_values[(item.pk, subunit.pk)] = quantity

        cleaned_data["matrix_values"] = matrix_values
        return cleaned_data

    def build_entries(self, consumption):
        entries = []
        for item in self.items:
            for subunit in self.subunits:
                quantity = self.cleaned_data["matrix_values"].get((item.pk, subunit.pk), 0)
                if quantity <= 0:
                    continue
                entries.append(
                    PuskesmasConsumptionEntry(
                        consumption=consumption,
                        item=item,
                        subunit=subunit,
                        quantity=quantity,
                    )
                )
        return entries


# ──────────────────────── Report Filter Forms ────────────────────────


class PuskesmasReceivingFilterForm(forms.Form):
    """Filter form for Riwayat Penerimaan Puskesmas report."""

    start_date = forms.DateField(
        label="Tanggal Mulai",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    end_date = forms.DateField(
        label="Tanggal Akhir",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get("start_date")
        end = cleaned_data.get("end_date")
        if start and end and start > end:
            raise forms.ValidationError(
                "Tanggal mulai tidak boleh lebih dari tanggal akhir."
            )
        return cleaned_data

    def clean_start_date(self):
        val = self.cleaned_data.get("start_date")
        if val and not (1000 <= val.year <= 9999):
            raise forms.ValidationError("Tahun tanggal tidak valid.")
        return val

    def clean_end_date(self):
        val = self.cleaned_data.get("end_date")
        if val and not (1000 <= val.year <= 9999):
            raise forms.ValidationError("Tahun tanggal tidak valid.")
        return val

    @classmethod
    def get_default_initial(cls):
        now = timezone.now().date()
        return {
            "start_date": now.replace(day=1),
            "end_date": now,
        }


class PuskesmasPemakaianFilterForm(forms.Form):
    """Filter form for Riwayat Pemakaian Puskesmas report (LPLPO-based).

    Only shows consumption data for DISTRIBUTED and CLOSED LPLPOs (finalized documents).
    """

    year = forms.IntegerField(
        label="Tahun",
        min_value=2000,
        max_value=2099,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "placeholder": "Contoh: 2026"}
        ),
    )
    month = forms.ChoiceField(
        label="Bulan",
        required=False,
        choices=[
            ("", "Semua Bulan"),
            ("1", "Januari"),
            ("2", "Februari"),
            ("3", "Maret"),
            ("4", "April"),
            ("5", "Mei"),
            ("6", "Juni"),
            ("7", "Juli"),
            ("8", "Agustus"),
            ("9", "September"),
            ("10", "Oktober"),
            ("11", "November"),
            ("12", "Desember"),
        ],
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    @classmethod
    def get_default_initial(cls):
        now = timezone.now().date()
        return {"year": now.year, "month": ""}


class PuskesmasPersediaanFilterForm(forms.Form):
    """Filter form for persediaan reports using yearly/quarterly/semester periods."""

    PERIOD_YEARLY = "yearly"
    PERIOD_Q1 = "q1"
    PERIOD_Q2 = "q2"
    PERIOD_Q3 = "q3"
    PERIOD_Q4 = "q4"
    PERIOD_S1 = "s1"
    PERIOD_S2 = "s2"

    PERIOD_CHOICES = [
        (PERIOD_YEARLY, "Tahunan"),
        (PERIOD_Q1, "Triwulan I (Januari - Maret)"),
        (PERIOD_Q2, "Triwulan II (April - Juni)"),
        (PERIOD_Q3, "Triwulan III (Juli - September)"),
        (PERIOD_Q4, "Triwulan IV (Oktober - Desember)"),
        (PERIOD_S1, "Semester I (Januari - Juni)"),
        (PERIOD_S2, "Semester II (Juli - Desember)"),
    ]

    PERIOD_BOUNDS = {
        PERIOD_YEARLY: (1, 12, "Tahunan"),
        PERIOD_Q1: (1, 3, "Triwulan I"),
        PERIOD_Q2: (4, 6, "Triwulan II"),
        PERIOD_Q3: (7, 9, "Triwulan III"),
        PERIOD_Q4: (10, 12, "Triwulan IV"),
        PERIOD_S1: (1, 6, "Semester I"),
        PERIOD_S2: (7, 12, "Semester II"),
    }

    year = forms.IntegerField(
        label="Tahun",
        min_value=2000,
        max_value=2099,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "placeholder": "Contoh: 2026"}
        ),
    )
    period = forms.ChoiceField(
        label="Periode",
        required=True,
        choices=PERIOD_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    @classmethod
    def get_period_bounds(cls, period_code):
        return cls.PERIOD_BOUNDS[period_code]

    @classmethod
    def get_default_initial(cls):
        now = timezone.now().date()
        return {"year": now.year, "period": cls.PERIOD_YEARLY}

