import unicodedata
from decimal import Decimal, InvalidOperation

from django import forms
from django.core.exceptions import ValidationError
from django.db.utils import OperationalError, ProgrammingError
from django.forms import inlineformset_factory

from apps.core.decimal_validation import validate_finite_decimal
from apps.items.models import FundingSource, Supplier

from .models import (
    Receiving,
    ReceivingItem,
    ReceivingOrderItem,
    ReceivingTypeOption,
    get_reserved_receiving_type_codes,
    validate_receiving_type_code,
)


def _format_id_decimal(value, places=2):
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        number = Decimal("0")

    formatted = f"{number:,.{places}f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def _get_receiving_type_choices():
    try:
        custom_choices = list(
            ReceivingTypeOption.objects.filter(is_active=True)
            .order_by("name")
            .values_list("code", "name")
        )
    except (ProgrammingError, OperationalError):
        custom_choices = []
    return list(Receiving.ReceivingType.choices) + custom_choices


def _get_receiving_type_widget_choices():
    return [("", "---------")] + _get_receiving_type_choices()


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

    def clean_receiving_type(self):
        try:
            return validate_receiving_type_code(self.cleaned_data.get("receiving_type"))
        except ValidationError as exc:
            if hasattr(exc, "error_dict") and "receiving_type" in exc.error_dict:
                raise forms.ValidationError(exc.error_dict["receiving_type"])
            raise



class ReceivingForm(BaseReceivingForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["document_number"].widget.attrs["placeholder"] = (
            "Kosongkan untuk generate otomatis"
        )

    class Meta:
        model = Receiving
        fields = [
            "document_number",
            "receiving_type",
            "receiving_date",
            "supplier",
            "sumber_dana",
            "notes",
        ]
        widgets = {
            "document_number": forms.TextInput(attrs={"class": "form-control"}),
            "receiving_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "supplier": forms.Select(attrs={"class": "form-select"}),
            "sumber_dana": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

class PlannedReceivingForm(BaseReceivingForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["document_number"].widget.attrs["placeholder"] = (
            "Kosongkan untuk generate otomatis"
        )

    class Meta:
        model = Receiving
        fields = [
            "document_number",
            "receiving_type",
            "receiving_date",
            "supplier",
            "sumber_dana",
            "notes",
        ]
        widgets = {
            "document_number": forms.TextInput(attrs={"class": "form-control"}),
            "receiving_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "supplier": forms.Select(attrs={"class": "form-select"}),
            "sumber_dana": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }


class ReceivingItemForm(forms.ModelForm):
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
            "item": forms.Select(
                attrs={"class": "form-select form-select-sm js-typeahead-select"}
            ),
            "quantity": forms.NumberInput(
                attrs={"class": "form-control form-control-sm", "min": "1"}
            ),
            "batch_lot": forms.TextInput(
                attrs={"class": "form-control form-control-sm"}
            ),
            "expiry_date": forms.DateInput(
                attrs={"class": "form-control form-control-sm", "type": "date"}
            ),
            "unit_price": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "min": "0",
                    "step": "0.01",
                }
            ),
            "location": forms.Select(attrs={"class": "form-select form-select-sm"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].label_from_instance = lambda obj: obj.picker_label
        self.fields["location"].required = True

    def clean_quantity(self):
        quantity = self.cleaned_data.get("quantity")
        quantity = validate_finite_decimal(quantity, field_label="Jumlah")
        if quantity is not None and quantity <= 0:
            raise forms.ValidationError("Jumlah harus lebih dari 0.")
        return quantity


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
                    "step": "0.01",
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
            "expiry_date": forms.DateInput(
                attrs={"class": "form-control form-control-sm", "type": "date"}
            ),
            "unit_price": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "min": "0",
                    "step": "0.01",
                }
            ),
            "location": forms.Select(attrs={"class": "form-select form-select-sm"}),
        }

    def __init__(self, *args, **kwargs):
        receiving = kwargs.pop("receiving", None)
        lock_order_item = kwargs.pop("lock_order_item", False)
        super().__init__(*args, **kwargs)
        self.lock_order_item = lock_order_item
        self.fields["location"].required = True
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
            self.fields["planned_quantity"].initial = _format_id_decimal(
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
            if not cleaned.get("expiry_date"):
                self.add_error("expiry_date", "Tanggal kedaluwarsa wajib diisi.")
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
