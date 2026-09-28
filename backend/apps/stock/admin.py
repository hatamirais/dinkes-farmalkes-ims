import csv
import hashlib
import io
import secrets
import unicodedata
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import F, Sum
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import path
from django.utils import timezone
from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import ForeignKeyWidget, DateWidget

from apps.core.admin_mixins import ImportGuideMixin
from apps.core.decimal_validation import PRICE_DECIMAL_PLACES, PRICE_MAX_DIGITS
from apps.core.upload_validation import validate_csv_upload
from .models import (
    OpeningBalanceImport,
    OpeningBalanceImportItem,
    SourceDocumentNumberClaim,
    Stock,
    Transaction,
    StockTransfer,
    StockTransferItem,
)
from apps.items.models import Item, Location, FundingSource
from apps.receiving.models import Receiving


OPENING_BALANCE_CSV_HEADERS = [
    "document_number",
    "effective_date",
    "sumber_dana_code",
    "location_code",
    "item_code",
    "quantity",
    "batch_lot",
    "expiry_date",
    "unit_price",
]
OPENING_BALANCE_TEXT_LIMITS = {
    "document_number": 100,
    "sumber_dana_code": 20,
    "location_code": 20,
    "item_code": 50,
    "batch_lot": 100,
}
CSV_IMPORT_MAX_SIZE_BYTES = 5 * 1024 * 1024
OPENING_BALANCE_PREVIEW_SESSION_KEY = "stock_opening_balance_import_preview_csv"
OPENING_BALANCE_MAX_PREVIEWS = 5


class OpeningBalanceCSVImportForm(forms.Form):
    csv_file = forms.FileField(
        label="File CSV",
        help_text="Format: document_number, effective_date, sumber_dana_code, "
        "location_code, item_code, quantity, batch_lot, expiry_date, unit_price",
    )

    def clean_csv_file(self):
        csv_file = self.cleaned_data.get("csv_file")
        return validate_csv_upload(
            csv_file,
            max_size_bytes=CSV_IMPORT_MAX_SIZE_BYTES,
        )


# ── Resources ──────────────────────────────────────────────


class StockResource(resources.ModelResource):
    item = fields.Field(
        column_name="item_code",
        attribute="item",
        widget=ForeignKeyWidget(Item, field="kode_barang"),
    )

    @staticmethod
    def _row_value(row, key):
        value = row.get(key, "")
        if value is None:
            return ""
        return str(value).strip()

    def before_import_row(self, row, **kwargs):
        item_code = self._row_value(row, "item_code")
        expiry_value = self._row_value(row, "expiry_date")
        if not item_code or expiry_value:
            return super().before_import_row(row, **kwargs)

        item = Item.objects.filter(kode_barang=item_code).only("requires_expiry_date").first()
        if item and item.requires_expiry_date:
            raise ValidationError(
                {"expiry_date": "Tanggal kedaluwarsa wajib diisi untuk item ini."}
            )

        return super().before_import_row(row, **kwargs)
    location = fields.Field(
        column_name="location_code",
        attribute="location",
        widget=ForeignKeyWidget(Location, field="code"),
    )
    sumber_dana = fields.Field(
        column_name="sumber_dana_code",
        attribute="sumber_dana",
        widget=ForeignKeyWidget(FundingSource, field="code"),
    )
    expiry_date = fields.Field(
        column_name="expiry_date",
        attribute="expiry_date",
        widget=DateWidget(format="%d/%m/%Y"),
    )

    class Meta:
        model = Stock
        fields = (
            "id",
            "item",
            "location",
            "batch_lot",
            "source_document_number",
            "expiry_date",
            "quantity",
            "reserved",
            "unit_price",
            "sumber_dana",
        )
        import_id_fields = (
            "item",
            "location",
            "batch_lot",
            "sumber_dana",
            "source_document_number",
        )
        skip_unchanged = True
        report_skipped = False


# ── Admin ──────────────────────────────────────────────────


@admin.register(Stock)
class StockAdmin(ImportGuideMixin, ImportExportModelAdmin):
    resource_classes = [StockResource]
    change_list_template = "admin/stock/stock_changelist.html"
    list_display = (
        "item",
        "location",
        "batch_lot",
        "source_document_number",
        "expiry_date",
        "quantity",
        "reserved",
        "unit_price",
        "sumber_dana",
    )
    list_filter = ("location", "sumber_dana", "item__kategori")
    search_fields = (
        "item__kode_barang",
        "item__nama_barang",
        "batch_lot",
        "source_document_number",
    )
    raw_id_fields = ("item", "receiving_ref")
    list_per_page = 50
    date_hierarchy = "expiry_date"
    import_guide = {
        "title": "Stok Barang",
        "description": (
            "Identifier unik: item_code + location_code + batch_lot + sumber_dana_code + source_document_number"
        ),
        "columns": [
            {
                "name": "item_code",
                "required": True,
                "description": "Kode barang (kode_barang) dari tabel Items",
            },
            {
                "name": "location_code",
                "required": True,
                "description": "Kode lokasi dari tabel Locations",
            },
            {"name": "batch_lot", "required": True, "description": "Nomor batch/lot"},
            {
                "name": "source_document_number",
                "required": False,
                "description": "Nomor dokumen sumber lapisan stok",
            },
            {
                "name": "expiry_date",
                "required": False,
                "description": "Format: DD/MM/YYYY. Kosongkan hanya untuk item tanpa kedaluwarsa.",
            },
            {
                "name": "quantity",
                "required": False,
                "description": "Jumlah stok (default: 0)",
            },
            {
                "name": "reserved",
                "required": False,
                "description": "Stok dialokasikan (default: 0)",
            },
            {
                "name": "unit_price",
                "required": False,
                "description": "Harga satuan (default: 0)",
            },
            {
                "name": "sumber_dana_code",
                "required": True,
                "description": "Kode sumber dana dari tabel Funding Sources",
            },
        ],
    }

    def has_import_permission(self, request):
        return False

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "opening-balance/export-csv-template/",
                self.admin_site.admin_view(self.export_opening_balance_template_view),
                name="stock_opening_balance_export_csv_template",
            ),
            path(
                "opening-balance/import-csv/",
                self.admin_site.admin_view(self.import_opening_balance_csv_view),
                name="stock_opening_balance_import_csv",
            ),
        ]
        return custom_urls + urls

    def _has_opening_balance_permission(self, request):
        user = request.user
        return bool(
            getattr(user, "is_superuser", False)
            or getattr(user, "role", None) == "ADMIN"
        )

    def export_opening_balance_template_view(self, request):
        if not self._has_opening_balance_permission(request):
            raise PermissionDenied

        response = HttpResponse(
            content_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="opening_balance_template.csv"'
            },
        )
        csv.writer(response).writerow(OPENING_BALANCE_CSV_HEADERS)
        return response

    def import_opening_balance_csv_view(self, request):
        if not self._has_opening_balance_permission(request):
            raise PermissionDenied

        if request.method == "POST" and request.POST.get("action") == "confirm":
            preview_token = request.POST.get("preview_token", "")
            previews = request.session.get(OPENING_BALANCE_PREVIEW_SESSION_KEY, {})
            decoded = previews.get(preview_token)
            if not decoded:
                messages.error(
                    request,
                    "Sesi pratinjau import saldo awal tidak ditemukan. Unggah ulang file CSV.",
                )
                return redirect("admin:stock_opening_balance_import_csv")
            try:
                result = self._process_opening_balance_csv(decoded, request.user)
                previews.pop(preview_token, None)
                if previews:
                    request.session[OPENING_BALANCE_PREVIEW_SESSION_KEY] = previews
                else:
                    request.session.pop(OPENING_BALANCE_PREVIEW_SESSION_KEY, None)
                request.session.modified = True
                messages.success(
                    request,
                    f"Import saldo awal berhasil: {result['imports']} dokumen baru, "
                    f"{result['items']} item, {result['stock']} stok, "
                    f"{result['transactions']} transaksi dibuat, "
                    f"{result['skipped']} baris dilewati.",
                )
                return redirect("admin:stock_openingbalanceimport_changelist")
            except (UnicodeDecodeError, csv.Error, ValueError) as exc:
                messages.error(request, f"Import saldo awal gagal: {exc}")
            except Exception:
                messages.error(
                    request,
                    "Import saldo awal gagal karena kesalahan internal.",
                )
            return redirect("admin:stock_opening_balance_import_csv")

        if request.method == "POST":
            form = OpeningBalanceCSVImportForm(request.POST, request.FILES)
            if form.is_valid():
                try:
                    decoded = self._decode_opening_balance_csv(form.cleaned_data["csv_file"])
                    validation_report = self._preflight_opening_balance_csv(decoded)
                    if validation_report["errors"]:
                        return render(
                            request,
                            "admin/stock/opening_balance_csv_import.html",
                            {
                                "form": form,
                                "validation_report": validation_report,
                                "title": "Validasi Import Saldo Awal dari CSV",
                                "opts": self.model._meta,
                            },
                        )
                    preview = self._parse_opening_balance_csv(decoded)
                    previews = request.session.get(OPENING_BALANCE_PREVIEW_SESSION_KEY, {})
                    preview_token = secrets.token_urlsafe(24)
                    previews[preview_token] = decoded
                    while len(previews) > OPENING_BALANCE_MAX_PREVIEWS:
                        previews.pop(next(iter(previews)))
                    request.session[OPENING_BALANCE_PREVIEW_SESSION_KEY] = previews
                    request.session.modified = True
                    return render(
                        request,
                        "admin/stock/opening_balance_csv_import.html",
                        {
                            "form": form,
                            "preview": preview,
                            "preview_token": preview_token,
                            "title": "Konfirmasi Import Saldo Awal dari CSV",
                            "opts": self.model._meta,
                        },
                    )
                except (UnicodeDecodeError, csv.Error, ValueError) as exc:
                    messages.error(request, f"Validasi saldo awal gagal: {exc}")
        else:
            form = OpeningBalanceCSVImportForm()

        return render(
            request,
            "admin/stock/opening_balance_csv_import.html",
            {
                "form": form,
                "title": "Import Saldo Awal dari CSV",
                "opts": self.model._meta,
            },
        )

    @staticmethod
    def _decode_opening_balance_csv(csv_file):
        return csv_file.read().decode("utf-8-sig")

    @transaction.atomic
    def _process_opening_balance_csv(self, decoded, user):
        validation_report = self._preflight_opening_balance_csv(decoded)
        if validation_report["errors"]:
            raise ValueError(
                f"CSV saldo awal memiliki {len(validation_report['errors'])} error validasi. Unggah ulang file yang sudah diperbaiki."
            )
        preview = self._parse_opening_balance_csv(decoded)
        counts = {"imports": 0, "items": 0, "stock": 0, "transactions": 0, "skipped": 0}
        existing_opening_balances = self._lock_existing_opening_balance_imports(
            preview["documents"]
        )
        new_claims = self._claim_new_opening_balance_document_numbers(
            preview["documents"],
            existing_opening_balances,
        )

        for document in preview["documents"]:
            opening_balance = existing_opening_balances.get(document["document_number"])
            source_document_number = document.get(
                "source_document_number",
                document["document_number"],
            )
            if opening_balance:
                existing_document = True
                if opening_balance.effective_date != document["effective_date"]:
                    raise ValueError(
                        f"Dokumen saldo awal '{document['document_number']}' sudah memakai effective_date "
                        f"{opening_balance.effective_date:%d/%m/%Y}."
                    )
                generated_batch_rows = [
                    str(row["row_num"])
                    for row in document["rows"]
                    if not row.get("batch_lot_was_supplied", True)
                ]
                if generated_batch_rows:
                    raise ValueError(
                        "batch_lot wajib diisi saat reimport dokumen saldo awal "
                        f"yang sudah diposting. Baris: {', '.join(generated_batch_rows)}."
                    )
            else:
                existing_document = False
                claim = new_claims[document["document_number"]]
                opening_balance = OpeningBalanceImport.objects.create(
                    document_number=document["document_number"],
                    effective_date=document["effective_date"],
                    created_by=user,
                    posted_at=timezone.now(),
                    notes=f"Imported via opening balance CSV on {timezone.now().strftime('%Y-%m-%d %H:%M')}",
                )
                claim.source_id = opening_balance.pk
                claim.save(update_fields=["source_id", "updated_at"])
                counts["imports"] += 1

            existing_import_layers = (
                self._lock_existing_opening_balance_import_layers(
                    opening_balance,
                    document,
                )
                if existing_document
                else {}
            )
            for row in document["rows"]:
                stock_key = self._opening_balance_stock_key(
                    item=row["item"],
                    location=row["location"],
                    batch_lot=row["batch_lot"],
                    source_document_number=source_document_number,
                    sumber_dana=row["funding"],
                )
                existing_import = existing_import_layers.get(stock_key)
                if existing_import:
                    if existing_import["expiry_date"] != row["expiry_date"]:
                        raise ValueError(
                            "Batch stok yang sama tidak boleh memiliki tanggal kedaluwarsa berbeda."
                        )
                    if existing_import["unit_price"] != row["unit_price"]:
                        raise ValueError(
                            "Batch stok yang sama tidak boleh memiliki harga satuan berbeda."
                        )
                    if row["quantity"] < existing_import["quantity"]:
                        raise ValueError(
                            "Quantity reimport tidak boleh lebih kecil dari total "
                            "quantity saldo awal yang sudah diposting untuk batch stok yang sama."
                        )
                    if row["quantity"] == existing_import["quantity"]:
                        counts["skipped"] += 1
                        continue
                    posting_quantity = row["quantity"] - existing_import["quantity"]
                else:
                    posting_quantity = row["quantity"]

                OpeningBalanceImportItem.objects.create(
                    opening_balance=opening_balance,
                    item=row["item"],
                    location=row["location"],
                    sumber_dana=row["funding"],
                    batch_lot=row["batch_lot"],
                    expiry_date=row["expiry_date"],
                    quantity=posting_quantity,
                    unit_price=row["unit_price"],
                )
                counts["items"] += 1

                self._increment_opening_balance_stock(
                    item=row["item"],
                    location=row["location"],
                    batch_lot=row["batch_lot"],
                    source_document_number=source_document_number,
                    sumber_dana=row["funding"],
                    expiry_date=row["expiry_date"],
                    quantity=posting_quantity,
                    unit_price=row["unit_price"],
                )
                counts["stock"] += 1

                Transaction.objects.create(
                    transaction_type=Transaction.TransactionType.IN,
                    item=row["item"],
                    location=row["location"],
                    batch_lot=row["batch_lot"],
                    quantity=posting_quantity,
                    unit_price=row["unit_price"],
                    source_document_number=source_document_number,
                    sumber_dana=row["funding"],
                    reference_type=Transaction.ReferenceType.INITIAL_IMPORT,
                    reference_id=opening_balance.pk,
                    user=user,
                    notes=f"Import saldo awal: {document['document_number']}",
                )
                counts["transactions"] += 1

        return counts

    @staticmethod
    def _lock_existing_opening_balance_imports(documents):
        document_numbers = sorted(
            {document["document_number"] for document in documents}
        )
        if not document_numbers:
            return {}

        return {
            opening_balance.document_number: opening_balance
            for opening_balance in OpeningBalanceImport.objects.select_for_update()
            .filter(document_number__in=document_numbers)
            .order_by("document_number")
        }

    @staticmethod
    def _claim_new_opening_balance_document_numbers(documents, existing_opening_balances):
        document_numbers = sorted(
            {
                document["document_number"]
                for document in documents
                if document["document_number"] not in existing_opening_balances
            }
        )
        claims = {}
        for document_number in document_numbers:
            try:
                claims[document_number] = SourceDocumentNumberClaim.objects.create(
                    document_number=document_number,
                    source_type=SourceDocumentNumberClaim.SourceType.OPENING_BALANCE,
                )
            except IntegrityError as exc:
                raise ValueError(
                    f"Nomor dokumen '{document_number}' sudah diklaim "
                    "oleh dokumen sumber stok lain."
                ) from exc
        return claims

    def _preflight_opening_balance_csv(self, decoded):
        fieldnames, rows, dialect_info = self._read_opening_balance_csv(decoded)
        errors = []
        report = {
            "delimiter": dialect_info["delimiter_label"],
            "format_label": dialect_info["format_label"],
            "total_rows": max(len(rows) - 1, 0),
            "errors": errors,
        }

        if not fieldnames:
            errors.append(
                {
                    "row_num": 1,
                    "field": "header",
                    "value": "",
                    "message": "Header CSV tidak ditemukan.",
                }
            )
            return report

        required_columns = {
            "document_number",
            "sumber_dana_code",
            "location_code",
            "item_code",
            "quantity",
        }
        if "effective_date" not in fieldnames and "receiving_date" not in fieldnames:
            required_columns.add("effective_date")
        for column in sorted(required_columns - set(fieldnames)):
            errors.append(
                {
                    "row_num": 1,
                    "field": column,
                    "value": "",
                    "message": "Kolom wajib tidak ditemukan.",
                }
            )
        if errors:
            return report

        item_cache = {
            item.kode_barang: item
            for item in Item.objects.all().only("id", "kode_barang", "requires_expiry_date")
        }
        funding_cache = {
            source.code: source
            for source in FundingSource.objects.all().only("id", "code")
        }
        location_cache = {
            location.code: location
            for location in Location.objects.all().only("id", "code")
        }
        imported_documents = {
            document["document_number"]: document
            for document in OpeningBalanceImport.objects.values(
                "id",
                "document_number",
                "effective_date",
            )
        }
        receiving_documents = set(
            Receiving.objects.values_list("document_number", flat=True)
        )
        claimed_documents = {
            claim["document_number"]: claim
            for claim in SourceDocumentNumberClaim.objects.values(
                "document_number",
                "source_type",
                "source_id",
            )
        }
        seen_doc_dates = {}
        seen_stock_rows = {}
        seen_stock_expiry = {}
        seen_stock_price = {}
        posting_date = timezone.localdate()

        def add_error(row_num, field, value, message):
            errors.append(
                {
                    "row_num": row_num,
                    "field": field,
                    "value": value,
                    "message": message,
                }
            )

        normalized_rows = []
        stock_lookup_keys = set()
        import_lookup_keys = set()
        for row_num, raw_row in rows[1:]:
            if raw_row.get(None):
                add_error(
                    row_num,
                    "row",
                    ", ".join(raw_row.get(None) or []),
                    "Jumlah kolom melebihi header CSV. Pastikan nilai yang mengandung delimiter diapit tanda kutip.",
                )

            row = {
                (key or "").strip(): self._normalize_opening_balance_text(
                    value,
                    row_num=row_num,
                    field_name=(key or "kolom"),
                )
                for key, value in raw_row.items()
                if key is not None
            }
            normalized_rows.append((row_num, row))
            item = item_cache.get(row.get("item_code", ""))
            funding = funding_cache.get(row.get("sumber_dana_code", ""))
            location = location_cache.get(row.get("location_code", ""))
            doc_number = row.get("document_number", "")
            raw_batch_lot = row.get("batch_lot", "").strip()
            imported_document = imported_documents.get(doc_number)
            if imported_document and not raw_batch_lot:
                add_error(
                    row_num,
                    "batch_lot",
                    raw_batch_lot,
                    "batch_lot wajib diisi saat reimport dokumen saldo awal yang sudah diposting.",
                )
            batch_lot = raw_batch_lot or self._generate_opening_balance_batch_lot(
                doc_number or "SALDO-AWAL",
                row_num,
            )
            if item and funding and location and doc_number:
                receiving_collision = self._has_opening_balance_receiving_collision(
                    doc_number,
                    bool(imported_document),
                    receiving_documents,
                    claimed_documents,
                )
                source_document_number = self._opening_balance_source_document_number(
                    doc_number,
                    receiving_collision,
                )
                stock_lookup_keys.add(
                    (
                        item.pk,
                        location.pk,
                        batch_lot,
                        funding.pk,
                        source_document_number,
                    )
                )
                if imported_document:
                    import_lookup_keys.add(
                        (
                            imported_document["id"],
                            item.pk,
                            location.pk,
                            batch_lot,
                            funding.pk,
                            source_document_number,
                        )
                    )

        existing_stock_by_key = {}
        if stock_lookup_keys:
            item_ids = {key[0] for key in stock_lookup_keys}
            location_ids = {key[1] for key in stock_lookup_keys}
            batch_lots = {key[2] for key in stock_lookup_keys}
            funding_ids = {key[3] for key in stock_lookup_keys}
            source_document_numbers = {key[4] for key in stock_lookup_keys}
            existing_stock_by_key = {
                (
                    stock["item_id"],
                    stock["location_id"],
                    stock["batch_lot"],
                    stock["sumber_dana_id"],
                    stock["source_document_number"],
                ): stock
                for stock in Stock.objects.filter(
                    item_id__in=item_ids,
                    location_id__in=location_ids,
                    batch_lot__in=batch_lots,
                    sumber_dana_id__in=funding_ids,
                    source_document_number__in=source_document_numbers,
                ).values(
                    "item_id",
                    "location_id",
                    "batch_lot",
                    "sumber_dana_id",
                    "source_document_number",
                    "expiry_date",
                    "unit_price",
                )
            }

        existing_import_by_key = {}
        if import_lookup_keys:
            opening_balance_ids = {key[0] for key in import_lookup_keys}
            item_ids = {key[1] for key in import_lookup_keys}
            location_ids = {key[2] for key in import_lookup_keys}
            batch_lots = {key[3] for key in import_lookup_keys}
            funding_ids = {key[4] for key in import_lookup_keys}
            source_document_numbers_by_import = {
                key[0]: key[5] for key in import_lookup_keys
            }
            for import_item in OpeningBalanceImportItem.objects.filter(
                opening_balance_id__in=opening_balance_ids,
                item_id__in=item_ids,
                location_id__in=location_ids,
                batch_lot__in=batch_lots,
                sumber_dana_id__in=funding_ids,
            ).values(
                "opening_balance_id",
                "item_id",
                "location_id",
                "batch_lot",
                "sumber_dana_id",
                "expiry_date",
                "unit_price",
                "quantity",
            ):
                key = (
                    import_item["opening_balance_id"],
                    import_item["item_id"],
                    import_item["location_id"],
                    import_item["batch_lot"],
                    import_item["sumber_dana_id"],
                    source_document_numbers_by_import[
                        import_item["opening_balance_id"]
                    ],
                )
                layer = existing_import_by_key.setdefault(
                    key,
                    {
                        "expiry_date": import_item["expiry_date"],
                        "unit_price": import_item["unit_price"],
                        "quantity": Decimal("0"),
                    },
                )
                layer["quantity"] += import_item["quantity"]

        for row_num, row in normalized_rows:

            for field_name in ("receiving_type", "supplier_code"):
                value = row.get(field_name, "")
                if value:
                    add_error(
                        row_num,
                        field_name,
                        value,
                        f"{field_name} tidak digunakan untuk import saldo awal.",
                    )

            doc_number = row.get("document_number", "")
            if not doc_number:
                add_error(row_num, "document_number", doc_number, "document_number kosong.")
            else:
                try:
                    self._validate_opening_balance_text_length(
                        doc_number,
                        "document_number",
                        row_num,
                    )
                except ValueError as exc:
                    add_error(row_num, "document_number", doc_number, str(exc))
                imported_document = imported_documents.get(doc_number)
                receiving_collision = self._has_opening_balance_receiving_collision(
                    doc_number,
                    bool(imported_document),
                    receiving_documents,
                    claimed_documents,
                )
                if doc_number in receiving_documents and not imported_document:
                    add_error(
                        row_num,
                        "document_number",
                        doc_number,
                        f"Nomor dokumen '{doc_number}' sudah digunakan oleh dokumen penerimaan. Gunakan document_number saldo awal yang berbeda.",
                    )
                claimed_document = claimed_documents.get(doc_number)
                if (
                    claimed_document
                    and claimed_document["source_type"]
                    != SourceDocumentNumberClaim.SourceType.OPENING_BALANCE
                    and not receiving_collision
                ):
                    add_error(
                        row_num,
                        "document_number",
                        doc_number,
                        f"Nomor dokumen '{doc_number}' sudah diklaim oleh dokumen sumber stok lain.",
                    )
                elif (
                    claimed_document
                    and claimed_document["source_type"]
                    == SourceDocumentNumberClaim.SourceType.OPENING_BALANCE
                    and (
                        not imported_document
                        or claimed_document["source_id"] != imported_document["id"]
                    )
                ):
                    add_error(
                        row_num,
                        "document_number",
                        doc_number,
                        f"Nomor dokumen '{doc_number}' sudah diklaim oleh dokumen sumber stok lain.",
                    )

            effective_date_str = row.get("effective_date") or row.get("receiving_date")
            effective_date = None
            if not effective_date_str:
                add_error(row_num, "effective_date", "", "effective_date kosong.")
            else:
                try:
                    effective_date = self._parse_opening_balance_date(
                        effective_date_str,
                        row_num=row_num,
                        field_name="effective_date",
                    )
                    if effective_date > posting_date:
                        add_error(
                            row_num,
                            "effective_date",
                            effective_date_str,
                            f"effective_date tidak boleh melebihi tanggal posting ({posting_date:%d/%m/%Y}).",
                        )
                    if doc_number:
                        imported_document = imported_documents.get(doc_number)
                        imported_effective_date = (
                            imported_document["effective_date"]
                            if imported_document
                            else None
                        )
                        if (
                            imported_effective_date is not None
                            and imported_effective_date != effective_date
                        ):
                            add_error(
                                row_num,
                                "effective_date",
                                effective_date_str,
                                f"effective_date harus sama dengan dokumen saldo awal yang sudah ada ({imported_effective_date:%d/%m/%Y}).",
                            )
                        first_effective_date = seen_doc_dates.setdefault(
                            doc_number,
                            effective_date,
                        )
                        if first_effective_date != effective_date:
                            add_error(
                                row_num,
                                "effective_date",
                                effective_date_str,
                                f"effective_date harus sama dengan dokumen '{doc_number}' ({first_effective_date:%d/%m/%Y}).",
                            )
                except ValueError as exc:
                    add_error(row_num, "effective_date", effective_date_str, str(exc))

            item_code = row.get("item_code", "")
            funding_code = row.get("sumber_dana_code", "")
            location_code = row.get("location_code", "")
            item = item_cache.get(item_code)
            funding = funding_cache.get(funding_code)
            location = location_cache.get(location_code)

            for field_name, value, cache, model_label in (
                ("item_code", item_code, item_cache, "item_code"),
                ("sumber_dana_code", funding_code, funding_cache, "sumber_dana_code"),
                ("location_code", location_code, location_cache, "location_code"),
            ):
                if not value:
                    add_error(row_num, field_name, value, f"{field_name} kosong.")
                else:
                    try:
                        self._validate_opening_balance_text_length(
                            value,
                            field_name,
                            row_num,
                        )
                    except ValueError as exc:
                        add_error(row_num, field_name, value, str(exc))
                    if value not in cache:
                        add_error(
                            row_num,
                            field_name,
                            value,
                            f"{model_label} '{value}' tidak ditemukan.",
                        )

            quantity = self._preflight_parse_opening_balance_decimal(
                row.get("quantity", ""),
                row_num=row_num,
                field_name="quantity",
                required=True,
                must_be_positive=True,
                max_digits=12,
                decimal_places=2,
                add_error=add_error,
            )
            unit_price = self._preflight_parse_opening_balance_decimal(
                row.get("unit_price", "0"),
                row_num=row_num,
                field_name="unit_price",
                must_be_non_negative=True,
                max_digits=PRICE_MAX_DIGITS,
                decimal_places=PRICE_DECIMAL_PLACES,
                add_error=add_error,
            )

            batch_lot = row.get("batch_lot", "").strip() or self._generate_opening_balance_batch_lot(
                doc_number or "SALDO-AWAL",
                row_num,
            )
            try:
                self._validate_opening_balance_text_length(
                    batch_lot,
                    "batch_lot",
                    row_num,
                )
            except ValueError as exc:
                add_error(row_num, "batch_lot", batch_lot, str(exc))

            expiry_date_str = row.get("expiry_date", "").strip()
            expiry_date = None
            if expiry_date_str:
                try:
                    expiry_date = self._parse_opening_balance_date(
                        expiry_date_str,
                        row_num=row_num,
                        field_name="expiry_date",
                    )
                except ValueError as exc:
                    add_error(row_num, "expiry_date", expiry_date_str, str(exc))
            elif item and item.requires_expiry_date:
                add_error(
                    row_num,
                    "expiry_date",
                    expiry_date_str,
                    f"expiry_date wajib diisi untuk item '{item.kode_barang}'.",
                )

            if item and funding and location and unit_price is not None and doc_number:
                imported_document = imported_documents.get(doc_number)
                receiving_collision = self._has_opening_balance_receiving_collision(
                    doc_number,
                    bool(imported_document),
                    receiving_documents,
                    claimed_documents,
                )
                source_document_number = self._opening_balance_source_document_number(
                    doc_number,
                    receiving_collision,
                )
                stock_key = (
                    item.pk,
                    location.pk,
                    batch_lot,
                    funding.pk,
                    source_document_number,
                )
                first_stock_row = seen_stock_rows.setdefault(stock_key, row_num)
                if first_stock_row != row_num:
                    add_error(
                        row_num,
                        "batch_lot",
                        batch_lot,
                        "Batch stok duplikat dalam CSV saldo awal. "
                        f"Gabungkan quantity dengan baris {first_stock_row} atau gunakan batch_lot/document_number berbeda.",
                    )
                    continue
                existing_expiry = seen_stock_expiry.setdefault(stock_key, expiry_date)
                if existing_expiry != expiry_date:
                    add_error(
                        row_num,
                        "expiry_date",
                        expiry_date_str,
                        "Batch stok yang sama dalam dokumen sumber yang sama tidak boleh memiliki tanggal kedaluwarsa berbeda.",
                    )
                existing_price = seen_stock_price.setdefault(stock_key, unit_price)
                if existing_price != unit_price:
                    add_error(
                        row_num,
                        "unit_price",
                        row.get("unit_price", ""),
                        "Batch stok yang sama dalam dokumen sumber yang sama tidak boleh memiliki harga satuan berbeda. Gunakan document_number berbeda untuk memisahkan lapisan harga.",
                    )
                existing_stock = existing_stock_by_key.get(stock_key)
                if existing_stock and existing_stock["expiry_date"] != expiry_date:
                    add_error(
                        row_num,
                        "expiry_date",
                        expiry_date_str,
                        "Batch stok sudah ada untuk dokumen sumber ini dengan tanggal kedaluwarsa berbeda.",
                    )
                if existing_stock and existing_stock["unit_price"] != unit_price:
                    add_error(
                        row_num,
                        "unit_price",
                        row.get("unit_price", ""),
                        "Batch stok sudah ada untuk dokumen sumber ini dengan harga satuan berbeda.",
                    )
                if imported_document and quantity is not None:
                    import_key = (
                        imported_document["id"],
                        item.pk,
                        location.pk,
                        batch_lot,
                        funding.pk,
                        source_document_number,
                    )
                    existing_import = existing_import_by_key.get(import_key)
                    if existing_import:
                        if existing_import["expiry_date"] != expiry_date:
                            add_error(
                                row_num,
                                "expiry_date",
                                expiry_date_str,
                                "Batch stok yang sama tidak boleh memiliki tanggal kedaluwarsa berbeda.",
                            )
                        if existing_import["unit_price"] != unit_price:
                            add_error(
                                row_num,
                                "unit_price",
                                row.get("unit_price", ""),
                                "Batch stok yang sama tidak boleh memiliki harga satuan berbeda.",
                            )
                        if quantity < existing_import["quantity"]:
                            add_error(
                                row_num,
                                "quantity",
                                row.get("quantity", ""),
                                "Quantity reimport tidak boleh lebih kecil dari total quantity saldo awal yang sudah diposting untuk batch stok yang sama.",
                            )

        return report

    @staticmethod
    def _preflight_parse_opening_balance_decimal(
        value,
        *,
        row_num,
        field_name,
        add_error,
        required=False,
        must_be_positive=False,
        must_be_non_negative=False,
        max_digits=None,
        decimal_places=None,
    ):
        try:
            return StockAdmin._parse_opening_balance_decimal(
                value,
                row_num=row_num,
                field_name=field_name,
                required=required,
                must_be_positive=must_be_positive,
                must_be_non_negative=must_be_non_negative,
                max_digits=max_digits,
                decimal_places=decimal_places,
            )
        except ValueError as exc:
            add_error(row_num, field_name, value, str(exc))
            return None

    def _read_opening_balance_csv(self, decoded):
        dialect_info = self._detect_opening_balance_csv_dialect(decoded)
        reader = csv.DictReader(
            io.StringIO(decoded),
            delimiter=dialect_info["delimiter"],
        )

        if not reader.fieldnames:
            return [], [], dialect_info

        reader.fieldnames = [
            self._normalize_opening_balance_text(h, row_num=1, field_name="header").lower()
            for h in reader.fieldnames
        ]
        rows = [(1, {})]
        rows.extend((row_num, row) for row_num, row in enumerate(reader, start=2))
        return reader.fieldnames, rows, dialect_info

    @staticmethod
    def _detect_opening_balance_csv_dialect(decoded):
        sample = decoded[:4096]
        first_line = sample.splitlines()[0] if sample.splitlines() else ""
        semicolon_count = first_line.count(";")
        comma_count = first_line.count(",")
        if semicolon_count > comma_count:
            delimiter = ";"
        else:
            try:
                delimiter = csv.Sniffer().sniff(sample, delimiters=",;").delimiter
            except csv.Error:
                delimiter = ","
        return {
            "delimiter": delimiter,
            "delimiter_label": "semicolon (;)" if delimiter == ";" else "comma (,)",
            "format_label": "CSV semicolon" if delimiter == ";" else "CSV comma",
        }

    def _parse_opening_balance_csv(self, decoded):
        fieldnames, rows, dialect_info = self._read_opening_balance_csv(decoded)

        if not fieldnames:
            raise ValueError("Header CSV tidak ditemukan.")

        required_columns = {
            "document_number",
            "sumber_dana_code",
            "location_code",
            "item_code",
            "quantity",
        }
        if "effective_date" not in fieldnames and "receiving_date" not in fieldnames:
            required_columns.add("effective_date")
        missing_columns = sorted(required_columns - set(fieldnames))
        if missing_columns:
            raise ValueError(
                "Kolom wajib tidak ditemukan: " + ", ".join(missing_columns)
            )

        grouped = defaultdict(list)
        for row_num, row in rows[1:]:
            if row.get(None):
                raise ValueError(
                    f"Baris {row_num}: jumlah kolom melebihi header CSV. Pastikan nilai yang mengandung delimiter diapit tanda kutip."
                )
            row = {
                (k or "").strip(): self._normalize_opening_balance_text(
                    v,
                    row_num=row_num,
                    field_name=(k or "kolom"),
                )
                for k, v in row.items()
                if k is not None
            }
            if row.get("receiving_type"):
                raise ValueError(
                    f"Baris {row_num}: receiving_type tidak digunakan untuk import saldo awal."
                )
            if row.get("supplier_code"):
                raise ValueError(
                    f"Baris {row_num}: supplier_code tidak digunakan untuk import saldo awal."
                )
            doc_number = row.get("document_number")
            if not doc_number:
                raise ValueError(f"Baris {row_num}: document_number kosong")
            self._validate_opening_balance_text_length(
                doc_number,
                "document_number",
                row_num,
            )
            grouped[doc_number].append((row_num, row))

        if not grouped:
            raise ValueError("CSV saldo awal tidak memiliki baris data.")

        preview = {
            "documents": [],
            "total_documents": 0,
            "total_rows": 0,
            "delimiter": dialect_info["delimiter_label"],
            "format_label": dialect_info["format_label"],
        }
        seen_stock_rows = {}
        seen_stock_expiry = {}
        seen_stock_price = {}
        posting_date = timezone.localdate()
        receiving_documents = set(
            Receiving.objects.values_list("document_number", flat=True)
        )
        claimed_documents = {
            claim["document_number"]: claim
            for claim in SourceDocumentNumberClaim.objects.values(
                "document_number",
                "source_type",
                "source_id",
            )
        }

        for doc_number, rows in grouped.items():
            opening_balance = OpeningBalanceImport.objects.filter(
                document_number=doc_number
            ).only("effective_date").first()
            receiving_collision = self._has_opening_balance_receiving_collision(
                doc_number,
                bool(opening_balance),
                receiving_documents,
                claimed_documents,
            )
            if doc_number in receiving_documents and not opening_balance:
                raise ValueError(
                    f"Nomor dokumen '{doc_number}' sudah digunakan oleh dokumen penerimaan. Gunakan document_number saldo awal yang berbeda."
                )
            if receiving_collision and not opening_balance:
                raise ValueError(
                    f"Nomor dokumen '{doc_number}' sudah digunakan oleh dokumen penerimaan. Gunakan document_number saldo awal yang berbeda."
                )
            existing_claim = claimed_documents.get(doc_number)
            if (
                existing_claim
                and existing_claim["source_type"]
                != SourceDocumentNumberClaim.SourceType.OPENING_BALANCE
                and not (receiving_collision and opening_balance)
            ):
                raise ValueError(
                    f"Nomor dokumen '{doc_number}' sudah diklaim oleh dokumen sumber stok lain."
                )
            if (
                existing_claim
                and existing_claim["source_type"]
                == SourceDocumentNumberClaim.SourceType.OPENING_BALANCE
                and (
                    not opening_balance
                    or existing_claim["source_id"] != opening_balance.pk
                )
            ):
                raise ValueError(
                    f"Nomor dokumen '{doc_number}' sudah diklaim oleh dokumen sumber stok lain."
                )
            source_document_number = self._opening_balance_source_document_number(
                doc_number,
                bool(receiving_collision and opening_balance),
            )

            first_row_num, first_row = rows[0]
            effective_date_str = first_row.get("effective_date") or first_row.get("receiving_date")
            if not effective_date_str:
                raise ValueError(f"Baris {first_row_num}: effective_date kosong")
            effective_date = self._parse_opening_balance_date(
                effective_date_str,
                row_num=first_row_num,
                field_name="effective_date",
            )
            if effective_date > posting_date:
                raise ValueError(
                    f"Baris {first_row_num}: effective_date tidak boleh melebihi tanggal posting ({posting_date:%d/%m/%Y})."
                )
            if opening_balance and opening_balance.effective_date != effective_date:
                raise ValueError(
                    f"Baris {first_row_num}: effective_date harus sama dengan dokumen saldo awal yang sudah ada ({opening_balance.effective_date:%d/%m/%Y})."
                )

            document = {
                "document_number": doc_number,
                "source_document_number": source_document_number,
                "effective_date": effective_date,
                "rows": [],
            }

            for row_num, row in rows:
                row_effective_date_str = row.get("effective_date") or row.get("receiving_date")
                if not row_effective_date_str:
                    raise ValueError(f"Baris {row_num}: effective_date kosong")
                row_effective_date = self._parse_opening_balance_date(
                    row_effective_date_str,
                    row_num=row_num,
                    field_name="effective_date",
                )
                if row_effective_date != effective_date:
                    raise ValueError(
                        f"Baris {row_num}: effective_date harus sama dengan dokumen '{doc_number}' ({effective_date:%d/%m/%Y})."
                    )
                item_code = row.get("item_code", "")
                funding_code = row.get("sumber_dana_code", "")
                location_code = row.get("location_code", "")
                for field_name, value in (
                    ("item_code", item_code),
                    ("sumber_dana_code", funding_code),
                    ("location_code", location_code),
                ):
                    if not value:
                        raise ValueError(f"Baris {row_num}: {field_name} kosong")
                    self._validate_opening_balance_text_length(
                        value,
                        field_name,
                        row_num,
                    )

                try:
                    item = Item.objects.get(kode_barang=item_code)
                except Item.DoesNotExist as exc:
                    raise ValueError(
                        f"Baris {row_num}: item_code '{item_code}' tidak ditemukan"
                    ) from exc
                try:
                    funding = FundingSource.objects.get(code=funding_code)
                except FundingSource.DoesNotExist as exc:
                    raise ValueError(
                        f"Baris {row_num}: sumber_dana_code '{funding_code}' tidak ditemukan"
                    ) from exc
                try:
                    location = Location.objects.get(code=location_code)
                except Location.DoesNotExist as exc:
                    raise ValueError(
                        f"Baris {row_num}: location_code '{location_code}' tidak ditemukan"
                    ) from exc

                quantity = self._parse_opening_balance_decimal(
                    row.get("quantity", ""),
                    row_num=row_num,
                    field_name="quantity",
                    required=True,
                    must_be_positive=True,
                    max_digits=12,
                    decimal_places=2,
                )
                unit_price = self._parse_opening_balance_decimal(
                    row.get("unit_price", "0"),
                    row_num=row_num,
                    field_name="unit_price",
                    must_be_non_negative=True,
                    max_digits=PRICE_MAX_DIGITS,
                    decimal_places=PRICE_DECIMAL_PLACES,
                )
                raw_batch_lot = row.get("batch_lot", "").strip()
                if opening_balance and not raw_batch_lot:
                    raise ValueError(
                        f"Baris {row_num}: batch_lot wajib diisi saat reimport dokumen saldo awal yang sudah diposting."
                    )
                batch_lot_was_supplied = bool(raw_batch_lot)
                batch_lot = raw_batch_lot or self._generate_opening_balance_batch_lot(
                    doc_number,
                    row_num,
                )
                self._validate_opening_balance_text_length(batch_lot, "batch_lot", row_num)

                expiry_date_str = row.get("expiry_date", "").strip()
                if expiry_date_str:
                    expiry_date = self._parse_opening_balance_date(
                        expiry_date_str,
                        row_num=row_num,
                        field_name="expiry_date",
                    )
                elif item.requires_expiry_date:
                    raise ValueError(
                        f"Baris {row_num}: expiry_date wajib diisi untuk item '{item.kode_barang}'."
                    )
                else:
                    expiry_date = None

                stock_key = (
                    item.pk,
                    location.pk,
                    batch_lot,
                    funding.pk,
                    source_document_number,
                )
                first_stock_row = seen_stock_rows.setdefault(stock_key, row_num)
                if first_stock_row != row_num:
                    raise ValueError(
                        f"Baris {row_num}: batch stok duplikat dalam CSV saldo awal. "
                        f"Gabungkan quantity dengan baris {first_stock_row} atau gunakan batch_lot/document_number berbeda."
                    )
                if stock_key in seen_stock_expiry and seen_stock_expiry[stock_key] != expiry_date:
                    raise ValueError(
                        f"Baris {row_num}: batch stok yang sama tidak boleh memiliki tanggal kedaluwarsa berbeda."
                    )
                seen_stock_expiry[stock_key] = expiry_date
                if stock_key in seen_stock_price and seen_stock_price[stock_key] != unit_price:
                    raise ValueError(
                        f"Baris {row_num}: batch stok yang sama tidak boleh memiliki harga satuan berbeda."
                    )
                seen_stock_price[stock_key] = unit_price
                existing_stock = Stock.objects.filter(
                    item=item,
                    location=location,
                    batch_lot=batch_lot,
                    sumber_dana=funding,
                    source_document_number=source_document_number,
                ).values("expiry_date", "unit_price").first()
                if existing_stock and existing_stock["expiry_date"] != expiry_date:
                    raise ValueError(
                        f"Baris {row_num}: batch stok sudah ada dengan tanggal kedaluwarsa berbeda."
                    )
                if existing_stock and existing_stock["unit_price"] != unit_price:
                    raise ValueError(
                        f"Baris {row_num}: batch stok sudah ada dengan harga satuan berbeda."
                    )
                existing_import = None
                if opening_balance:
                    existing_import = (
                        OpeningBalanceImportItem.objects.filter(
                            opening_balance=opening_balance,
                            item=item,
                            location=location,
                            batch_lot=batch_lot,
                            sumber_dana=funding,
                        )
                        .order_by("expiry_date", "unit_price")
                        .values("expiry_date", "unit_price")
                        .annotate(quantity=Sum("quantity"))
                        .first()
                    )
                quantity_delta = quantity
                is_existing = False
                if existing_import:
                    if existing_import["expiry_date"] != expiry_date:
                        raise ValueError(
                            f"Baris {row_num}: batch stok yang sama tidak boleh memiliki tanggal kedaluwarsa berbeda."
                        )
                    if existing_import["unit_price"] != unit_price:
                        raise ValueError(
                            f"Baris {row_num}: batch stok yang sama tidak boleh memiliki harga satuan berbeda."
                        )
                    if quantity < existing_import["quantity"]:
                        raise ValueError(
                            f"Baris {row_num}: quantity reimport tidak boleh lebih kecil dari total quantity saldo awal yang sudah diposting untuk batch stok yang sama."
                        )
                    quantity_delta = quantity - existing_import["quantity"]
                    is_existing = quantity_delta == 0

                document["rows"].append(
                    {
                        "row_num": row_num,
                        "document_number": doc_number,
                        "effective_date": effective_date,
                        "item_code": item.kode_barang,
                        "item_name": item.nama_barang,
                        "item": item,
                        "location_code": location.code,
                        "location_name": location.name,
                        "location": location,
                        "funding_code": funding.code,
                        "funding_name": funding.name,
                        "funding": funding,
                        "batch_lot": batch_lot,
                        "batch_lot_was_supplied": batch_lot_was_supplied,
                        "expiry_date": expiry_date,
                        "quantity": quantity,
                        "quantity_delta": quantity_delta,
                        "unit_price": unit_price,
                        "is_existing": is_existing,
                    }
                )

            preview["documents"].append(document)
            preview["total_rows"] += len(document["rows"])

        preview["total_documents"] = len(preview["documents"])
        return preview

    @staticmethod
    def _opening_balance_stock_key(
        *,
        item,
        location,
        batch_lot,
        source_document_number,
        sumber_dana,
    ):
        return (
            item.pk,
            location.pk,
            batch_lot,
            sumber_dana.pk,
            source_document_number,
        )

    @staticmethod
    def _lock_existing_opening_balance_import_layers(opening_balance, document):
        stock_keys = {
            StockAdmin._opening_balance_stock_key(
                item=row["item"],
                location=row["location"],
                batch_lot=row["batch_lot"],
                source_document_number=document.get(
                    "source_document_number",
                    document["document_number"],
                ),
                sumber_dana=row["funding"],
            )
            for row in document["rows"]
        }
        if not stock_keys:
            return {}

        item_ids = {key[0] for key in stock_keys}
        location_ids = {key[1] for key in stock_keys}
        batch_lots = {key[2] for key in stock_keys}
        funding_ids = {key[3] for key in stock_keys}
        source_document_number = document.get(
            "source_document_number",
            document["document_number"],
        )
        existing_layers = {}
        for import_item in (
            OpeningBalanceImportItem.objects.select_for_update()
            .filter(
                opening_balance=opening_balance,
                item_id__in=item_ids,
                location_id__in=location_ids,
                batch_lot__in=batch_lots,
                sumber_dana_id__in=funding_ids,
            )
            .values(
                "item_id",
                "location_id",
                "batch_lot",
                "sumber_dana_id",
                "expiry_date",
                "unit_price",
                "quantity",
            )
        ):
            key = (
                import_item["item_id"],
                import_item["location_id"],
                import_item["batch_lot"],
                import_item["sumber_dana_id"],
                source_document_number,
            )
            layer = existing_layers.setdefault(
                key,
                {
                    "expiry_date": import_item["expiry_date"],
                    "unit_price": import_item["unit_price"],
                    "quantity": Decimal("0"),
                },
            )
            if layer["expiry_date"] != import_item["expiry_date"]:
                raise ValueError(
                    "Batch stok yang sama tidak boleh memiliki tanggal kedaluwarsa berbeda."
                )
            if layer["unit_price"] != import_item["unit_price"]:
                raise ValueError(
                    "Batch stok yang sama tidak boleh memiliki harga satuan berbeda."
                )
            layer["quantity"] += import_item["quantity"]
        return existing_layers

    @staticmethod
    def _opening_balance_stock_exists(
        *,
        item,
        location,
        batch_lot,
        source_document_number,
        sumber_dana,
        expiry_date,
        unit_price,
        lock=False,
    ):
        stock_filters = {
            "item": item,
            "location": location,
            "batch_lot": batch_lot,
            "sumber_dana": sumber_dana,
            "source_document_number": source_document_number,
        }
        queryset = Stock.objects.filter(**stock_filters)
        if lock:
            queryset = queryset.select_for_update()
        existing_stock = queryset.values("expiry_date", "unit_price").first()
        if existing_stock and existing_stock["expiry_date"] != expiry_date:
            raise ValueError(
                "Batch stok yang sama tidak boleh memiliki tanggal kedaluwarsa berbeda."
            )
        if existing_stock and existing_stock.get("unit_price") != unit_price:
            raise ValueError(
                "Batch stok yang sama tidak boleh memiliki harga satuan berbeda."
            )
        return bool(existing_stock)

    @staticmethod
    def _increment_opening_balance_stock(
        *,
        item,
        location,
        batch_lot,
        source_document_number,
        sumber_dana,
        expiry_date,
        quantity,
        unit_price,
    ):
        stock_filters = {
            "item": item,
            "location": location,
            "batch_lot": batch_lot,
            "sumber_dana": sumber_dana,
            "source_document_number": source_document_number,
        }
        StockAdmin._opening_balance_stock_exists(
            item=item,
            location=location,
            batch_lot=batch_lot,
            source_document_number=source_document_number,
            sumber_dana=sumber_dana,
            expiry_date=expiry_date,
            unit_price=unit_price,
        )

        update_filters = {
            **stock_filters,
            "expiry_date": expiry_date,
            "unit_price": unit_price,
        }
        updated = Stock.objects.filter(**update_filters).update(
            quantity=F("quantity") + quantity,
            receiving_ref=None,
            updated_at=timezone.now(),
        )
        if updated:
            return

        try:
            with transaction.atomic():
                Stock.objects.create(
                    item=item,
                    location=location,
                    batch_lot=batch_lot,
                    source_document_number=source_document_number,
                    sumber_dana=sumber_dana,
                    expiry_date=expiry_date,
                    quantity=quantity,
                    unit_price=unit_price,
                    receiving_ref=None,
                )
        except IntegrityError as exc:
            existing_stock = Stock.objects.filter(**stock_filters).values(
                "expiry_date",
                "unit_price",
            ).first()
            if existing_stock and existing_stock["expiry_date"] != expiry_date:
                raise ValueError(
                    "Batch stok yang sama tidak boleh memiliki tanggal kedaluwarsa berbeda."
                ) from exc
            if existing_stock and existing_stock.get("unit_price") != unit_price:
                raise ValueError(
                    "Batch stok yang sama tidak boleh memiliki harga satuan berbeda."
                ) from exc
            updated = Stock.objects.filter(**update_filters).update(
                quantity=F("quantity") + quantity,
                receiving_ref=None,
                updated_at=timezone.now(),
            )
            if not updated:
                raise

    @staticmethod
    def _normalize_opening_balance_text(value, *, row_num, field_name):
        normalized = unicodedata.normalize("NFC", str(value or "")).strip()
        if "\x00" in normalized:
            raise ValueError(
                f"Baris {row_num}: {field_name} mengandung null byte yang tidak diizinkan"
            )
        return normalized

    @staticmethod
    def _validate_opening_balance_text_length(value, field_name, row_num):
        max_length = OPENING_BALANCE_TEXT_LIMITS.get(field_name)
        if max_length is not None and len(value) > max_length:
            raise ValueError(
                f"Baris {row_num}: {field_name} maksimal {max_length} karakter"
            )

    @staticmethod
    def _generate_opening_balance_batch_lot(document_number, row_num):
        document_hash = hashlib.sha1(document_number.encode("utf-8")).hexdigest()[:12]
        return f"SALDO-{document_hash}-{row_num:04d}"

    @staticmethod
    def _opening_balance_source_document_number(document_number, has_receiving_collision):
        if not has_receiving_collision:
            return document_number
        digest = hashlib.sha1(
            f"INITIAL_IMPORT:{document_number}".encode("utf-8")
        ).hexdigest()[:8]
        suffix_length = 100 - len("OBI") - len(digest) - 2
        return f"OBI-{digest}-{document_number[:suffix_length]}"

    @staticmethod
    def _has_opening_balance_receiving_collision(
        document_number,
        opening_balance_exists,
        receiving_documents,
        claimed_documents,
    ):
        if not opening_balance_exists:
            return False
        if document_number in receiving_documents:
            return True
        raw_claim = claimed_documents.get(document_number)
        if (
            raw_claim
            and raw_claim["source_type"]
            == SourceDocumentNumberClaim.SourceType.RECEIVING
        ):
            return True
        return False

    @staticmethod
    def _parse_opening_balance_date(value, row_num=None, field_name="tanggal"):
        value = (value or "").strip()
        formats = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y")
        for date_format in formats:
            try:
                parsed = timezone.datetime.strptime(value, date_format).date()
                if not 1000 <= parsed.year <= 9999:
                    raise ValueError
                return parsed
            except ValueError:
                continue
        prefix = f"Baris {row_num}: " if row_num is not None else ""
        raise ValueError(
            f"{prefix}{field_name} '{value}' tidak valid. Gunakan DD/MM/YYYY atau YYYY-MM-DD."
        )

    @staticmethod
    def _parse_opening_balance_decimal(
        value,
        *,
        row_num,
        field_name,
        required=False,
        must_be_positive=False,
        must_be_non_negative=False,
        max_digits=None,
        decimal_places=None,
    ):
        raw_value = str(value or "").strip()
        if not raw_value:
            if required:
                raise ValueError(f"Baris {row_num}: {field_name} kosong")
            return Decimal("0")
        try:
            parsed = Decimal(raw_value.replace(",", "."))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(
                f"Baris {row_num}: {field_name} '{raw_value}' tidak valid"
            ) from exc
        if not parsed.is_finite():
            raise ValueError(f"Baris {row_num}: {field_name} harus bilangan finite")
        if must_be_positive and parsed <= 0:
            raise ValueError(f"Baris {row_num}: {field_name} harus lebih dari 0")
        if must_be_non_negative and parsed < 0:
            raise ValueError(f"Baris {row_num}: {field_name} tidak boleh negatif")
        if max_digits is not None and decimal_places is not None:
            StockAdmin._validate_opening_balance_decimal_precision(
                parsed,
                row_num=row_num,
                field_name=field_name,
                max_digits=max_digits,
                decimal_places=decimal_places,
            )
        return parsed

    @staticmethod
    def _validate_opening_balance_decimal_precision(
        value,
        *,
        row_num,
        field_name,
        max_digits,
        decimal_places,
    ):
        exponent = value.as_tuple().exponent
        actual_decimal_places = max(-exponent, 0)
        whole_digits = max(value.adjusted() + 1, 0) if value else 1
        max_whole_digits = max_digits - decimal_places
        if actual_decimal_places > decimal_places or whole_digits > max_whole_digits:
            raise ValueError(
                f"Baris {row_num}: {field_name} maksimal {max_digits} digit dan {decimal_places} angka desimal"
            )


class OpeningBalanceImportItemInline(admin.TabularInline):
    model = OpeningBalanceImportItem
    extra = 0
    can_delete = False
    readonly_fields = (
        "item",
        "location",
        "sumber_dana",
        "batch_lot",
        "expiry_date",
        "quantity",
        "unit_price",
        "created_at",
    )

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(OpeningBalanceImport)
class OpeningBalanceImportAdmin(admin.ModelAdmin):
    change_list_template = "admin/stock/stock_changelist.html"
    list_display = ("document_number", "effective_date", "created_by", "posted_at")
    search_fields = ("document_number", "notes")
    date_hierarchy = "effective_date"
    readonly_fields = ("document_number", "effective_date", "created_by", "posted_at", "notes")
    inlines = [OpeningBalanceImportItemInline]

    @staticmethod
    def _has_opening_balance_permission(request):
        user = request.user
        return bool(
            getattr(user, "is_superuser", False)
            or getattr(user, "role", None) == "ADMIN"
        )

    def has_module_permission(self, request):
        return self._has_opening_balance_permission(request)

    def has_view_permission(self, request, obj=None):
        return self._has_opening_balance_permission(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    """Transactions are immutable — no import/export."""

    list_display = (
        "transaction_type",
        "item",
        "batch_lot",
        "quantity",
        "reference_type",
        "user",
        "created_at",
    )
    list_filter = ("transaction_type", "reference_type", "location")
    search_fields = ("item__kode_barang", "item__nama_barang", "batch_lot", "notes")
    date_hierarchy = "created_at"
    list_per_page = 50

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class StockTransferItemInline(admin.TabularInline):
    model = StockTransferItem
    extra = 0
    autocomplete_fields = ("stock", "item")

    def _parent_is_draft(self, obj):
        return obj is None or obj.status == StockTransfer.Status.DRAFT

    def has_add_permission(self, request, obj=None):
        return super().has_add_permission(request, obj) and self._parent_is_draft(obj)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and self._parent_is_draft(obj)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and self._parent_is_draft(obj)


@admin.register(StockTransfer)
class StockTransferAdmin(admin.ModelAdmin):
    list_display = (
        "document_number",
        "transfer_date",
        "source_location",
        "destination_location",
        "status",
        "created_by",
    )
    list_filter = ("status", "source_location", "destination_location")
    search_fields = (
        "document_number",
        "source_location__name",
        "destination_location__name",
    )
    inlines = [StockTransferItemInline]
    readonly_fields = ("document_number", "status", "completed_by", "completed_at")
    actions = []

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.status != StockTransfer.Status.DRAFT:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status != StockTransfer.Status.DRAFT:
            return False
        return super().has_delete_permission(request, obj)
