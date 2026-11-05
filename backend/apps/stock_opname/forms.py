from django import forms

from apps.users.models import User

from .models import StockOpname


class StockOpnameForm(forms.ModelForm):
    class Meta:
        model = StockOpname
        fields = ['period_type', 'period_start', 'period_end', 'categories', 'assigned_to', 'notes']
        widgets = {
            'period_type': forms.Select(attrs={'class': 'ims-control'}),
            'period_start': forms.DateInput(attrs={'class': 'ims-control', 'type': 'date'}),
            'period_end': forms.DateInput(attrs={'class': 'ims-control', 'type': 'date'}),
            'categories': forms.CheckboxSelectMultiple(),
            'assigned_to': forms.CheckboxSelectMultiple(),
            'notes': forms.Textarea(attrs={'class': 'ims-control', 'rows': 2}),
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
        # F10: Only active users may be assigned to new opname sessions.
        # For existing instances (edit), also include any currently assigned
        # users who may have since been deactivated, so saving an unrelated
        # field change does not silently drop them from the M2M relation.
        active_qs = User.objects.filter(is_active=True)
        if self.instance and self.instance.pk:
            current_assignees = self.instance.assigned_to.filter(is_active=False)
            if current_assignees.exists():
                active_qs = (active_qs | current_assignees).distinct()
        self.fields['assigned_to'].queryset = active_qs.order_by('full_name', 'username')
        self.fields['categories'].required = True
        if self.instance.pk and self.instance.document_number:
            self.fields['period_end'].disabled = True
            self.fields['period_end'].help_text = (
                'Tanggal selesai dikunci setelah nomor dokumen diterbitkan.'
            )


    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('period_start')
        end = cleaned_data.get('period_end')
        if start and end and start > end:
            raise forms.ValidationError('Tanggal mulai tidak boleh lebih besar dari tanggal selesai.')
        return cleaned_data
