import calendar

from django import forms
from django.utils import timezone

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
        super().__init__(*args, **kwargs)
        from apps.items.models import Facility
        self.fields["facility"].queryset = Facility.objects.filter(
            facility_type="PUSKESMAS", is_active=True
        )


class LPLPOItemPuskesmasForm(forms.ModelForm):
    """Form for Puskesmas operator to fill their columns per item."""

    class Meta:
        model = LPLPOItem
        fields = [
            "stock_awal",
            "penerimaan",
            "pemakaian",
            "stock_gudang_puskesmas",
            "waktu_kosong",
            "permintaan_jumlah",
            "permintaan_alasan",
        ]
        widgets = {
            "stock_awal": forms.NumberInput(
                attrs={"class": "form-control form-control-sm text-end", "step": "0.01"}
            ),
            "penerimaan": forms.NumberInput(
                attrs={"class": "form-control form-control-sm text-end", "step": "0.01"}
            ),
            "pemakaian": forms.NumberInput(
                attrs={"class": "form-control form-control-sm text-end", "step": "0.01"}
            ),
            "stock_gudang_puskesmas": forms.NumberInput(
                attrs={"class": "form-control form-control-sm text-end", "step": "0.01"}
            ),
            "waktu_kosong": forms.NumberInput(
                attrs={"class": "form-control form-control-sm text-end", "step": "0.01"}
            ),
            "permintaan_jumlah": forms.NumberInput(
                attrs={"class": "form-control form-control-sm text-end", "step": "0.01"}
            ),
            "permintaan_alasan": forms.Textarea(
                attrs={"class": "form-control form-control-sm", "rows": 1}
            ),
        }


class LPLPOItemReviewForm(forms.ModelForm):
    """Form for Instalasi Farmasi to fill pemberian columns."""

    class Meta:
        model = LPLPOItem
        fields = [
            "pemberian_jumlah",
            "pemberian_alasan",
        ]
        widgets = {
            "pemberian_jumlah": forms.NumberInput(
                attrs={"class": "form-control form-control-sm text-end", "step": "0.01"}
            ),
            "pemberian_alasan": forms.Textarea(
                attrs={"class": "form-control form-control-sm", "rows": 1}
            ),
        }
