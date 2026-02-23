from django import forms
from django.forms import inlineformset_factory
from .models import Distribution, DistributionItem


class DistributionForm(forms.ModelForm):
    class Meta:
        model = Distribution
        fields = [
            'document_number', 'distribution_type', 'request_date',
            'facility', 'notes',
        ]
        widgets = {
            'document_number': forms.TextInput(attrs={'class': 'form-control'}),
            'distribution_type': forms.Select(attrs={'class': 'form-select'}),
            'request_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'facility': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class DistributionItemForm(forms.ModelForm):
    class Meta:
        model = DistributionItem
        fields = ['item', 'quantity_requested', 'quantity_approved', 'stock', 'notes']
        widgets = {
            'item': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'quantity_requested': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'min': '1'}),
            'quantity_approved': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'min': '0'}),
            'stock': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'notes': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['quantity_approved'].required = False
        self.fields['stock'].required = False
        self.fields['notes'].required = False


DistributionItemFormSet = inlineformset_factory(
    Distribution,
    DistributionItem,
    form=DistributionItemForm,
    extra=3,
    can_delete=True,
)
