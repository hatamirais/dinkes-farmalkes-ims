from django import forms
from django.db.models import F
from django.forms import inlineformset_factory
from .models import Distribution, DistributionItem
from apps.stock.models import Stock


class StockByItemSelect(forms.Select):
    def create_option(
        self, name, value, label, selected, index, subindex=None, attrs=None
    ):
        option = super().create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs
        )
        instance = getattr(value, "instance", None)
        if instance is not None and getattr(instance, "item_id", None):
            option.setdefault("attrs", {})["data-item-id"] = str(instance.item_id)
        return option


class DistributionForm(forms.ModelForm):
    class Meta:
        model = Distribution
        fields = [
            "distribution_type",
            "request_date",
            "facility",
            "notes",
        ]
        widgets = {
            "distribution_type": forms.Select(attrs={"class": "form-select"}),
            "request_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "facility": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }


class DistributionItemForm(forms.ModelForm):
    class Meta:
        model = DistributionItem
        fields = ["item", "quantity_requested", "quantity_approved", "stock", "notes"]
        widgets = {
            "item": forms.Select(
                attrs={
                    "class": "form-select form-select-sm js-typeahead-select js-item-select"
                }
            ),
            "quantity_requested": forms.NumberInput(
                attrs={"class": "form-control form-control-sm", "min": "1"}
            ),
            "quantity_approved": forms.NumberInput(
                attrs={"class": "form-control form-control-sm", "min": "0"}
            ),
            "stock": StockByItemSelect(
                attrs={"class": "form-select form-select-sm js-stock-select"}
            ),
            "notes": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["quantity_approved"].required = False
        self.fields["stock"].required = False
        self.fields["notes"].required = False
        # FEFO default: only show batches with available stock, ordered by earliest expiry
        self.fields["stock"].queryset = (
            Stock.objects.select_related("item")
            .filter(quantity__gt=F("reserved"))
            .order_by("item_id", "expiry_date", "batch_lot")
        )
        self.fields["stock"].label_from_instance = lambda obj: (
            f"{obj.batch_lot} | Tersedia: {obj.available_quantity} | Exp: {obj.expiry_date}"
        )

    def clean(self):
        cleaned_data = super().clean()
        item = cleaned_data.get('item')
        stock = cleaned_data.get('stock')
        quantity = cleaned_data.get('quantity_requested')

        if stock and item and stock.item_id != item.id:
            self.add_error('stock', 'Batch stok harus sesuai dengan barang yang dipilih.')

        if quantity is not None and quantity <= 0:
            self.add_error('quantity_requested', 'Jumlah harus lebih dari 0.')

        return cleaned_data


DistributionItemFormSet = inlineformset_factory(
    Distribution,
    DistributionItem,
    form=DistributionItemForm,
    extra=3,
    can_delete=True,
)
