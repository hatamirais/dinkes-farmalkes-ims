from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.expired.forms import ExpiredItemForm
from apps.expired.models import Expired, ExpiredItem
from apps.expired.services import build_expired_audit_report
from apps.items.models import Category, FundingSource, Item, Location, Unit
from apps.stock.models import Stock, Transaction
from apps.users.access import ensure_default_module_access
from apps.users.models import ModuleAccess, User


class ExpiredWorkflowTest(TestCase):
    """Tests for the expired module workflow transitions, stock posting, and edge cases."""

    def setUp(self):
        self.user = User.objects.create_superuser(
            username="gudang_expired",
            password="secret12345",
        )
        self.kepala_user = User.objects.create_user(
            username="kepala_instalasi",
            password="secret12345",
            role=User.Role.KEPALA,
            full_name="Kepala Instalasi",
            nip="1212121212",
            is_active=True,
        )

        self.unit = Unit.objects.create(code="BOT", name="Botol")
        self.category = Category.objects.create(
            code="SYRUP", name="Sirup", sort_order=1
        )
        self.item = Item.objects.create(
            nama_barang="Sirup Cough 60ml",
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal("0"),
        )
        self.location = Location.objects.create(code="LOC-02", name="Gudang Farmasi")
        self.funding_source = FundingSource.objects.create(
            code="APBD", name="Anggaran APBD"
        )

        self.stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="BATCH-EXP-01",
            expiry_date="2026-01-01",
            quantity=Decimal("50"),
            reserved=Decimal("0"),
            unit_price=Decimal("2500"),
            sumber_dana=self.funding_source,
        )

        self.client.force_login(self.user)

    def _create_expired(
        self, status=Expired.Status.DRAFT, with_items=True, document_number=""
    ):
        """Helper to create an expired document with optional items."""
        kwargs = {
            "report_date": "2026-03-10",
            "status": status,
            "created_by": self.user,
        }
        if document_number:
            kwargs["document_number"] = document_number
        expired_doc = Expired.objects.create(**kwargs)
        if with_items:
            ExpiredItem.objects.create(
                expired=expired_doc,
                item=self.item,
                stock=self.stock,
                quantity=Decimal("5"),
                notes="Melewati tanggal ED",
            )
        return expired_doc

    # --- Auto-generated document number ---

    def test_auto_generated_document_number(self):
        expired_doc = self._create_expired()
        self.assertTrue(expired_doc.document_number.startswith("EXP-"))
        now_prefix = timezone.now().strftime("%Y%m")
        self.assertIn(now_prefix, expired_doc.document_number)

    def test_custom_document_number_preserved(self):
        expired_doc = self._create_expired(document_number="CUSTOM-EXP-001")
        self.assertEqual(expired_doc.document_number, "CUSTOM-EXP-001")

    # --- Submit workflow ---

    def test_submit_draft_to_submitted(self):
        expired_doc = self._create_expired(status=Expired.Status.DRAFT)
        response = self.client.post(
            reverse("expired:expired_submit", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)
        expired_doc.refresh_from_db()
        self.assertEqual(expired_doc.status, Expired.Status.SUBMITTED)

    def test_submit_requires_items(self):
        expired_doc = self._create_expired(
            status=Expired.Status.DRAFT, with_items=False
        )
        response = self.client.post(
            reverse("expired:expired_submit", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)
        expired_doc.refresh_from_db()
        self.assertEqual(expired_doc.status, Expired.Status.DRAFT)  # unchanged

    def test_submit_only_from_draft(self):
        expired_doc = self._create_expired(status=Expired.Status.SUBMITTED)
        response = self.client.post(
            reverse("expired:expired_submit", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)
        expired_doc.refresh_from_db()
        self.assertEqual(expired_doc.status, Expired.Status.SUBMITTED)  # unchanged

    # --- Verify workflow (stock deduction + transaction) ---

    def test_verify_deducts_stock_and_creates_transaction(self):
        expired_doc = self._create_expired(status=Expired.Status.SUBMITTED)
        response = self.client.post(
            reverse("expired:expired_verify", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)

        expired_doc.refresh_from_db()
        self.stock.refresh_from_db()

        self.assertEqual(expired_doc.status, Expired.Status.VERIFIED)
        self.assertEqual(expired_doc.verified_by, self.user)
        self.assertIsNotNone(expired_doc.verified_at)
        self.assertEqual(self.stock.quantity, Decimal("45"))  # 50 - 5

        txn = Transaction.objects.get(
            reference_type=Transaction.ReferenceType.EXPIRED,
            reference_id=expired_doc.id,
        )
        self.assertEqual(txn.transaction_type, Transaction.TransactionType.OUT)
        self.assertEqual(txn.quantity, Decimal("5"))
        self.assertEqual(txn.item, self.item)

    def test_verify_insufficient_stock_fails(self):
        self.stock.quantity = Decimal("3")
        self.stock.save()
        expired_doc = self._create_expired(status=Expired.Status.SUBMITTED)
        response = self.client.post(
            reverse("expired:expired_verify", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)
        expired_doc.refresh_from_db()
        self.assertEqual(expired_doc.status, Expired.Status.SUBMITTED)  # unchanged
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal("3"))  # unchanged

    def test_verify_only_from_submitted(self):
        expired_doc = self._create_expired(status=Expired.Status.DRAFT)
        response = self.client.post(
            reverse("expired:expired_verify", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)
        expired_doc.refresh_from_db()
        self.assertEqual(expired_doc.status, Expired.Status.DRAFT)  # unchanged

    # --- Dispose workflow ---

    def test_dispose_verified_to_disposed(self):
        expired_doc = self._create_expired(status=Expired.Status.VERIFIED)
        expired_doc.verified_by = self.user
        expired_doc.verified_at = timezone.now()
        expired_doc.save()

        response = self.client.post(
            reverse("expired:expired_dispose", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)
        expired_doc.refresh_from_db()
        self.assertEqual(expired_doc.status, Expired.Status.DISPOSED)
        self.assertEqual(expired_doc.disposed_by, self.user)
        self.assertIsNotNone(expired_doc.disposed_at)

    def test_dispose_only_from_verified(self):
        expired_doc = self._create_expired(status=Expired.Status.SUBMITTED)
        response = self.client.post(
            reverse("expired:expired_dispose", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)
        expired_doc.refresh_from_db()
        self.assertEqual(expired_doc.status, Expired.Status.SUBMITTED)  # unchanged

    def test_reset_to_draft_from_submitted(self):
        expired_doc = self._create_expired(status=Expired.Status.SUBMITTED)
        response = self.client.post(
            reverse("expired:expired_reset_to_draft", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)
        expired_doc.refresh_from_db()
        self.assertEqual(expired_doc.status, Expired.Status.DRAFT)

    def test_reset_to_draft_blocked_for_verified(self):
        expired_doc = self._create_expired(status=Expired.Status.VERIFIED)
        response = self.client.post(
            reverse("expired:expired_reset_to_draft", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)
        expired_doc.refresh_from_db()
        self.assertEqual(expired_doc.status, Expired.Status.VERIFIED)

    def test_step_back_disposed_to_verified(self):
        expired_doc = self._create_expired(status=Expired.Status.DISPOSED)
        expired_doc.disposed_by = self.user
        expired_doc.disposed_at = timezone.now()
        expired_doc.save(update_fields=["disposed_by", "disposed_at", "updated_at"])

        response = self.client.post(
            reverse("expired:expired_step_back", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)
        expired_doc.refresh_from_db()
        self.assertEqual(expired_doc.status, Expired.Status.VERIFIED)
        self.assertIsNone(expired_doc.disposed_by)
        self.assertIsNone(expired_doc.disposed_at)

    def test_step_back_blocked_for_verified(self):
        expired_doc = self._create_expired(status=Expired.Status.VERIFIED)
        response = self.client.post(
            reverse("expired:expired_step_back", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)
        expired_doc.refresh_from_db()
        self.assertEqual(expired_doc.status, Expired.Status.VERIFIED)

    # --- Edit access ---

    def test_edit_allowed_for_draft(self):
        expired_doc = self._create_expired(status=Expired.Status.DRAFT)
        response = self.client.get(
            reverse("expired:expired_edit", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_edit_allowed_for_submitted(self):
        expired_doc = self._create_expired(status=Expired.Status.SUBMITTED)
        response = self.client.get(
            reverse("expired:expired_edit", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_edit_blocked_for_verified(self):
        expired_doc = self._create_expired(status=Expired.Status.VERIFIED)
        response = self.client.get(
            reverse("expired:expired_edit", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)  # redirect with error

    def test_edit_blocked_for_disposed(self):
        expired_doc = self._create_expired(status=Expired.Status.DISPOSED)
        response = self.client.get(
            reverse("expired:expired_edit", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)  # redirect with error

    # --- Delete ---

    def test_delete_draft_expired(self):
        expired_doc = self._create_expired(status=Expired.Status.DRAFT)
        pk = expired_doc.pk
        response = self.client.post(reverse("expired:expired_delete", args=[pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Expired.objects.filter(pk=pk).exists())

    def test_delete_blocked_for_submitted(self):
        expired_doc = self._create_expired(status=Expired.Status.SUBMITTED)
        response = self.client.post(
            reverse("expired:expired_delete", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Expired.objects.filter(pk=expired_doc.pk).exists()
        )  # still exists

    def test_gudang_cannot_verify_expired(self):
        expired_doc = self._create_expired(status=Expired.Status.SUBMITTED)
        gudang = User.objects.create_user(
            username="gudang_only_exp",
            password="secret12345",
            role=User.Role.GUDANG,
        )
        ensure_default_module_access(gudang, overwrite=True)
        self.client.force_login(gudang)

        response = self.client.post(
            reverse("expired:expired_verify", args=[expired_doc.pk])
        )
        self.assertEqual(response.status_code, 403)

    # --- Pending quantity handling ---

    def test_expired_create_prefills_only_remaining_quantity_after_submitted_docs(self):
        self._create_expired(status=Expired.Status.SUBMITTED)

        response = self.client.get(
            reverse("expired:expired_create") + f"?stocks={self.stock.pk}"
        )

        self.assertEqual(response.status_code, 200)
        formset = response.context["formset"]
        self.assertEqual(formset.forms[0].initial["quantity"], Decimal("45"))

    def test_expired_create_prefills_one_form_per_selected_stock(self):
        other_item = Item.objects.create(
            nama_barang="Paracetamol 500mg",
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal("0"),
        )
        third_item = Item.objects.create(
            nama_barang="Vitamin C 100mg",
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal("0"),
        )
        other_stock = Stock.objects.create(
            item=other_item,
            location=self.location,
            batch_lot="BATCH-EXP-02",
            expiry_date="2026-02-01",
            quantity=Decimal("25"),
            reserved=Decimal("0"),
            unit_price=Decimal("1500"),
            sumber_dana=self.funding_source,
        )
        third_stock = Stock.objects.create(
            item=third_item,
            location=self.location,
            batch_lot="BATCH-EXP-03",
            expiry_date="2026-03-01",
            quantity=Decimal("10"),
            reserved=Decimal("0"),
            unit_price=Decimal("500"),
            sumber_dana=self.funding_source,
        )

        response = self.client.get(
            reverse("expired:expired_create")
            + f"?stocks={self.stock.pk},{other_stock.pk},{third_stock.pk}"
        )

        self.assertEqual(response.status_code, 200)
        formset = response.context["formset"]
        self.assertEqual(formset.total_form_count(), 3)
        self.assertEqual(len(formset.forms), 3)

        initial_by_stock = {
            form.initial["stock"]: {
                "item": form.initial["item"],
                "quantity": form.initial["quantity"],
            }
            for form in formset.forms
        }
        self.assertEqual(
            initial_by_stock,
            {
                self.stock.pk: {
                    "item": self.item.pk,
                    "quantity": Decimal("50"),
                },
                other_stock.pk: {
                    "item": other_item.pk,
                    "quantity": Decimal("25"),
                },
                third_stock.pk: {
                    "item": third_item.pk,
                    "quantity": Decimal("10"),
                },
            },
        )

    def test_expired_create_rejects_quantity_reserved_by_other_submitted_docs(self):
        self._create_expired(status=Expired.Status.SUBMITTED)

        response = self.client.post(
            reverse("expired:expired_create"),
            {
                "document_number": "",
                "report_date": "2026-03-15",
                "notes": "Dokumen baru",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-item": str(self.item.pk),
                "items-0-stock": str(self.stock.pk),
                "items-0-quantity": "46",
                "items-0-notes": "Perlu diproses",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Expired.objects.count(), 1)
        error_message = response.context["formset"].forms[0].errors["quantity"][0]
        self.assertIn(
            "Jumlah melebihi stok yang masih bisa diproses.", error_message
        )
        self.assertIn(
            "dokumen kedaluwarsa yang masih diajukan sebanyak", error_message
        )

    def test_expired_item_form_uses_picker_label_without_suffixes(self):
        self.item.nama_barang = "Sirup Cough 60ml [P]"
        self.item.save(update_fields=["nama_barang", "updated_at"])

        form = ExpiredItemForm()

        self.assertEqual(form.fields["item"].label_from_instance(self.item), "Sirup Cough 60ml")

    def test_expired_create_includes_item_picker_table_script(self):
        response = self.client.get(reverse("expired:expired_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "js/item-picker-table.js?v=")

    def test_build_expired_audit_report_includes_destroy_rows_only(self):
        out_transaction = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.item,
            location=self.location,
            batch_lot=self.stock.batch_lot,
            quantity=Decimal("7"),
            unit_price=self.stock.unit_price,
            sumber_dana=self.funding_source,
            reference_type=Transaction.ReferenceType.DISTRIBUTION,
            reference_id=999,
            user=self.user,
            notes="Distribusi darurat",
        )
        Transaction.objects.filter(pk=out_transaction.pk).update(
            created_at=timezone.make_aware(timezone.datetime(2026, 3, 15, 8, 0, 0))
        )

        expired_doc = self._create_expired(status=Expired.Status.DISPOSED)
        expired_doc.verified_by = self.user
        expired_doc.verified_at = timezone.make_aware(timezone.datetime(2026, 3, 16, 9, 0, 0))
        expired_doc.disposed_by = self.user
        expired_doc.disposed_at = timezone.make_aware(timezone.datetime(2026, 3, 17, 10, 0, 0))
        expired_doc.save(update_fields=["verified_by", "verified_at", "disposed_by", "disposed_at", "updated_at"])

        report = build_expired_audit_report(
            {
                "start_date": timezone.datetime(2026, 3, 1).date(),
                "end_date": timezone.datetime(2026, 3, 31).date(),
                "date_field": "disposed_at",
                "location": self.location,
                "item": self.item,
                "outcome_type": "BOTH",
                "funding_source": self.funding_source,
            }
        )

        self.assertEqual(len(report["rows"]), 1)
        self.assertEqual(report["totals_by_outcome"]["DESTROY"], Decimal("5"))
        self.assertEqual(report["totals_value_by_outcome"]["DESTROY"], Decimal("12500"))
        self.assertEqual(len(report["summary_rows"]), 1)
        self.assertFalse(report["reconciliation_notes"])
        self.assertEqual(report["rows"][0]["document_type"], "Expired/Disposal")
        self.assertEqual(report["rows"][0]["unit_price"], Decimal("2500"))
        self.assertEqual(report["rows"][0]["total_price"], Decimal("12500"))
        self.assertEqual(report["summary_rows"][0]["destroy_total_value"], Decimal("12500"))

    def test_expired_audit_report_csv_endpoint_returns_destroy_rows_only(self):
        out_transaction = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.item,
            location=self.location,
            batch_lot=self.stock.batch_lot,
            quantity=Decimal("4"),
            unit_price=self.stock.unit_price,
            sumber_dana=self.funding_source,
            reference_type=Transaction.ReferenceType.DISTRIBUTION,
            reference_id=777,
            user=self.user,
            notes="Distribusi uji",
        )
        Transaction.objects.filter(pk=out_transaction.pk).update(
            created_at=timezone.make_aware(timezone.datetime(2026, 3, 12, 8, 0, 0))
        )
        expired_doc = self._create_expired(status=Expired.Status.DISPOSED)
        expired_doc.disposed_by = self.user
        expired_doc.disposed_at = timezone.make_aware(timezone.datetime(2026, 3, 18, 9, 0, 0))
        expired_doc.save(update_fields=["disposed_by", "disposed_at", "updated_at"])

        response = self.client.get(
            reverse("expired:expired_audit_report"),
            {
                "start_date": "2026-03-01",
                "end_date": "2026-03-31",
                "date_field": "disposed_at",
                "outcome_type": "BOTH",
                "location": str(self.location.pk),
                "item": str(self.item.pk),
                "funding_source": str(self.funding_source.pk),
                "format": "csv",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        csv_output = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("Outcome Type", csv_output)
        self.assertIn("DESTROY", csv_output)
        self.assertIn(self.item.nama_barang, csv_output)
        self.assertIn("Unit Price", csv_output)
        self.assertIn("Total Price", csv_output)
        self.assertNotIn("Distribusi uji", csv_output)

    def test_expired_audit_report_csv_neutralizes_formula_prefixed_values(self):
        expired_doc = self._create_expired(status=Expired.Status.DISPOSED)
        expired_doc.disposed_by = self.user
        expired_doc.disposed_at = timezone.make_aware(timezone.datetime(2026, 3, 18, 9, 0, 0))
        expired_doc.save(update_fields=["disposed_by", "disposed_at", "updated_at"])
        expired_doc.items.update(notes="=hapus-semua")

        response = self.client.get(
            reverse("expired:expired_audit_report"),
            {
                "start_date": "2026-03-01",
                "end_date": "2026-03-31",
                "date_field": "disposed_at",
                "outcome_type": "BOTH",
                "location": str(self.location.pk),
                "item": str(self.item.pk),
                "funding_source": str(self.funding_source.pk),
                "format": "csv",
            },
        )

        self.assertEqual(response.status_code, 200)
        csv_output = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("'=hapus-semua", csv_output)

    def test_expired_audit_report_print_endpoint_returns_printable_html(self):
        response = self.client.get(
            reverse("expired:expired_audit_report"),
            {
                "start_date": "2026-03-01",
                "end_date": "2026-03-31",
                "date_field": "disposed_at",
                "outcome_type": "BOTH",
                "format": "print",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Expired Audit Report")
        self.assertContains(response, 'data-action="print"')
        self.assertContains(response, "Harga Satuan")
        self.assertContains(response, "<th>Satuan</th>", html=True)
        self.assertContains(response, "Total Nilai Barang di Musnahkan")
        self.assertContains(response, self.user.username)
        self.assertContains(response, "Kepala Instalasi")
        self.assertContains(response, self.kepala_user.nip)
        self.assertNotContains(response, "<th>User</th>", html=True)
        self.assertNotContains(response, "<th>Ref Item</th>", html=True)
        self.assertNotContains(
            response,
            "generated_by.get_full_name|default:generated_by.username|default:generated_by",
        )

    def test_expired_audit_report_print_empty_state_uses_current_column_count(self):
        response = self.client.get(
            reverse("expired:expired_audit_report"),
            {
                "start_date": "2027-03-01",
                "end_date": "2027-03-31",
                "date_field": "disposed_at",
                "format": "print",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<td colspan="12">Tidak ada data untuk filter yang dipilih.</td>',
            html=True,
        )

    def test_expired_document_print_endpoint_returns_printable_html(self):
        expired_doc = self._create_expired(status=Expired.Status.DRAFT)

        response = self.client.get(
            reverse("expired:expired_print", args=[expired_doc.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, expired_doc.document_number)
        self.assertContains(response, 'data-action="print"')
        self.assertContains(response, self.item.nama_barang)

    def test_expired_alerts_show_remaining_actionable_quantity(self):
        self._create_expired(status=Expired.Status.SUBMITTED)

        response = self.client.get(reverse("expired:expired_alerts") + "?pending=0")

        self.assertEqual(response.status_code, 200)
        row = response.context["items"].object_list[0]
        self.assertEqual(row["pending_quantity"], Decimal("5"))
        self.assertEqual(row["actionable"], Decimal("45"))

    def test_expired_alerts_hide_fully_allocated_batch_when_pending_only(self):
        expired_doc = Expired.objects.create(
            report_date="2026-03-10",
            status=Expired.Status.SUBMITTED,
            created_by=self.user,
        )
        ExpiredItem.objects.create(
            expired=expired_doc,
            item=self.item,
            stock=self.stock,
            quantity=Decimal("50"),
            notes="Menunggu verifikasi",
        )

        response = self.client.get(reverse("expired:expired_alerts"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["items"].object_list), [])

    def test_expired_alerts_forbid_user_without_expired_view_scope(self):
        limited_user = User.objects.create_user(
            username="expired-alerts-blocked",
            password="secret12345",
            role=User.Role.ADMIN_UMUM,
        )
        ensure_default_module_access(limited_user, overwrite=True)
        ModuleAccess.objects.update_or_create(
            user=limited_user,
            module=ModuleAccess.Module.EXPIRED,
            defaults={"scope": ModuleAccess.Scope.NONE},
        )
        self.client.force_login(limited_user)

        response = self.client.get(reverse("expired:expired_alerts"))

        self.assertEqual(response.status_code, 403)
