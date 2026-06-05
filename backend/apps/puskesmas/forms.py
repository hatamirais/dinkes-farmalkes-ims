from django import forms
from django.forms import inlineformset_factory
from django.utils import timezone

from apps.core.decimal_validation import validate_finite_decimal
from apps.distribution.models import Distribution
from apps.items.models import Facility, Item
from apps.users.models import User

from .models import PuskesmasRequest, PuskesmasRequestItem


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
    distribution_type = forms.ChoiceField(
        label="Tipe Distribusi",
        required=False,
        choices=[
            ("", "Semua Tipe"),
            (Distribution.DistributionType.LPLPO, "LPLPO"),
            (Distribution.DistributionType.SPECIAL_REQUEST, "Permintaan Khusus"),
            (Distribution.DistributionType.ALLOCATION, "Alokasi"),
        ],
        widget=forms.Select(attrs={"class": "form-select"}),
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
            "distribution_type": "",
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
    """Filter form for Laporan Persediaan Puskesmas.

    Filters by month/year to align with the monthly nature of LPLPO data.
    Stock is calculated dynamically from the latest LPLPO plus any newer
    distributions received after that LPLPO period.
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
            ("", "Semua Bulan (Stok Kumulatif)"),
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
        return {"year": now.year, "month": str(now.month)}

