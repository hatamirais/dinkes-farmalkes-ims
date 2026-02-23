from django import forms
from django.forms import inlineformset_factory
from .models import Receiving, ReceivingItem


class ReceivingForm(forms.ModelForm):
    class Meta:
        model = Receiving
        fields = [
            'document_number', 'receiving_type', 'receiving_date',
            'supplier', 'sumber_dana', 'notes',
        ]
        widgets = {
            'document_number': forms.TextInput(attrs={'class': 'form-control'}),
            'receiving_type': forms.Select(attrs={'class': 'form-select'}),
            'receiving_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'supplier': forms.Select(attrs={'class': 'form-select'}),
            'sumber_dana': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class ReceivingItemForm(forms.ModelForm):
    class Meta:
        model = ReceivingItem
        fields = ['item', 'quantity', 'batch_lot', 'expiry_date', 'unit_price']
        widgets = {
            'item': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'min': '1'}),
            'batch_lot': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'expiry_date': forms.DateInput(attrs={'class': 'form-control form-control-sm', 'type': 'date'}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'min': '0', 'step': '0.01'}),
        }


ReceivingItemFormSet = inlineformset_factory(
    Receiving,
    ReceivingItem,
    form=ReceivingItemForm,
    extra=3,
    can_delete=True,
)
