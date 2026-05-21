import calendar
import unicodedata
from decimal import ROUND_HALF_UP

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Div, Layout
from django import forms
from django.core.exceptions import ValidationError

from apps.users.models import User

from .models import (
    LPLPOItem,
    format_lplpo_period_label,
    get_active_lplpo_year,
    get_next_required_lplpo_period,
)


def _normalize_text_value(value, *, field_label, max_length=None):
    if value in (None, ""):
        return ""

    normalized = unicodedata.normalize("NFC", value).strip()
    if "\x00" in normalized:
        raise ValidationError(f"{field_label} tidak boleh mengandung null byte.")
    if max_length is not None and len(normalized) > max_length:
        raise ValidationError(
            f"{field_label} tidak boleh lebih dari {max_length} karakter."
        )
    return normalized


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
        initial=get_active_lplpo_year(),
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
        self.user = user
        super().__init__(*args, **kwargs)
        from apps.items.models import Facility

        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.disable_csrf = True
        self.helper.layout = Layout(
            Div("bulan", css_class="mb-3"),
            Div("tahun", css_class="mb-3"),
            Div("facility", css_class="mb-3"),
            Div("notes", css_class="mb-0"),
        )

        self.fields["facility"].queryset = Facility.objects.filter(
            facility_type="PUSKESMAS", is_active=True
        ).order_by("name")
        self.active_year = get_active_lplpo_year()
        self.next_required_month = None
        self.selected_facility = self._resolve_selected_facility()

        self.fields["tahun"].initial = self.active_year
        self.fields["tahun"].min_value = self.active_year
        self.fields["tahun"].max_value = self.active_year
        self.fields["tahun"].error_messages["min_value"] = (
            f"LPLPO baru hanya dapat dibuat untuk tahun server aktif {self.active_year}."
        )
        self.fields["tahun"].error_messages["max_value"] = (
            f"LPLPO baru hanya dapat dibuat untuk tahun server aktif {self.active_year}."
        )
        self.fields["tahun"].help_text = (
            f"LPLPO baru hanya dapat dibuat untuk tahun server aktif {self.active_year}."
        )
        if user and getattr(user, "role", None) == User.Role.PUSKESMAS:
            self.fields["facility"].widget = forms.HiddenInput()
            self.fields["facility"].required = False
        else:
            self.fields["facility"].help_text = (
                "Pilih puskesmas untuk melihat periode berikutnya yang wajib dibuat."
            )

        if self.selected_facility:
            self._apply_period_restrictions(self.selected_facility)

    @property
    def can_create(self):
        if self.selected_facility is None:
            return True
        return self.next_required_month is not None

    def _resolve_selected_facility(self):
        if getattr(self.user, "role", None) == User.Role.PUSKESMAS:
            return getattr(self.user, "facility", None)

        facility_field = self.fields["facility"]
        if self.is_bound:
            facility_id = self.data.get(self.add_prefix("facility")) or self.data.get(
                "facility"
            )
            if facility_id:
                try:
                    return facility_field.queryset.get(pk=facility_id)
                except (ValueError, TypeError, facility_field.queryset.model.DoesNotExist):
                    return None

        initial_facility = self.initial.get("facility")
        if initial_facility is not None:
            if hasattr(initial_facility, "pk"):
                return initial_facility
            try:
                return facility_field.queryset.get(pk=initial_facility)
            except facility_field.queryset.model.DoesNotExist:
                return None
        return None

    def _apply_period_restrictions(self, facility):
        active_year, next_month = get_next_required_lplpo_period(facility)
        self.active_year = active_year
        self.next_required_month = next_month
        self.selected_facility = facility

        self.fields["tahun"].initial = active_year
        self.fields["tahun"].min_value = active_year
        self.fields["tahun"].max_value = active_year
        self.fields["tahun"].error_messages["min_value"] = (
            f"LPLPO baru hanya dapat dibuat untuk tahun server aktif {active_year}."
        )
        self.fields["tahun"].error_messages["max_value"] = (
            f"LPLPO baru hanya dapat dibuat untuk tahun server aktif {active_year}."
        )
        self.fields["tahun"].help_text = (
            f"Tahun LPLPO terkunci ke tahun server aktif {active_year}."
        )

        if next_month is None:
            self.fields["bulan"].choices = []
            self.fields["bulan"].required = False
            self.fields["bulan"].help_text = (
                f"Semua LPLPO tahun {active_year} untuk {facility.name} sudah dibuat."
            )
            self.fields["bulan"].widget.attrs["disabled"] = "disabled"
            self.fields["tahun"].widget.attrs["readonly"] = "readonly"
            return

        self.fields["bulan"].choices = [
            (str(next_month), calendar.month_name[next_month]),
        ]
        self.fields["bulan"].error_messages["invalid_choice"] = (
            "Periode berikutnya yang wajib dibuat adalah "
            f"{format_lplpo_period_label(next_month, active_year)}."
        )
        self.fields["bulan"].help_text = (
            "Periode berikutnya yang wajib dibuat: "
            f"{format_lplpo_period_label(next_month, active_year)}."
        )
        self.fields["tahun"].widget.attrs["readonly"] = "readonly"

    def clean_notes(self):
        return _normalize_text_value(
            self.cleaned_data.get("notes"),
            field_label="Catatan",
            max_length=1000,
        )

    def clean(self):
        cleaned_data = super().clean()
        user_role = getattr(self.user, "role", None)
        if user_role != User.Role.PUSKESMAS and not cleaned_data.get("facility"):
            self.add_error("facility", "Fasilitas puskesmas wajib dipilih.")
            return cleaned_data

        facility = (
            cleaned_data.get("facility")
            if user_role != User.Role.PUSKESMAS
            else getattr(self.user, "facility", None)
        )
        if not facility:
            return cleaned_data

        active_year, next_month = get_next_required_lplpo_period(facility)
        self.active_year = active_year
        self.next_required_month = next_month
        self.selected_facility = facility

        tahun = cleaned_data.get("tahun")
        bulan = cleaned_data.get("bulan")

        if next_month is None:
            self.add_error(
                None,
                ValidationError(
                    f"Semua LPLPO tahun {active_year} untuk {facility.name} sudah dibuat."
                ),
            )
            return cleaned_data

        if tahun is not None and tahun != active_year:
            self.add_error(
                "tahun",
                ValidationError(
                    f"LPLPO baru hanya dapat dibuat untuk tahun server aktif {active_year}."
                ),
            )

        if bulan is not None and int(bulan) != next_month:
            self.add_error(
                "bulan",
                ValidationError(
                    "Periode berikutnya yang wajib dibuat adalah "
                    f"{format_lplpo_period_label(next_month, active_year)}."
                ),
            )

        return cleaned_data


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

    def clean_permintaan_alasan(self):
        return _normalize_text_value(
            self.cleaned_data.get("permintaan_alasan"),
            field_label="Alasan",
            max_length=1000,
        )

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

    def clean_pemberian_alasan(self):
        return _normalize_text_value(
            self.cleaned_data.get("pemberian_alasan"),
            field_label="Alasan pemberian",
            max_length=1000,
        )


class RejectLPLPOForm(forms.Form):
    """Form for Instalasi Farmasi to provide a rejection reason."""

    rejection_reason = forms.CharField(
        max_length=1000,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        label="Alasan Penolakan",
        error_messages={"required": "Alasan penolakan wajib diisi."},
    )

    def clean_rejection_reason(self):
        return _normalize_text_value(
            self.cleaned_data.get("rejection_reason"),
            field_label="Alasan penolakan",
            max_length=1000,
        )
