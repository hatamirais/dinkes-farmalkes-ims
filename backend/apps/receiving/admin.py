from django.contrib import admin
from django.shortcuts import render, redirect
from django.contrib import messages
from django.urls import path
from django import forms
from django.db import transaction
from django.utils import timezone

import csv
import io
from collections import defaultdict
from datetime import datetime

from .models import Receiving, ReceivingItem, ReceivingDocument
from apps.items.models import Item, FundingSource, Location, Supplier
from apps.stock.models import Stock, Transaction


# ── Inlines ────────────────────────────────────────────────


class ReceivingItemInline(admin.TabularInline):
    model = ReceivingItem
    extra = 1
    fields = ('item', 'quantity', 'batch_lot', 'expiry_date', 'unit_price')
    raw_id_fields = ('item',)


class ReceivingDocumentInline(admin.TabularInline):
    model = ReceivingDocument
    extra = 0
    fields = ('file', 'file_name', 'file_type')


# ── CSV Import Form ────────────────────────────────────────


class ReceivingCSVImportForm(forms.Form):
    csv_file = forms.FileField(
        label='File CSV',
        help_text='Format: document_number, receiving_type, receiving_date, '
                  'supplier_code, sumber_dana_code, location_code, item_code, '
                  'quantity, batch_lot, expiry_date, unit_price',
    )


# ── Admin ──────────────────────────────────────────────────


@admin.register(Receiving)
class ReceivingAdmin(admin.ModelAdmin):
    list_display = (
        'document_number', 'receiving_type', 'receiving_date',
        'supplier', 'sumber_dana', 'status', 'created_by',
    )
    list_filter = ('receiving_type', 'status', 'sumber_dana')
    search_fields = ('document_number', 'supplier__name')
    date_hierarchy = 'receiving_date'
    inlines = [ReceivingItemInline, ReceivingDocumentInline]
    raw_id_fields = ('supplier', 'created_by', 'verified_by')
    readonly_fields = ('verified_at',)
    list_per_page = 25

    change_list_template = 'admin/receiving/receiving_changelist.html'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'import-csv/',
                self.admin_site.admin_view(self.import_csv_view),
                name='receiving_import_csv',
            ),
        ]
        return custom_urls + urls

    def import_csv_view(self, request):
        """Custom CSV import view for bulk receiving + stock creation."""
        if request.method == 'POST':
            form = ReceivingCSVImportForm(request.POST, request.FILES)
            if form.is_valid():
                try:
                    result = self._process_csv(
                        request.FILES['csv_file'],
                        request.user,
                    )
                    messages.success(
                        request,
                        f"Import berhasil: {result['receivings']} penerimaan, "
                        f"{result['items']} item, {result['stock']} stok, "
                        f"{result['transactions']} transaksi dibuat.",
                    )
                    return redirect('..')
                except Exception as e:
                    messages.error(request, f"Import gagal: {e}")
        else:
            form = ReceivingCSVImportForm()

        return render(request, 'admin/receiving/csv_import.html', {
            'form': form,
            'title': 'Import Penerimaan dari CSV',
            'opts': self.model._meta,
        })

    @transaction.atomic
    def _process_csv(self, csv_file, user):
        """Parse flat CSV and create Receiving + ReceivingItem + Stock + Transaction."""
        decoded = csv_file.read().decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(decoded))

        # Normalize headers (strip whitespace, lowercase)
        if reader.fieldnames:
            reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]

        # Group rows by document_number
        grouped = defaultdict(list)
        for row_num, row in enumerate(reader, start=2):
            row = {k.strip(): v.strip() for k, v in row.items()}
            if not row.get('document_number'):
                raise ValueError(f"Baris {row_num}: document_number kosong")
            grouped[row['document_number']].append((row_num, row))

        counts = {'receivings': 0, 'items': 0, 'stock': 0, 'transactions': 0}

        for doc_number, rows in grouped.items():
            # Use first row for header-level data
            first_row = rows[0][1]

            # Resolve FKs
            sumber_dana = FundingSource.objects.get(code=first_row['sumber_dana_code'])
            location = Location.objects.get(code=first_row['location_code'])

            supplier = None
            supplier_code = first_row.get('supplier_code', '').strip()
            if supplier_code:
                supplier = Supplier.objects.get(code=supplier_code)

            # Parse date
            receiving_date = self._parse_date(first_row['receiving_date'])

            # Create Receiving (parent)
            receiving = Receiving.objects.create(
                document_number=doc_number,
                receiving_type=first_row.get('receiving_type', 'GRANT'),
                receiving_date=receiving_date,
                supplier=supplier,
                sumber_dana=sumber_dana,
                status=Receiving.Status.VERIFIED,
                created_by=user,
                verified_by=user,
                verified_at=timezone.now(),
                notes=f'Imported via CSV on {timezone.now().strftime("%Y-%m-%d %H:%M")}',
            )
            counts['receivings'] += 1

            # Create ReceivingItem + Stock + Transaction for each row
            for row_num, row in rows:
                item = Item.objects.get(kode_barang=row['item_code'])
                quantity = self._parse_decimal(row.get('quantity', '0'))
                unit_price = self._parse_decimal(row.get('unit_price', '0'))
                batch_lot = row.get('batch_lot', '')
                expiry_date = self._parse_date(row['expiry_date'])

                if not batch_lot:
                    raise ValueError(f"Baris {row_num}: batch_lot kosong")

                # ReceivingItem
                ReceivingItem.objects.create(
                    receiving=receiving,
                    item=item,
                    quantity=quantity,
                    batch_lot=batch_lot,
                    expiry_date=expiry_date,
                    unit_price=unit_price,
                )
                counts['items'] += 1

                # Row-level overrides (location/sumber_dana can vary per row)
                row_sumber_dana_code = row.get('sumber_dana_code', '').strip()
                row_location_code = row.get('location_code', '').strip()
                row_sumber_dana = (
                    FundingSource.objects.get(code=row_sumber_dana_code)
                    if row_sumber_dana_code else sumber_dana
                )
                row_location = (
                    Location.objects.get(code=row_location_code)
                    if row_location_code else location
                )

                # Stock — update or create
                stock, created = Stock.objects.get_or_create(
                    item=item,
                    location=row_location,
                    batch_lot=batch_lot,
                    sumber_dana=row_sumber_dana,
                    defaults={
                        'expiry_date': expiry_date,
                        'quantity': quantity,
                        'unit_price': unit_price,
                        'receiving_ref': receiving,
                    },
                )
                if not created:
                    stock.quantity += quantity
                    stock.save()
                counts['stock'] += 1

                # Transaction
                Transaction.objects.create(
                    transaction_type=Transaction.TransactionType.IN,
                    item=item,
                    location=row_location,
                    batch_lot=batch_lot,
                    quantity=quantity,
                    unit_price=unit_price,
                    sumber_dana=row_sumber_dana,
                    reference_type=Transaction.ReferenceType.RECEIVING,
                    reference_id=receiving.pk,
                    user=user,
                    notes=f'Import saldo awal: {doc_number}',
                )
                counts['transactions'] += 1

        return counts

    @staticmethod
    def _parse_date(value):
        """Parse date from DD/MM/YYYY or YYYY-MM-DD format."""
        for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%y'):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Format tanggal tidak dikenali: '{value}'. Gunakan DD/MM/YYYY.")

    @staticmethod
    def _parse_decimal(value):
        """Parse decimal value, handling comma as decimal separator."""
        value = value.strip().replace(',', '.').replace(' ', '')
        if not value:
            return 0
        return float(value)
