from django import forms
from .models import SystemSettings

class SystemSettingsForm(forms.ModelForm):
    class Meta:
        model = SystemSettings
        fields = [
            'platform_label',
            'facility_name',
            'facility_address',
            'facility_phone',
            'header_title',
            'logo'
        ]
        widgets = {
            'facility_address': forms.Textarea(attrs={'rows': 3}),
        }
