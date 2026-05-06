from django import forms
from django.db.models import F
from django.forms import inlineformset_factory

from apps.items.models import Facility
from apps.stock.models import Stock
from apps.users.models import User

from .models import Allocation, AllocationItem, AllocationItemFacility


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


class AllocationForm(forms.ModelForm):
    selected_facilities = forms.ModelMultipleChoiceField(
        queryset=Facility.objects.filter(is_active=True).order_by("code", "name"),
        required=False,
        label="Fasilitas Tujuan",
        widget=forms.CheckboxSelectMultiple,
        help_text="Pilih fasilitas tujuan yang akan menerima alokasi.",
    )
    assigned_staff = forms.ModelMultipleChoiceField(
        queryset=User.objects.filter(is_active=True).order_by("full_name", "username"),
        required=False,
        label="Petugas",
        widget=forms.CheckboxSelectMultiple,
        help_text="Pilih satu atau lebih petugas yang menyiapkan alokasi.",
    )

    class Meta:
        model = Allocation
        fields = ["title", "referensi", "allocation_date", "notes"]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Judul alokasi (opsional)",
                }
            ),
            "referensi": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Nomor BAST / SP (opsional)",
                }
            ),
            "allocation_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"},
                format="%Y-%m-%d",
            ),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["title"].label = "Judul Alokasi"
        self.fields["allocation_date"].input_formats = ["%Y-%m-%d"]
        self.fields["selected_facilities"].label_from_instance = (
            lambda facility: facility.name
        )
        if self.instance.pk:
            self.fields["selected_facilities"].initial = (
                self.instance.selected_facilities.values_list("facility_id", flat=True)
            )
            self.fields["assigned_staff"].initial = (
                self.instance.staff_assignments.values_list("user_id", flat=True)
            )


class AllocationItemForm(forms.ModelForm):
    class Meta:
        model = AllocationItem
        fields = ["item", "stock", "total_qty_available", "notes"]
        widgets = {
            "item": forms.Select(
                attrs={
                    "class": "form-select form-select-sm js-typeahead-select js-item-select"
                }
            ),
            "stock": StockByItemSelect(
                attrs={"class": "form-select form-select-sm js-stock-select"}
            ),
            "total_qty_available": forms.HiddenInput(),
            "notes": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
        }

    def __init__(self, *args, **kwargs):
        kwargs.pop("selected_facility_ids", None)
        super().__init__(*args, **kwargs)
        self.fields["item"].label_from_instance = lambda obj: obj.picker_label
        self.fields["notes"].required = False
        self.fields["stock"].required = False
        self.fields["total_qty_available"].required = False

        available_stock_queryset = (
            Stock.objects.select_related("item")
            .filter(quantity__gt=F("reserved"))
            .order_by("item_id", "expiry_date", "batch_lot")
        )

        stock_item_id = (
            self.instance.item_id
            if self.instance.pk and self.instance.item_id
            else None
        )
        if self.is_bound:
            posted_item_id = self.data.get(self.add_prefix("item"))
            try:
                stock_item_id = (
                    int(posted_item_id) if posted_item_id else stock_item_id
                )
            except (TypeError, ValueError):
                stock_item_id = stock_item_id

        if stock_item_id:
            self.fields["stock"].queryset = available_stock_queryset.filter(
                item_id=stock_item_id
            )
        else:
            self.fields["stock"].queryset = Stock.objects.none()

        self.fields["stock"].label_from_instance = lambda obj: (
            f"{obj.batch_lot} | Tersedia: {obj.available_quantity} | Exp: {obj.expiry_date}"
        )

    def clean(self):
        cleaned_data = super().clean()
        item = cleaned_data.get("item")
        stock = cleaned_data.get("stock")

        if stock and item and stock.item_id != item.id:
            self.add_error(
                "stock", "Batch stok harus sesuai dengan barang yang dipilih."
            )

        # Snapshot available quantity from selected stock
        if stock:
            cleaned_data["total_qty_available"] = stock.available_quantity

        return cleaned_data


AllocationItemFormSet = inlineformset_factory(
    Allocation,
    AllocationItem,
    form=AllocationItemForm,
    extra=1,
    can_delete=True,
)
