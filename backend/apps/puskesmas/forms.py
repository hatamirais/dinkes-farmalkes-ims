from django import forms
from django.forms import inlineformset_factory
from apps.items.models import Facility, Item
from apps.users.models import User

from .models import PuskesmasRequest, PuskesmasRequestItem


class PuskesmasRequestForm(forms.ModelForm):
    class Meta:
        model = PuskesmasRequest
        fields = ["document_number", "facility", "request_date", "notes"]
        widgets = {
            "document_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Kosongkan untuk auto-generate",
                }
            ),
            "facility": forms.Select(attrs={"class": "form-select"}),
            "request_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.fields["document_number"].required = False
        self.fields["notes"].required = False
        # Only show active puskesmas facilities
        self.fields["facility"].queryset = Facility.objects.filter(
            facility_type=Facility.FacilityType.PUSKESMAS, is_active=True
        ).order_by("name")
        if self.user and getattr(self.user, "role", None) == User.Role.PUSKESMAS:
            self.fields["facility"].widget = forms.HiddenInput()
            self.fields["facility"].required = False
            if self.user.facility_id:
                self.fields["facility"].initial = self.user.facility_id

    def clean_facility(self):
        if self.user and getattr(self.user, "role", None) == User.Role.PUSKESMAS:
            if not self.user.facility_id:
                raise forms.ValidationError(
                    "Akun operator belum terhubung ke fasilitas puskesmas."
                )
            return self.user.facility
        return self.cleaned_data.get("facility")


class PuskesmasRequestItemForm(forms.ModelForm):
    class Meta:
        model = PuskesmasRequestItem
        fields = ["item", "quantity_requested", "notes"]
        widgets = {
            "item": forms.Select(
                attrs={
                    "class": "form-select form-select-sm js-typeahead-select js-item-select"
                }
            ),
            "quantity_requested": forms.NumberInput(
                attrs={"class": "form-control form-control-sm", "min": "1", "step": "1"}
            ),
            "notes": forms.TextInput(
                attrs={"class": "form-control form-control-sm", "placeholder": "Keterangan (opsional)"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["notes"].required = False
        # Prefer program items first in the dropdown
        self.fields["item"].queryset = (
            Item.objects.select_related("satuan", "kategori", "program")
            .filter(is_active=True)
            .order_by("-is_program_item", "kode_barang")
        )
        self.fields["item"].label_from_instance = lambda obj: obj.nama_barang

    def clean_quantity_requested(self):
        qty = self.cleaned_data.get("quantity_requested")
        if qty is not None and qty <= 0:
            raise forms.ValidationError("Jumlah harus lebih dari 0.")
        return qty


class ApprovalItemForm(forms.ModelForm):
    """Inline form for approving/adjusting quantity per item during the approval step."""

    class Meta:
        model = PuskesmasRequestItem
        fields = ["quantity_approved"]
        widgets = {
            "quantity_approved": forms.NumberInput(
                attrs={"class": "form-control form-control-sm", "min": "0", "step": "1"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["quantity_approved"].required = False


PuskesmasRequestItemFormSet = inlineformset_factory(
    PuskesmasRequest,
    PuskesmasRequestItem,
    form=PuskesmasRequestItemForm,
    extra=3,
    can_delete=True,
    min_num=1,
    validate_min=True,
)
