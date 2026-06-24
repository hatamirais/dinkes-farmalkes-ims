import unicodedata

from django import forms
from django.core.exceptions import ValidationError

from apps.core.decimal_validation import validate_finite_decimal
from apps.items.models import Location
from apps.users.models import User

from .models import StockOpname


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


class StockOpnameFilterForm(forms.Form):
    status = forms.ChoiceField(required=False)
    period = forms.ChoiceField(required=False)
    q = forms.CharField(required=False, max_length=100)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [("", "Semua Status"), *StockOpname.Status.choices]
        self.fields["period"].choices = [("", "Semua Periode"), *StockOpname.PeriodType.choices]

    def clean_q(self):
        return _normalize_text_value(
            self.cleaned_data.get("q"),
            field_label="Pencarian",
            max_length=100,
        )


class StockOpnameLocationFilterForm(forms.Form):
    location = forms.ModelChoiceField(
        queryset=Location.objects.none(),
        required=False,
    )

    def __init__(self, *args, allowed_location_ids=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["location"].queryset = Location.objects.filter(
            pk__in=(allowed_location_ids or [])
        ).order_by("code")


class StockOpnameItemInputForm(forms.Form):
    actual_quantity = forms.DecimalField(
        required=False,
        max_digits=12,
        decimal_places=2,
        error_messages={"invalid": "Jumlah aktual harus berupa angka yang valid."},
    )
    notes = forms.CharField(required=False, max_length=255, help_text="Maksimal 255 karakter.")

    def clean_actual_quantity(self):
        value = self.cleaned_data.get("actual_quantity")
        try:
            value = validate_finite_decimal(value, field_label="Jumlah aktual")
        except ValidationError as exc:
            raise forms.ValidationError(
                "Jumlah aktual harus berupa angka yang valid."
            ) from exc
        if value is not None and value < 0:
            raise forms.ValidationError("Jumlah aktual tidak boleh kurang dari 0.")
        return value

    def clean_notes(self):
        return _normalize_text_value(
            self.cleaned_data.get("notes"),
            field_label="Catatan",
            max_length=255,
        )


class StockOpnameForm(forms.ModelForm):
    class Meta:
        model = StockOpname
        fields = [
            "period_type",
            "period_start",
            "period_end",
            "categories",
            "assigned_to",
            "notes",
        ]
        widgets = {
            "period_type": forms.Select(attrs={"class": "form-select"}),
            "period_start": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "period_end": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "categories": forms.CheckboxSelectMultiple(),
            "assigned_to": forms.CheckboxSelectMultiple(),
            "notes": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "maxlength": 1000}
            ),
        }
        labels = {
            "period_type": "Tipe Periode",
            "period_start": "Tanggal Mulai",
            "period_end": "Tanggal Selesai",
            "categories": "Kategori Barang",
            "assigned_to": "Ditugaskan Kepada",
            "notes": "Catatan",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = User.objects.all().order_by(
            "full_name", "username"
        )
        self.fields["categories"].required = True
        self.fields["notes"].help_text = "Maksimal 1000 karakter."

    def clean_period_start(self):
        value = self.cleaned_data.get("period_start")
        if value and not (1000 <= value.year <= 9999):
            raise forms.ValidationError("Tahun tanggal mulai tidak valid.")
        return value

    def clean_period_end(self):
        value = self.cleaned_data.get("period_end")
        if value and not (1000 <= value.year <= 9999):
            raise forms.ValidationError("Tahun tanggal selesai tidak valid.")
        return value

    def clean_notes(self):
        return _normalize_text_value(
            self.cleaned_data.get("notes"),
            field_label="Catatan",
            max_length=1000,
        )

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get("period_start")
        end = cleaned_data.get("period_end")
        if start and end and start > end:
            raise forms.ValidationError(
                "Tanggal mulai tidak boleh lebih besar dari tanggal selesai."
            )
        return cleaned_data
