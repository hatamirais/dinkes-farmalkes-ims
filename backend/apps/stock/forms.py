import unicodedata

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Div, Layout
from django import forms
from django.utils import timezone

from apps.items.models import Facility, Location
from apps.lplpo.models import LPLPO

from .models import StockTransfer


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


class StockTransferForm(forms.ModelForm):
    class Meta:
        model = StockTransfer
        fields = ["transfer_date", "source_location", "destination_location", "notes"]
        widgets = {
            "transfer_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "source_location": forms.Select(attrs={"class": "form-select"}),
            "destination_location": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        active_locations = Location.objects.filter(is_active=True).order_by("code")
        self.fields["source_location"].queryset = active_locations
        self.fields["destination_location"].queryset = active_locations

    def clean(self):
        cleaned = super().clean()
        source = cleaned.get("source_location")
        destination = cleaned.get("destination_location")
        if source and destination and source == destination:
            self.add_error(
                "destination_location",
                "Lokasi tujuan harus berbeda dari lokasi asal.",
            )
        return cleaned


class PuskesmasStockFilterForm(forms.Form):
    year = forms.TypedChoiceField(
        label="Tahun",
        coerce=int,
        choices=[],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    facility = forms.ChoiceField(
        label="Puskesmas",
        required=False,
        choices=[],
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        self.facility_choices = list(
            Facility.objects.filter(
                facility_type=Facility.FacilityType.PUSKESMAS,
                is_active=True,
            )
            .order_by("name")
            .values_list("id", "name")
        )
        self.year_choices = self._build_year_choices()
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.disable_csrf = True
        self.helper.layout = Layout(
            Div("year", css_class="mb-0"),
            Div("facility", css_class="mb-0"),
        )

        self.fields["year"].choices = [
            (str(year), str(year)) for year in self.year_choices
        ]
        self.fields["facility"].choices = [("", "Semua Puskesmas")] + [
            (str(facility_id), name) for facility_id, name in self.facility_choices
        ]

    @classmethod
    def _build_year_choices(cls):
        current_year = timezone.localdate().year
        available_years = set(
            LPLPO.objects.order_by()
            .values_list("tahun", flat=True)
            .distinct()
        )
        available_years.update(range(current_year - 3, current_year + 2))
        return sorted(
            {year for year in available_years if 1000 <= int(year) <= 9999},
            reverse=True,
        )

    @classmethod
    def get_default_initial(cls):
        return {"year": timezone.localdate().year, "facility": ""}

    def clean_year(self):
        year = self.cleaned_data.get("year")
        if year is None or not 1000 <= year <= 9999:
            raise forms.ValidationError("Tahun harus berada pada rentang 1000-9999.")
        if year not in self.year_choices:
            raise forms.ValidationError("Pilihan tahun tidak valid.")
        return year

    def clean_facility(self):
        facility = _normalize_text_value(
            self.cleaned_data.get("facility"),
            field_label="Puskesmas",
            max_length=20,
        )
        if not facility:
            return ""
        if not facility.isdigit():
            raise forms.ValidationError("Pilihan puskesmas tidak valid.")

        allowed_ids = {str(facility_id) for facility_id, _ in self.facility_choices}
        if facility not in allowed_ids:
            raise forms.ValidationError("Pilihan puskesmas tidak valid.")
        return facility
