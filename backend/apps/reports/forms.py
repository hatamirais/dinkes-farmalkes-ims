from django import forms
from django.utils import timezone
import datetime

class InventoryReportFilterForm(forms.Form):
    start_date = forms.DateField(
        label='Tanggal Mulai',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    end_date = forms.DateField(
        label='Tanggal Akhir',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start_date')
        end = cleaned_data.get('end_date')

        if start and end and start > end:
            raise forms.ValidationError("Tanggal mulai tidak boleh lebih dari tanggal akhir.")
        
        return cleaned_data

    @classmethod
    def get_default_initial(cls):
        now = timezone.now().date()
        start_date = now.replace(day=1)
        return {
            'start_date': start_date,
            'end_date': now
        }
