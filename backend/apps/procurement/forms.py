from crispy_forms.helper import FormHelper
from crispy_forms.layout import Div, Layout
from django import forms
from django.forms import inlineformset_factory

from apps.core.decimal_validation import (
    PRICE_DECIMAL_PLACES,
    PRICE_MAX_DIGITS,
    format_price_exact,
    validate_finite_decimal,
)
from apps.core.form_fields import (
    INDONESIAN_DATE_INPUT_FORMATS,
    IndonesianDateInput,
    IndonesianPriceTextInput,
    IndonesianUnitPriceField,
)
from apps.items.models import FundingSource, Item, Supplier

from .models import (
    ProcurementAmendment,
    ProcurementAmendmentLine,
    ProcurementContract,
    ProcurementContractLine,
)


def _format_plain_decimal(value, places=None):
    if places is None:
        label = format(value, "f")
        if "." in label:
            label = label.rstrip("0").rstrip(".")
        return label or "0"

    try:
        places_int = int(places)
    except (TypeError, ValueError):
        places_int = None
    if places_int is None:
        label = format(value, "f")
        if "." in label:
            label = label.rstrip("0").rstrip(".")
        return label or "0"
    if places_int < 0:
        places_int = 0
    return f"{value:.{places_int}f}"


def _format_id_price_exact(value):
    label = format_price_exact(value)
    if not label:
        return ""

    sign = ""
    if label.startswith("-"):
        sign = "-"
        label = label[1:]

    whole, separator, fractional = label.partition(".")
    grouped_whole = f"{int(whole or '0'):,}".replace(",", ".")
    if separator:
        return f"{sign}{grouped_whole},{fractional}"
    return f"{sign}{grouped_whole}"


def _normalize_text_value(value, *, field_label, max_length=None, allow_blank=True):
    if value is None:
        return "" if allow_blank else value

    raw_value = str(value)
    if "\x00" in raw_value:
        raise forms.ValidationError(f"{field_label} mengandung karakter yang tidak valid.")

    normalized = " ".join(raw_value.strip().split())
    if not normalized and not allow_blank:
        raise forms.ValidationError(f"{field_label} wajib diisi.")
    if max_length is not None and len(normalized) > max_length:
        raise forms.ValidationError(
            f"{field_label} tidak boleh lebih dari {max_length} karakter."
        )
    return normalized


class ProcurementContractForm(forms.ModelForm):
    class Meta:
        model = ProcurementContract
        fields = ["contract_date", "supplier", "sumber_dana", "notes"]
        widgets = {
            "contract_date": IndonesianDateInput(
                attrs={
                    "class": "form-control js-date-mask",
                    "data-native-date-picker": "true",
                    "placeholder": "DD/MM/YYYY",
                    "inputmode": "numeric",
                    "autocomplete": "off",
                }
            ),
            "supplier": forms.Select(attrs={"class": "form-select"}),
            "sumber_dana": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["contract_date"].input_formats = INDONESIAN_DATE_INPUT_FORMATS
        self.fields["supplier"].queryset = Supplier.objects.filter(is_active=True).order_by("name")
        self.fields["sumber_dana"].queryset = FundingSource.objects.filter(is_active=True).order_by("name")
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.disable_csrf = True
        self.helper.layout = Layout(
            Div("contract_date", css_class="mb-3"),
            Div("supplier", css_class="mb-3"),
            Div("sumber_dana", css_class="mb-3"),
            Div("notes", css_class="mb-0"),
        )

    def clean_notes(self):
        return _normalize_text_value(self.cleaned_data.get("notes"), field_label="Catatan")

    def clean_contract_date(self):
        value = self.cleaned_data.get("contract_date")
        if value and (value.year < 1000 or value.year > 9999):
            raise forms.ValidationError("Tanggal kontrak harus berada pada rentang tahun 1000-9999.")
        return value


class ProcurementContractCancelForm(forms.Form):
    cancel_reason = forms.CharField(
        label="Alasan Pembatalan",
        required=True,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": "Alasan pembatalan SPJ",
            }
        ),
    )

    def clean_cancel_reason(self):
        return _normalize_text_value(
            self.cleaned_data.get("cancel_reason"),
            field_label="Alasan pembatalan",
            max_length=1000,
            allow_blank=False,
        )


class ProcurementContractLineForm(forms.ModelForm):
    original_unit_price = IndonesianUnitPriceField(
        max_digits=PRICE_MAX_DIGITS,
        decimal_places=PRICE_DECIMAL_PLACES,
        widget=IndonesianPriceTextInput(
            attrs={
                "class": "form-control form-control-sm",
                "inputmode": "decimal",
                "min": "0.0000000001",
            }
        ),
    )

    class Meta:
        model = ProcurementContractLine
        fields = ["item", "original_quantity", "original_unit_price", "notes"]
        widgets = {
            "item": forms.Select(attrs={"class": "form-select form-select-sm js-typeahead-select"}),
            "original_quantity": forms.NumberInput(attrs={"class": "form-control form-control-sm", "step": "0.01", "min": "0.01"}),
            "notes": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = Item.objects.filter(is_active=True).order_by("nama_barang")
        self.fields["item"].label_from_instance = lambda obj: obj.picker_label

    def clean_original_quantity(self):
        quantity = validate_finite_decimal(
            self.cleaned_data.get("original_quantity"),
            field_label="Jumlah kontrak awal",
        )
        if quantity is not None and quantity <= 0:
            raise forms.ValidationError("Jumlah kontrak awal harus lebih dari 0.")
        return quantity

    def clean_original_unit_price(self):
        unit_price = validate_finite_decimal(
            self.cleaned_data.get("original_unit_price"),
            field_label="Harga satuan awal",
        )
        if unit_price is not None and unit_price <= 0:
            raise forms.ValidationError("Harga satuan awal harus lebih dari 0.")
        return unit_price

    def clean_notes(self):
        return _normalize_text_value(self.cleaned_data.get("notes"), field_label="Catatan")


ProcurementContractLineFormSet = inlineformset_factory(
    ProcurementContract,
    ProcurementContractLine,
    form=ProcurementContractLineForm,
    extra=1,
    can_delete=True,
)


class ProcurementAmendmentForm(forms.ModelForm):
    class Meta:
        model = ProcurementAmendment
        fields = ["amendment_date", "notes"]
        widgets = {
            "amendment_date": IndonesianDateInput(
                attrs={
                    "class": "form-control js-date-mask",
                    "data-native-date-picker": "true",
                    "placeholder": "DD/MM/YYYY",
                    "inputmode": "numeric",
                    "autocomplete": "off",
                }
            ),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["amendment_date"].input_formats = INDONESIAN_DATE_INPUT_FORMATS
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.disable_csrf = True
        self.helper.layout = Layout(
            Div("amendment_date", css_class="mb-3"),
            Div("notes", css_class="mb-0"),
        )

    def clean_notes(self):
        return _normalize_text_value(self.cleaned_data.get("notes"), field_label="Catatan")

    def clean_amendment_date(self):
        value = self.cleaned_data.get("amendment_date")
        if value and (value.year < 1000 or value.year > 9999):
            raise forms.ValidationError("Tanggal amandemen harus berada pada rentang tahun 1000-9999.")
        return value


class ProcurementAmendmentLineForm(forms.ModelForm):
    revised_unit_price = IndonesianUnitPriceField(
        max_digits=PRICE_MAX_DIGITS,
        decimal_places=PRICE_DECIMAL_PLACES,
        widget=IndonesianPriceTextInput(
            attrs={
                "class": "form-control form-control-sm",
                "inputmode": "decimal",
                "min": "0.0000000001",
            }
        ),
    )

    class Meta:
        model = ProcurementAmendmentLine
        fields = ["contract_line", "revised_quantity", "revised_unit_price", "notes"]
        widgets = {
            "contract_line": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "revised_quantity": forms.NumberInput(attrs={"class": "form-control form-control-sm", "step": "0.01", "min": "0.01"}),
            "notes": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
        }

    def __init__(self, *args, **kwargs):
        contract = kwargs.pop("contract", None)
        contract_line_summary = kwargs.pop("contract_line_summary", None) or {}
        super().__init__(*args, **kwargs)
        queryset = ProcurementContractLine.objects.none()
        if contract is not None:
            queryset = contract.lines.select_related("item").order_by("item__nama_barang")
        self.fields["contract_line"].queryset = queryset
        self.fields["contract_line"].label_from_instance = (
            lambda line: self._contract_line_label(line, contract_line_summary)
        )

    @staticmethod
    def _contract_line_label(line, contract_line_summary):
        summary = contract_line_summary.get(line.pk)
        if not summary:
            return (
                f"{line.item.nama_barang} | Awal: {_format_plain_decimal(line.original_quantity)} "
                f"@ {_format_id_price_exact(line.original_unit_price)}"
            )
        return (
            f"{line.item.nama_barang} | Saat ini: "
            f"{_format_plain_decimal(summary['current_quantity'])} @ "
            f"{_format_id_price_exact(summary['current_unit_price'])} | Diterima: "
            f"{_format_plain_decimal(summary['received_quantity'])} | Sisa: "
            f"{_format_plain_decimal(summary['remaining_quantity'])}"
        )

    def clean_revised_quantity(self):
        quantity = validate_finite_decimal(
            self.cleaned_data.get("revised_quantity"),
            field_label="Jumlah revisi",
        )
        if quantity is not None and quantity <= 0:
            raise forms.ValidationError("Jumlah revisi harus lebih dari 0.")
        return quantity

    def clean_revised_unit_price(self):
        unit_price = validate_finite_decimal(
            self.cleaned_data.get("revised_unit_price"),
            field_label="Harga satuan revisi",
        )
        if unit_price is not None and unit_price <= 0:
            raise forms.ValidationError("Harga satuan revisi harus lebih dari 0.")
        return unit_price

    def clean_notes(self):
        return _normalize_text_value(self.cleaned_data.get("notes"), field_label="Catatan")


ProcurementAmendmentLineFormSet = inlineformset_factory(
    ProcurementAmendment,
    ProcurementAmendmentLine,
    form=ProcurementAmendmentLineForm,
    extra=1,
    can_delete=True,
)
