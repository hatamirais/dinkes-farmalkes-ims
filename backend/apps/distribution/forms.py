from django import forms
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import F
from django.forms import inlineformset_factory
from django.utils import timezone
from apps.users.models import User

from .models import Distribution, DistributionItem
from .numbering import (
    generate_distribution_document_number,
    get_distribution_document_number_template,
    render_distribution_document_number_preview,
)
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
    document_number_preview = forms.CharField(required=False, widget=forms.HiddenInput())

    assigned_staff = forms.ModelMultipleChoiceField(
        queryset=User.objects.filter(is_active=True).order_by("full_name", "username"),
        required=False,
        label="Petugas",
        widget=forms.CheckboxSelectMultiple,
        help_text="Pilih petugas yang terlibat dalam proses distribusi ini.",
    )

    class Meta:
        model = Distribution
        fields = [
            "document_number",
            "distribution_type",
            "request_date",
            "facility",
            "program",
            "notes",
        ]
        widgets = {
            "document_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Kosongkan untuk auto-generate",
                }
            ),
            "distribution_type": forms.Select(attrs={"class": "form-select"}),
            "request_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "facility": forms.Select(attrs={"class": "form-select"}),
            "program": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Contoh: TB, HIV, Imunisasi",
                }
            ),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        self.forced_distribution_type = kwargs.pop("forced_distribution_type", None)
        super().__init__(*args, **kwargs)
        self.fields["program"].required = False
        # Remove LPLPO from manual selection unless this is a generated LPLPO distribution
        if not self._is_generated_lplpo_distribution():
            self.fields["distribution_type"].choices = [
                choice
                for choice in self.fields["distribution_type"].choices
                if choice[0] != Distribution.DistributionType.LPLPO
            ]
        # Also remove ALLOCATION from the manual distribution create/edit form
        # Allocations generate distributions automatically; prevent manual selection here.
        self.fields["distribution_type"].choices = [
            choice
            for choice in self.fields["distribution_type"].choices
            if choice[0] != Distribution.DistributionType.ALLOCATION
        ]
        if self.forced_distribution_type:
            self.fields["distribution_type"].required = False
            self.fields["distribution_type"].initial = self.forced_distribution_type
        self._configure_document_number_field()
        if self.instance.pk:
            self.fields[
                "assigned_staff"
            ].initial = self.instance.staff_assignments.values_list(
                "user_id", flat=True
            )
        elif user is not None:
            self.fields["assigned_staff"].initial = [user.pk]

    def _is_generated_lplpo_distribution(self):
        if not self.instance.pk:
            return False
        if self.instance.distribution_type != Distribution.DistributionType.LPLPO:
            return False
        try:
            self.instance.lplpo_source
        except ObjectDoesNotExist:
            return False
        return True

    def clean_distribution_type(self):
        if self.forced_distribution_type:
            return self.forced_distribution_type
        distribution_type = self.cleaned_data.get("distribution_type")
        return distribution_type

    def _get_effective_distribution_type(self):
        if self.forced_distribution_type:
            return self.forced_distribution_type
        if self.instance.pk:
            return self.instance.distribution_type
        return None

    def _configure_document_number_field(self):
        distribution_type = self._get_effective_distribution_type()
        template = get_distribution_document_number_template(distribution_type)
        if template is None:
            return

        example = render_distribution_document_number_preview(
            distribution_type,
            sequence="12",
            year=timezone.now().year,
        )
        field = self.fields["document_number"]
        field.required = False

        if distribution_type == Distribution.DistributionType.SPECIAL_REQUEST:
            preview_number = self.instance.document_number or generate_distribution_document_number(
                Distribution,
                distribution_type,
            )
            self.fields["document_number_preview"].initial = preview_number
            field.initial = preview_number
            field.help_text = (
                f"Nomor berikutnya saat ini: {preview_number}. Template aktif: {template} "
                f"(contoh format: {example})."
            )
            field.widget.attrs["placeholder"] = "Nomor dokumen permintaan khusus"
            field.widget.attrs["readonly"] = True
            return

        field.disabled = True
        field.help_text = (
            f"Nomor dokumen dibuat otomatis sesuai template {template} "
            f"(contoh: {example})."
        )
        field.widget.attrs["placeholder"] = "Nomor dokumen dibuat otomatis"
        field.widget.attrs["readonly"] = True

    def clean_document_number(self):
        document_number = (self.cleaned_data.get("document_number") or "").strip()
        preview_number = (
            self.data.get(self.add_prefix("document_number_preview"), "") or ""
        ).strip()
        distribution_type = self._get_effective_distribution_type()

        if distribution_type != Distribution.DistributionType.SPECIAL_REQUEST:
            return document_number

        if self.instance.pk:
            return document_number or self.instance.document_number

        if document_number and preview_number and document_number == preview_number:
            return ""

        return document_number

    def clean(self):
        cleaned_data = super().clean()
        submitted_distribution_type = self.data.get(
            self.add_prefix("distribution_type")
        )
        if submitted_distribution_type is not None:
            submitted_distribution_type = str(submitted_distribution_type)
        if (
            submitted_distribution_type == Distribution.DistributionType.LPLPO
            and not self._is_generated_lplpo_distribution()
        ):
            self.add_error(
                "distribution_type",
                "Distribusi tipe LPLPO hanya dapat dibuat dari dokumen LPLPO yang sudah diajukan oleh Puskesmas.",
            )
        return cleaned_data


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
        if "quantity_approved" in self.fields:
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
        item = cleaned_data.get("item")
        stock = cleaned_data.get("stock")
        quantity_requested = cleaned_data.get("quantity_requested")
        quantity_approved = cleaned_data.get("quantity_approved")

        if stock and item and stock.item_id != item.id:
            self.add_error(
                "stock", "Batch stok harus sesuai dengan barang yang dipilih."
            )

        if quantity_requested is not None and quantity_requested <= 0:
            self.add_error("quantity_requested", "Jumlah harus lebih dari 0.")

        if quantity_approved is not None and quantity_approved <= 0:
            self.add_error(
                "quantity_approved", "Jumlah disetujui harus lebih dari 0."
            )

        if (
            stock is not None
            and quantity_approved is not None
            and quantity_approved > stock.available_quantity
        ):
            self.add_error(
                "quantity_approved",
                "Jumlah disetujui melebihi stok batch yang tersedia.",
            )

        if (
            quantity_requested is not None
            and quantity_approved is not None
            and quantity_approved > quantity_requested
        ):
            self.add_error(
                "quantity_approved",
                "Jumlah disetujui tidak boleh melebihi jumlah diminta.",
            )

        return cleaned_data


DistributionItemFormSet = inlineformset_factory(
    Distribution,
    DistributionItem,
    form=DistributionItemForm,
    extra=3,
    can_delete=True,
)
