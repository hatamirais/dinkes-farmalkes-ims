import calendar
from decimal import ROUND_HALF_UP

from django import forms
from django.utils import timezone

from apps.users.models import User

from .models import LPLPOItem


class LPLPOCreateForm(forms.Form):
    """Period selector form for creating a new LPLPO."""

    bulan = forms.ChoiceField(
        choices=[(i, calendar.month_name[i]) for i in range(1, 13)],
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Bulan",
    )
    tahun = forms.IntegerField(
        min_value=2020,
        max_value=2099,
        initial=timezone.now().year,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
        label="Tahun",
    )
    facility = forms.ModelChoiceField(
        queryset=None,  # Populated in __init__
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Fasilitas (Puskesmas)",
        help_text="Pilih puskesmas jika Anda bertindak mewakili puskesmas."
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        label="Catatan",
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        from apps.items.models import Facility

        self.fields["facility"].queryset = Facility.objects.filter(
            facility_type="PUSKESMAS", is_active=True
        )
        if user and getattr(user, "role", None) == User.Role.PUSKESMAS:
            self.fields["facility"].widget = forms.HiddenInput()
            self.fields["facility"].required = False


class LPLPOItemPuskesmasForm(forms.ModelForm):
    """Form for Puskesmas operator to fill their columns per item."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["stock_awal"].required = False
        self.fields["pembelian_puskesmas"].required = False

    def clean_stock_awal(self):
        value = self.cleaned_data.get("stock_awal")
        if value in (None, ""):
            return 0
        return value

    def clean_pembelian_puskesmas(self):
        value = self.cleaned_data.get("pembelian_puskesmas")
        if value in (None, ""):
            return 0
        return value

    class Meta:
        model = LPLPOItem
        fields = [
            "stock_awal",
            "penerimaan",
            "pembelian_puskesmas",
            "pemakaian",
            "stock_gudang_puskesmas",
            "waktu_kosong",
            "permintaan_jumlah",
            "permintaan_alasan",
        ]
        widgets = {
            "stock_awal": forms.NumberInput(attrs={"class": "form-control form-control-sm text-end", "step": "1", "min": "0"}),
            "penerimaan": forms.NumberInput(attrs={"class": "form-control form-control-sm text-end", "step": "1", "min": "0"}),
            "pembelian_puskesmas": forms.NumberInput(attrs={"class": "form-control form-control-sm text-end", "step": "1", "min": "0"}),
            "pemakaian": forms.NumberInput(attrs={"class": "form-control form-control-sm text-end", "step": "1", "min": "0"}),
            "stock_gudang_puskesmas": forms.NumberInput(attrs={"class": "form-control form-control-sm text-end", "step": "1", "min": "0"}),
            "waktu_kosong": forms.NumberInput(attrs={"class": "form-control form-control-sm text-end", "step": "1", "min": "0"}),
            "permintaan_jumlah": forms.NumberInput(attrs={"class": "form-control form-control-sm text-end", "step": "1", "min": "0"}),
            "permintaan_alasan": forms.Textarea(attrs={"class": "form-control form-control-sm", "rows": 1}),
        }


class LPLPOItemReviewForm(forms.ModelForm):
    """Form for Instalasi Farmasi to fill pemberian columns."""

    pemberian_jumlah = forms.IntegerField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "form-control form-control-sm text-end", "step": "1", "min": "0"}
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.pemberian_jumlah is None:
            suggested_value = int(
                self.instance.jumlah_kebutuhan.to_integral_value(
                    rounding=ROUND_HALF_UP
                )
            )
            self.initial["pemberian_jumlah"] = suggested_value
            self.fields["pemberian_jumlah"].initial = suggested_value

    class Meta:
        model = LPLPOItem
        fields = [
            "pemberian_jumlah",
            "pemberian_alasan",
        ]
        widgets = {
            "pemberian_alasan": forms.Textarea(
                attrs={"class": "form-control form-control-sm", "rows": 1}
            ),
        }


class RejectLPLPOForm(forms.Form):
    """Form for Instalasi Farmasi to provide a rejection reason."""

    rejection_reason = forms.CharField(
        max_length=1000,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        label="Alasan Penolakan",
        error_messages={"required": "Alasan penolakan wajib diisi."},
    )
