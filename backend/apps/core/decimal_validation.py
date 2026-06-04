from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError


def validate_finite_decimal(value, *, field_label="Nilai"):
    if value in (None, ""):
        return value

    decimal_value = value
    if not isinstance(decimal_value, Decimal):
        try:
            decimal_value = Decimal(str(value).strip())
        except (InvalidOperation, TypeError, ValueError):
            return value

    if not decimal_value.is_finite():
        raise ValidationError(f"{field_label} tidak boleh NaN atau Infinity.")

    return decimal_value


def parse_decimal_input(value, *, field_label="Nilai", allow_empty=False):
    raw_value = (value or "").strip().replace(",", ".").replace(" ", "")
    if not raw_value:
        if allow_empty:
            return None
        return Decimal("0")

    try:
        decimal_value = Decimal(raw_value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"format {field_label} tidak valid: '{raw_value}'") from exc

    return validate_finite_decimal(decimal_value, field_label=field_label)