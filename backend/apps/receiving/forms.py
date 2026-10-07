import unicodedata
from decimal import Decimal, InvalidOperation

from django import forms
from django.core.exceptions import ValidationError
from django.db.utils import OperationalError, ProgrammingError
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
from apps.items.models import FundingSource, Supplier

from .models import (
    Receiving,
    ReceivingItem,
    ReceivingOrderItem,
    ReceivingTypeOption,
    get_reserved_receiving_type_codes,
    normalize_receiving_type_code,
    validate_receiving_type_code,
)


def _format_plain_decimal(value, places=None):
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        number = Decimal("0")

    if places is None:
        label = format(number, "f")
        if "." in label:
            label = label.rstrip("0").rstrip(".")
        return label or "0"

    return f"{number:.{places}f}"


def _format_id_price_exact(value):
    label = format_price_exact(value)
    if not label:
        return label
    whole, separator, fractional = label.partition(".")
    grouped_whole = f"{int(whole or '0'):,}".replace(",", ".")
    if separator:
        return f"{grouped_whole},{fractional}"
    return grouped_whole


def _get_receiving_type_choices():
    try:
        custom_choices = list(
            ReceivingTypeOption.objects.filter(is_active=True)
            .exclude(code="RETURN_RS")
            .order_by("sort_order", "name")
            .values_list("code", "name")
        )
    except (ProgrammingError, OperationalError):
        custom_choices = list(Receiving.ReceivingType.choices)
    return custom_choices


def _get_receiving_type_widget_choices():
    return [("", "---------")] + _get_receiving_type_choices()


def _receiving_type_label(code):
    if not code:
        return ""
    try:
        option = ReceivingTypeOption.objects.filter(code=code).only("name").first()
    except (ProgrammingError, OperationalError):
        option = None
    if option:
        return option.name
    return dict(Receiving.ReceivingType.choices).get(code, code)


def _add_receiving_type_choice(choices, code):
    if not code:
        return choices
    if any(choice_code == code for choice_code, _ in choices):
        return choices
    return [*choices, (code, _receiving_type_label(code))]


class ItemExpirySelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(
            name,
            value,
            label,
            selected,
            index,
            subindex,
            attrs,
        )
        if value and hasattr(value, "instance"):
            option["attrs"]["data-requires-expiry-date"] = (
                "true" if value.instance.requires_expiry_date else "false"
            )
        return option


def _normalize_text_value(value, *, field_label, max_length=None, allow_blank=True):
    if value is None:
        return "" if allow_blank else value

    raw_value = str(value)
    if "\x00" in raw_value:
        raise forms.ValidationError(f"{field_label} mengandung karakter yang tidak valid.")

    normalized = unicodedata.normalize("NFC", raw_value)
    normalized = " ".join(normalized.strip().split())
    if not normalized and not allow_blank:
        raise forms.ValidationError(f"{field_label} wajib diisi.")
    if max_length is not None and len(normalized) > max_length:
        raise forms.ValidationError(
            f"{field_label} tidak boleh lebih dari {max_length} karakter."
        )
    return normalized


def _item_requires_expiry_date(item):
    if item is None:
        return True
    return bool(getattr(item, "requires_expiry_date", True))


def _indonesian_date_attrs(css_class="form-control"):
    return {
        "class": f"{css_class} js-date-mask",
        "data-native-date-picker": "true",
        "placeholder": "DD/MM/YYYY",
        "inputmode": "numeric",
        "autocomplete": "off",
    }


class ReceivingQuickCreateValidationMixin:
    code_field_name = "code"
    name_field_name = "name"

    def _normalize_code(self, *, field_label="Kode", max_length=20):
        code = _normalize_text_value(
            self.cleaned_data.get(self.code_field_name),
            field_label=field_label,
            max_length=max_length,
            allow_blank=False,
        )
        return code.upper()

    def _normalize_name(self, *, field_label="Nama", max_length=100):
        return _normalize_text_value(
            self.cleaned_data.get(self.name_field_name),
            field_label=field_label,
            max_length=max_length,
            allow_blank=False,
        )

    def _normalize_optional_text(self, field_name, *, field_label, max_length=None):
        return _normalize_text_value(
            self.cleaned_data.get(field_name),
            field_label=field_label,
            max_length=max_length,
            allow_blank=True,
        )

    def _validate_unique_code(self, model_class, code):
        queryset = model_class.objects.filter(code__iexact=code)
        if self.instance and self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError("Kode sudah digunakan. Gunakan kode lain.")
        return code

    def _validate_unique_name(self, model_class, value, *, field_name="name"):
        queryset = model_class.objects.filter(**{f"{field_name}__iexact": value})
        if self.instance and self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError("Nama sudah digunakan. Gunakan nama lain.")
        return value


class ReceivingQuickCreateSupplierForm(ReceivingQuickCreateValidationMixin, forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["code", "name", "address", "phone", "email", "notes"]

    def clean_code(self):
        code = self._normalize_code(max_length=20)
        return self._validate_unique_code(Supplier, code)

    def clean_name(self):
        name = self._normalize_name(max_length=255)
        return self._validate_unique_name(Supplier, name)

    def clean_address(self):
        return self._normalize_optional_text("address", field_label="Alamat")

    def clean_phone(self):
        return self._normalize_optional_text(
            "phone",
            field_label="Telepon",
            max_length=50,
        )

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if not email:
            return ""
        return _normalize_text_value(
            email,
            field_label="Email",
            max_length=254,
            allow_blank=True,
        )

    def clean_notes(self):
        return self._normalize_optional_text("notes", field_label="Catatan")


class ReceivingQuickCreateFundingSourceForm(ReceivingQuickCreateValidationMixin, forms.ModelForm):
    class Meta:
        model = FundingSource
        fields = ["code", "name", "description"]

    def clean_code(self):
        code = self._normalize_code(max_length=20)
        return self._validate_unique_code(FundingSource, code)

    def clean_name(self):
        name = self._normalize_name(max_length=100)
        return self._validate_unique_name(FundingSource, name)

    def clean_description(self):
        return self._normalize_optional_text("description", field_label="Keterangan")


class ReceivingQuickCreateReceivingTypeForm(ReceivingQuickCreateValidationMixin, forms.ModelForm):
    class Meta:
        model = ReceivingTypeOption
        fields = ["code", "name"]

    def clean_code(self):
        code = self._normalize_code(max_length=20)
        if code in get_reserved_receiving_type_codes():
            raise forms.ValidationError(
                f'Kode "{code}" sudah digunakan tipe bawaan sistem.'
            )
        return self._validate_unique_code(ReceivingTypeOption, code)

    def clean_name(self):
        name = self._normalize_name(max_length=100)
        return self._validate_unique_name(ReceivingTypeOption, name)


class BaseReceivingForm(forms.ModelForm):
    receiving_type = forms.CharField(
        error_messages={"required": "Tipe penerimaan wajib dipilih."},
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["receiving_type"].widget.choices = _get_receiving_type_widget_choices()
        if "receiving_date" in self.fields:
            self.fields["receiving_date"].input_formats = INDONESIAN_DATE_INPUT_FORMATS

    def clean_receiving_type(self):
        try:
            return validate_receiving_type_code(self.cleaned_data.get("receiving_type"))
        except ValidationError as exc:
            if hasattr(exc, "error_dict") and "receiving_type" in exc.error_dict:
                raise forms.ValidationError(exc.error_dict["receiving_type"])
            raise



class ReceivingForm(BaseReceivingForm):
    class Meta:
        model = Receiving
        fields = [
            "receiving_type",
            "receiving_date",
            "supplier",
            "sumber_dana",
            "notes",
        ]
        widgets = {
            "receiving_date": IndonesianDateInput(
                attrs=_indonesian_date_attrs()
            ),
            "supplier": forms.Select(attrs={"class": "form-select"}),
            "sumber_dana": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def clean_receiving_date(self):
        value = self.cleaned_data.get("receiving_date")
        if value and not (1000 <= value.year <= 9999):
            raise forms.ValidationError(
                "Tanggal penerimaan harus berada pada rentang tahun 1000-9999."
            )
        return value

    def clean_notes(self):
        return _normalize_text_value(
            self.cleaned_data.get("notes"),
            field_label="Catatan",
        )


class ReceivingEditForm(ReceivingForm):
    correction_reason = forms.CharField(
        label="Alasan Koreksi",
        required=True,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current_type = getattr(self.instance, "receiving_type", "")
        self.fields["receiving_type"].widget.choices = _add_receiving_type_choice(
            list(self.fields["receiving_type"].widget.choices),
            current_type,
        )
        if getattr(self.instance, "document_number", None):
            self.fields["receiving_date"].disabled = True

    def clean_receiving_type(self):
        try:
            return super().clean_receiving_type()
        except ValidationError:
            current_type = getattr(self.instance, "receiving_type", "")
            submitted_type = normalize_receiving_type_code(
                self.cleaned_data.get("receiving_type")
            )
            if submitted_type and submitted_type == current_type:
                return submitted_type
            raise

    def clean_correction_reason(self):
        return _normalize_text_value(
            self.cleaned_data.get("correction_reason"),
            field_label="Alasan koreksi",
            max_length=1000,
            allow_blank=False,
        )


class ReceivingCancelForm(forms.Form):
    cancel_reason = forms.CharField(
        label="Alasan Pembatalan",
        required=True,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )

    def clean_cancel_reason(self):
        return _normalize_text_value(
            self.cleaned_data.get("cancel_reason"),
            field_label="Alasan pembatalan",
            max_length=1000,
            allow_blank=False,
        )

class PlannedReceivingForm(BaseReceivingForm):
    class Meta:
        model = Receiving
        fields = [
            "receiving_type",
            "receiving_date",
            "supplier",
            "sumber_dana",
            "notes",
        ]
        widgets = {
            "receiving_date": IndonesianDateInput(
                attrs=_indonesian_date_attrs()
            ),
            "supplier": forms.Select(attrs={"class": "form-select"}),
            "sumber_dana": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }


class ReceivingItemForm(forms.ModelForm):
    unit_price = IndonesianUnitPriceField(
        required=True,
        min_value=Decimal("0"),
        max_digits=PRICE_MAX_DIGITS,
        decimal_places=PRICE_DECIMAL_PLACES,
        widget=IndonesianPriceTextInput(
            attrs={
                "class": "form-control form-control-sm",
                "inputmode": "decimal",
                "min": "0",
            }
        ),
    )

    class Meta:
        model = ReceivingItem
        fields = [
            "item",
            "quantity",
            "batch_lot",
            "expiry_date",
            "unit_price",
            "location",
        ]
        widgets = {
            "item": ItemExpirySelect(
                attrs={"class": "form-select form-select-sm js-typeahead-select"}
            ),
            "quantity": forms.NumberInput(
                attrs={"class": "form-control form-control-sm", "min": "1"}
            ),
            "batch_lot": forms.TextInput(
                attrs={"class": "form-control form-control-sm"}
            ),
            "expiry_date": IndonesianDateInput(
                attrs=_indonesian_date_attrs("form-control form-control-sm")
            ),
            "location": forms.Select(attrs={"class": "form-select form-select-sm"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].label_from_instance = lambda obj: obj.picker_label
        self.fields["location"].required = True
        self.fields["batch_lot"].required = False
        self.fields["expiry_date"].required = False
        self.fields["expiry_date"].input_formats = INDONESIAN_DATE_INPUT_FORMATS

    def clean_quantity(self):
        quantity = self.cleaned_data.get("quantity")
        quantity = validate_finite_decimal(quantity, field_label="Jumlah")
        if quantity is not None and quantity <= 0:
            raise forms.ValidationError("Jumlah harus lebih dari 0.")
        return quantity

    def clean_unit_price(self):
        unit_price = self.cleaned_data.get("unit_price")
        unit_price = validate_finite_decimal(unit_price, field_label="Harga satuan")
        if unit_price is not None and unit_price < 0:
            raise forms.ValidationError("Harga satuan tidak boleh negatif.")
        return unit_price

    def clean_batch_lot(self):
        batch_lot = _normalize_text_value(
            self.cleaned_data.get("batch_lot"),
            field_label="Batch/Lot",
            max_length=100,
            allow_blank=True,
        )
        return batch_lot or "-"

    def clean_expiry_date(self):
        value = self.cleaned_data.get("expiry_date")
        if value and not (1000 <= value.year <= 9999):
            raise forms.ValidationError(
                "Tanggal kedaluwarsa harus berada pada rentang tahun 1000-9999."
            )
        if (
            value is None
            and self.instance.pk
            and self.instance.expiry_date is not None
            and self.add_prefix("expiry_date") not in self.data
        ):
            item = self.cleaned_data.get("item")
            if (
                item
                and self.instance.item_id == item.pk
                and not _item_requires_expiry_date(item)
            ):
                return self.instance.expiry_date
        return value

    def clean(self):
        cleaned = super().clean()
        item = cleaned.get("item")
        if item and _item_requires_expiry_date(item) and not cleaned.get("expiry_date"):
            self.add_error("expiry_date", "Tanggal kedaluwarsa wajib diisi untuk barang ini.")
        return cleaned


ReceivingItemFormSet = inlineformset_factory(
    Receiving,
    ReceivingItem,
    form=ReceivingItemForm,
    extra=3,
    can_delete=True,
)


class ReceivingOrderItemForm(forms.ModelForm):
    class Meta:
        model = ReceivingOrderItem
        fields = ["item", "planned_quantity", "unit_price", "notes"]
        widgets = {
            "item": forms.Select(
                attrs={"class": "form-select form-select-sm js-typeahead-select"}
            ),
            "planned_quantity": forms.NumberInput(
                attrs={"class": "form-control form-control-sm", "min": "1"}
            ),
            "unit_price": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "min": "0",
                    "step": "any",
                }
            ),
            "notes": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
        }

    def clean_planned_quantity(self):
        quantity = self.cleaned_data.get("planned_quantity")
        quantity = validate_finite_decimal(quantity, field_label="Jumlah rencana")
        if quantity is not None and quantity <= 0:
            raise forms.ValidationError("Jumlah rencana harus lebih dari 0.")
        return quantity

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].label_from_instance = lambda obj: obj.picker_label

    def clean_unit_price(self):
        unit_price = self.cleaned_data.get("unit_price")
        unit_price = validate_finite_decimal(unit_price, field_label="Harga satuan")
        if unit_price is None or unit_price <= 0:
            raise forms.ValidationError("Harga satuan harus lebih dari 0.")
        return unit_price


ReceivingOrderItemFormSet = inlineformset_factory(
    Receiving,
    ReceivingOrderItem,
    form=ReceivingOrderItemForm,
    extra=3,
    can_delete=True,
)


class ReceivingReceiptItemForm(forms.ModelForm):
    unit_price = IndonesianUnitPriceField(
        required=True,
        min_value=Decimal("0"),
        max_digits=PRICE_MAX_DIGITS,
        decimal_places=PRICE_DECIMAL_PLACES,
        widget=IndonesianPriceTextInput(
            attrs={
                "class": "form-control form-control-sm",
                "inputmode": "decimal",
            }
        ),
    )
    order_item_label = forms.CharField(
        required=False,
        disabled=True,
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm"}),
    )
    planned_quantity = forms.CharField(
        required=False,
        disabled=True,
        widget=forms.TextInput(
            attrs={"class": "form-control form-control-sm text-end", "readonly": True}
        ),
    )
    order_item = forms.ModelChoiceField(
        queryset=ReceivingOrderItem.objects.none(),
        widget=forms.Select(
            attrs={"class": "form-select form-select-sm js-typeahead-select"}
        ),
        required=True,
    )

    class Meta:
        model = ReceivingItem
        fields = [
            "order_item",
            "quantity",
            "batch_lot",
            "expiry_date",
            "unit_price",
            "location",
        ]
        widgets = {
            "quantity": forms.NumberInput(
                attrs={"class": "form-control form-control-sm", "min": "1"}
            ),
            "batch_lot": forms.TextInput(
                attrs={"class": "form-control form-control-sm"}
            ),
            "expiry_date": IndonesianDateInput(
                attrs=_indonesian_date_attrs("form-control form-control-sm")
            ),
            "location": forms.Select(attrs={"class": "form-select form-select-sm"}),
        }

    def __init__(self, *args, **kwargs):
        receiving = kwargs.pop("receiving", None)
        lock_order_item = kwargs.pop("lock_order_item", False)
        super().__init__(*args, **kwargs)
        self.lock_order_item = lock_order_item
        self.fields["location"].required = True
        self.fields["expiry_date"].input_formats = INDONESIAN_DATE_INPUT_FORMATS
        selected_order_item = None
        if receiving is not None:
            self.fields["order_item"].queryset = ReceivingOrderItem.objects.filter(
                receiving=receiving,
                is_cancelled=False,
            )
        if self.is_bound:
            selected_order_item_id = self.data.get(self.add_prefix("order_item"))
        else:
            selected_order_item_id = self.initial.get("order_item")

        if selected_order_item_id:
            selected_order_item = (
                self.fields["order_item"]
                .queryset.filter(pk=selected_order_item_id)
                .first()
            )

        if selected_order_item:
            self.fields["order_item_label"].initial = (
                selected_order_item.item.nama_barang
            )
            self.fields["planned_quantity"].initial = _format_plain_decimal(
                selected_order_item.remaining_quantity
            )

        if self.lock_order_item:
            self.fields["order_item"].widget = forms.HiddenInput()
            self.fields["quantity"].required = False
            self.fields["quantity"].widget.attrs["min"] = "0"
            self.fields["batch_lot"].required = False
            self.fields["expiry_date"].required = False
            self.fields["unit_price"].required = False
            self.fields["location"].required = False
        self.fields["order_item"].label_from_instance = lambda obj: (
            f"{obj.item} (Sisa: {obj.remaining_quantity})"
        )
        self.fields["location"].label_from_instance = lambda obj: obj.name

    def clean(self):
        cleaned = super().clean()
        order_item = cleaned.get("order_item")
        quantity = cleaned.get("quantity")
        quantity_invalid = False

        if quantity not in (None, ""):
            try:
                quantity = validate_finite_decimal(quantity, field_label="Jumlah")
                cleaned["quantity"] = quantity
            except forms.ValidationError as exc:
                self.add_error("quantity", exc)
                cleaned["quantity"] = None
                quantity = None
                quantity_invalid = True

        unit_price = cleaned.get("unit_price")
        if unit_price not in (None, ""):
            try:
                cleaned["unit_price"] = validate_finite_decimal(
                    unit_price,
                    field_label="Harga satuan",
                )
                if cleaned["unit_price"] < 0:
                    self.add_error("unit_price", "Harga satuan tidak boleh negatif.")
            except forms.ValidationError as exc:
                self.add_error("unit_price", exc)
                cleaned["unit_price"] = None

        if not order_item or quantity is None:
            if (
                not quantity_invalid
                and self.lock_order_item
                and order_item
                and quantity in (None, "")
            ):
                cleaned["quantity"] = 0
                return cleaned
            return cleaned
        location = cleaned.get("location")
        if self.lock_order_item:
            if quantity < 0:
                self.add_error("quantity", "Jumlah tidak boleh kurang dari 0.")
            if quantity == 0:
                return cleaned
            if location is None:
                self.add_error("location", "Lokasi wajib dipilih.")
            if not cleaned.get("batch_lot"):
                self.add_error("batch_lot", "Batch/Lot wajib diisi.")
            if _item_requires_expiry_date(order_item.item) and not cleaned.get("expiry_date"):
                self.add_error("expiry_date", "Tanggal kedaluwarsa wajib diisi untuk barang ini.")
            if cleaned.get("unit_price") is None:
                self.add_error("unit_price", "Harga satuan wajib diisi.")
        else:
            if location is None:
                self.add_error("location", "Lokasi wajib dipilih.")
            if quantity <= 0:
                self.add_error("quantity", "Jumlah harus lebih dari 0.")
        if order_item.is_cancelled:
            self.add_error("order_item", "Item pesanan ini sudah dibatalkan.")
        if order_item.remaining_quantity < quantity:
            self.add_error("quantity", "Jumlah melebihi sisa pesanan.")
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        if instance.order_item_id:
            instance.item = instance.order_item.item
        if commit:
            instance.save()
        return instance


ReceivingReceiptItemFormSet = inlineformset_factory(
    Receiving,
    ReceivingItem,
    form=ReceivingReceiptItemForm,
    extra=3,
    can_delete=True,
)


def build_planned_receipt_item_formset(extra_forms):
    return inlineformset_factory(
        Receiving,
        ReceivingItem,
        form=ReceivingReceiptItemForm,
        extra=extra_forms,
        can_delete=False,
    )


class ReceivingCloseForm(forms.Form):
    closed_reason = forms.CharField(
        label="Alasan Penutupan",
        required=True,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}),
    )


class ReceivingOrderCloseItemForm(forms.ModelForm):
    class Meta:
        model = ReceivingOrderItem
        fields = ["is_cancelled", "cancel_reason"]
        widgets = {
            "is_cancelled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "cancel_reason": forms.TextInput(
                attrs={"class": "form-control form-control-sm"}
            ),
        }

    def clean(self):
        cleaned = super().clean()
        is_cancelled = cleaned.get("is_cancelled")
        cancel_reason = (cleaned.get("cancel_reason") or "").strip()
        if is_cancelled and self.instance.remaining_quantity > 0 and not cancel_reason:
            self.add_error("cancel_reason", "Alasan pembatalan wajib diisi.")
        if not is_cancelled:
            cleaned["cancel_reason"] = ""
        return cleaned


ReceivingOrderCloseItemFormSet = inlineformset_factory(
    Receiving,
    ReceivingOrderItem,
    form=ReceivingOrderCloseItemForm,
    extra=0,
    can_delete=False,
)
