from crispy_forms.helper import FormHelper
from crispy_forms.layout import Div, Layout
from django import forms

from apps.users.models import User

from .models import StockOpname


class StockOpnameForm(forms.ModelForm):
    class Meta:
        model = StockOpname
        fields = ['period_type', 'period_start', 'period_end', 'categories', 'assigned_to', 'notes']
        widgets = {
            'period_type': forms.Select(attrs={'class': 'form-select'}),
            'period_start': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'period_end': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'categories': forms.CheckboxSelectMultiple(),
            'assigned_to': forms.CheckboxSelectMultiple(),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }
        labels = {
            'period_type': 'Tipe Periode',
            'period_start': 'Tanggal Mulai',
            'period_end': 'Tanggal Selesai',
            'categories': 'Kategori Barang',
            'assigned_to': 'Ditugaskan Kepada',
            'notes': 'Catatan',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # F10: Only active users may be assigned to an opname session.
        self.fields['assigned_to'].queryset = (
            User.objects.filter(is_active=True).order_by('full_name', 'username')
        )
        self.fields['categories'].required = True

        # F9: crispy-forms helper — renders via {% crispy form %} in the template.
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.disable_csrf = True
        self.helper.layout = Layout(
            Div('period_type', css_class='mb-3'),
            Div('period_start', css_class='mb-3'),
            Div('period_end', css_class='mb-3'),
            Div('categories', css_class='mb-3'),
            Div('assigned_to', css_class='mb-3'),
            Div('notes', css_class='mb-0'),
        )

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('period_start')
        end = cleaned_data.get('period_end')
        if start and end and start > end:
            raise forms.ValidationError('Tanggal mulai tidak boleh lebih besar dari tanggal selesai.')
        return cleaned_data
