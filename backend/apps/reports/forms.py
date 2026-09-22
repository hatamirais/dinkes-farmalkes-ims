from django import forms
from django.utils import timezone
import datetime

from apps.distribution.models import Distribution

ALLOCATION_ORIGIN_FILTER = "ALLOCATION"

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


class PengeluaranReportFilterForm(InventoryReportFilterForm):
    distribution_type = forms.ChoiceField(
        label='Jenis Distribusi',
        required=False,
        choices=[
            ('', 'Semua Distribusi'),
            (Distribution.DistributionType.SPECIAL_REQUEST, 'Permintaan Khusus'),
            (ALLOCATION_ORIGIN_FILTER, 'Asal Alokasi'),
            (Distribution.DistributionType.LPLPO, 'LPLPO'),
        ],
        widget=forms.HiddenInput(),
    )
    facility = forms.ModelChoiceField(
        label='Fasilitas',
        queryset=None,
        required=False,
        empty_label='Semua Fasilitas',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.items.models import Facility
        self.fields['facility'].queryset = Facility.objects.filter(is_active=True).order_by('name')

    @classmethod
    def get_default_initial(cls):
        initial = super().get_default_initial()
        initial['distribution_type'] = ''
        return initial


class NumberingHistoryFilterForm(forms.Form):
    rule_key = forms.ChoiceField(
        label='Jenis Dokumen',
        required=False,
        choices=[('', 'Semua Dokumen')],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    year = forms.IntegerField(
        label='Tahun',
        min_value=1000,
        max_value=9999,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '2026'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.core.models import DocumentNumberRule

        self.fields['rule_key'].choices = [('', 'Semua Dokumen'), *list(
            DocumentNumberRule.objects.order_by('label', 'key').values_list('key', 'label')
        )]

    @classmethod
    def get_default_initial(cls):
        return {
            'rule_key': '',
            'year': timezone.now().year,
        }
