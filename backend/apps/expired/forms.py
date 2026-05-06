from collections import defaultdict
from decimal import Decimal

from django import forms
from django.db.models import DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.forms import BaseInlineFormSet, inlineformset_factory

from apps.recall.forms import StockByItemSelect
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
