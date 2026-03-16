from django import forms
from django.forms import inlineformset_factory
from django.db.utils import OperationalError, ProgrammingError
from .models import Receiving, ReceivingItem, ReceivingOrderItem, ReceivingTypeOption


def _get_receiving_type_choices():
    builtin_choices = list(Receiving.ReceivingType.choices)
    try:
        custom_choices = list(
            ReceivingTypeOption.objects.filter(is_active=True)
            .order_by("name")
            .values_list("code", "name")
        )
    except (ProgrammingError, OperationalError):
        custom_choices = []
    return builtin_choices + custom_choices


class ReceivingForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["receiving_type"].choices = _get_receiving_type_choices()

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
            "receiving_type": forms.Select(attrs={"class": "form-select"}),
            "receiving_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "supplier": forms.Select(attrs={"class": "form-select"}),
            "sumber_dana": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }


class PlannedReceivingForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["receiving_type"].choices = _get_receiving_type_choices()

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
            "receiving_type": forms.Select(attrs={"class": "form-select"}),
            "receiving_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "supplier": forms.Select(attrs={"class": "form-select"}),
            "sumber_dana": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }


class ReceivingItemForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["location"].required = True

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

    def clean_quantity(self):
        quantity = self.cleaned_data.get("quantity")
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
        if quantity is not None and quantity <= 0:
            raise forms.ValidationError("Jumlah rencana harus lebih dari 0.")
        return quantity


ReceivingOrderItemFormSet = inlineformset_factory(
    Receiving,
    ReceivingOrderItem,
    form=ReceivingOrderItemForm,
    extra=3,
    can_delete=True,
)


class ReceivingReceiptItemForm(forms.ModelForm):
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
        super().__init__(*args, **kwargs)
        self.fields["location"].required = True
        if receiving is not None:
            self.fields["order_item"].queryset = ReceivingOrderItem.objects.filter(
                receiving=receiving,
                is_cancelled=False,
            )
        self.fields["order_item"].label_from_instance = lambda obj: (
            f"{obj.item} (Sisa: {obj.remaining_quantity})"
        )

    def clean(self):
        cleaned = super().clean()
        order_item = cleaned.get("order_item")
        quantity = cleaned.get("quantity")
        if not order_item or quantity is None:
            return cleaned
        location = cleaned.get("location")
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
