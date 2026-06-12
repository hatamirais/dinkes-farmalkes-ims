import unicodedata

from django import forms
from django.forms import inlineformset_factory
from django.utils import timezone

from apps.core.decimal_validation import validate_finite_decimal
from apps.items.models import Facility, Item
from apps.users.models import User

from .models import (
    PuskesmasRequest,
    PuskesmasRequestItem,
    PuskesmasSBBK,
    PuskesmasSBBKItem,
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


class PuskesmasSBBKForm(forms.ModelForm):
    class Meta:
        model = PuskesmasSBBK
        fields = ["document_number", "facility", "received_date", "notes"]
        widgets = {
            "document_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Kosongkan untuk auto-generate",
                }
            ),
            "facility": forms.Select(attrs={"class": "form-select"}),
            "received_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.fields["document_number"].required = False
        self.fields["notes"].required = False
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


class PuskesmasSBBKItemForm(forms.ModelForm):
    class Meta:
        model = PuskesmasSBBKItem
        fields = ["item", "quantity", "unit_price", "notes"]
        widgets = {
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
            "notes": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "placeholder": "Keterangan (opsional)",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["notes"].required = False
        self.fields["item"].queryset = (
            Item.objects.select_related("satuan", "kategori", "program")
            .filter(is_active=True)
            .order_by("-is_program_item", "kode_barang")
        )
        self.fields["item"].label_from_instance = lambda obj: obj.picker_label

    def clean_quantity(self):
        quantity = self.cleaned_data.get("quantity")
        quantity = validate_finite_decimal(quantity, field_label="Jumlah")
        if quantity is not None and quantity <= 0:
            raise forms.ValidationError("Jumlah harus lebih dari 0.")
        if quantity is not None and quantity != quantity.to_integral_value():
            raise forms.ValidationError(
                "Jumlah SBBK harus berupa bilangan bulat agar sinkron dengan LPLPO."
            )
        return quantity

    def clean_unit_price(self):
        unit_price = self.cleaned_data.get("unit_price")
        unit_price = validate_finite_decimal(unit_price, field_label="Harga satuan")
        if unit_price is None or unit_price < 0:
            raise forms.ValidationError("Harga satuan tidak boleh kurang dari 0.")
        return unit_price

    def clean_notes(self):
        return _normalize_text_value(
            self.cleaned_data.get("notes"),
            field_label="Keterangan",
            max_length=255,
        )


PuskesmasSBBKItemFormSet = inlineformset_factory(
    PuskesmasSBBK,
    PuskesmasSBBKItem,
    form=PuskesmasSBBKItemForm,
    extra=3,
    can_delete=True,
    min_num=1,
    validate_min=True,
)


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

