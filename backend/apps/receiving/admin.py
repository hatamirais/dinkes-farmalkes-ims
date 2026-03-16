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
from decimal import Decimal, InvalidOperation

from .models import (
    Receiving,
    ReceivingItem,
    ReceivingDocument,
    ReceivingOrderItem,
    ReceivingTypeOption,
)
from apps.items.models import Item, FundingSource, Location, Supplier
from apps.stock.models import Stock, Transaction


# ── Inlines ────────────────────────────────────────────────


class ReceivingItemInline(admin.TabularInline):
    model = ReceivingItem
    extra = 1
    fields = ("item", "quantity", "batch_lot", "expiry_date", "unit_price", "location")
    raw_id_fields = ("item",)


class ReceivingOrderItemInline(admin.TabularInline):
    model = ReceivingOrderItem
    extra = 1
    fields = (
        "item",
        "planned_quantity",
        "received_quantity",
        "unit_price",
        "is_cancelled",
    )
    readonly_fields = ("received_quantity",)
    raw_id_fields = ("item",)


class ReceivingDocumentInline(admin.TabularInline):
    model = ReceivingDocument
    extra = 0
    fields = ("file", "file_name", "file_type")


@admin.register(ReceivingTypeOption)
class ReceivingTypeOptionAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("code", "name")
    ordering = ("name",)


# ── CSV Import Form ────────────────────────────────────────


class ReceivingCSVImportForm(forms.Form):
    csv_file = forms.FileField(
        label="File CSV",
        help_text="Format: document_number, receiving_type, receiving_date, "
        "supplier_code, sumber_dana_code, location_code, item_code, "
        "quantity, batch_lot, expiry_date, unit_price",
    )


# ── Admin ──────────────────────────────────────────────────


@admin.register(Receiving)
class ReceivingAdmin(admin.ModelAdmin):
    list_display = (
        "document_number",
        "receiving_type",
        "receiving_date",
        "supplier",
        "sumber_dana",
        "status",
        "created_by",
    )
    list_filter = ("receiving_type", "status", "sumber_dana")
    search_fields = ("document_number", "supplier__name")
    date_hierarchy = "receiving_date"
    inlines = [ReceivingOrderItemInline, ReceivingItemInline, ReceivingDocumentInline]
    raw_id_fields = ("supplier", "created_by", "verified_by")
    readonly_fields = ("verified_at",)
    list_per_page = 25

    change_list_template = "admin/receiving/receiving_changelist.html"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "import-csv/",
                self.admin_site.admin_view(self.import_csv_view),
                name="receiving_import_csv",
            ),
        ]
        return custom_urls + urls

    def import_csv_view(self, request):
        """Custom CSV import view for bulk receiving + stock creation."""
        if request.method == "POST":
            form = ReceivingCSVImportForm(request.POST, request.FILES)
            if form.is_valid():
                try:
                    result = self._process_csv(
                        request.FILES["csv_file"],
                        request.user,
                    )
                    messages.success(
                        request,
                        f"Import berhasil: {result['receivings']} penerimaan, "
                        f"{result['items']} item, {result['stock']} stok, "
                        f"{result['transactions']} transaksi dibuat.",
                    )
                    return redirect("..")
                except Exception as e:
                    messages.error(request, f"Import gagal: {e}")
        else:
            form = ReceivingCSVImportForm()

        return render(
            request,
            "admin/receiving/csv_import.html",
            {
                "form": form,
                "title": "Import Penerimaan dari CSV",
                "opts": self.model._meta,
            },
        )

    @transaction.atomic
    def _process_csv(self, csv_file, user):
        """Parse flat CSV and create Receiving + ReceivingItem + Stock + Transaction."""
        decoded = csv_file.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(decoded))

        # Normalize headers (strip whitespace, lowercase)
        if not reader.fieldnames:
            raise ValueError("Header CSV tidak ditemukan.")
        reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]

        required_columns = {
            "document_number",
            "receiving_date",
            "item_code",
            "sumber_dana_code",
            "location_code",
            "quantity",
        }
        missing_columns = sorted(required_columns - set(reader.fieldnames))
        if missing_columns:
            raise ValueError(
                "Kolom wajib tidak ditemukan: " + ", ".join(missing_columns)
            )

        # Group rows by document_number
        grouped = defaultdict(list)
        for row_num, row in enumerate(reader, start=2):
            row = {
                (k or "").strip(): (v or "").strip()
                for k, v in row.items()
                if k is not None
            }
            if not row.get("document_number"):
                raise ValueError(f"Baris {row_num}: document_number kosong")
            grouped[row["document_number"]].append((row_num, row))

        counts = {"receivings": 0, "items": 0, "stock": 0, "transactions": 0}

        for doc_number, rows in grouped.items():
            # Use first row for header-level data
            first_row_num, first_row = rows[0]

            receiving_date_str = first_row.get("receiving_date", "")
            if not receiving_date_str:
                raise ValueError(f"Baris {first_row_num}: receiving_date kosong")

            header_sumber_dana_code = first_row.get("sumber_dana_code", "")
            if not header_sumber_dana_code:
                raise ValueError(f"Baris {first_row_num}: sumber_dana_code kosong")

            header_location_code = first_row.get("location_code", "")
            if not header_location_code:
                raise ValueError(f"Baris {first_row_num}: location_code kosong")

            # Resolve FKs
            try:
                sumber_dana = FundingSource.objects.get(code=header_sumber_dana_code)
            except FundingSource.DoesNotExist as exc:
                raise ValueError(
                    f"Baris {first_row_num}: sumber_dana_code '{header_sumber_dana_code}' tidak ditemukan"
                ) from exc

            try:
                location = Location.objects.get(code=header_location_code)
            except Location.DoesNotExist as exc:
                raise ValueError(
                    f"Baris {first_row_num}: location_code '{header_location_code}' tidak ditemukan"
                ) from exc

            supplier = None
            supplier_code = first_row.get("supplier_code", "").strip()
            if supplier_code:
                try:
                    supplier = Supplier.objects.get(code=supplier_code)
                except Supplier.DoesNotExist as exc:
                    raise ValueError(
                        f"Baris {first_row_num}: supplier_code '{supplier_code}' tidak ditemukan"
                    ) from exc

            # Parse date
            receiving_date = self._parse_date(
                receiving_date_str,
                row_num=first_row_num,
                field_name="receiving_date",
            )

            # Create Receiving (parent)
            receiving = Receiving.objects.create(
                document_number=doc_number,
                receiving_type=first_row.get("receiving_type", "GRANT"),
                receiving_date=receiving_date,
                supplier=supplier,
                sumber_dana=sumber_dana,
                status=Receiving.Status.VERIFIED,
                created_by=user,
                verified_by=user,
                verified_at=timezone.now(),
                notes=f"Imported via CSV on {timezone.now().strftime('%Y-%m-%d %H:%M')}",
            )
            counts["receivings"] += 1

            # Create ReceivingItem + Stock + Transaction for each row
            for row_num, row in rows:
                item_code = row.get("item_code", "")
                if not item_code:
                    raise ValueError(f"Baris {row_num}: item_code kosong")
                try:
                    item = Item.objects.get(kode_barang=item_code)
                except Item.DoesNotExist as exc:
                    raise ValueError(
                        f"Baris {row_num}: item_code '{item_code}' tidak ditemukan"
                    ) from exc

                quantity = self._parse_decimal(
                    row.get("quantity", "0"),
                    row_num=row_num,
                    field_name="quantity",
                )
                unit_price = self._parse_decimal(
                    row.get("unit_price", "0"),
                    row_num=row_num,
                    field_name="unit_price",
                )
                batch_lot = row.get("batch_lot", "").strip()
                expiry_date_str = row.get("expiry_date", "").strip()

                # Auto-generate batch_lot if empty
                if not batch_lot:
                    batch_lot = f"SALDO-{row_num:04d}"

                # Default expiry_date if empty
                if expiry_date_str:
                    expiry_date = self._parse_date(
                        expiry_date_str,
                        row_num=row_num,
                        field_name="expiry_date",
                    )
                else:
                    from datetime import date

                    expiry_date = date(2099, 12, 31)

                # Row-level overrides (location/sumber_dana can vary per row)
                row_sumber_dana_code = row.get("sumber_dana_code", "").strip()
                row_location_code = row.get("location_code", "").strip()
                effective_sumber_dana_code = (
                    row_sumber_dana_code or header_sumber_dana_code
                )
                effective_location_code = row_location_code or header_location_code

                if not effective_sumber_dana_code:
                    raise ValueError(f"Baris {row_num}: sumber_dana_code kosong")
                if not effective_location_code:
                    raise ValueError(f"Baris {row_num}: location_code kosong")

                try:
                    row_sumber_dana = FundingSource.objects.get(
                        code=effective_sumber_dana_code
                    )
                except FundingSource.DoesNotExist as exc:
                    raise ValueError(
                        f"Baris {row_num}: sumber_dana_code '{effective_sumber_dana_code}' tidak ditemukan"
                    ) from exc

                try:
                    row_location = Location.objects.get(code=effective_location_code)
                except Location.DoesNotExist as exc:
                    raise ValueError(
                        f"Baris {row_num}: location_code '{effective_location_code}' tidak ditemukan"
                    ) from exc

                # ReceivingItem
                ReceivingItem.objects.create(
                    receiving=receiving,
                    item=item,
                    quantity=quantity,
                    batch_lot=batch_lot,
                    expiry_date=expiry_date,
                    unit_price=unit_price,
                    location=row_location,
                    received_by=user,
                    received_at=timezone.now(),
                )
                counts["items"] += 1

                # Stock — update or create
                stock, created = Stock.objects.get_or_create(
                    item=item,
                    location=row_location,
                    batch_lot=batch_lot,
                    sumber_dana=row_sumber_dana,
                    defaults={
                        "expiry_date": expiry_date,
                        "quantity": quantity,
                        "unit_price": unit_price,
                        "receiving_ref": receiving,
                    },
                )
                if not created:
                    stock.quantity += quantity
                    stock.save()
                counts["stock"] += 1

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
                    notes=f"Import saldo awal: {doc_number}",
                )
                counts["transactions"] += 1

        return counts

    @staticmethod
    def _parse_date(value, row_num=None, field_name="tanggal"):
        """Parse date from DD/MM/YYYY or YYYY-MM-DD format."""
        value = (value or "").strip()
        if not value:
            if row_num is not None:
                raise ValueError(f"Baris {row_num}: {field_name} kosong")
            raise ValueError(f"{field_name} kosong")

        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        if row_num is not None:
            raise ValueError(
                f"Baris {row_num}: format {field_name} tidak dikenali: '{value}'. Gunakan DD/MM/YYYY."
            )
        raise ValueError(
            f"Format {field_name} tidak dikenali: '{value}'. Gunakan DD/MM/YYYY."
        )

    @staticmethod
    def _parse_decimal(value, row_num=None, field_name="nilai"):
        """Parse decimal value, handling comma as decimal separator."""
        value = (value or "").strip().replace(",", ".").replace(" ", "")
        if not value:
            return Decimal("0")
        try:
            return Decimal(value)
        except (InvalidOperation, ValueError) as exc:
            if row_num is not None:
                raise ValueError(
                    f"Baris {row_num}: format {field_name} tidak valid: '{value}'"
                ) from exc
            raise ValueError(f"Format {field_name} tidak valid: '{value}'") from exc
