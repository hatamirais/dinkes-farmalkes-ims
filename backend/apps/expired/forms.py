from collections import defaultdict
from decimal import Decimal

from django import forms
from django.utils import timezone
from django.db.models import DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.forms import BaseInlineFormSet, inlineformset_factory

from apps.core.decimal_validation import validate_finite_decimal
from apps.recall.forms import StockByItemSelect
from apps.items.models import FundingSource, Item, Location
from apps.stock.models import Stock

from .models import Expired, ExpiredItem


class ExpiredForm(forms.ModelForm):
    class Meta:
        model = Expired
        fields = ['document_number', 'report_date', 'notes']
        widgets = {
            'document_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Kosongkan untuk auto-generate',
            }),
            'report_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class ExpiredItemForm(forms.ModelForm):
    class Meta:
        model = ExpiredItem
        fields = ['item', 'stock', 'quantity', 'notes']
        widgets = {
            'item': forms.Select(attrs={
                'class': 'form-select form-select-sm js-typeahead-select js-item-select',
            }),
            'stock': StockByItemSelect(attrs={
                'class': 'form-select form-select-sm js-stock-select',
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm',
                'min': '0.01',
                'step': '0.01',
            }),
            'notes': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['item'].label_from_instance = lambda obj: obj.picker_label
        self.fields['notes'].required = False
        # FEFO default: only show batches with available stock, ordered by earliest expiry
        self.fields['stock'].queryset = (
            Stock.objects.select_related('item')
            .filter(quantity__gt=F('reserved'))
            .order_by('item_id', 'expiry_date', 'batch_lot')
        )
        self.fields['stock'].label_from_instance = lambda obj: (
            f"{obj.batch_lot} | Tersedia: {obj.available_quantity} | Exp: {obj.expiry_date}"
        )

    def clean(self):
        cleaned_data = super().clean()
        item = cleaned_data.get('item')
        stock = cleaned_data.get('stock')
        quantity = cleaned_data.get('quantity')

        if quantity is not None:
            try:
                quantity = validate_finite_decimal(quantity, field_label='Jumlah')
                cleaned_data['quantity'] = quantity
            except forms.ValidationError as exc:
                self.add_error('quantity', exc)
                quantity = None

        if stock and item and stock.item_id != item.id:
            self.add_error('stock', 'Batch stok harus sesuai dengan barang yang dipilih.')

        if quantity is not None and quantity <= 0:
            self.add_error('quantity', 'Jumlah harus lebih dari 0.')

        return cleaned_data


class BaseExpiredItemFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()

        if any(self.errors):
            return

        requested_by_stock = defaultdict(lambda: Decimal("0"))
        stock_map = {}
        forms_by_stock = defaultdict(list)

        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue

            cleaned_data = form.cleaned_data
            if not cleaned_data or cleaned_data.get("DELETE"):
                continue

            stock = cleaned_data.get("stock")
            quantity = cleaned_data.get("quantity")
            if not stock or quantity is None:
                continue

            requested_by_stock[stock.pk] += quantity
            stock_map[stock.pk] = stock
            forms_by_stock[stock.pk].append(form)

        if not requested_by_stock:
            return

        pending_rows = (
            ExpiredItem.objects.filter(
                stock_id__in=requested_by_stock.keys(),
                expired__status=Expired.Status.SUBMITTED,
            )
            .exclude(expired_id=self.instance.pk or 0)
            .values("stock_id")
            .annotate(
                total=Coalesce(
                    Sum("quantity"),
                    Value(0),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                )
            )
        )
        pending_by_stock = {
            row["stock_id"]: row["total"] for row in pending_rows
        }

        for stock_id, requested_total in requested_by_stock.items():
            stock = stock_map[stock_id]
            pending_total = pending_by_stock.get(stock_id, Decimal("0"))
            allowed_quantity = stock.available_quantity - pending_total

            if requested_total > allowed_quantity:
                remaining_quantity = max(allowed_quantity, Decimal("0"))
                message = (
                    "Jumlah melebihi stok yang masih bisa diproses. "
                    f"Sisa tersedia {remaining_quantity} setelah dikurangi "
                    f"dokumen kedaluwarsa yang masih diajukan sebanyak {pending_total}."
                )
                for form in forms_by_stock[stock_id]:
                    form.add_error("quantity", message)


ExpiredItemFormSet = inlineformset_factory(
    Expired,
    ExpiredItem,
    form=ExpiredItemForm,
    formset=BaseExpiredItemFormSet,
    extra=1,
    can_delete=True,
)


class ExpiredAuditReportFilterForm(forms.Form):
    DATE_FIELD_CHOICES = [
        ("disposed_at", "Tanggal Pemusnahan"),
        ("verified_at", "Tanggal Verifikasi"),
        ("created_at", "Tanggal Dibuat"),
    ]

    date_field = forms.ChoiceField(
        label="Basis Tanggal",
        choices=DATE_FIELD_CHOICES,
        initial="disposed_at",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    start_date = forms.DateField(
        label="Tanggal Mulai",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    end_date = forms.DateField(
        label="Tanggal Selesai",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    location = forms.ModelChoiceField(
        label="Lokasi",
        required=False,
        queryset=Location.objects.none(),
        empty_label="Semua Lokasi",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    item = forms.ModelChoiceField(
        label="Barang",
        required=False,
        queryset=Item.objects.none(),
        empty_label="Semua Barang",
        widget=forms.Select(attrs={"class": "form-select js-typeahead-select"}),
    )
    outcome_type = forms.CharField(
        required=False,
        initial="DESTROY",
        widget=forms.HiddenInput(),
    )
    funding_source = forms.ModelChoiceField(
        label="Sumber Dana",
        required=False,
        queryset=FundingSource.objects.none(),
        empty_label="Semua Sumber Dana",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["location"].queryset = Location.objects.filter(is_active=True).order_by("code", "name")
        self.fields["item"].queryset = Item.objects.filter(is_active=True).select_related("satuan").order_by("nama_barang")
        self.fields["item"].label_from_instance = lambda obj: obj.picker_label
        self.fields["funding_source"].queryset = FundingSource.objects.filter(is_active=True).order_by("code", "name")

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        cleaned_data["outcome_type"] = "DESTROY"
        if start_date and end_date and start_date > end_date:
            raise forms.ValidationError("Tanggal mulai tidak boleh lebih dari tanggal selesai.")
        return cleaned_data

    @classmethod
    def get_default_initial(cls):
        today = timezone.now().date()
        return {
            "start_date": today.replace(day=1),
            "end_date": today,
            "date_field": "disposed_at",
            "outcome_type": "DESTROY",
        }
