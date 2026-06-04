from django import forms
from django.db.models import F
from django.forms import inlineformset_factory

from apps.core.decimal_validation import validate_finite_decimal
from apps.stock.models import Stock

from .models import Recall, RecallItem


class StockByItemSelect(forms.Select):
    """Custom select widget that adds data-item-id to each option so JS can
    filter stock batches by the selected item in the same row."""

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


class RecallForm(forms.ModelForm):
    class Meta:
        model = Recall
        fields = ['document_number', 'recall_date', 'supplier', 'notes']
        widgets = {
            'document_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Kosongkan untuk auto-generate',
            }),
            'recall_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'supplier': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class RecallItemForm(forms.ModelForm):
    class Meta:
        model = RecallItem
        fields = ['item', 'stock', 'quantity', 'notes']
        widgets = {
            'item': forms.Select(attrs={
                'class': 'form-select form-select-sm js-typeahead-select js-item-select',
            }),
            'stock': StockByItemSelect(attrs={
                'class': 'form-select form-select-sm js-stock-select',
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm',
                'min': '0.01',
                'step': '0.01',
            }),
            'notes': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['item'].label_from_instance = lambda obj: obj.picker_label
        self.fields['notes'].required = False
        # FEFO default: only show batches with available stock, ordered by earliest expiry
        self.fields['stock'].queryset = (
            Stock.objects.select_related('item')
            .filter(quantity__gt=F('reserved'))
            .order_by('item_id', 'expiry_date', 'batch_lot')
        )
        self.fields['stock'].label_from_instance = lambda obj: (
            f"{obj.batch_lot} | Tersedia: {obj.available_quantity} | Exp: {obj.expiry_date}"
        )

    def clean(self):
        cleaned_data = super().clean()
        item = cleaned_data.get('item')
        stock = cleaned_data.get('stock')
        quantity = cleaned_data.get('quantity')

        if quantity is not None:
            try:
                quantity = validate_finite_decimal(quantity, field_label='Jumlah')
                cleaned_data['quantity'] = quantity
            except forms.ValidationError as exc:
                self.add_error('quantity', exc)
                quantity = None

        if stock and item and stock.item_id != item.id:
            self.add_error('stock', 'Batch stok harus sesuai dengan barang yang dipilih.')

        if quantity is not None and quantity <= 0:
            self.add_error('quantity', 'Jumlah harus lebih dari 0.')

        return cleaned_data


RecallItemFormSet = inlineformset_factory(
    Recall,
    RecallItem,
    form=RecallItemForm,
    extra=1,
    can_delete=True,
)
