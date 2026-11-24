from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from .decimal_validation import format_price_exact


INDONESIAN_DECIMAL_SEPARATOR_ERROR = (
    "Gunakan angka tanpa pemisah ribuan. Gunakan koma untuk desimal."
)
INDONESIAN_DATE_INPUT_FORMATS = ["%d/%m/%Y", "%Y-%m-%d"]


class ItemBatchSelect(forms.Select):
    """Model-choice batch options filtered by the existing shared item picker JS."""
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        instance = getattr(value, "instance", None)
        if instance is not None and getattr(instance, "item_id", None):
            option.setdefault("attrs", {})["data-item-id"] = str(instance.item_id)
        return option


class IndonesianDateInput(forms.DateInput):
    input_type = "text"

    def __init__(self, attrs=None, format=None):
        super().__init__(attrs=attrs, format=format or "%d/%m/%Y")


class IndonesianPriceTextInput(forms.TextInput):
    def format_value(self, value):
        if value is None or value == "":
            return None
        if isinstance(value, Decimal):
            label = format_price_exact(value)
            return label.replace(".", ",") if label else label
        return value


class IndonesianUnitPriceField(forms.DecimalField):
    default_error_messages = {
        **forms.DecimalField.default_error_messages,
        "dot_separator": INDONESIAN_DECIMAL_SEPARATOR_ERROR,
    }

    def to_python(self, value):
        if isinstance(value, str):
            normalized_value = value.strip().replace(" ", "")
            if "." in normalized_value:
                raise ValidationError(
                    self.error_messages["dot_separator"],
                    code="dot_separator",
                )
            if "," in normalized_value:
                normalized_value = normalized_value.replace(",", ".")
            value = normalized_value
        return super().to_python(value)
