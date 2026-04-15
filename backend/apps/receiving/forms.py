from django import forms
from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce
from django.db.utils import OperationalError, ProgrammingError
from django.forms import inlineformset_factory
from django.forms.models import BaseInlineFormSet

from apps.distribution.models import Distribution, DistributionItem
from apps.items.models import Facility

from .models import Receiving, ReceivingItem, ReceivingOrderItem, ReceivingTypeOption


def _get_receiving_type_choices(include_return_rs=True):
    builtin_choices = [
        choice
        for choice in Receiving.ReceivingType.choices
        if include_return_rs or choice[0] != Receiving.ReceivingType.RETURN_RS
    ]
    try:
        custom_choices = list(
            ReceivingTypeOption.objects.filter(is_active=True)
            .order_by("name")
            .values_list("code", "name")
        )
    except (ProgrammingError, OperationalError):
        custom_choices = []
    return builtin_choices + custom_choices


class BaseReceivingForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        include_return_rs = kwargs.pop("include_return_rs", True)
        super().__init__(*args, **kwargs)
        self.fields["receiving_type"].choices = _get_receiving_type_choices(
            include_return_rs=include_return_rs
        )

    def clean(self):
        cleaned_data = super().clean()
        receiving_type = cleaned_data.get("receiving_type")
        supplier = cleaned_data.get("supplier")
        facility = cleaned_data.get("facility")

        if receiving_type == Receiving.ReceivingType.PROCUREMENT and not supplier:
            self.add_error("supplier", "Supplier wajib diisi untuk tipe Pengadaan.")

        if receiving_type == Receiving.ReceivingType.RETURN_RS:
            if not facility:
                self.add_error("facility", "Rumah sakit asal wajib dipilih.")
            elif facility.facility_type != facility.FacilityType.RS:
                self.add_error(
                    "facility",
                    "Pengembalian RS hanya dapat dikaitkan ke fasilitas Rumah Sakit.",
                )

        return cleaned_data


class ReceivingForm(BaseReceivingForm):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("include_return_rs", False)
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
            "receiving_type": forms.Select(attrs={"class": "form-select"}),
            "receiving_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "supplier": forms.Select(attrs={"class": "form-select"}),
            "sumber_dana": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }


class RsReturnReceivingForm(forms.ModelForm):
    class Meta:
        model = Receiving
        fields = [
            "document_number",
            "receiving_date",
            "facility",
            "sumber_dana",
            "notes",
        ]
        widgets = {
            "document_number": forms.TextInput(attrs={"class": "form-control"}),
            "receiving_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "facility": forms.Select(attrs={"class": "form-select"}),
            "sumber_dana": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["document_number"].widget.attrs["placeholder"] = (
            "Kosongkan untuk generate otomatis"
        )
        self.fields["facility"].queryset = Facility.objects.filter(
            facility_type=Facility.FacilityType.RS
        ).order_by("name")

    def clean(self):
        cleaned_data = super().clean()
        facility = cleaned_data.get("facility")

        if not facility:
            self.add_error("facility", "Rumah sakit asal wajib dipilih.")

        return cleaned_data


class PrefilledRsReturnReceivingForm(RsReturnReceivingForm):
    def __init__(self, *args, **kwargs):
        source_distribution = kwargs.pop("source_distribution", None)
        locked_funding_source = kwargs.pop("locked_funding_source", None)
        super().__init__(*args, **kwargs)
        self.source_distribution = source_distribution
        self.locked_funding_source = locked_funding_source

        if self.source_distribution is not None:
            facility = self.source_distribution.facility
            self.fields["facility"].queryset = Facility.objects.filter(pk=facility.pk)
            self.fields["facility"].initial = facility.pk
            self.fields["facility"].disabled = True

        if self.locked_funding_source is not None:
            self.fields["sumber_dana"].queryset = self.fields["sumber_dana"].queryset.filter(
                pk=self.locked_funding_source.pk
            )
            self.fields["sumber_dana"].initial = self.locked_funding_source.pk
            self.fields["sumber_dana"].disabled = True

    def clean(self):
        cleaned_data = super().clean()

        if self.source_distribution is not None:
            cleaned_data["facility"] = self.source_distribution.facility

        if self.locked_funding_source is not None:
            cleaned_data["sumber_dana"] = self.locked_funding_source

        return cleaned_data


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
            "receiving_type": forms.Select(attrs={"class": "form-select"}),
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
        self.fields["location"].required = True

    def clean_quantity(self):
        quantity = self.cleaned_data.get("quantity")
        if quantity is not None and quantity <= 0:
            raise forms.ValidationError("Jumlah harus lebih dari 0.")
        return quantity


class RSReturnReceivingItemForm(forms.ModelForm):
    settlement_distribution_item = forms.ModelChoiceField(
        queryset=DistributionItem.objects.none(),
        required=False,
        label="Dokumen RS Asal",
        widget=forms.Select(
            attrs={"class": "form-select form-select-sm js-typeahead-select"}
        ),
    )

    def __init__(self, *args, **kwargs):
        receiving_type = kwargs.pop("receiving_type", None)
        receiving_facility_id = kwargs.pop("receiving_facility_id", None)
        super().__init__(*args, **kwargs)
        self.fields["location"].required = True

        open_rs_items = (
            DistributionItem.objects.select_related(
                "distribution",
                "distribution__facility",
                "item",
            )
            .filter(
                distribution__status=Distribution.Status.DISTRIBUTED,
                distribution__distribution_type__in=[
                    Distribution.DistributionType.BORROW_RS,
                    Distribution.DistributionType.SWAP_RS,
                ],
            )
            .annotate(
                settled_quantity_total=Coalesce(
                    Sum("settlement_receipts__quantity"),
                    Value(0, output_field=DecimalField(max_digits=12, decimal_places=2)),
                )
            )
            .order_by(
                "distribution__facility__name",
                "distribution__request_date",
                "id",
            )
        )
        if receiving_facility_id:
            open_rs_items = open_rs_items.filter(
                distribution__facility_id=receiving_facility_id
            )

        open_rs_item_ids = [
            distribution_item.pk
            for distribution_item in open_rs_items
            if (
                (distribution_item.quantity_approved or distribution_item.quantity_requested)
                - distribution_item.settled_quantity_total
            )
            > 0
        ]
        self.fields["settlement_distribution_item"].queryset = (
            DistributionItem.objects.select_related(
                "distribution",
                "distribution__facility",
                "item",
            ).filter(pk__in=open_rs_item_ids)
        )
        self.fields["settlement_distribution_item"].label_from_instance = lambda obj: (
            f"{obj.distribution.document_number} | {obj.distribution.facility.name} | "
            f"{obj.item.nama_barang} | Sisa Pengembalian: {obj.outstanding_quantity}"
        )

        if receiving_type != Receiving.ReceivingType.RETURN_RS:
            self.fields["settlement_distribution_item"].widget = forms.HiddenInput()

    class Meta:
        model = ReceivingItem
        fields = [
            "item",
            "settlement_distribution_item",
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
            "settlement_distribution_item": forms.Select(
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

    def clean(self):
        cleaned_data = super().clean()
        item = cleaned_data.get("item")
        settlement_distribution_item = cleaned_data.get("settlement_distribution_item")

        if settlement_distribution_item and item:
            if settlement_distribution_item.item_id != item.id:
                self.add_error(
                    "settlement_distribution_item",
                    "Item pengembalian harus sama dengan item distribusi RS yang dipilih.",
                )

        return cleaned_data


class PrefilledRSReturnReceivingItemForm(RSReturnReceivingItemForm):
    def __init__(self, *args, **kwargs):
        locked_distribution_item = kwargs.pop("locked_distribution_item", None)
        super().__init__(*args, **kwargs)
        self.locked_distribution_item = locked_distribution_item

        if self.locked_distribution_item is None:
            return

        self.fields["item"].queryset = self.fields["item"].queryset.filter(
            pk=self.locked_distribution_item.item_id
        )
        self.fields["item"].initial = self.locked_distribution_item.item_id
        self.fields["item"].disabled = True

        self.fields["settlement_distribution_item"].queryset = DistributionItem.objects.filter(
            pk=self.locked_distribution_item.pk
        )
        self.fields["settlement_distribution_item"].initial = self.locked_distribution_item.pk
        self.fields["settlement_distribution_item"].disabled = True

        self.fields["unit_price"].initial = self.locked_distribution_item.issued_unit_price
        self.fields["unit_price"].disabled = True

    def clean(self):
        cleaned_data = super().clean()

        if self.locked_distribution_item is not None:
            cleaned_data["item"] = self.locked_distribution_item.item
            cleaned_data["settlement_distribution_item"] = self.locked_distribution_item
            cleaned_data["unit_price"] = self.locked_distribution_item.issued_unit_price

        return cleaned_data


ReceivingItemFormSet = inlineformset_factory(
    Receiving,
    ReceivingItem,
    form=ReceivingItemForm,
    extra=3,
    can_delete=True,
)


RSReturnReceivingItemFormSet = inlineformset_factory(
    Receiving,
    ReceivingItem,
    form=RSReturnReceivingItemForm,
    extra=3,
    can_delete=True,
)


class PrefilledRSReturnReceivingItemBaseFormSet(BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        self.locked_distribution_items = list(kwargs.pop("locked_distribution_items", []))
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        if index is not None and index < len(self.locked_distribution_items):
            distribution_item = self.locked_distribution_items[index]
            kwargs["locked_distribution_item"] = distribution_item
            kwargs["receiving_type"] = Receiving.ReceivingType.RETURN_RS
            kwargs["receiving_facility_id"] = distribution_item.distribution.facility_id
        return kwargs


def build_prefilled_rs_return_item_formset(extra_forms):
    return inlineformset_factory(
        Receiving,
        ReceivingItem,
        form=PrefilledRSReturnReceivingItemForm,
        formset=PrefilledRSReturnReceivingItemBaseFormSet,
        extra=extra_forms,
        can_delete=False,
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
    order_item_label = forms.CharField(
        required=False,
        disabled=True,
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm"}),
    )
    planned_quantity = forms.DecimalField(
        required=False,
        disabled=True,
        decimal_places=2,
        widget=forms.NumberInput(
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
            self.fields["order_item_label"].initial = str(selected_order_item.item)
            self.fields[
                "planned_quantity"
            ].initial = selected_order_item.planned_quantity

        if self.lock_order_item:
            self.fields["order_item"].widget = forms.HiddenInput()
            self.fields["quantity"].required = False
            self.fields["quantity"].widget.attrs["min"] = "0"
        self.fields["order_item"].label_from_instance = lambda obj: (
            f"{obj.item} (Sisa: {obj.remaining_quantity})"
        )

    def clean(self):
        cleaned = super().clean()
        order_item = cleaned.get("order_item")
        quantity = cleaned.get("quantity")
        if not order_item or quantity is None:
            if self.lock_order_item and order_item and quantity in (None, ""):
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


ReceivingPlannedReceiptItemFormSet = inlineformset_factory(
    Receiving,
    ReceivingItem,
    form=ReceivingReceiptItemForm,
    extra=0,
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
