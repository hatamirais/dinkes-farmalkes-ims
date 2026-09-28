from io import BytesIO
import hashlib
from importlib import import_module
import shutil
import threading
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from unittest.mock import PropertyMock, patch

from auditlog.context import set_actor
from auditlog.models import LogEntry
from django.apps import apps as django_apps
from django.contrib.admin.sites import AdminSite
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connections, transaction
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.distribution.models import Distribution, DistributionItem
from apps.core.models import DocumentNumberRule
from apps.core.numbering import issue_document_number
from apps.items.models import Category, Facility, FundingSource, Item, Location, Supplier, Unit
from apps.procurement.models import ProcurementContract
from apps.receiving.admin import (
    RECEIVING_CSV_HEADERS,
    ReceivingAdmin,
    ReceivingCSVImportForm,
    ReceivingTypeOptionAdmin,
)
from apps.receiving.apps import ensure_system_receiving_types
from apps.receiving.forms import (
    PlannedReceivingForm,
    ReceivingForm,
    ReceivingItemForm,
    ReceivingOrderItemForm,
    ReceivingReceiptItemForm,
)
from apps.receiving.models import (
    Receiving,
    ReceivingDocument,
    ReceivingItem,
    ReceivingOrderItem,
    ReceivingTypeOption,
    resolve_receiving_source_document_number,
)
from apps.stock.models import (
    OpeningBalanceImport,
    SourceDocumentNumberClaim,
    Stock,
    StockTransfer,
    StockTransferItem,
    Transaction,
)
from apps.users.access import ensure_default_module_access
from apps.users.models import ModuleAccess, User


def _ensure_receiving_number_rule():
    DocumentNumberRule.objects.get_or_create(
        key=DocumentNumberRule.Key.RECEIVING,
        defaults={
            "label": "Penerimaan",
            "template": "RCV-{year}-{seq}",
            "reset_period": DocumentNumberRule.ResetPeriod.YEARLY,
            "padding": 5,
        },
    )


class ReceivingItemModelExpiryValidationTests(TestCase):
    def setUp(self):
        _ensure_receiving_number_rule()
        self.user = User.objects.create_superuser(
            username="receiving-model-admin",
            password="secret12345",
        )
        self.unit = Unit.objects.create(code="BOT", name="Bottle")
        self.category = Category.objects.create(code="ALK", name="Alkes", sort_order=1)
        self.location = Location.objects.create(code="RCV-MODEL", name="Gudang Receiving Model")
        self.funding = FundingSource.objects.create(code="BOK", name="BOK")
        self.receiving = Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 1, 15),
            supplier=None,
            sumber_dana=self.funding,
            status=Receiving.Status.DRAFT,
            created_by=self.user,
        )

    def test_full_clean_rejects_blank_expiry_for_expiring_item(self):
        item = Item.objects.create(
            kode_barang="ITM-RCV-MODEL-EXP",
            nama_barang="Receiving Model Expiring Item",
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal("0"),
            requires_expiry_date=True,
        )
        receiving_item = ReceivingItem(
            receiving=self.receiving,
            item=item,
            quantity=Decimal("5"),
            batch_lot="RCV-MODEL-EXP-01",
            expiry_date=None,
            unit_price=Decimal("1200"),
            location=self.location,
        )

        with self.assertRaises(ValidationError) as exc:
            receiving_item.full_clean()

        self.assertEqual(
            exc.exception.message_dict["expiry_date"],
            ["Tanggal kedaluwarsa wajib diisi untuk item ini."],
        )

    def test_full_clean_allows_blank_expiry_for_non_expiring_item(self):
        item = Item.objects.create(
            kode_barang="ITM-RCV-MODEL-NOEXP",
            nama_barang="Receiving Model Non Expiring Item",
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal("0"),
            requires_expiry_date=False,
        )
        receiving_item = ReceivingItem(
            receiving=self.receiving,
            item=item,
            quantity=Decimal("6"),
            batch_lot="RCV-MODEL-NOEXP-01",
            expiry_date=None,
            unit_price=Decimal("800"),
            location=self.location,
        )

        receiving_item.full_clean()


class ReceivingTypeMigrationTests(TestCase):
    migration = import_module("apps.receiving.migrations.0019_seed_system_receiving_types")

    def test_seed_migration_allows_legacy_return_rs_receivings(self):
        user = User.objects.create_superuser(
            username="receiving-type-migration-admin",
            password="secret12345",
        )
        funding = FundingSource.objects.create(code="RTM-FUND", name="RTM Fund")
        Receiving.objects.create(
            document_number="RCV-LEGACY-RS",
            receiving_type="RETURN_RS",
            receiving_date=date(2026, 3, 16),
            sumber_dana=funding,
            status=Receiving.Status.VERIFIED,
            created_by=user,
            verified_by=user,
        )

        self.migration.seed_system_receiving_types(django_apps, None)

        self.assertTrue(
            ReceivingTypeOption.objects.filter(
                code=Receiving.ReceivingType.PROCUREMENT,
                is_system=True,
            ).exists()
        )
        self.assertFalse(ReceivingTypeOption.objects.filter(code="RETURN_RS").exists())

    def test_seed_migration_allows_inactive_custom_type_history(self):
        user = User.objects.create_superuser(
            username="receiving-type-inactive-admin",
            password="secret12345",
        )
        funding = FundingSource.objects.create(code="RTM-INACT", name="RTM Inactive")
        ReceivingTypeOption.objects.create(
            code="DON",
            name="Donasi Lama",
            is_active=False,
        )
        Receiving.objects.create(
            document_number="RCV-INACTIVE-TYPE",
            receiving_type="DON",
            receiving_date=date(2026, 3, 16),
            sumber_dana=funding,
            status=Receiving.Status.VERIFIED,
            created_by=user,
            verified_by=user,
        )

        self.migration.seed_system_receiving_types(django_apps, None)

        self.assertTrue(ReceivingTypeOption.objects.filter(code="DON").exists())

    def test_seed_migration_preserves_deleted_custom_type_history(self):
        user = User.objects.create_superuser(
            username="receiving-type-deleted-admin",
            password="secret12345",
        )
        funding = FundingSource.objects.create(code="RTM-DEL", name="RTM Deleted")
        Receiving.objects.create(
            document_number="RCV-DELETED-TYPE",
            receiving_type="DONASI",
            receiving_date=date(2026, 3, 16),
            sumber_dana=funding,
            status=Receiving.Status.VERIFIED,
            created_by=user,
            verified_by=user,
        )

        self.migration.seed_system_receiving_types(django_apps, None)

        receiving_type = ReceivingTypeOption.objects.get(code="DONASI")
        self.assertEqual(receiving_type.name, "DONASI")
        self.assertFalse(receiving_type.is_active)
        self.assertFalse(receiving_type.is_system)
        self.assertFalse(receiving_type.requires_supplier)

    def test_seed_migration_restores_existing_system_type_defaults(self):
        ReceivingTypeOption.objects.filter(
            code=Receiving.ReceivingType.PROCUREMENT
        ).update(
            name="Pengadaan Lama",
            is_active=False,
            is_system=False,
            requires_supplier=False,
            sort_order=77,
        )

        self.migration.seed_system_receiving_types(django_apps, None)

        procurement_type = ReceivingTypeOption.objects.get(
            code=Receiving.ReceivingType.PROCUREMENT
        )
        self.assertEqual(procurement_type.name, "Pengadaan")
        self.assertTrue(procurement_type.is_active)
        self.assertTrue(procurement_type.is_system)
        self.assertTrue(procurement_type.requires_supplier)
        self.assertEqual(procurement_type.sort_order, 10)

    def test_post_migrate_seed_preserves_existing_system_type_metadata(self):
        ReceivingTypeOption.objects.filter(
            code=Receiving.ReceivingType.PROCUREMENT
        ).update(
            name="Pengadaan Manual",
            is_active=False,
            is_system=False,
            requires_supplier=False,
            sort_order=88,
        )

        ensure_system_receiving_types(sender=None, using="default")

        procurement_type = ReceivingTypeOption.objects.get(
            code=Receiving.ReceivingType.PROCUREMENT
        )
        self.assertEqual(procurement_type.name, "Pengadaan Manual")
        self.assertFalse(procurement_type.is_active)
        self.assertTrue(procurement_type.is_system)
        self.assertFalse(procurement_type.requires_supplier)
        self.assertEqual(procurement_type.sort_order, 88)


class ReceivingTypeOptionAdminTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="receiving-type-option-admin",
            password="secret12345",
        )
        self.request = RequestFactory().get("/admin/receiving/receivingtypeoption/")
        self.request.user = self.user
        self.admin = ReceivingTypeOptionAdmin(ReceivingTypeOption, AdminSite())

    def test_system_receiving_type_cannot_be_deleted_from_object_page(self):
        system_type = ReceivingTypeOption.objects.get(code=Receiving.ReceivingType.GRANT)

        self.assertFalse(self.admin.has_delete_permission(self.request, system_type))

    def test_is_system_is_readonly_when_adding_receiving_type(self):
        readonly_fields = self.admin.get_readonly_fields(self.request)

        self.assertIn("is_system", readonly_fields)

    def test_is_system_is_readonly_when_editing_custom_receiving_type(self):
        custom_type = ReceivingTypeOption.objects.create(code="DON", name="Donasi")
        readonly_fields = self.admin.get_readonly_fields(self.request, custom_type)

        self.assertIn("is_system", readonly_fields)
        self.assertNotIn("code", readonly_fields)

    def test_system_receiving_type_locks_code_and_system_flag(self):
        system_type = ReceivingTypeOption.objects.get(code=Receiving.ReceivingType.GRANT)
        readonly_fields = self.admin.get_readonly_fields(self.request, system_type)

        self.assertIn("is_system", readonly_fields)
        self.assertIn("code", readonly_fields)

    def test_bulk_delete_rejects_system_receiving_types(self):
        system_type = ReceivingTypeOption.objects.get(code=Receiving.ReceivingType.GRANT)

        with self.assertRaises(PermissionDenied):
            self.admin.delete_queryset(
                None,
                ReceivingTypeOption.objects.filter(pk=system_type.pk),
            )

        self.assertTrue(ReceivingTypeOption.objects.filter(pk=system_type.pk).exists())

    def test_bulk_delete_allows_custom_receiving_types(self):
        custom_type = ReceivingTypeOption.objects.create(code="DON", name="Donasi")

        self.admin.delete_queryset(None, ReceivingTypeOption.objects.filter(pk=custom_type.pk))

        self.assertFalse(ReceivingTypeOption.objects.filter(pk=custom_type.pk).exists())


class ReceivingModelDocumentNumberCollisionTests(TestCase):
    def setUp(self):
        _ensure_receiving_number_rule()
        self.user = User.objects.create_superuser(
            username="receiving-docnum-admin",
            password="secret12345",
        )
        self.unit = Unit.objects.create(code="RCV-DOCNUM-UNT", name="Docnum Unit")
        self.category = Category.objects.create(
            code="RCV-DOCNUM-CAT",
            name="Docnum Category",
        )
        self.item = Item.objects.create(
            kode_barang="RCV-DOCNUM-ITEM",
            nama_barang="Receiving Docnum Item",
            satuan=self.unit,
            kategori=self.category,
        )
        self.location = Location.objects.create(
            code="RCV-DOCNUM-LOC",
            name="Receiving Docnum Location",
        )
        self.funding = FundingSource.objects.create(code="RCV-DOCNUM", name="Dana Docnum")

    def _create_opening_balance_import(self, document_number):
        return OpeningBalanceImport.objects.create(
            document_number=document_number,
            effective_date=date(2026, 1, 1),
            created_by=self.user,
        )

    def test_full_clean_rejects_opening_balance_document_number_collision(self):
        self._create_opening_balance_import("RCV-OB-COLLISION")
        receiving = Receiving(
            document_number="RCV-OB-COLLISION",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 1, 15),
            sumber_dana=self.funding,
            status=Receiving.Status.DRAFT,
            created_by=self.user,
        )

        with self.assertRaises(ValidationError) as exc:
            receiving.full_clean()

        self.assertIn("document_number", exc.exception.message_dict)
        self.assertIn(
            "sudah digunakan oleh dokumen saldo awal",
            exc.exception.message_dict["document_number"][0],
        )

    def test_save_rejects_opening_balance_document_number_collision(self):
        self._create_opening_balance_import("RCV-OB-SAVE-COLLISION")

        with self.assertRaises(ValidationError) as exc:
            Receiving.objects.create(
                document_number="RCV-OB-SAVE-COLLISION",
                receiving_type=Receiving.ReceivingType.GRANT,
                receiving_date=date(2026, 1, 15),
                sumber_dana=self.funding,
                status=Receiving.Status.DRAFT,
                created_by=self.user,
            )

        self.assertIn("document_number", exc.exception.message_dict)
        self.assertFalse(Receiving.objects.exists())

    def test_save_claims_receiving_document_number(self):
        receiving = Receiving.objects.create(
            document_number="RCV-CLAIM-001",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 1, 15),
            sumber_dana=self.funding,
            status=Receiving.Status.DRAFT,
            created_by=self.user,
        )

        claim = SourceDocumentNumberClaim.objects.get(
            document_number="RCV-CLAIM-001"
        )
        self.assertEqual(
            claim.source_type,
            SourceDocumentNumberClaim.SourceType.RECEIVING,
        )
        self.assertEqual(claim.source_id, receiving.pk)

    def test_save_without_document_number_does_not_create_claim(self):
        receiving = Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 1, 15),
            sumber_dana=self.funding,
            status=Receiving.Status.DRAFT,
            created_by=self.user,
        )

        self.assertIsNone(receiving.document_number)
        self.assertEqual(SourceDocumentNumberClaim.objects.count(), 0)

    def test_queryset_delete_retains_issued_receiving_document_number_claim(self):
        receiving = Receiving.objects.create(
            document_number="RCV-DELETE-UNPOSTED",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 1, 15),
            sumber_dana=self.funding,
            status=Receiving.Status.DRAFT,
            created_by=self.user,
        )
        self.assertTrue(
            SourceDocumentNumberClaim.objects.filter(
                document_number="RCV-DELETE-UNPOSTED",
                source_type=SourceDocumentNumberClaim.SourceType.RECEIVING,
                source_id=receiving.pk,
            ).exists()
        )

        Receiving.objects.filter(pk=receiving.pk).delete()

        self.assertTrue(
            SourceDocumentNumberClaim.objects.filter(
                document_number="RCV-DELETE-UNPOSTED",
                source_type=SourceDocumentNumberClaim.SourceType.RECEIVING,
                source_id=receiving.pk,
            ).exists()
        )

    def test_delete_retains_posted_receiving_document_number_claim(self):
        receiving = Receiving.objects.create(
            document_number="RCV-DELETE-POSTED",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 1, 15),
            sumber_dana=self.funding,
            status=Receiving.Status.VERIFIED,
            created_by=self.user,
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot="RCV-DELETE-POSTED-BATCH",
            quantity=Decimal("5"),
            unit_price=Decimal("1000"),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=receiving.pk,
            user=self.user,
        )
        receiving_id = receiving.pk

        receiving.delete()

        self.assertTrue(
            SourceDocumentNumberClaim.objects.filter(
                document_number="RCV-DELETE-POSTED",
                source_type=SourceDocumentNumberClaim.SourceType.RECEIVING,
                source_id=receiving_id,
            ).exists()
        )

    def test_save_rejects_preclaimed_source_document_number(self):
        SourceDocumentNumberClaim.objects.create(
            document_number="RCV-PRECLAIMED-001",
            source_type=SourceDocumentNumberClaim.SourceType.OPENING_BALANCE,
        )

        with self.assertRaises(ValidationError) as exc:
            Receiving.objects.create(
                document_number="RCV-PRECLAIMED-001",
                receiving_type=Receiving.ReceivingType.GRANT,
                receiving_date=date(2026, 1, 15),
                sumber_dana=self.funding,
                status=Receiving.Status.DRAFT,
                created_by=self.user,
            )

        self.assertIn("document_number", exc.exception.message_dict)
        self.assertFalse(Receiving.objects.exists())

    def test_save_allows_unchanged_legacy_opening_balance_collision(self):
        receiving = Receiving.objects.create(
            document_number="RCV-LEGACY-COLLISION",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 1, 15),
            sumber_dana=self.funding,
            status=Receiving.Status.DRAFT,
            created_by=self.user,
        )
        self._create_opening_balance_import("RCV-LEGACY-COLLISION")

        receiving.notes = "Status update on migrated document"
        receiving.full_clean()
        receiving.save()

        receiving.refresh_from_db()
        self.assertEqual(receiving.document_number, "RCV-LEGACY-COLLISION")
        self.assertEqual(receiving.notes, "Status update on migrated document")

    def test_generated_document_number_skips_opening_balance_numbers(self):
        year = timezone.now().year
        self._create_opening_balance_import(f"RCV-{year}-00001")

        receiving = Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 1, 15),
            sumber_dana=self.funding,
            status=Receiving.Status.DRAFT,
            created_by=self.user,
        )
        issue_document_number(
            DocumentNumberRule.Key.RECEIVING,
            business_date=receiving.receiving_date,
            target=receiving,
            actor=self.user,
        )
        receiving.refresh_from_db()

        self.assertEqual(receiving.document_number, f"RCV-{year}-00002")

    def test_generated_document_number_skips_retained_registry_claims(self):
        year = timezone.now().year
        SourceDocumentNumberClaim.objects.create(
            document_number=f"RCV-{year}-00001",
            source_type=SourceDocumentNumberClaim.SourceType.RECEIVING,
            source_id=999999,
        )

        receiving = Receiving.objects.create(
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 1, 15),
            sumber_dana=self.funding,
            status=Receiving.Status.DRAFT,
            created_by=self.user,
        )
        issue_document_number(
            DocumentNumberRule.Key.RECEIVING,
            business_date=receiving.receiving_date,
            target=receiving,
            actor=self.user,
        )
        receiving.refresh_from_db()

        self.assertEqual(receiving.document_number, f"RCV-{year}-00002")

    def test_resolver_uses_existing_transaction_source_when_stock_reference_is_absent(self):
        receiving = Receiving.objects.create(
            document_number="RCV-RESOLVE-TX",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 1, 15),
            sumber_dana=self.funding,
            status=Receiving.Status.PARTIAL,
            created_by=self.user,
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot="RCV-RESOLVE-TX-BATCH",
            source_document_number="LEGACY-AGGREGATE-RCV",
            quantity=Decimal("5"),
            unit_price=Decimal("1000"),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=receiving.pk,
            user=self.user,
        )

        self.assertEqual(
            resolve_receiving_source_document_number(receiving),
            "LEGACY-AGGREGATE-RCV",
        )

    def test_resolver_uses_stock_tuple_when_receiving_has_mixed_sources(self):
        receiving = Receiving.objects.create(
            document_number="RCV-RESOLVE-MIXED",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 1, 15),
            sumber_dana=self.funding,
            status=Receiving.Status.PARTIAL,
            created_by=self.user,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="RCV-RESOLVE-HEADER",
            source_document_number="RCV-RESOLVE-MIXED",
            expiry_date=date(2030, 1, 1),
            quantity=Decimal("4"),
            reserved=Decimal("0"),
            unit_price=Decimal("1000"),
            sumber_dana=self.funding,
            receiving_ref=receiving,
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot="RCV-RESOLVE-LEGACY",
            source_document_number="LEGACY-MIXED-RCV",
            quantity=Decimal("5"),
            unit_price=Decimal("1000"),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=receiving.pk,
            user=self.user,
        )

        self.assertEqual(
            resolve_receiving_source_document_number(
                receiving,
                item=self.item,
                location=self.location,
                batch_lot="RCV-RESOLVE-HEADER",
                sumber_dana=self.funding,
            ),
            "RCV-RESOLVE-MIXED",
        )
        self.assertEqual(
            resolve_receiving_source_document_number(
                receiving,
                item=self.item,
                location=self.location,
                batch_lot="RCV-RESOLVE-LEGACY",
                sumber_dana=self.funding,
            ),
            "LEGACY-MIXED-RCV",
        )

    def test_resolver_reuses_collision_alias_for_new_receiving_tuple(self):
        document_number = "RCV-RESOLVE-COLLISION"
        receiving = Receiving.objects.create(
            document_number=document_number,
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 1, 15),
            sumber_dana=self.funding,
            status=Receiving.Status.PARTIAL,
            created_by=self.user,
        )
        self._create_opening_balance_import(document_number)
        digest = hashlib.sha1(
            f"RECEIVING:{document_number}".encode("utf-8")
        ).hexdigest()[:8]
        alias = f"RCV-{digest}-{document_number}"
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="RCV-RESOLVE-COLLISION-OLD",
            source_document_number=alias,
            expiry_date=date(2030, 1, 1),
            quantity=Decimal("4"),
            reserved=Decimal("0"),
            unit_price=Decimal("1000"),
            sumber_dana=self.funding,
            receiving_ref=receiving,
        )

        self.assertEqual(
            resolve_receiving_source_document_number(
                receiving,
                item=self.item,
                location=self.location,
                batch_lot="RCV-RESOLVE-COLLISION-NEW",
                sumber_dana=self.funding,
            ),
            alias,
        )

    def test_full_clean_rejects_document_number_change_after_ledger_transaction(self):
        receiving = Receiving.objects.create(
            document_number="RCV-LOCKED-001",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 1, 15),
            sumber_dana=self.funding,
            status=Receiving.Status.VERIFIED,
            created_by=self.user,
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot="RCV-LOCKED-BATCH",
            quantity=Decimal("5"),
            unit_price=Decimal("1000"),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=receiving.pk,
            user=self.user,
        )
        receiving.document_number = "RCV-LOCKED-RENAMED"

        with self.assertRaises(ValidationError) as exc:
            receiving.full_clean()

        self.assertIn("document_number", exc.exception.message_dict)
        self.assertIn(
            "tidak dapat diubah",
            exc.exception.message_dict["document_number"][0],
        )

    def test_save_rejects_document_number_change_after_stock_posting(self):
        receiving = Receiving.objects.create(
            document_number="RCV-STOCK-LOCKED-001",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 1, 15),
            sumber_dana=self.funding,
            status=Receiving.Status.VERIFIED,
            created_by=self.user,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="RCV-STOCK-LOCKED-BATCH",
            expiry_date=date(2030, 1, 1),
            quantity=Decimal("5"),
            reserved=Decimal("0"),
            unit_price=Decimal("1000"),
            sumber_dana=self.funding,
            receiving_ref=receiving,
            source_document_number=receiving.document_number,
        )
        receiving.document_number = "RCV-STOCK-LOCKED-RENAMED"

        with self.assertRaises(ValidationError) as exc:
            receiving.save()

        self.assertIn("document_number", exc.exception.message_dict)
        receiving.refresh_from_db()
        self.assertEqual(receiving.document_number, "RCV-STOCK-LOCKED-001")

    def test_receiving_admin_makes_document_number_readonly_after_posting(self):
        receiving = Receiving.objects.create(
            document_number="RCV-ADMIN-LOCKED-001",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 1, 15),
            sumber_dana=self.funding,
            status=Receiving.Status.VERIFIED,
            created_by=self.user,
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot="RCV-ADMIN-LOCKED-BATCH",
            quantity=Decimal("5"),
            unit_price=Decimal("1000"),
            sumber_dana=self.funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=receiving.pk,
            user=self.user,
        )
        admin = ReceivingAdmin(Receiving, AdminSite())

        self.assertIn("document_number", admin.get_readonly_fields(None, receiving))


class ReceivingCSVImportTest(TestCase):
    def setUp(self):
        _ensure_receiving_number_rule()
        self.user = User.objects.create_superuser(
            username="admin_receiving",
            password="secret12345",
        )

        unit = Unit.objects.create(code="TAB", name="Tablet")
        category = Category.objects.create(code="OBAT", name="Obat", sort_order=1)
        self.item = Item.objects.create(
            kode_barang="ITM-TEST-0001",
            nama_barang="Paracetamol 500mg",
            satuan=unit,
            kategori=category,
            minimum_stock=Decimal("0"),
        )
        self.funding = FundingSource.objects.create(code="APBD", name="APBD")
        self.location = Location.objects.create(code="GUDANG", name="Gudang Utama")

        self.admin = ReceivingAdmin(Receiving, AdminSite())

    @staticmethod
    def _csv_file(content):
        return SimpleUploadedFile(
            "receiving.csv",
            content.encode("utf-8"),
            content_type="text/csv",
        )

    @staticmethod
    def _uploaded_file(name, content, content_type="text/plain"):
        return SimpleUploadedFile(name, content, content_type=content_type)

    def test_csv_import_form_rejects_non_csv_extension(self):
        form = ReceivingCSVImportForm(
            data={},
            files={
                "csv_file": self._uploaded_file(
                    "receiving.pdf",
                    b"%PDF-1.4\n",
                    content_type="application/pdf",
                )
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("csv_file", form.errors)

    def test_csv_import_form_rejects_non_csv_content(self):
        form = ReceivingCSVImportForm(
            data={},
            files={
                "csv_file": self._uploaded_file(
                    "receiving.csv",
                    b"\x89PNG\r\n\x1a\n",
                    content_type="text/csv",
                )
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("csv_file", form.errors)

    def test_csv_import_form_rejects_non_csv_mime_type(self):
        form = ReceivingCSVImportForm(
            data={},
            files={
                "csv_file": self._uploaded_file(
                    "receiving.csv",
                    b"import_group,receiving_type\nGROUP-1,GRANT\n",
                    content_type="application/octet-stream",
                )
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("csv_file", form.errors)

    def test_process_csv_applies_defaults_for_empty_optional_fields(self):
        self.item.requires_expiry_date = False
        self.item.save(update_fields=["requires_expiry_date", "updated_at"])
        csv_content = (
            "import_group,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-TEST-0001,10,,,\n"
        )

        result = self.admin._process_csv(self._csv_file(csv_content), self.user)

        self.assertEqual(result["receivings"], 1)
        self.assertEqual(result["items"], 1)
        self.assertEqual(result["stock"], 1)
        self.assertEqual(result["transactions"], 1)

        receiving_item = ReceivingItem.objects.get()
        self.assertEqual(receiving_item.quantity, Decimal("10"))
        self.assertEqual(receiving_item.unit_price, Decimal("0"))
        self.assertEqual(receiving_item.batch_lot, "SALDO-0002")
        self.assertIsNone(receiving_item.expiry_date)
        self.assertEqual(receiving_item.posted_sumber_dana, self.funding)
        self.assertEqual(
            receiving_item.posted_source_document_number,
            receiving_item.receiving.document_number,
        )
        self.assertEqual(receiving_item.receiving.import_group, "RCV-2026-00001")

        stock = Stock.objects.get()
        self.assertEqual(stock.quantity, Decimal("10"))
        self.assertEqual(stock.batch_lot, "SALDO-0002")
        self.assertIsNone(stock.expiry_date)

    def test_process_csv_preserves_high_precision_unit_price(self):
        csv_content = (
            "import_group,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-TEST-0001,10,B-001,01/01/2030,8893.31985\n"
        )

        result = self.admin._process_csv(self._csv_file(csv_content), self.user)

        self.assertEqual(result["items"], 1)
        receiving_item = ReceivingItem.objects.get()
        self.assertEqual(receiving_item.unit_price, Decimal("8893.31985"))
        stock = Stock.objects.get()
        self.assertEqual(stock.unit_price, Decimal("8893.31985"))
        transaction = Transaction.objects.get()
        self.assertEqual(transaction.unit_price, Decimal("8893.31985"))

    def test_process_csv_skips_opening_balance_official_number_collision(self):
        OpeningBalanceImport.objects.create(
            document_number="RCV-2026-00001",
            effective_date=date(2026, 1, 1),
            created_by=self.user,
        )
        csv_content = (
            "import_group,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "GROUP-OB-COLLISION,GRANT,12/03/2026,,APBD,GUDANG,ITM-TEST-0001,10,B-001,01/01/2030,1000\n"
        )

        self.admin._process_csv(self._csv_file(csv_content), self.user)

        receiving = Receiving.objects.get()
        self.assertEqual(receiving.import_group, "GROUP-OB-COLLISION")
        self.assertEqual(receiving.document_number, "RCV-2026-00002")

    def test_process_csv_rejects_blank_expiry_for_items_that_require_it(self):
        csv_content = (
            "import_group,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-TEST-0001,10,,,\n"
        )

        with self.assertRaisesMessage(
            ValueError,
            "expiry_date wajib diisi untuk item 'ITM-TEST-0001'",
        ):
            self.admin._process_csv(self._csv_file(csv_content), self.user)

    def test_process_csv_rejects_blank_quantity(self):
        csv_content = (
            "import_group,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-TEST-0001,,B-001,01/01/2030,1000\n"
        )

        with self.assertRaisesMessage(ValueError, "Baris 2: quantity wajib diisi"):
            self.admin._process_csv(self._csv_file(csv_content), self.user)

        self.assertEqual(Receiving.objects.count(), 0)
        self.assertEqual(ReceivingItem.objects.count(), 0)
        self.assertEqual(Stock.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_process_csv_rejects_zero_quantity(self):
        csv_content = (
            "import_group,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-TEST-0001,0,B-001,01/01/2030,1000\n"
        )

        with self.assertRaisesMessage(ValueError, "Baris 2: quantity harus lebih dari 0"):
            self.admin._process_csv(self._csv_file(csv_content), self.user)

        self.assertEqual(Receiving.objects.count(), 0)
        self.assertEqual(ReceivingItem.objects.count(), 0)
        self.assertEqual(Stock.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_process_csv_rejects_negative_quantity(self):
        csv_content = (
            "import_group,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-TEST-0001,-5,B-001,01/01/2030,1000\n"
        )

        with self.assertRaisesMessage(ValueError, "Baris 2: quantity harus lebih dari 0"):
            self.admin._process_csv(self._csv_file(csv_content), self.user)

        self.assertEqual(Receiving.objects.count(), 0)
        self.assertEqual(ReceivingItem.objects.count(), 0)
        self.assertEqual(Stock.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_process_csv_handles_missing_cell_without_strip_crash(self):
        csv_content = (
            "import_group,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,,10,B-001,01/01/2030,1000\n"
        )

        with self.assertRaisesMessage(ValueError, "Baris 2: item_code kosong"):
            self.admin._process_csv(self._csv_file(csv_content), self.user)

    def test_process_csv_invalid_foreign_key_has_clear_message(self):
        csv_content = (
            "import_group,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-NOT-FOUND,10,B-001,01/01/2030,1000\n"
        )

        with self.assertRaisesMessage(
            ValueError, "Baris 2: item_code 'ITM-NOT-FOUND' tidak ditemukan"
        ):
            self.admin._process_csv(self._csv_file(csv_content), self.user)

    def test_process_csv_invalid_decimal_has_clear_message(self):
        csv_content = (
            "import_group,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-TEST-0001,sepuluh,B-001,01/01/2030,1000\n"
        )

        with self.assertRaisesMessage(
            ValueError, "Baris 2: format quantity tidak valid: 'sepuluh'"
        ):
            self.admin._process_csv(self._csv_file(csv_content), self.user)

        self.assertEqual(Receiving.objects.count(), 0)
        self.assertEqual(ReceivingItem.objects.count(), 0)
        self.assertEqual(Stock.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_process_csv_rejects_null_byte_in_later_row(self):
        csv_content = (
            "import_group,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-TEST-0001,10,B-001,01/01/2030,1000\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-TEST-0001,10,BAD\x00BATCH,01/01/2030,1000\n"
        )

        with self.assertRaisesMessage(
            ValueError,
            "Baris 3: batch_lot mengandung null byte yang tidak diizinkan",
        ):
            self.admin._process_csv(self._csv_file(csv_content), self.user)

        self.assertEqual(Receiving.objects.count(), 0)
        self.assertEqual(ReceivingItem.objects.count(), 0)
        self.assertEqual(Stock.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_process_csv_rejects_overlong_text_fields_before_save(self):
        cases = [
            (
                "import_group",
                "D" * 101,
                "GRANT",
                "APBD",
                "GUDANG",
                "ITM-TEST-0001",
                "B-001",
                "Baris 2: import_group maksimal 100 karakter",
            ),
            (
                "receiving_type",
                "RCV-2026-00001",
                "R" * 21,
                "APBD",
                "GUDANG",
                "ITM-TEST-0001",
                "B-001",
                "Baris 2: receiving_type maksimal 20 karakter",
            ),
            (
                "sumber_dana_code",
                "RCV-2026-00001",
                "GRANT",
                "S" * 21,
                "GUDANG",
                "ITM-TEST-0001",
                "B-001",
                "Baris 2: sumber_dana_code maksimal 20 karakter",
            ),
            (
                "item_code",
                "RCV-2026-00001",
                "GRANT",
                "APBD",
                "GUDANG",
                "I" * 51,
                "B-001",
                "Baris 2: item_code maksimal 50 karakter",
            ),
            (
                "batch_lot",
                "RCV-2026-00001",
                "GRANT",
                "APBD",
                "GUDANG",
                "ITM-TEST-0001",
                "B" * 101,
                "Baris 2: batch_lot maksimal 100 karakter",
            ),
        ]

        for (
            field_name,
            doc,
            receiving_type,
            funding,
            location,
            item_code,
            batch,
            message,
        ) in cases:
            with self.subTest(field_name=field_name):
                csv_content = (
                    "import_group,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
                    "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
                    f"{doc},{receiving_type},12/03/2026,,{funding},{location},{item_code},10,{batch},01/01/2030,1000\n"
                )

                with self.assertRaisesMessage(ValueError, message):
                    self.admin._process_csv(self._csv_file(csv_content), self.user)

                self.assertEqual(Receiving.objects.count(), 0)
                self.assertEqual(ReceivingItem.objects.count(), 0)
                self.assertEqual(Stock.objects.count(), 0)
                self.assertEqual(Transaction.objects.count(), 0)

    def test_process_csv_rejects_date_year_outside_supported_range(self):
        cases = [
            (
                "receiving_date",
                "01/01/0999",
                "01/01/2030",
                "Baris 2: receiving_date harus memiliki tahun antara 1000 dan 9999",
            ),
            (
                "receiving_date",
                "01/01/10000",
                "01/01/2030",
                "Baris 2: receiving_date harus memiliki tahun antara 1000 dan 9999",
            ),
            (
                "expiry_date",
                "12/03/2026",
                "01/01/0999",
                "Baris 2: expiry_date harus memiliki tahun antara 1000 dan 9999",
            ),
        ]

        for field_name, receiving_date, expiry_date, message in cases:
            with self.subTest(
                field_name=field_name,
                receiving_date=receiving_date,
                expiry_date=expiry_date,
            ):
                csv_content = (
                    "import_group,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
                    "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
                    f"RCV-2026-00001,GRANT,{receiving_date},,APBD,GUDANG,ITM-TEST-0001,10,B-001,{expiry_date},1000\n"
                )

                with self.assertRaisesMessage(ValueError, message):
                    self.admin._process_csv(self._csv_file(csv_content), self.user)

                self.assertEqual(Receiving.objects.count(), 0)
                self.assertEqual(ReceivingItem.objects.count(), 0)
                self.assertEqual(Stock.objects.count(), 0)
                self.assertEqual(Transaction.objects.count(), 0)

    def test_process_csv_normalizes_and_strips_headers_and_values(self):
        decomposed_doc_number = "RCV-2026-A\u0301"
        csv_content = (
            " import_group , receiving_type , receiving_date , supplier_code , sumber_dana_code ,"
            " location_code , item_code , quantity , batch_lot , expiry_date , unit_price \n"
            f" {decomposed_doc_number} , GRANT , 12/03/2026 , , APBD , GUDANG , ITM-TEST-0001 , 10 , B-001 , 01/01/2030 , 1000 \n"
        )

        result = self.admin._process_csv(self._csv_file(csv_content), self.user)

        self.assertEqual(result["receivings"], 1)
        receiving = Receiving.objects.get()
        self.assertEqual(receiving.import_group, "RCV-2026-Á")
        self.assertNotEqual(receiving.document_number, receiving.import_group)
        receiving_item = ReceivingItem.objects.get()
        self.assertEqual(receiving_item.batch_lot, "B-001")

    def test_process_csv_rejects_nan_decimal(self):
        csv_content = (
            "import_group,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-TEST-0001,NaN,B-001,01/01/2030,1000\n"
        )

        with self.assertRaisesMessage(
            ValueError, "Baris 2: quantity tidak boleh NaN atau Infinity"
        ):
            self.admin._process_csv(self._csv_file(csv_content), self.user)

        self.assertEqual(Receiving.objects.count(), 0)
        self.assertEqual(ReceivingItem.objects.count(), 0)
        self.assertEqual(Stock.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_import_view_requires_add_permission(self):
        user = User.objects.create_user(
            username="receiving_staff",
            password="secret12345",
            is_staff=True,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("admin:receiving_import_csv"), secure=True)

        self.assertEqual(response.status_code, 403)

    def test_import_view_logs_success(self):
        self.client.force_login(self.user)
        csv_content = (
            "import_group,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-TEST-0001,10,B-001,01/01/2030,1000\n"
        )

        with self.assertLogs("security", level="INFO") as logs:
            response = self.client.post(
                reverse("admin:receiving_import_csv"),
                {"csv_file": self._csv_file(csv_content)},
                secure=True,
            )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            any("receiving_csv_import_succeeded" in message for message in logs.output)
        )

    def test_process_csv_missing_required_header_rejected(self):
        csv_content = (
            "import_group,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,10,B-001,01/01/2030,1000\n"
        )

        with self.assertRaisesMessage(
            ValueError, "Kolom wajib tidak ditemukan: item_code"
        ):
            self.admin._process_csv(self._csv_file(csv_content), self.user)

    def test_process_csv_invalid_date_has_clear_message(self):
        csv_content = (
            "import_group,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,notadate,,APBD,GUDANG,ITM-TEST-0001,10,B-001,01/01/2030,1000\n"
        )

        with self.assertRaisesMessage(
            ValueError,
            "Baris 2: format receiving_date tidak dikenali: 'notadate'. Gunakan DD/MM/YYYY.",
        ):
            self.admin._process_csv(self._csv_file(csv_content), self.user)

    def test_process_csv_rolls_back_on_error(self):
        csv_content = (
            "import_group,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-TEST-0001,10,B-001,01/01/2030,1000\n"
            "RCV-2026-00001,GRANT,12/03/2026,,APBD,GUDANG,ITM-NOT-FOUND,10,B-002,01/01/2030,1000\n"
        )

        with self.assertRaises(ValueError):
            self.admin._process_csv(self._csv_file(csv_content), self.user)

        self.assertEqual(Receiving.objects.count(), 0)
        self.assertEqual(ReceivingItem.objects.count(), 0)
        self.assertEqual(Stock.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_process_csv_rejects_invalid_receiving_type(self):
        csv_content = (
            "import_group,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            "RCV-2026-00001,FOO,12/03/2026,,APBD,GUDANG,ITM-TEST-0001,10,B-001,01/01/2030,1000\n"
        )

        with self.assertRaisesMessage(ValueError, "Baris 2: Masukkan pilihan yang valid."):
            self.admin._process_csv(self._csv_file(csv_content), self.user)

    def test_import_view_template_documents_current_optional_columns(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("admin:receiving_import_csv"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<code>batch_lot</code>", html=False)
        self.assertContains(response, "Opsional; otomatis dibuat jika kosong")
        self.assertContains(response, "<code>expiry_date</code>", html=False)
        self.assertContains(
            response,
            "Wajib hanya untuk item yang memerlukan tanggal kedaluwarsa",
        )

    def test_export_csv_template_downloads_expected_headers(self):
        self.client.force_login(self.user)

        with self.assertLogs("security", level="INFO") as logs:
            response = self.client.get(
                reverse("admin:receiving_export_csv_template"),
                secure=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="receiving_template.csv"',
        )
        self.assertEqual(
            response.content.decode("utf-8").strip(),
            ",".join(RECEIVING_CSV_HEADERS),
        )
        self.assertTrue(
            any(
                "receiving_csv_template_exported" in message
                for message in logs.output
            )
        )

    def test_export_csv_template_requires_add_permission(self):
        user = User.objects.create_user(
            username="receiving_template_staff",
            password="secret12345",
            is_staff=True,
        )
        self.client.force_login(user)

        response = self.client.get(
            reverse("admin:receiving_export_csv_template"),
            secure=True,
        )

        self.assertEqual(response.status_code, 403)

    def test_receiving_admin_changelist_links_csv_template_download(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("admin:receiving_receiving_changelist"),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="export-csv-template/"', html=False)
        self.assertContains(response, "Download Template CSV")


@override_settings(SECURE_SSL_REDIRECT=False)
class ReceivingWorkflowCleanupTest(TestCase):
    def setUp(self):
        _ensure_receiving_number_rule()
        self.user = User.objects.create_superuser(
            username="admin_workflow",
            password="secret12345",
        )
        self.client.force_login(self.user)

        unit = Unit.objects.create(code="TAB", name="Tablet")
        category = Category.objects.create(code="OBAT2", name="Obat 2", sort_order=2)
        self.item = Item.objects.create(
            kode_barang="ITM-TEST-0101",
            nama_barang="Amoxicillin 500mg",
            satuan=unit,
            kategori=category,
            minimum_stock=Decimal("0"),
        )
        self.funding = FundingSource.objects.create(code="DAK", name="DAK")
        self.location = Location.objects.create(code="LOC-01", name="Gudang A")
        self.rs_facility = Facility.objects.create(
            code="RS-01",
            name="RSUD Meulaboh",
            facility_type=Facility.FacilityType.RS,
        )

    def _create_contract_linked_plan(self):
        supplier = Supplier.objects.create(
            code="SUP-RCV-WF",
            name="PT Receiving Workflow",
        )
        contract = ProcurementContract.objects.create(
            document_number="SPJ-2026-RCVWF",
            contract_date=date(2026, 3, 16),
            supplier=supplier,
            sumber_dana=self.funding,
            status=ProcurementContract.Status.APPROVED,
            created_by=self.user,
            approved_by=self.user,
        )
        receiving = Receiving.objects.create(
            document_number="RCV-2026-SPJWF",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            supplier=supplier,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            contract=contract,
            created_by=self.user,
            approved_by=self.user,
        )
        ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=self.item,
            planned_quantity=Decimal("5"),
            received_quantity=Decimal("0"),
            unit_price=Decimal("1000"),
        )
        return receiving

    def test_system_receiving_type_options_seeded_and_shared_by_forms(self):
        procurement_type = ReceivingTypeOption.objects.get(
            code=Receiving.ReceivingType.PROCUREMENT
        )
        grant_type = ReceivingTypeOption.objects.get(code=Receiving.ReceivingType.GRANT)

        self.assertTrue(procurement_type.is_system)
        self.assertTrue(procurement_type.requires_supplier)
        self.assertTrue(grant_type.is_system)
        self.assertFalse(grant_type.requires_supplier)

        regular_choices = list(ReceivingForm().fields["receiving_type"].widget.choices)
        planned_choices = list(
            PlannedReceivingForm().fields["receiving_type"].widget.choices
        )

        self.assertEqual(regular_choices[0], ("", "---------"))
        self.assertEqual(planned_choices[0], ("", "---------"))
        self.assertIn(
            (Receiving.ReceivingType.PROCUREMENT, "Pengadaan"),
            regular_choices,
        )
        self.assertIn(
            (Receiving.ReceivingType.PROCUREMENT, "Pengadaan"),
            planned_choices,
        )
        self.assertIn((Receiving.ReceivingType.GRANT, "Hibah"), regular_choices)
        self.assertIn((Receiving.ReceivingType.GRANT, "Hibah"), planned_choices)

    def test_regular_receiving_create_auto_verifies_and_posts_stock_transaction(self):
        response = self.client.post(
            reverse("receiving:receiving_create"),
            {
                "document_number": "",
                "receiving_type": Receiving.ReceivingType.GRANT,
                "receiving_date": "2026-03-16",
                "supplier": "",
                "sumber_dana": self.funding.pk,
                "notes": "",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-item": self.item.pk,
                "items-0-quantity": "10",
                "items-0-batch_lot": "BATCH-001",
                "items-0-expiry_date": "2030-01-01",
                "items-0-unit_price": "1500",
                "items-0-location": self.location.pk,
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        receiving = Receiving.objects.get()
        self.assertEqual(receiving.status, Receiving.Status.VERIFIED)
        self.assertEqual(receiving.verified_by, self.user)
        self.assertTrue(receiving.document_number.startswith("RCV-"))

        receiving_item = ReceivingItem.objects.get(receiving=receiving)
        self.assertEqual(receiving_item.received_by, self.user)
        self.assertEqual(receiving_item.location, self.location)

        stock = Stock.objects.get(item=self.item, batch_lot="BATCH-001")
        self.assertEqual(stock.quantity, Decimal("10"))
        self.assertEqual(stock.location, self.location)

        trx = Transaction.objects.get(reference_id=receiving.pk)
        self.assertEqual(trx.reference_type, Transaction.ReferenceType.RECEIVING)
        self.assertEqual(trx.transaction_type, Transaction.TransactionType.IN)
        self.assertEqual(trx.quantity, Decimal("10"))

    def test_regular_receiving_create_accepts_comma_decimal_unit_price(self):
        response = self.client.post(
            reverse("receiving:receiving_create"),
            {
                "document_number": "",
                "receiving_type": Receiving.ReceivingType.GRANT,
                "receiving_date": "2026-03-16",
                "supplier": "",
                "sumber_dana": self.funding.pk,
                "notes": "",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-item": self.item.pk,
                "items-0-quantity": "10",
                "items-0-batch_lot": "BATCH-IDPRICE",
                "items-0-expiry_date": "2030-01-01",
                "items-0-unit_price": "1500,50",
                "items-0-location": self.location.pk,
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        receiving_item = ReceivingItem.objects.get()
        stock = Stock.objects.get(item=self.item, batch_lot="BATCH-IDPRICE")
        trx = Transaction.objects.get(reference_id=receiving_item.receiving_id)
        self.assertEqual(receiving_item.unit_price, Decimal("1500.50"))
        self.assertEqual(stock.unit_price, Decimal("1500.50"))
        self.assertEqual(trx.unit_price, Decimal("1500.50"))

    def test_regular_receiving_create_rejects_dot_decimal_unit_price(self):
        response = self.client.post(
            reverse("receiving:receiving_create"),
            {
                "document_number": "",
                "receiving_type": Receiving.ReceivingType.GRANT,
                "receiving_date": "2026-03-16",
                "supplier": "",
                "sumber_dana": self.funding.pk,
                "notes": "",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-item": self.item.pk,
                "items-0-quantity": "10",
                "items-0-batch_lot": "BATCH-DOTPRICE",
                "items-0-expiry_date": "2030-01-01",
                "items-0-unit_price": "1500.50",
                "items-0-location": self.location.pk,
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Gunakan angka tanpa pemisah ribuan. Gunakan koma untuk desimal.",
        )
        self.assertEqual(Receiving.objects.count(), 0)

    def test_regular_receiving_create_allows_blank_expiry_for_non_expiring_item(self):
        self.item.requires_expiry_date = False
        self.item.save(update_fields=["requires_expiry_date", "updated_at"])

        response = self.client.post(
            reverse("receiving:receiving_create"),
            {
                "document_number": "",
                "receiving_type": Receiving.ReceivingType.GRANT,
                "receiving_date": "2026-03-16",
                "supplier": "",
                "sumber_dana": self.funding.pk,
                "notes": "",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-item": self.item.pk,
                "items-0-quantity": "10",
                "items-0-batch_lot": "BATCH-NO-EXP",
                "items-0-expiry_date": "",
                "items-0-unit_price": "1500",
                "items-0-location": self.location.pk,
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        receiving_item = ReceivingItem.objects.get(batch_lot="BATCH-NO-EXP")
        self.assertIsNone(receiving_item.expiry_date)
        stock = Stock.objects.get(item=self.item, batch_lot="BATCH-NO-EXP")
        self.assertIsNone(stock.expiry_date)

    def test_regular_receiving_create_normalizes_blank_batch_to_dash(self):
        self.item.requires_expiry_date = False
        self.item.save(update_fields=["requires_expiry_date", "updated_at"])

        response = self.client.post(
            reverse("receiving:receiving_create"),
            {
                "document_number": "",
                "receiving_type": Receiving.ReceivingType.GRANT,
                "receiving_date": "2026-03-16",
                "supplier": "",
                "sumber_dana": self.funding.pk,
                "notes": "",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-item": self.item.pk,
                "items-0-quantity": "10",
                "items-0-batch_lot": "",
                "items-0-expiry_date": "",
                "items-0-unit_price": "1500",
                "items-0-location": self.location.pk,
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        receiving_item = ReceivingItem.objects.get(batch_lot="-")
        self.assertEqual(receiving_item.item, self.item)
        self.assertIsNone(receiving_item.expiry_date)
        stock = Stock.objects.get(item=self.item, batch_lot="-")
        self.assertIsNone(stock.expiry_date)
        transaction = Transaction.objects.get(reference_id=receiving_item.receiving_id)
        self.assertEqual(transaction.batch_lot, "-")

    def test_regular_receiving_create_skips_opening_balance_number_collision(self):
        OpeningBalanceImport.objects.create(
            document_number="RCV-2026-00001",
            effective_date=date(2026, 1, 1),
            created_by=self.user,
        )

        response = self.client.post(
            reverse("receiving:receiving_create"),
            {
                "document_number": "IGNORED-MANUAL-NUMBER",
                "receiving_type": Receiving.ReceivingType.GRANT,
                "receiving_date": "2026-03-16",
                "supplier": "",
                "sumber_dana": self.funding.pk,
                "notes": "",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-item": self.item.pk,
                "items-0-quantity": "10",
                "items-0-batch_lot": "BATCH-OB-COLLISION",
                "items-0-expiry_date": "2030-01-01",
                "items-0-unit_price": "1500",
                "items-0-location": self.location.pk,
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        receiving = Receiving.objects.get()
        self.assertEqual(receiving.document_number, "RCV-2026-00002")
        self.assertEqual(Stock.objects.count(), 1)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_regular_receiving_create_requires_expiry_for_expiring_item(self):
        response = self.client.post(
            reverse("receiving:receiving_create"),
            {
                "document_number": "",
                "receiving_type": Receiving.ReceivingType.GRANT,
                "receiving_date": "2026-03-16",
                "supplier": "",
                "sumber_dana": self.funding.pk,
                "notes": "",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-item": self.item.pk,
                "items-0-quantity": "10",
                "items-0-batch_lot": "BATCH-001",
                "items-0-expiry_date": "",
                "items-0-unit_price": "1500",
                "items-0-location": self.location.pk,
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tanggal kedaluwarsa wajib diisi untuk barang ini.")
        self.assertEqual(Receiving.objects.count(), 0)

    def test_regular_receiving_create_allows_blank_batch_for_expiring_item(self):
        response = self.client.post(
            reverse("receiving:receiving_create"),
            {
                "document_number": "",
                "receiving_type": Receiving.ReceivingType.GRANT,
                "receiving_date": "2026-03-16",
                "supplier": "",
                "sumber_dana": self.funding.pk,
                "notes": "",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-item": self.item.pk,
                "items-0-quantity": "10",
                "items-0-batch_lot": "",
                "items-0-expiry_date": "2030-01-01",
                "items-0-unit_price": "1500",
                "items-0-location": self.location.pk,
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(ReceivingItem.objects.filter(batch_lot="-").exists())
        self.assertTrue(Stock.objects.filter(item=self.item, batch_lot="-").exists())

    def test_regular_receiving_create_allows_same_batch_with_different_expiry_for_new_document(self):
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="BATCH-DUP",
            expiry_date=date(2030, 1, 1),
            quantity=Decimal("5"),
            reserved=Decimal("0"),
            unit_price=Decimal("1500"),
            sumber_dana=self.funding,
            source_document_number="LEGACY-DOC",
        )

        response = self.client.post(
            reverse("receiving:receiving_create"),
            {
                "document_number": "",
                "receiving_type": Receiving.ReceivingType.GRANT,
                "receiving_date": "2026-03-16",
                "supplier": "",
                "sumber_dana": self.funding.pk,
                "notes": "",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-item": self.item.pk,
                "items-0-quantity": "10",
                "items-0-batch_lot": "BATCH-DUP",
                "items-0-expiry_date": "2030-02-01",
                "items-0-unit_price": "1500",
                "items-0-location": self.location.pk,
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            list(
                Stock.objects.filter(item=self.item, batch_lot="BATCH-DUP")
                .order_by("source_document_number")
                .values_list("source_document_number", "expiry_date", "quantity")
            ),
            [
                ("LEGACY-DOC", date(2030, 1, 1), Decimal("5.00")),
                (Receiving.objects.get().document_number, date(2030, 2, 1), Decimal("10.00")),
            ],
        )

    def test_regular_receiving_create_rejects_non_finite_quantity(self):
        response = self.client.post(
            reverse("receiving:receiving_create"),
            {
                "document_number": "",
                "receiving_type": Receiving.ReceivingType.GRANT,
                "receiving_date": "2026-03-16",
                "supplier": "",
                "sumber_dana": self.funding.pk,
                "notes": "",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-item": self.item.pk,
                "items-0-quantity": "NaN",
                "items-0-batch_lot": "BATCH-001",
                "items-0-expiry_date": "2030-01-01",
                "items-0-unit_price": "1500",
                "items-0-location": self.location.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Masukkan sebuah bilangan.")
        self.assertEqual(Receiving.objects.count(), 0)

    def test_regular_receiving_create_accepts_custom_receiving_type(self):
        ReceivingTypeOption.objects.create(code="DON", name="Donasi")

        response = self.client.post(
            reverse("receiving:receiving_create"),
            {
                "document_number": "",
                "receiving_type": "DON",
                "receiving_date": "2026-03-16",
                "supplier": "",
                "sumber_dana": self.funding.pk,
                "notes": "",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-item": self.item.pk,
                "items-0-quantity": "10",
                "items-0-batch_lot": "BATCH-DON-001",
                "items-0-expiry_date": "2030-01-01",
                "items-0-unit_price": "1500",
                "items-0-location": self.location.pk,
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        receiving = Receiving.objects.get(document_number__startswith="RCV-")
        self.assertEqual(receiving.receiving_type, "DON")
        self.assertEqual(receiving.receiving_type_label, "Donasi")
        self.assertEqual(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.RECEIVING,
                reference_id=receiving.pk,
                transaction_type=Transaction.TransactionType.IN,
            ).count(),
            1,
        )

    def _create_posted_regular_receiving(
        self,
        *,
        document_number="RCV-2026-CORR-001",
        quantity=Decimal("10"),
        unit_price=Decimal("1500"),
        funding=None,
    ):
        funding = funding or self.funding
        receiving = Receiving.objects.create(
            document_number=document_number,
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=funding,
            status=Receiving.Status.VERIFIED,
            is_planned=False,
            created_by=self.user,
            verified_by=self.user,
            verified_at=timezone.now(),
        )
        ReceivingItem.objects.create(
            receiving=receiving,
            item=self.item,
            quantity=quantity,
            batch_lot="BATCH-CORR-OLD",
            expiry_date=date(2030, 1, 1),
            unit_price=unit_price,
            location=self.location,
            posted_sumber_dana=funding,
            posted_source_document_number=document_number,
            received_by=self.user,
            received_at=timezone.now(),
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="BATCH-CORR-OLD",
            expiry_date=date(2030, 1, 1),
            quantity=quantity,
            reserved=Decimal("0"),
            unit_price=unit_price,
            sumber_dana=funding,
            receiving_ref=receiving,
            source_document_number=document_number,
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot="BATCH-CORR-OLD",
            quantity=quantity,
            unit_price=unit_price,
            source_document_number=document_number,
            sumber_dana=funding,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=receiving.pk,
            user=self.user,
            notes=f"Penerimaan reguler {document_number}",
        )
        return receiving

    def _regular_edit_payload(
        self,
        receiving,
        *,
        funding=None,
        quantity="7",
        unit_price="1750",
    ):
        funding = funding or receiving.sumber_dana
        item = receiving.items.get()
        return {
            "document_number": receiving.document_number,
            "receiving_type": receiving.receiving_type,
            "receiving_date": "2026-03-17",
            "supplier": "",
            "sumber_dana": funding.pk,
            "notes": "Koreksi hasil QA",
            "correction_reason": "Jumlah dan harga salah input",
            "items-TOTAL_FORMS": "1",
            "items-INITIAL_FORMS": "1",
            "items-MIN_NUM_FORMS": "0",
            "items-MAX_NUM_FORMS": "1000",
            "items-0-id": item.pk,
            "items-0-item": self.item.pk,
            "items-0-quantity": quantity,
            "items-0-batch_lot": "BATCH-CORR-OLD",
            "items-0-expiry_date": "2030-01-01",
            "items-0-unit_price": unit_price,
            "items-0-location": self.location.pk,
        }

    def test_regular_receiving_edit_reverses_old_stock_and_posts_corrected_stock(self):
        receiving = self._create_posted_regular_receiving()
        new_funding = FundingSource.objects.create(code="BLUD", name="BLUD")

        response = self.client.post(
            reverse("receiving:receiving_edit", args=[receiving.pk]),
            self._regular_edit_payload(receiving, funding=new_funding),
            secure=True,
        )

        self.assertRedirects(
            response,
            reverse("receiving:receiving_detail", args=[receiving.pk]),
            fetch_redirect_response=False,
        )
        receiving.refresh_from_db()
        self.assertEqual(receiving.sumber_dana, new_funding)
        self.assertEqual(receiving.receiving_date, date(2026, 3, 17))
        self.assertEqual(receiving.items.get().quantity, Decimal("7"))
        reversed_stock = Stock.objects.get(
            source_document_number=receiving.document_number,
            sumber_dana=self.funding,
        )
        self.assertEqual(reversed_stock.quantity, Decimal("0"))
        corrected_stock = Stock.objects.get(
            source_document_number=receiving.document_number,
            sumber_dana=new_funding,
        )
        self.assertEqual(corrected_stock.quantity, Decimal("7"))
        self.assertEqual(corrected_stock.unit_price, Decimal("1750"))
        transactions = Transaction.objects.filter(
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=receiving.pk,
        ).order_by("created_at", "pk")
        self.assertEqual(transactions.count(), 3)
        self.assertEqual(
            list(transactions.values_list("transaction_type", "quantity")),
            [
                (Transaction.TransactionType.IN, Decimal("10.00")),
                (Transaction.TransactionType.OUT, Decimal("10.00")),
                (Transaction.TransactionType.IN, Decimal("7.00")),
            ],
        )

    def test_regular_receiving_edit_preserves_omitted_optional_expiry_date(self):
        self.item.requires_expiry_date = False
        self.item.save(update_fields=["requires_expiry_date", "updated_at"])
        receiving = self._create_posted_regular_receiving()
        payload = self._regular_edit_payload(receiving, quantity="8")
        payload.pop("items-0-expiry_date")

        response = self.client.post(
            reverse("receiving:receiving_edit", args=[receiving.pk]),
            payload,
            secure=True,
        )

        self.assertRedirects(
            response,
            reverse("receiving:receiving_detail", args=[receiving.pk]),
            fetch_redirect_response=False,
        )
        corrected_item = receiving.items.get()
        self.assertEqual(corrected_item.quantity, Decimal("8"))
        self.assertEqual(corrected_item.expiry_date, date(2030, 1, 1))
        corrected_stock = Stock.objects.get(
            source_document_number=receiving.document_number,
            sumber_dana=self.funding,
        )
        self.assertEqual(corrected_stock.quantity, Decimal("8"))
        self.assertEqual(corrected_stock.expiry_date, date(2030, 1, 1))

    def test_regular_receiving_edit_renders_stale_hidden_id_error(self):
        receiving = self._create_posted_regular_receiving()
        payload = self._regular_edit_payload(receiving, quantity="8")
        ReceivingItem.objects.filter(pk=payload["items-0-id"]).delete()

        response = self.client.post(
            reverse("receiving:receiving_edit", args=[receiving.pk]),
            payload,
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Baris item tidak valid")
        self.assertContains(response, "Masukkan pilihan yang valid")

    def test_regular_receiving_edit_reverses_imported_row_funding_override(self):
        row_funding = FundingSource.objects.create(code="ROWEDIT", name="Row Edit")
        receiving = self._create_posted_regular_receiving(funding=row_funding)
        receiving.sumber_dana = self.funding
        receiving.save(update_fields=["sumber_dana", "updated_at"])

        response = self.client.post(
            reverse("receiving:receiving_edit", args=[receiving.pk]),
            self._regular_edit_payload(receiving, funding=self.funding),
            secure=True,
        )

        self.assertRedirects(
            response,
            reverse("receiving:receiving_detail", args=[receiving.pk]),
            fetch_redirect_response=False,
        )
        row_stock = Stock.objects.get(
            source_document_number=receiving.document_number,
            sumber_dana=row_funding,
        )
        self.assertEqual(row_stock.quantity, Decimal("0"))
        corrected_stock = Stock.objects.get(
            source_document_number=receiving.document_number,
            sumber_dana=self.funding,
        )
        self.assertEqual(corrected_stock.quantity, Decimal("7"))
        self.assertEqual(
            list(
                Transaction.objects.filter(
                    reference_type=Transaction.ReferenceType.RECEIVING,
                    reference_id=receiving.pk,
                )
                .order_by("created_at", "pk")
                .values_list("transaction_type", "sumber_dana", "quantity")
            ),
            [
                (Transaction.TransactionType.IN, row_funding.pk, Decimal("10.00")),
                (Transaction.TransactionType.OUT, row_funding.pk, Decimal("10.00")),
                (Transaction.TransactionType.IN, self.funding.pk, Decimal("7.00")),
            ],
        )

    def test_regular_receiving_delete_reverses_current_layer_after_imported_override_edit(self):
        row_funding = FundingSource.objects.create(code="ROWCURR", name="Row Current")
        receiving = self._create_posted_regular_receiving(funding=row_funding)
        receiving.sumber_dana = self.funding
        receiving.save(update_fields=["sumber_dana", "updated_at"])

        first_response = self.client.post(
            reverse("receiving:receiving_edit", args=[receiving.pk]),
            self._regular_edit_payload(
                receiving,
                funding=self.funding,
                quantity="10",
                unit_price="1500",
            ),
            secure=True,
        )

        self.assertRedirects(
            first_response,
            reverse("receiving:receiving_detail", args=[receiving.pk]),
            fetch_redirect_response=False,
        )
        row_stock = Stock.objects.get(
            source_document_number=receiving.document_number,
            sumber_dana=row_funding,
        )
        self.assertEqual(row_stock.quantity, Decimal("0"))
        current_stock = Stock.objects.get(
            source_document_number=receiving.document_number,
            sumber_dana=self.funding,
        )
        self.assertEqual(current_stock.quantity, Decimal("10"))

        second_response = self.client.post(
            reverse("receiving:receiving_delete", args=[receiving.pk]),
            {"cancel_reason": "Batalkan setelah koreksi sumber dana"},
            secure=True,
        )

        self.assertRedirects(
            second_response,
            reverse("receiving:receiving_detail", args=[receiving.pk]),
            fetch_redirect_response=False,
        )
        current_stock.refresh_from_db()
        self.assertEqual(current_stock.quantity, Decimal("0"))
        receiving.refresh_from_db()
        self.assertEqual(receiving.status, Receiving.Status.CANCELLED)
        self.assertEqual(
            list(
                Transaction.objects.filter(
                    reference_type=Transaction.ReferenceType.RECEIVING,
                    reference_id=receiving.pk,
                )
                .order_by("created_at", "pk")
                .values_list("transaction_type", "sumber_dana", "quantity")
            ),
            [
                (Transaction.TransactionType.IN, row_funding.pk, Decimal("10.00")),
                (Transaction.TransactionType.OUT, row_funding.pk, Decimal("10.00")),
                (Transaction.TransactionType.IN, self.funding.pk, Decimal("10.00")),
                (Transaction.TransactionType.OUT, self.funding.pk, Decimal("10.00")),
            ],
        )

    def test_regular_receiving_edit_preserves_effective_received_at_date(self):
        original_received_at = timezone.make_aware(datetime(2026, 3, 16, 8, 30, 0))
        receiving = self._create_posted_regular_receiving()
        item = receiving.items.get()
        item.received_at = original_received_at
        item.save(update_fields=["received_at"])

        response = self.client.post(
            reverse("receiving:receiving_edit", args=[receiving.pk]),
            self._regular_edit_payload(receiving),
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        corrected_item = receiving.items.get()
        local_received_at = timezone.localtime(corrected_item.received_at)
        self.assertEqual(local_received_at.date(), date(2026, 3, 17))
        self.assertEqual(local_received_at.time().replace(tzinfo=None), time(8, 30, 0))

    def test_regular_receiving_edit_reports_stock_layer_mismatch_as_form_error(self):
        receiving = self._create_posted_regular_receiving()
        item = receiving.items.get()
        payload = self._regular_edit_payload(receiving)
        payload.update(
            {
                "items-TOTAL_FORMS": "2",
                "items-1-id": "",
                "items-1-item": self.item.pk,
                "items-1-quantity": "3",
                "items-1-batch_lot": "BATCH-CORR-OLD",
                "items-1-expiry_date": "2031-01-01",
                "items-1-unit_price": "1750",
                "items-1-location": self.location.pk,
            }
        )

        response = self.client.post(
            reverse("receiving:receiving_edit", args=[receiving.pk]),
            payload,
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Batch stok yang sama tidak boleh memiliki tanggal kedaluwarsa berbeda.",
        )
        self.assertTrue(ReceivingItem.objects.filter(pk=item.pk).exists())
        stock = Stock.objects.get(source_document_number=receiving.document_number)
        self.assertEqual(stock.quantity, Decimal("10"))
        self.assertEqual(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.RECEIVING,
                reference_id=receiving.pk,
            ).count(),
            1,
        )

    def test_regular_receiving_edit_retains_inactive_historical_receiving_type(self):
        receiving_type = ReceivingTypeOption.objects.create(
            code="HIBAH_KHUSUS",
            name="Hibah Khusus",
            is_active=True,
        )
        receiving = self._create_posted_regular_receiving()
        receiving.receiving_type = receiving_type.code
        receiving.save(update_fields=["receiving_type", "updated_at"])
        receiving_type.is_active = False
        receiving_type.save(update_fields=["is_active", "updated_at"])

        response = self.client.get(
            reverse("receiving:receiving_edit", args=[receiving.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="HIBAH_KHUSUS" selected', html=False)

        payload = self._regular_edit_payload(receiving)
        payload["receiving_type"] = "HIBAH_KHUSUS"
        response = self.client.post(
            reverse("receiving:receiving_edit", args=[receiving.pk]),
            payload,
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        receiving.refresh_from_db()
        self.assertEqual(receiving.receiving_type, "HIBAH_KHUSUS")

    def test_regular_receiving_edit_enforces_supplier_for_inactive_historical_type(self):
        supplier = Supplier.objects.create(
            code="SUP-HIST",
            name="Supplier Historical",
        )
        receiving_type = ReceivingTypeOption.objects.create(
            code="PENGADAAN_LAMA",
            name="Pengadaan Lama",
            is_active=True,
            requires_supplier=True,
        )
        receiving = self._create_posted_regular_receiving()
        receiving.receiving_type = receiving_type.code
        receiving.supplier = supplier
        receiving.save(update_fields=["receiving_type", "supplier", "updated_at"])
        receiving_type.is_active = False
        receiving_type.save(update_fields=["is_active", "updated_at"])

        payload = self._regular_edit_payload(receiving)
        payload["receiving_type"] = "PENGADAAN_LAMA"
        payload["supplier"] = ""
        response = self.client.post(
            reverse("receiving:receiving_edit", args=[receiving.pk]),
            payload,
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Supplier wajib diisi untuk tipe penerimaan ini.",
        )
        receiving.refresh_from_db()
        self.assertEqual(receiving.supplier, supplier)
        self.assertEqual(receiving.items.get().quantity, Decimal("10"))
        self.assertEqual(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.RECEIVING,
                reference_id=receiving.pk,
            ).count(),
            1,
        )

    def test_regular_receiving_edit_preserves_zero_stock_with_draft_transfer_reference(self):
        receiving = self._create_posted_regular_receiving()
        stock = Stock.objects.get(source_document_number=receiving.document_number)
        destination = Location.objects.create(
            code="LOC-CORR-EDIT",
            name="Gudang Koreksi Edit",
        )
        transfer = StockTransfer.objects.create(
            source_location=self.location,
            destination_location=destination,
            created_by=self.user,
            status=StockTransfer.Status.DRAFT,
        )
        StockTransferItem.objects.create(
            transfer=transfer,
            stock=stock,
            item=self.item,
            quantity=Decimal("4"),
        )
        new_funding = FundingSource.objects.create(code="BTT", name="BTT")

        response = self.client.post(
            reverse("receiving:receiving_edit", args=[receiving.pk]),
            self._regular_edit_payload(receiving, funding=new_funding),
            secure=True,
        )

        self.assertRedirects(
            response,
            reverse("receiving:receiving_detail", args=[receiving.pk]),
            fetch_redirect_response=False,
        )
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, Decimal("0"))
        self.assertTrue(StockTransferItem.objects.filter(stock=stock).exists())
        corrected_stock = Stock.objects.get(
            source_document_number=receiving.document_number,
            sumber_dana=new_funding,
        )
        self.assertEqual(corrected_stock.quantity, Decimal("7"))

    def test_regular_receiving_edit_displays_trimmed_unit_price(self):
        receiving = self._create_posted_regular_receiving(unit_price=Decimal("120"))
        form = ReceivingItemForm(instance=receiving.items.get(), prefix="items-0")

        self.assertIn('value="120"', str(form["unit_price"]))
        self.assertNotIn("120.0000000000", str(form["unit_price"]))

    def test_regular_receiving_item_form_accepts_comma_decimal_unit_price(self):
        form = ReceivingItemForm(
            data={
                "item": self.item.pk,
                "quantity": "1",
                "batch_lot": "FORM-IDPRICE",
                "expiry_date": "2030-01-01",
                "unit_price": "1500,50",
                "location": self.location.pk,
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["unit_price"], Decimal("1500.50"))

    def test_regular_receiving_item_form_rejects_dot_decimal_unit_price(self):
        form = ReceivingItemForm(
            data={
                "item": self.item.pk,
                "quantity": "1",
                "batch_lot": "FORM-DOTPRICE",
                "expiry_date": "2030-01-01",
                "unit_price": "1500.50",
                "location": self.location.pk,
            }
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["unit_price"],
            ["Gunakan angka tanpa pemisah ribuan. Gunakan koma untuk desimal."],
        )

    def test_regular_receiving_edit_accepts_comma_decimal_unit_price(self):
        receiving = self._create_posted_regular_receiving()

        response = self.client.post(
            reverse("receiving:receiving_edit", args=[receiving.pk]),
            self._regular_edit_payload(receiving, unit_price="1750,50"),
            secure=True,
        )

        self.assertRedirects(
            response,
            reverse("receiving:receiving_detail", args=[receiving.pk]),
            fetch_redirect_response=False,
        )
        receiving.refresh_from_db()
        corrected_item = receiving.items.get()
        corrected_stock = Stock.objects.get(
            source_document_number=receiving.document_number,
            batch_lot="BATCH-CORR-OLD",
        )
        self.assertEqual(corrected_item.unit_price, Decimal("1750.50"))
        self.assertEqual(corrected_stock.unit_price, Decimal("1750.50"))

    def test_regular_receiving_edit_rejects_dot_decimal_unit_price(self):
        receiving = self._create_posted_regular_receiving()

        response = self.client.post(
            reverse("receiving:receiving_edit", args=[receiving.pk]),
            self._regular_edit_payload(receiving, unit_price="1750.50"),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Gunakan angka tanpa pemisah ribuan. Gunakan koma untuk desimal.",
        )
        receiving.refresh_from_db()
        self.assertEqual(receiving.items.get().unit_price, Decimal("1500"))
        self.assertEqual(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.RECEIVING,
                reference_id=receiving.pk,
            ).count(),
            1,
        )

    def test_regular_receiving_edit_blocks_when_stock_is_reserved(self):
        receiving = self._create_posted_regular_receiving()
        stock = Stock.objects.get(source_document_number=receiving.document_number)
        stock.reserved = Decimal("4")
        stock.save(update_fields=["reserved", "updated_at"])

        response = self.client.post(
            reverse("receiving:receiving_edit", args=[receiving.pk]),
            self._regular_edit_payload(receiving),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "sudah dipakai atau direservasi")
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, Decimal("10"))
        self.assertEqual(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.RECEIVING,
                reference_id=receiving.pk,
            ).count(),
            1,
        )

    def test_regular_receiving_delete_cancels_and_reverses_stock(self):
        receiving = self._create_posted_regular_receiving()

        response = self.client.post(
            reverse("receiving:receiving_delete", args=[receiving.pk]),
            {"cancel_reason": "Dobel input oleh petugas berbeda"},
            secure=True,
        )

        self.assertRedirects(
            response,
            reverse("receiving:receiving_detail", args=[receiving.pk]),
            fetch_redirect_response=False,
        )
        receiving.refresh_from_db()
        self.assertEqual(receiving.status, Receiving.Status.CANCELLED)
        self.assertEqual(receiving.cancelled_by, self.user)
        self.assertEqual(receiving.cancel_reason, "Dobel input oleh petugas berbeda")
        reversed_stock = Stock.objects.get(
            source_document_number=receiving.document_number
        )
        self.assertEqual(reversed_stock.quantity, Decimal("0"))
        self.assertEqual(
            list(
                Transaction.objects.filter(
                    reference_type=Transaction.ReferenceType.RECEIVING,
                    reference_id=receiving.pk,
                )
                .order_by("created_at", "pk")
                .values_list("transaction_type", "quantity")
            ),
            [
                (Transaction.TransactionType.IN, Decimal("10.00")),
                (Transaction.TransactionType.OUT, Decimal("10.00")),
            ],
        )

    def test_regular_receiving_delete_reverses_imported_row_funding_override(self):
        row_funding = FundingSource.objects.create(code="ROWDEL", name="Row Delete")
        receiving = self._create_posted_regular_receiving(funding=row_funding)
        receiving.sumber_dana = self.funding
        receiving.save(update_fields=["sumber_dana", "updated_at"])

        response = self.client.post(
            reverse("receiving:receiving_delete", args=[receiving.pk]),
            {"cancel_reason": "Dobel input impor CSV"},
            secure=True,
        )

        self.assertRedirects(
            response,
            reverse("receiving:receiving_detail", args=[receiving.pk]),
            fetch_redirect_response=False,
        )
        receiving.refresh_from_db()
        self.assertEqual(receiving.status, Receiving.Status.CANCELLED)
        row_stock = Stock.objects.get(
            source_document_number=receiving.document_number,
            sumber_dana=row_funding,
        )
        self.assertEqual(row_stock.quantity, Decimal("0"))
        self.assertEqual(
            list(
                Transaction.objects.filter(
                    reference_type=Transaction.ReferenceType.RECEIVING,
                    reference_id=receiving.pk,
                )
                .order_by("created_at", "pk")
                .values_list("transaction_type", "sumber_dana", "quantity")
            ),
            [
                (Transaction.TransactionType.IN, row_funding.pk, Decimal("10.00")),
                (Transaction.TransactionType.OUT, row_funding.pk, Decimal("10.00")),
            ],
        )

    def test_regular_receiving_delete_disambiguates_identical_imported_rows_by_funding_layer(self):
        row_funding_a = FundingSource.objects.create(code="ROWA", name="Row A")
        row_funding_b = FundingSource.objects.create(code="ROWB", name="Row B")
        receiving = Receiving.objects.create(
            document_number="RCV-2026-CORR-DUP-FUND",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.VERIFIED,
            is_planned=False,
            created_by=self.user,
            verified_by=self.user,
            verified_at=timezone.now(),
        )
        for funding in (row_funding_a, row_funding_b):
            ReceivingItem.objects.create(
                receiving=receiving,
                item=self.item,
                quantity=Decimal("10"),
                batch_lot="BATCH-CORR-DUP",
                expiry_date=date(2030, 1, 1),
                unit_price=Decimal("1500"),
                location=self.location,
                posted_sumber_dana=funding,
                posted_source_document_number=receiving.document_number,
                received_by=self.user,
                received_at=timezone.now(),
            )
            Stock.objects.create(
                item=self.item,
                location=self.location,
                batch_lot="BATCH-CORR-DUP",
                expiry_date=date(2030, 1, 1),
                quantity=Decimal("10"),
                reserved=Decimal("0"),
                unit_price=Decimal("1500"),
                sumber_dana=funding,
                receiving_ref=receiving,
                source_document_number=receiving.document_number,
            )
            Transaction.objects.create(
                transaction_type=Transaction.TransactionType.IN,
                item=self.item,
                location=self.location,
                batch_lot="BATCH-CORR-DUP",
                quantity=Decimal("10"),
                unit_price=Decimal("1500"),
                source_document_number=receiving.document_number,
                sumber_dana=funding,
                reference_type=Transaction.ReferenceType.RECEIVING,
                reference_id=receiving.pk,
                user=self.user,
                notes=f"Penerimaan reguler {receiving.document_number}",
            )

        response = self.client.post(
            reverse("receiving:receiving_delete", args=[receiving.pk]),
            {"cancel_reason": "Dobel input impor CSV identik"},
            secure=True,
        )

        self.assertRedirects(
            response,
            reverse("receiving:receiving_detail", args=[receiving.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            list(
                Stock.objects.filter(source_document_number=receiving.document_number)
                .order_by("sumber_dana__code")
                .values_list("sumber_dana__code", "quantity")
            ),
            [
                ("ROWA", Decimal("0.00")),
                ("ROWB", Decimal("0.00")),
            ],
        )
        self.assertEqual(
            list(
                Transaction.objects.filter(
                    reference_type=Transaction.ReferenceType.RECEIVING,
                    reference_id=receiving.pk,
                )
                .order_by("created_at", "pk")
                .values_list("transaction_type", "sumber_dana__code", "quantity")
            ),
            [
                (Transaction.TransactionType.IN, "ROWA", Decimal("10.00")),
                (Transaction.TransactionType.IN, "ROWB", Decimal("10.00")),
                (Transaction.TransactionType.OUT, "ROWA", Decimal("10.00")),
                (Transaction.TransactionType.OUT, "ROWB", Decimal("10.00")),
            ],
        )

    def test_regular_receiving_delete_preserves_zero_stock_with_draft_transfer_reference(self):
        receiving = self._create_posted_regular_receiving()
        stock = Stock.objects.get(source_document_number=receiving.document_number)
        destination = Location.objects.create(
            code="LOC-CORR-DEST",
            name="Gudang Koreksi Tujuan",
        )
        transfer = StockTransfer.objects.create(
            source_location=self.location,
            destination_location=destination,
            created_by=self.user,
            status=StockTransfer.Status.DRAFT,
        )
        StockTransferItem.objects.create(
            transfer=transfer,
            stock=stock,
            item=self.item,
            quantity=Decimal("4"),
        )

        response = self.client.post(
            reverse("receiving:receiving_delete", args=[receiving.pk]),
            {"cancel_reason": "Dobel input"},
            secure=True,
        )

        self.assertRedirects(
            response,
            reverse("receiving:receiving_detail", args=[receiving.pk]),
            fetch_redirect_response=False,
        )
        receiving.refresh_from_db()
        stock.refresh_from_db()
        self.assertEqual(receiving.status, Receiving.Status.CANCELLED)
        self.assertEqual(stock.quantity, Decimal("0"))
        self.assertTrue(StockTransferItem.objects.filter(stock=stock).exists())

    def test_regular_receiving_delete_blocks_when_stock_was_consumed(self):
        receiving = self._create_posted_regular_receiving()
        stock = Stock.objects.get(source_document_number=receiving.document_number)
        stock.quantity = Decimal("3")
        stock.save(update_fields=["quantity", "updated_at"])

        response = self.client.post(
            reverse("receiving:receiving_delete", args=[receiving.pk]),
            {"cancel_reason": "Dobel input"},
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "sudah dipakai atau direservasi")
        receiving.refresh_from_db()
        self.assertEqual(receiving.status, Receiving.Status.VERIFIED)
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, Decimal("3"))

    def test_regular_receiving_correction_role_gate_allows_gudang_and_kepala_only(self):
        receiving = self._create_posted_regular_receiving()
        allowed_roles = [User.Role.GUDANG, User.Role.KEPALA]
        denied_roles = [User.Role.ADMIN_UMUM, User.Role.AUDITOR]

        for role in allowed_roles:
            user = User.objects.create_user(
                username=f"allowed-{role.lower()}",
                password="secret12345",
                role=role,
            )
            ensure_default_module_access(user)
            self.client.force_login(user)
            response = self.client.get(
                reverse("receiving:receiving_edit", args=[receiving.pk]),
                secure=True,
            )
            self.assertEqual(response.status_code, 200)

        for role in denied_roles:
            user = User.objects.create_user(
                username=f"denied-{role.lower()}",
                password="secret12345",
                role=role,
            )
            ensure_default_module_access(user)
            self.client.force_login(user)
            response = self.client.get(
                reverse("receiving:receiving_edit", args=[receiving.pk]),
                secure=True,
            )
            self.assertEqual(response.status_code, 403)

    def test_regular_receiving_detail_hides_correction_actions_without_operate_scope(self):
        receiving = self._create_posted_regular_receiving()
        user = User.objects.create_user(
            username="gudang-view-only",
            password="secret12345",
            role=User.Role.GUDANG,
        )
        ensure_default_module_access(user)
        ModuleAccess.objects.filter(
            user=user,
            module=ModuleAccess.Module.RECEIVING,
        ).update(scope=ModuleAccess.Scope.VIEW)
        self.client.force_login(user)

        response = self.client.get(
            reverse("receiving:receiving_detail", args=[receiving.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_correct_receiving"])
        self.assertNotContains(response, reverse("receiving:receiving_edit", args=[receiving.pk]))
        self.assertNotContains(response, reverse("receiving:receiving_delete", args=[receiving.pk]))


    def test_plan_close_blocked_when_remaining_items_not_cancelled(self):
        receiving = Receiving.objects.create(
            document_number="RCV-2026-99998",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )
        order_item = ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=self.item,
            planned_quantity=Decimal("5"),
            received_quantity=Decimal("0"),
            unit_price=Decimal("1000"),
            is_cancelled=False,
        )

        response = self.client.post(
            reverse("receiving:receiving_plan_close_items", args=[receiving.pk]),
            {
                "order_items-TOTAL_FORMS": "1",
                "order_items-INITIAL_FORMS": "1",
                "order_items-MIN_NUM_FORMS": "0",
                "order_items-MAX_NUM_FORMS": "1000",
                "order_items-0-id": order_item.pk,
                "order_items-0-is_cancelled": "",
                "order_items-0-cancel_reason": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        receiving.refresh_from_db()
        self.assertNotEqual(receiving.status, Receiving.Status.CLOSED)

    def test_contract_linked_plan_detail_routes_close_action_to_amendment(self):
        receiving = self._create_contract_linked_plan()

        response = self.client.get(
            reverse("receiving:receiving_plan_detail", args=[receiving.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Buat Amandemen")
        self.assertContains(
            response,
            reverse("procurement:amendment_create", args=[receiving.contract_id]),
        )
        self.assertNotContains(
            response,
            reverse("receiving:receiving_plan_close_items", args=[receiving.pk]),
        )

    def test_manual_plan_detail_keeps_receiving_close_action(self):
        receiving = Receiving.objects.create(
            document_number="RCV-2026-MANUALCLOSE",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )

        response = self.client.get(
            reverse("receiving:receiving_plan_detail", args=[receiving.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tutup Sisa")
        self.assertContains(
            response,
            reverse("receiving:receiving_plan_close_items", args=[receiving.pk]),
        )

    def test_plan_detail_formats_quantities_without_decimals(self):
        receiving = Receiving.objects.create(
            document_number="RCV-2026-QTYFORMAT",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.PARTIAL,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )
        ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=self.item,
            planned_quantity=Decimal("50000"),
            received_quantity=Decimal("10000"),
            unit_price=Decimal("1000"),
            is_cancelled=False,
        )

        response = self.client.get(
            reverse("receiving:receiving_plan_detail", args=[receiving.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "50000")
        self.assertContains(response, "10000")
        self.assertContains(response, "40000")
        self.assertNotContains(response, "50.000")
        self.assertNotContains(response, "10.000")
        self.assertNotContains(response, "40.000")
        self.assertNotContains(response, "50.000,00")
        self.assertNotContains(response, "10.000,00")
        self.assertNotContains(response, "40.000,00")

    def test_contract_linked_plan_close_items_redirects_to_amendment(self):
        receiving = self._create_contract_linked_plan()

        response = self.client.post(
            reverse("receiving:receiving_plan_close_items", args=[receiving.pk]),
            {
                "order_items-TOTAL_FORMS": "1",
                "order_items-INITIAL_FORMS": "1",
                "order_items-MIN_NUM_FORMS": "0",
                "order_items-MAX_NUM_FORMS": "1000",
                "order_items-0-id": receiving.order_items.get().pk,
                "order_items-0-is_cancelled": "on",
                "order_items-0-cancel_reason": "Sisa tidak diterima",
            },
            secure=True,
        )

        self.assertRedirects(
            response,
            reverse("procurement:amendment_create", args=[receiving.contract_id]),
            fetch_redirect_response=False,
        )
        receiving.refresh_from_db()
        self.assertEqual(receiving.status, Receiving.Status.APPROVED)
        self.assertFalse(receiving.order_items.get().is_cancelled)

    def test_quick_create_supplier_creates_normalized_lookup(self):
        response = self.client.post(
            reverse("receiving:quick_create_supplier"),
            {
                "code": " sup-01 ",
                "name": "  PT   Farmasi Nusantara  ",
                "address": "  Jl.  Merdeka   10  ",
                "phone": " 08123  ",
                "email": "vendor@example.com",
                "notes": "  Mitra   utama  ",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        supplier = Supplier.objects.get(code="SUP-01")
        self.assertEqual(supplier.name, "PT Farmasi Nusantara")
        self.assertEqual(supplier.address, "Jl. Merdeka 10")
        self.assertEqual(supplier.phone, "08123")
        self.assertEqual(supplier.notes, "Mitra utama")

    def test_quick_create_supplier_rejects_invalid_email(self):
        response = self.client.post(
            reverse("receiving:quick_create_supplier"),
            {"code": "SUP-01", "name": "PT Farmasi", "email": "tidak-valid"},
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Masukkan alamat email yang valid.", response.json()["error"])
        self.assertEqual(Supplier.objects.count(), 0)

    def test_quick_create_supplier_rejects_null_byte_input(self):
        response = self.client.post(
            reverse("receiving:quick_create_supplier"),
            {"code": "SUP-01", "name": "PT Farma\x00si"},
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Karakter null tidak diizinkan.", response.json()["error"])
        self.assertEqual(Supplier.objects.count(), 0)

    def test_quick_create_supplier_rejects_duplicate_name_case_insensitive(self):
        Supplier.objects.create(code="SUP-00", name="PT Farmasi Nusantara")

        response = self.client.post(
            reverse("receiving:quick_create_supplier"),
            {"code": "SUP-01", "name": "  pt   farmasi   nusantara  "},
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Nama sudah digunakan", response.json()["error"])
        self.assertEqual(Supplier.objects.count(), 1)

    def test_quick_create_funding_source_creates_normalized_lookup(self):
        response = self.client.post(
            reverse("receiving:quick_create_funding_source"),
            {
                "code": " apbn ",
                "name": "  Dana   Alokasi Khusus  ",
                "description": "  Bantuan   pusat  ",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        funding = FundingSource.objects.get(code="APBN")
        self.assertEqual(funding.name, "Dana Alokasi Khusus")
        self.assertEqual(funding.description, "Bantuan pusat")

    def test_quick_create_funding_source_rejects_overlong_code(self):
        response = self.client.post(
            reverse("receiving:quick_create_funding_source"),
            {"code": "X" * 21, "name": "Dana Baru"},
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("paling banyak 20 karakter", response.json()["error"])
        self.assertEqual(FundingSource.objects.count(), 1)

    def test_quick_create_funding_source_rejects_duplicate_name_case_insensitive(self):
        FundingSource.objects.create(code="DAU", name="Dana Alokasi Umum")

        response = self.client.post(
            reverse("receiving:quick_create_funding_source"),
            {"code": "DAU-2", "name": "  dana   alokasi umum  "},
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Nama sudah digunakan", response.json()["error"])

    def test_quick_create_receiving_type_adds_option_to_form_choices(self):
        response = self.client.post(
            reverse("receiving:quick_create_receiving_type"),
            {"code": "MUTASI", "name": "Mutasi Internal"},
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(ReceivingTypeOption.objects.filter(code="MUTASI").exists())

        form_page = self.client.get(
            reverse("receiving:receiving_create"),
            secure=True,
        )
        self.assertEqual(form_page.status_code, 200)
        self.assertContains(form_page, "Mutasi Internal")

        create_response = self.client.post(
            reverse("receiving:receiving_create"),
            {
                "document_number": "",
                "receiving_type": "MUTASI",
                "receiving_date": "2026-03-16",
                "supplier": "",
                "sumber_dana": self.funding.pk,
                "notes": "",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-item": self.item.pk,
                "items-0-quantity": "4",
                "items-0-batch_lot": "BATCH-MUT-001",
                "items-0-expiry_date": "2030-01-01",
                "items-0-unit_price": "1000",
                "items-0-location": self.location.pk,
            },
            secure=True,
        )

        self.assertEqual(create_response.status_code, 302)
        self.assertTrue(Receiving.objects.filter(receiving_type="MUTASI").exists())

    def test_quick_create_receiving_type_rejects_builtin_code(self):
        response = self.client.post(
            reverse("receiving:quick_create_receiving_type"),
            {"code": "GRANT", "name": "Hibah Khusus"},
            secure=True,
        )
        self.assertEqual(response.status_code, 400)

    def test_quick_create_receiving_type_rejects_reserved_internal_code(self):
        response = self.client.post(
            reverse("receiving:quick_create_receiving_type"),
            {"code": "RETURN_RS", "name": "Pengembalian RS"},
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(ReceivingTypeOption.objects.filter(code="RETURN_RS").exists())

    def test_quick_create_receiving_type_rejects_duplicate_name_case_insensitive(self):
        ReceivingTypeOption.objects.create(code="MUTASI", name="Mutasi Internal")

        response = self.client.post(
            reverse("receiving:quick_create_receiving_type"),
            {"code": "MUT-2", "name": "  mutasi   internal  "},
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Nama sudah digunakan", response.json()["error"])

    @override_settings(ITEM_MUTATION_RATE_LIMIT="1/m", RATELIMIT_USE_CACHE="locmem")
    def test_receiving_quick_create_uses_shared_item_mutation_rate_limit(self):
        first = self.client.post(
            reverse("receiving:quick_create_supplier"),
            {"code": "SUP-01", "name": "PT Farmasi"},
            secure=True,
        )
        second = self.client.post(
            reverse("receiving:quick_create_supplier"),
            {"code": "SUP-02", "name": "PT Farmasi Dua"},
            secure=True,
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)

    def test_receiving_item_forms_use_name_only_item_labels(self):
        self.item.nama_barang = "Paracetamol 500mg [P]"
        self.item.save(update_fields=["nama_barang", "updated_at"])

        receiving_form = ReceivingOrderItemForm()
        receipt_form = ReceivingForm()

        self.assertEqual(receiving_form.fields["item"].label_from_instance(self.item), "Paracetamol 500mg")
        self.assertNotIn("kode_barang", receipt_form.fields)

    def test_receiving_str_uses_safe_label_for_builtin_and_custom_types(self):
        builtin_receiving = Receiving.objects.create(
            document_number="RCV-2026-STR-001",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.VERIFIED,
            created_by=self.user,
            verified_by=self.user,
        )
        ReceivingTypeOption.objects.create(code="DON", name="Donasi")
        custom_receiving = Receiving.objects.create(
            document_number="RCV-2026-STR-002",
            receiving_type="DON",
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.VERIFIED,
            created_by=self.user,
            verified_by=self.user,
        )

        self.assertEqual(str(builtin_receiving), "RCV-2026-STR-001 (Hibah)")
        self.assertEqual(str(custom_receiving), "RCV-2026-STR-002 (Donasi)")

    def test_receiving_create_includes_item_picker_table_script(self):
        response = self.client.get(reverse("receiving:receiving_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "js/item-picker-table.js?v=")

    def test_receiving_create_marks_required_item_table_headers(self):
        response = self.client.get(reverse("receiving:receiving_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Barang <span class=\"text-danger\">*</span>", html=False)
        self.assertContains(response, "Kuantitas <span class=\"text-danger\">*</span>", html=False)
        self.assertContains(response, "Harga Satuan <span class=\"text-danger\">*</span>", html=False)
        self.assertContains(response, "Lokasi <span class=\"text-danger\">*</span>", html=False)
        self.assertContains(response, "Tanggal Kedaluwarsa", html=False)
        self.assertContains(response, "(jika wajib)", html=False)

    def test_receiving_create_item_options_include_expiry_requirement_metadata(self):
        self.item.requires_expiry_date = False
        self.item.save(update_fields=["requires_expiry_date", "updated_at"])

        response = self.client.get(reverse("receiving:receiving_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="{}"'.format(self.item.pk), html=False)
        self.assertContains(
            response,
            'data-requires-expiry-date="false"',
            html=False,
        )

    def test_receiving_plan_create_redirects_to_spj_create(self):
        response = self.client.get(reverse("receiving:receiving_plan_create"), secure=True)

        self.assertRedirects(
            response,
            reverse("procurement:contract_create"),
            fetch_redirect_response=False,
        )

    def test_regular_receiving_list_does_not_show_redundant_status_filter(self):
        Receiving.objects.create(
            document_number="RCV-2026-99994",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.VERIFIED,
            is_planned=False,
            created_by=self.user,
            verified_by=self.user,
        )

        response = self.client.get(reverse("receiving:receiving_list"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="status"', html=False)
        self.assertNotContains(response, 'Status:</span>', html=False)
        self.assertContains(response, 'badge-status badge-verified', html=False)

    def test_regular_receiving_list_uses_preloaded_type_labels(self):
        ReceivingTypeOption.objects.create(code="DON", name="Donasi")
        Receiving.objects.create(
            document_number="RCV-2026-LABEL-001",
            receiving_type="DON",
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.VERIFIED,
            is_planned=False,
            created_by=self.user,
            verified_by=self.user,
        )

        with patch.object(
            Receiving,
            "receiving_type_label",
            new_callable=PropertyMock,
            side_effect=AssertionError("List views must not call receiving_type_label."),
        ):
            response = self.client.get(reverse("receiving:receiving_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Donasi")

    def test_regular_receiving_create_page_does_not_show_rs_settlement_column(self):
        response = self.client.get(reverse("receiving:receiving_create"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Dokumen RS Asal")
        self.assertNotContains(response, 'name="items-0-settlement_distribution_item"', html=False)

    def test_regular_receiving_create_page_hides_facility_and_shows_required_markers(self):
        response = self.client.get(reverse("receiving:receiving_create"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="facility"', html=False)
        self.assertNotContains(response, 'name="document_number"', html=False)
        self.assertContains(
            response,
            "Nomor dokumen resmi diterbitkan otomatis ketika stok penerimaan diposting.",
        )
        self.assertContains(response, 'name="receiving_date"', html=False)
        self.assertContains(response, 'placeholder="DD/MM/YYYY"', html=False)
        self.assertContains(response, 'data-native-date-picker="true"', html=False)
        self.assertContains(response, 'class="form-control js-date-mask"', html=False)
        self.assertContains(response, 'class="form-control form-control-sm js-date-mask"', html=False)
        self.assertNotContains(response, 'type="date"', html=False)
        self.assertContains(response, 'Receiving type <span class="text-danger">*</span>', html=False)
        self.assertContains(response, 'Receiving date <span class="text-danger">*</span>', html=False)
        self.assertContains(response, 'Sumber dana <span class="text-danger">*</span>', html=False)

    def test_receiving_forms_accept_indonesian_date_input(self):
        form = ReceivingForm(
            data={
                "document_number": "",
                "receiving_type": Receiving.ReceivingType.GRANT,
                "receiving_date": "16/03/2026",
                "supplier": "",
                "sumber_dana": self.funding.pk,
                "notes": "",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["receiving_date"], date(2026, 3, 16))

        planned_form = PlannedReceivingForm(
            data={
                "document_number": "",
                "receiving_type": Receiving.ReceivingType.GRANT,
                "receiving_date": "17/03/2026",
                "supplier": "",
                "sumber_dana": self.funding.pk,
                "notes": "",
            }
        )

        self.assertTrue(planned_form.is_valid(), planned_form.errors)
        self.assertEqual(planned_form.cleaned_data["receiving_date"], date(2026, 3, 17))

    def test_receiving_item_form_accepts_indonesian_expiry_date_input(self):
        form = ReceivingItemForm(
            data={
                "item": self.item.pk,
                "quantity": "5",
                "batch_lot": "B-001",
                "expiry_date": "30/11/2030",
                "unit_price": "1000",
                "location": self.location.pk,
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["expiry_date"], date(2030, 11, 30))

    def test_receiving_plan_create_post_redirects_without_creating_manual_plan(self):
        response = self.client.post(
            reverse("receiving:receiving_plan_create"),
            {
                "document_number": "",
                "receiving_type": Receiving.ReceivingType.GRANT,
                "receiving_date": "2026-03-16",
                "supplier": "",
                "sumber_dana": self.funding.pk,
                "notes": "",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-item": self.item.pk,
                "items-0-planned_quantity": "5",
                "items-0-unit_price": "1000",
                "items-0-notes": "",
            },
            secure=True,
        )

        self.assertRedirects(
            response,
            reverse("procurement:contract_create"),
            fetch_redirect_response=False,
        )
        self.assertFalse(Receiving.objects.filter(is_planned=True, contract__isnull=True).exists())

    def test_planned_receiving_list_hides_manual_create_for_new_plans(self):
        response = self.client.get(reverse("receiving:receiving_plan_list"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("receiving:receiving_plan_create"))
        self.assertNotContains(response, "Buat Rencana")
        self.assertContains(
            response,
            "Rencana penerimaan pengadaan dibuat dari",
        )

    def test_receiving_sidebar_orders_spj_before_planned_receiving_queue(self):
        response = self.client.get(reverse("receiving:receiving_plan_list"), secure=True)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        regular_index = content.index('data-label="Buat Penerimaan"')
        spj_index = content.index('data-label="SPJ / Pengadaan"')
        planned_index = content.index('data-label="Rencana Penerimaan"')
        self.assertLess(regular_index, spj_index)
        self.assertLess(spj_index, planned_index)

    def test_planned_receiving_list_can_filter_cancelled_plans(self):
        cancelled = Receiving.objects.create(
            document_number="RCV-2026-CANCELLED-FILTER",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.CANCELLED,
            is_planned=True,
            created_by=self.user,
        )
        active = Receiving.objects.create(
            document_number="RCV-2026-ACTIVE-FILTER",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 3, 17),
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=self.user,
        )

        response = self.client.get(
            reverse("receiving:receiving_plan_list"),
            {"status": Receiving.Status.CANCELLED},
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dibatalkan")
        self.assertContains(response, cancelled.document_number)
        self.assertNotContains(response, active.document_number)
        self.assertContains(
            response,
            '<option value="CANCELLED" selected>Dibatalkan</option>',
            html=False,
        )

    def test_planned_receiving_list_uses_preloaded_type_labels(self):
        Receiving.objects.create(
            document_number="RCV-2026-LABEL-PLAN",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.DRAFT,
            is_planned=True,
            created_by=self.user,
        )

        with patch.object(
            Receiving,
            "receiving_type_label",
            new_callable=PropertyMock,
            side_effect=AssertionError("List views must not call receiving_type_label."),
        ):
            response = self.client.get(reverse("receiving:receiving_plan_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hibah")

    def test_regular_receiving_detail_rejects_planned_receiving(self):
        planned_receiving = Receiving.objects.create(
            document_number="RCV-2026-99993",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )

        response = self.client.get(
            reverse("receiving:receiving_detail", args=[planned_receiving.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_regular_receiving_detail_shows_exact_unit_price(self):
        precise_price = Decimal("1000.1234567890")
        receiving = Receiving.objects.create(
            document_number="RCV-2026-PRECISE",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.VERIFIED,
            is_planned=False,
            created_by=self.user,
            verified_by=self.user,
        )
        ReceivingItem.objects.create(
            receiving=receiving,
            item=self.item,
            quantity=Decimal("1.01"),
            batch_lot="BATCH-PRECISE",
            expiry_date=date(2030, 1, 1),
            unit_price=precise_price,
            location=self.location,
        )

        response = self.client.get(
            reverse("receiving:receiving_detail", args=[receiving.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1000.123456789")
        self.assertContains(response, "1.010,12469135689")
        self.assertNotContains(response, '<td class="text-end fw-semibold">1010</td>', html=True)

    def test_procurement_receiving_forms_require_supplier(self):
        form_data = {
            "document_number": "",
            "receiving_type": Receiving.ReceivingType.PROCUREMENT,
            "receiving_date": "2026-03-16",
            "supplier": "",
            "facility": "",
            "sumber_dana": self.funding.pk,
            "notes": "",
        }

        regular_form = ReceivingForm(data=form_data)
        planned_form = PlannedReceivingForm(data=form_data)

        self.assertFalse(regular_form.is_valid())
        self.assertFalse(planned_form.is_valid())
        self.assertEqual(
            regular_form.errors["supplier"],
            ["Supplier wajib diisi untuk tipe penerimaan ini."],
        )
        self.assertEqual(
            planned_form.errors["supplier"],
            ["Supplier wajib diisi untuk tipe penerimaan ini."],
        )

    def test_receiving_forms_reject_unknown_custom_receiving_type(self):
        form_data = {
            "document_number": "",
            "receiving_type": "TIDAKADA",
            "receiving_date": "2026-03-16",
            "supplier": "",
            "sumber_dana": self.funding.pk,
            "notes": "",
        }

        regular_form = ReceivingForm(data=form_data)
        planned_form = PlannedReceivingForm(data=form_data)

        self.assertFalse(regular_form.is_valid())
        self.assertFalse(planned_form.is_valid())
        self.assertEqual(regular_form.errors["receiving_type"], ["Masukkan pilihan yang valid."])
        self.assertEqual(planned_form.errors["receiving_type"], ["Masukkan pilihan yang valid."])

    def test_receiving_forms_reject_null_byte_receiving_type_as_field_error(self):
        form_data = {
            "document_number": "",
            "receiving_type": "DON\x00ASI",
            "receiving_date": "2026-03-16",
            "supplier": "",
            "sumber_dana": self.funding.pk,
            "notes": "",
        }

        regular_form = ReceivingForm(data=form_data)
        planned_form = PlannedReceivingForm(data=form_data)

        self.assertFalse(regular_form.is_valid())
        self.assertFalse(planned_form.is_valid())
        self.assertEqual(
            regular_form.errors["receiving_type"],
            ["Karakter null tidak diizinkan."],
        )
        self.assertEqual(
            planned_form.errors["receiving_type"],
            ["Karakter null tidak diizinkan."],
        )

    def test_receiving_forms_reject_reserved_internal_receiving_type(self):
        ReceivingTypeOption.objects.create(
            code="RETURN_RS",
            name="Pengembalian RS",
            is_active=True,
        )
        form_data = {
            "document_number": "",
            "receiving_type": "RETURN_RS",
            "receiving_date": "2026-03-16",
            "supplier": "",
            "sumber_dana": self.funding.pk,
            "notes": "",
        }

        regular_form = ReceivingForm(data=form_data)
        planned_form = PlannedReceivingForm(data=form_data)

        self.assertFalse(regular_form.is_valid())
        self.assertFalse(planned_form.is_valid())
        self.assertEqual(regular_form.errors["receiving_type"], ["Masukkan pilihan yang valid."])
        self.assertEqual(planned_form.errors["receiving_type"], ["Masukkan pilihan yang valid."])
        self.assertNotIn(
            ("RETURN_RS", "Pengembalian RS"),
            ReceivingForm().fields["receiving_type"].widget.choices,
        )

    def test_receiving_model_full_clean_rejects_invalid_receiving_type(self):
        receiving = Receiving(
            document_number="RCV-2026-INVALID",
            receiving_type="FOO",
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.VERIFIED,
            created_by=self.user,
            verified_by=self.user,
        )

        with self.assertRaises(ValidationError) as exc:
            receiving.full_clean()

        self.assertEqual(
            exc.exception.message_dict["receiving_type"],
            ["Masukkan pilihan yang valid."],
        )

    def test_receiving_model_full_clean_requires_supplier_for_procurement(self):
        receiving = Receiving(
            document_number="RCV-2026-PROC-001",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.VERIFIED,
            created_by=self.user,
            verified_by=self.user,
        )

        with self.assertRaises(ValidationError) as exc:
            receiving.full_clean()

        self.assertEqual(
            exc.exception.message_dict["supplier"],
            ["Supplier wajib diisi untuk tipe penerimaan ini."],
        )

    def test_receiving_forms_require_explicit_receiving_type_selection(self):
        regular_form = ReceivingForm(
            data={
                "document_number": "",
                "receiving_type": "",
                "receiving_date": "2026-03-16",
                "supplier": "",
                "sumber_dana": self.funding.pk,
                "notes": "",
            }
        )
        planned_form = PlannedReceivingForm(
            data={
                "document_number": "",
                "receiving_type": "",
                "receiving_date": "2026-03-16",
                "supplier": "",
                "sumber_dana": self.funding.pk,
                "notes": "",
            }
        )

        self.assertEqual(regular_form.fields["receiving_type"].widget.choices[0], ("", "---------"))
        self.assertEqual(planned_form.fields["receiving_type"].widget.choices[0], ("", "---------"))
        self.assertFalse(regular_form.is_valid())
        self.assertFalse(planned_form.is_valid())
        self.assertEqual(regular_form.errors["receiving_type"], ["Tipe penerimaan wajib dipilih."])
        self.assertEqual(planned_form.errors["receiving_type"], ["Tipe penerimaan wajib dipilih."])

    def test_receiving_full_clean_rejects_duplicate_planned_contract_link(self):
        supplier = Supplier.objects.create(code="SUP-RCV-001", name="PT Supplier Receiving")
        contract = ProcurementContract.objects.create(
            document_number="SPJ-RCV-001",
            contract_date=date(2026, 3, 16),
            supplier=supplier,
            sumber_dana=self.funding,
            notes="Kontrak receiving",
            created_by=self.user,
        )
        Receiving.objects.create(
            document_number="RCV-2026-CONTRACT-001",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            is_planned=True,
            contract=contract,
            supplier=supplier,
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            created_by=self.user,
        )
        duplicate = Receiving(
            document_number="RCV-2026-CONTRACT-002",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 17),
            is_planned=True,
            contract=contract,
            supplier=supplier,
            sumber_dana=self.funding,
            status=Receiving.Status.DRAFT,
            created_by=self.user,
        )

        with self.assertRaises(ValidationError) as exc:
            duplicate.full_clean()

        self.assertEqual(
            exc.exception.message_dict["contract"],
            ["Setiap kontrak SPJ hanya boleh memiliki satu rencana penerimaan."],
        )

    def test_receiving_db_constraint_rejects_duplicate_planned_contract_link(self):
        supplier = Supplier.objects.create(code="SUP-RCV-002", name="PT Supplier Receiving 2")
        contract = ProcurementContract.objects.create(
            document_number="SPJ-RCV-002",
            contract_date=date(2026, 3, 16),
            supplier=supplier,
            sumber_dana=self.funding,
            notes="Kontrak receiving",
            created_by=self.user,
        )
        Receiving.objects.create(
            document_number="RCV-2026-CONTRACT-003",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            is_planned=True,
            contract=contract,
            supplier=supplier,
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            created_by=self.user,
        )

        with self.assertRaises(IntegrityError):
            Receiving.objects.create(
                document_number="RCV-2026-CONTRACT-004",
                receiving_type=Receiving.ReceivingType.PROCUREMENT,
                receiving_date=date(2026, 3, 17),
                is_planned=True,
                contract=contract,
                supplier=supplier,
                sumber_dana=self.funding,
                status=Receiving.Status.DRAFT,
                created_by=self.user,
            )

    def test_plan_receive_page_uses_fixed_rows_without_delete_control(self):
        receiving = Receiving.objects.create(
            document_number="RCV-2026-99997",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )
        ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=self.item,
            planned_quantity=Decimal("5000.50"),
            received_quantity=Decimal("0"),
            unit_price=Decimal("10000"),
            is_cancelled=False,
        )

        response = self.client.get(
            reverse("receiving:receiving_plan_receive", args=[receiving.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sisa Rencana")
        self.assertContains(response, "Kuantitas Diterima")
        self.assertContains(response, self.item.nama_barang)
        self.assertNotContains(response, self.item.kode_barang)
        self.assertContains(response, 'name="items-0-order_item"', html=False)
        self.assertContains(response, 'value="5000.5"', html=False)
        self.assertContains(response, 'value="10000"', html=False)
        self.assertContains(response, self.location.name)
        self.assertNotContains(response, self.location.code)
        self.assertNotContains(response, "Hapus")

    def test_plan_receive_page_shows_only_outstanding_items_and_remaining_quantity(self):
        receiving = Receiving.objects.create(
            document_number="RCV-2026-99988",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.PARTIAL,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )
        partial_order = ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=self.item,
            planned_quantity=Decimal("10000"),
            received_quantity=Decimal("5000"),
            unit_price=Decimal("500"),
            is_cancelled=False,
        )
        second_item = Item.objects.create(
            kode_barang="ITM-TEST-0103",
            nama_barang="Alopurinol 100 mg",
            satuan=self.item.satuan,
            kategori=self.item.kategori,
            minimum_stock=Decimal("0"),
        )
        ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=second_item,
            planned_quantity=Decimal("20000"),
            received_quantity=Decimal("20000"),
            unit_price=Decimal("2000"),
            is_cancelled=False,
        )

        response = self.client.get(
            reverse("receiving:receiving_plan_receive", args=[receiving.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.item.nama_barang)
        self.assertContains(response, 'value="5000"', html=False)
        self.assertContains(response, 'value="500"', html=False)
        self.assertNotContains(response, second_item.nama_barang)
        self.assertNotContains(response, 'value="20000"', html=False)
        self.assertContains(response, f'value="{partial_order.pk}"', html=False)

    def test_plan_receive_unit_price_accepts_comma_decimal_separator(self):
        receiving = Receiving.objects.create(
            document_number="RCV-2026-IDPRICE",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )
        order_item = ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=self.item,
            planned_quantity=Decimal("5"),
            received_quantity=Decimal("0"),
            unit_price=Decimal("10000"),
            is_cancelled=False,
        )
        form = ReceivingReceiptItemForm(
            data={
                "order_item": str(order_item.pk),
                "quantity": "1",
                "batch_lot": "IDPRICE",
                "expiry_date": "2030-11-30",
                "unit_price": "10000,5",
                "location": str(self.location.pk),
            },
            receiving=receiving,
            lock_order_item=True,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["unit_price"], Decimal("10000.5"))

    def test_plan_receive_unit_price_rejects_dot_separator(self):
        receiving = Receiving.objects.create(
            document_number="RCV-2026-DOTPRICE",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )
        order_item = ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=self.item,
            planned_quantity=Decimal("5"),
            received_quantity=Decimal("0"),
            unit_price=Decimal("10000"),
            is_cancelled=False,
        )
        form = ReceivingReceiptItemForm(
            data={
                "order_item": str(order_item.pk),
                "quantity": "1",
                "batch_lot": "DOTPRICE",
                "expiry_date": "2030-11-30",
                "unit_price": "10.000",
                "location": str(self.location.pk),
            },
            receiving=receiving,
            lock_order_item=True,
        )

        self.assertFalse(form.is_valid())
        self.assertIn(
            "Gunakan angka tanpa pemisah ribuan. Gunakan koma untuk desimal.",
            form.errors["unit_price"],
        )

    def test_plan_receive_accepts_zero_qty_as_no_receipt_for_row(self):
        receiving = Receiving.objects.create(
            document_number="RCV-2026-99996",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )
        oi = ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=self.item,
            planned_quantity=Decimal("5"),
            received_quantity=Decimal("0"),
            unit_price=Decimal("1000"),
            is_cancelled=False,
        )

        response = self.client.post(
            reverse("receiving:receiving_plan_receive", args=[receiving.pk]),
            {
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-order_item": str(oi.pk),
                "items-0-quantity": "0",
                "items-0-batch_lot": "",
                "items-0-expiry_date": "",
                "items-0-unit_price": "1000",
                "items-0-location": "",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        receiving.refresh_from_db()
        self.assertEqual(receiving.status, Receiving.Status.APPROVED)
        self.assertEqual(ReceivingItem.objects.filter(receiving=receiving).count(), 0)

    def test_plan_receive_allows_partial_and_full_receipt_mix(self):
        receiving = Receiving.objects.create(
            document_number="RCV-2026-99990",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )
        amoxicillin_order = ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=self.item,
            planned_quantity=Decimal("10000"),
            received_quantity=Decimal("0"),
            unit_price=Decimal("100"),
            is_cancelled=False,
        )
        second_item = Item.objects.create(
            kode_barang="ITM-TEST-0102",
            nama_barang="Alopurinol 100 mg",
            satuan=self.item.satuan,
            kategori=self.item.kategori,
            minimum_stock=Decimal("0"),
        )
        alopurinol_order = ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=second_item,
            planned_quantity=Decimal("20000"),
            received_quantity=Decimal("0"),
            unit_price=Decimal("0"),
            is_cancelled=False,
        )

        response = self.client.post(
            reverse("receiving:receiving_plan_receive", args=[receiving.pk]),
            {
                "items-TOTAL_FORMS": "2",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-order_item": str(amoxicillin_order.pk),
                "items-0-quantity": "5000",
                "items-0-batch_lot": "AHSGK",
                "items-0-expiry_date": "2030-11-30",
                "items-0-unit_price": "100",
                "items-0-location": str(self.location.pk),
                "items-1-order_item": str(alopurinol_order.pk),
                "items-1-quantity": "20000",
                "items-1-batch_lot": "DSAGJK",
                "items-1-expiry_date": "2030-12-02",
                "items-1-unit_price": "200",
                "items-1-location": str(self.location.pk),
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        receiving.refresh_from_db()
        amoxicillin_order.refresh_from_db()
        alopurinol_order.refresh_from_db()
        self.assertEqual(receiving.status, Receiving.Status.PARTIAL)
        self.assertEqual(amoxicillin_order.received_quantity, Decimal("5000"))
        self.assertEqual(alopurinol_order.received_quantity, Decimal("20000"))
        self.assertEqual(ReceivingItem.objects.filter(receiving=receiving).count(), 2)
        self.assertTrue(
            Stock.objects.filter(
                item=self.item,
                batch_lot="AHSGK",
                quantity=Decimal("5000"),
            ).exists()
        )
        self.assertTrue(
            Stock.objects.filter(
                item=second_item,
                batch_lot="DSAGJK",
                quantity=Decimal("20000"),
                unit_price=Decimal("200.00"),
            ).exists()
        )

    def test_plan_receive_continues_migrated_disambiguated_source_layer(self):
        receiving = Receiving.objects.create(
            document_number="SRC-COLLIDE-PLAN",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.PARTIAL,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )
        order_item = ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=self.item,
            planned_quantity=Decimal("5"),
            received_quantity=Decimal("2"),
            unit_price=Decimal("100"),
            is_cancelled=False,
        )
        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot="MIGRATED-ALIAS",
            source_document_number="RCV-HASHED-SRC-COLLIDE-PLAN",
            expiry_date=date(2030, 11, 30),
            quantity=Decimal("2"),
            reserved=Decimal("0"),
            unit_price=Decimal("100"),
            sumber_dana=self.funding,
            receiving_ref=receiving,
        )

        response = self.client.post(
            reverse("receiving:receiving_plan_receive", args=[receiving.pk]),
            {
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-order_item": str(order_item.pk),
                "items-0-quantity": "3",
                "items-0-batch_lot": "MIGRATED-ALIAS",
                "items-0-expiry_date": "2030-11-30",
                "items-0-unit_price": "100",
                "items-0-location": str(self.location.pk),
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        stock = Stock.objects.get(
            receiving_ref=receiving,
            source_document_number="RCV-HASHED-SRC-COLLIDE-PLAN",
        )
        self.assertEqual(stock.quantity, Decimal("5"))
        self.assertFalse(
            Stock.objects.filter(
                receiving_ref=receiving,
                source_document_number="SRC-COLLIDE-PLAN",
            ).exists()
        )
        self.assertTrue(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.RECEIVING,
                reference_id=receiving.pk,
                source_document_number="RCV-HASHED-SRC-COLLIDE-PLAN",
                quantity=Decimal("3"),
            ).exists()
        )

    def test_plan_receive_rejects_stale_locked_overage(self):
        from apps.receiving import views as receiving_views

        receiving = Receiving.objects.create(
            document_number="RCV-2026-99991",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )
        order_item = ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=self.item,
            planned_quantity=Decimal("5"),
            received_quantity=Decimal("0"),
            unit_price=Decimal("1000"),
            is_cancelled=False,
        )

        original_helper = receiving_views._get_locked_planned_receiving_order_items

        def mutate_before_lock(order_item_ids):
            locked_order_items = original_helper(order_item_ids)
            locked_order_items[order_item.pk].received_quantity = Decimal("4")
            return locked_order_items

        with patch(
            "apps.receiving.views._get_locked_planned_receiving_order_items",
            side_effect=mutate_before_lock,
        ):
            response = self.client.post(
                reverse("receiving:receiving_plan_receive", args=[receiving.pk]),
                {
                    "items-TOTAL_FORMS": "1",
                    "items-INITIAL_FORMS": "0",
                    "items-MIN_NUM_FORMS": "0",
                    "items-MAX_NUM_FORMS": "1000",
                    "items-0-order_item": str(order_item.pk),
                    "items-0-quantity": "3",
                    "items-0-batch_lot": "BATCH-STALE",
                    "items-0-expiry_date": "2030-01-01",
                    "items-0-unit_price": "1000",
                    "items-0-location": str(self.location.pk),
                },
                secure=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Jumlah melebihi sisa pesanan.")
        order_item.refresh_from_db()
        receiving.refresh_from_db()
        self.assertEqual(order_item.received_quantity, Decimal("0"))
        self.assertEqual(receiving.status, Receiving.Status.APPROVED)
        self.assertEqual(ReceivingItem.objects.filter(receiving=receiving).count(), 0)
        self.assertEqual(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.RECEIVING,
                reference_id=receiving.pk,
            ).count(),
            0,
        )
        self.assertFalse(Stock.objects.filter(batch_lot="BATCH-STALE").exists())

    def test_plan_receive_revalidates_status_after_form_validation(self):
        from apps.receiving import views as receiving_views

        receiving = Receiving.objects.create(
            document_number="RCV-2026-99992",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )
        order_item = ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=self.item,
            planned_quantity=Decimal("5"),
            received_quantity=Decimal("0"),
            unit_price=Decimal("1000"),
            is_cancelled=False,
        )
        original_builder = receiving_views.build_planned_receipt_item_formset
        cancelling_user = self.user

        def build_cancelling_formset(*args, **kwargs):
            base_formset = original_builder(*args, **kwargs)

            class CancellingFormSet(base_formset):
                def is_valid(self):
                    result = super().is_valid()
                    Receiving.objects.filter(pk=receiving.pk).update(
                        status=Receiving.Status.CANCELLED,
                        cancelled_by_id=cancelling_user.pk,
                        cancelled_at=timezone.now(),
                        cancel_reason="Dibatalkan request lain",
                    )
                    return result

            return CancellingFormSet

        with patch(
            "apps.receiving.views.build_planned_receipt_item_formset",
            side_effect=build_cancelling_formset,
        ):
            response = self.client.post(
                reverse("receiving:receiving_plan_receive", args=[receiving.pk]),
                {
                    "items-TOTAL_FORMS": "1",
                    "items-INITIAL_FORMS": "0",
                    "items-MIN_NUM_FORMS": "0",
                    "items-MAX_NUM_FORMS": "1000",
                    "items-0-order_item": str(order_item.pk),
                    "items-0-quantity": "3",
                    "items-0-batch_lot": "BATCH-CANCELLED-RACE",
                    "items-0-expiry_date": "2030-01-01",
                    "items-0-unit_price": "1000",
                    "items-0-location": str(self.location.pk),
                },
                secure=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Status rencana penerimaan sudah berubah dan tidak dapat menerima barang.",
        )
        receiving.refresh_from_db()
        order_item.refresh_from_db()
        self.assertEqual(receiving.status, Receiving.Status.CANCELLED)
        self.assertEqual(order_item.received_quantity, Decimal("0"))
        self.assertEqual(ReceivingItem.objects.filter(receiving=receiving).count(), 0)
        self.assertFalse(
            Stock.objects.filter(batch_lot="BATCH-CANCELLED-RACE").exists()
        )
        self.assertFalse(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.RECEIVING,
                reference_id=receiving.pk,
            ).exists()
        )

    def test_plan_receive_invalid_post_rerenders_row_errors(self):
        receiving = Receiving.objects.create(
            document_number="RCV-2026-99989",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )
        oi = ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=self.item,
            planned_quantity=Decimal("5"),
            received_quantity=Decimal("0"),
            unit_price=Decimal("1000"),
            is_cancelled=False,
        )

        response = self.client.post(
            reverse("receiving:receiving_plan_receive", args=[receiving.pk]),
            {
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-order_item": str(oi.pk),
                "items-0-quantity": "3",
                "items-0-batch_lot": "BATCH-ERR",
                "items-0-expiry_date": "2030-01-01",
                "items-0-unit_price": "1000",
                "items-0-location": "",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lokasi wajib dipilih.")
        self.assertContains(response, 'value="3"', html=False)

    def test_receiving_order_item_form_rejects_zero_unit_price(self):
        form = ReceivingOrderItemForm(
            data={
                "item": self.item.pk,
                "planned_quantity": "5",
                "unit_price": "0",
                "notes": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["unit_price"],
            ["Harga satuan harus lebih dari 0."],
        )

    def test_receiving_order_item_form_rejects_infinite_unit_price(self):
        form = ReceivingOrderItemForm(
            data={
                "item": self.item.pk,
                "planned_quantity": "5",
                "unit_price": "Infinity",
                "notes": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["unit_price"],
            ["Masukkan sebuah bilangan."],
        )

    def test_gudang_cannot_approve_receiving_plan(self):
        receiving = Receiving.objects.create(
            document_number="RCV-2026-99995",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.SUBMITTED,
            is_planned=True,
            created_by=self.user,
        )
        gudang = User.objects.create_user(
            username="gudang_only_rcv",
            password="secret12345",
            role=User.Role.GUDANG,
        )
        ensure_default_module_access(gudang, overwrite=True)
        self.client.force_login(gudang)

        response = self.client.post(
            reverse("receiving:receiving_plan_approve", args=[receiving.pk])
        )
        self.assertEqual(response.status_code, 403)


class PlannedReceivingConcurrencyTest(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="admin_receiving_concurrency",
            password="secret12345",
        )
        unit = Unit.objects.create(code="TABC", name="Tablet Concurrency")
        category = Category.objects.create(code="OBATC", name="Obat C", sort_order=3)
        self.item = Item.objects.create(
            kode_barang="ITM-TEST-CONC-0001",
            nama_barang="Cefixime 200mg",
            satuan=unit,
            kategori=category,
            minimum_stock=Decimal("0"),
        )
        self.funding = FundingSource.objects.create(code="DAKC", name="DAK C")
        self.location = Location.objects.create(code="LOC-C1", name="Gudang Concurrency")

    def _build_payload(self, order_item):
        return {
            "items-TOTAL_FORMS": "1",
            "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0",
            "items-MAX_NUM_FORMS": "1000",
            "items-0-order_item": str(order_item.pk),
            "items-0-quantity": "5",
            "items-0-batch_lot": "BATCH-CONC",
            "items-0-expiry_date": "2030-01-01",
            "items-0-unit_price": "1000",
            "items-0-location": str(self.location.pk),
        }

    def _post_receipt(self, client, receiving_pk, order_item, results, key):
        try:
            response = client.post(
                reverse("receiving:receiving_plan_receive", args=[receiving_pk]),
                self._build_payload(order_item),
                secure=True,
            )
            results[key] = {
                "status_code": response.status_code,
                "body": response.content.decode("utf-8", errors="ignore"),
            }
        finally:
            connections.close_all()

    def test_plan_receive_concurrent_posts_do_not_over_receive(self):
        from apps.receiving import views as receiving_views

        receiving = Receiving.objects.create(
            document_number="RCV-2026-CONC-0001",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )
        order_item = ReceivingOrderItem.objects.create(
            receiving=receiving,
            item=self.item,
            planned_quantity=Decimal("5"),
            received_quantity=Decimal("0"),
            unit_price=Decimal("1000"),
            is_cancelled=False,
        )

        barrier = threading.Barrier(2)
        original_builder = receiving_views.build_planned_receipt_item_formset

        def build_synchronized_formset(*args, **kwargs):
            base_formset = original_builder(*args, **kwargs)

            class SynchronizedFormSet(base_formset):
                def is_valid(self):
                    result = super().is_valid()
                    barrier.wait(timeout=5)
                    return result

            return SynchronizedFormSet

        client_one = Client()
        client_two = Client()
        client_one.force_login(self.user)
        client_two.force_login(self.user)
        results = {}

        with patch(
            "apps.receiving.views.build_planned_receipt_item_formset",
            side_effect=build_synchronized_formset,
        ):
            thread_one = threading.Thread(
                target=self._post_receipt,
                args=(client_one, receiving.pk, order_item, results, "one"),
            )
            thread_two = threading.Thread(
                target=self._post_receipt,
                args=(client_two, receiving.pk, order_item, results, "two"),
            )
            thread_one.start()
            thread_two.start()
            thread_one.join(timeout=10)
            thread_two.join(timeout=10)

        self.assertFalse(thread_one.is_alive())
        self.assertFalse(thread_two.is_alive())
        self.assertEqual(sorted(result["status_code"] for result in results.values()), [200, 302])
        self.assertTrue(
            any(
                "Jumlah melebihi sisa pesanan." in result["body"]
                or "Status rencana penerimaan sudah berubah dan tidak dapat menerima barang."
                in result["body"]
                for result in results.values()
                if result["status_code"] == 200
            )
        )

        order_item.refresh_from_db()
        receiving.refresh_from_db()
        self.assertEqual(order_item.received_quantity, Decimal("5"))
        self.assertEqual(receiving.status, Receiving.Status.RECEIVED)
        self.assertEqual(ReceivingItem.objects.filter(receiving=receiving).count(), 1)
        self.assertEqual(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.RECEIVING,
                reference_id=receiving.pk,
            ).count(),
            1,
        )
        stock = Stock.objects.get(batch_lot="BATCH-CONC")
        self.assertEqual(stock.quantity, Decimal("5"))


class ReceivingStockConcurrencyTest(TransactionTestCase):
    def setUp(self):
        _ensure_receiving_number_rule()
        self.user = User.objects.create_superuser(
            username="admin_receiving_stock_concurrency",
            password="secret12345",
        )
        unit = Unit.objects.create(code="TABS", name="Tablet Stock")
        category = Category.objects.create(code="OBATS", name="Obat Stock", sort_order=4)
        self.item = Item.objects.create(
            kode_barang="ITM-TEST-STOCK-0001",
            nama_barang="Azithromycin 500mg",
            satuan=unit,
            kategori=category,
            minimum_stock=Decimal("0"),
        )
        self.funding = FundingSource.objects.create(code="APBDS", name="APBD Stock")
        self.location = Location.objects.create(code="LOC-S1", name="Gudang Stock Race")
        self.batch_lot = "BATCH-STOCK-RACE"
        self.expiry_date = "2030-01-01"

    @staticmethod
    def _csv_file(content):
        return SimpleUploadedFile(
            "receiving.csv",
            content.encode("utf-8"),
            content_type="text/csv",
        )

    def _regular_payload(self, document_number, quantity):
        return {
            "receiving_type": Receiving.ReceivingType.GRANT,
            "receiving_date": "2026-03-16",
            "supplier": "",
            "sumber_dana": self.funding.pk,
            "notes": "",
            "items-TOTAL_FORMS": "1",
            "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0",
            "items-MAX_NUM_FORMS": "1000",
            "items-0-item": self.item.pk,
            "items-0-quantity": str(quantity),
            "items-0-batch_lot": self.batch_lot,
            "items-0-expiry_date": self.expiry_date,
            "items-0-unit_price": "1500",
            "items-0-location": self.location.pk,
        }

    def _planned_payload(self, order_item, quantity):
        return {
            "items-TOTAL_FORMS": "1",
            "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0",
            "items-MAX_NUM_FORMS": "1000",
            "items-0-order_item": str(order_item.pk),
            "items-0-quantity": str(quantity),
            "items-0-batch_lot": self.batch_lot,
            "items-0-expiry_date": self.expiry_date,
            "items-0-unit_price": "1000",
            "items-0-location": str(self.location.pk),
        }

    def _csv_content(self, document_number, quantity):
        return (
            "import_group,receiving_type,receiving_date,supplier_code,sumber_dana_code,"
            "location_code,item_code,quantity,batch_lot,expiry_date,unit_price\n"
            f"{document_number},GRANT,12/03/2026,,{self.funding.code},{self.location.code},"
            f"{self.item.kode_barang},{quantity},{self.batch_lot},01/01/2030,1000\n"
        )

    def _post_regular_receiving(self, client, payload, results, key):
        try:
            response = client.post(
                reverse("receiving:receiving_create"),
                payload,
                secure=True,
            )
            results[key] = {"status_code": response.status_code}
        except Exception as exc:
            results[key] = {"error": repr(exc)}
        finally:
            connections.close_all()

    def _post_planned_receiving(self, client, receiving_pk, payload, results, key):
        try:
            response = client.post(
                reverse("receiving:receiving_plan_receive", args=[receiving_pk]),
                payload,
                secure=True,
            )
            results[key] = {"status_code": response.status_code}
        except Exception as exc:
            results[key] = {"error": repr(exc)}
        finally:
            connections.close_all()

    def _run_csv_import(self, csv_content, results, key):
        admin = ReceivingAdmin(Receiving, AdminSite())
        try:
            counts = admin._process_csv(self._csv_file(csv_content), self.user)
            results[key] = {"counts": counts}
        except Exception as exc:
            results[key] = {"error": repr(exc)}
        finally:
            connections.close_all()

    def test_regular_receiving_concurrent_posts_create_source_document_layers(self):
        client_one = Client()
        client_two = Client()
        client_one.force_login(self.user)
        client_two.force_login(self.user)
        results = {}

        thread_one = threading.Thread(
            target=self._post_regular_receiving,
            args=(
                client_one,
                self._regular_payload("RCV-2026-RACE-REG-1", Decimal("3")),
                results,
                "one",
            ),
        )
        thread_two = threading.Thread(
            target=self._post_regular_receiving,
            args=(
                client_two,
                self._regular_payload("RCV-2026-RACE-REG-2", Decimal("4")),
                results,
                "two",
            ),
        )
        thread_one.start()
        thread_two.start()
        thread_one.join(timeout=10)
        thread_two.join(timeout=10)

        self.assertFalse(thread_one.is_alive())
        self.assertFalse(thread_two.is_alive())
        self.assertNotIn("error", results.get("one", {}))
        self.assertNotIn("error", results.get("two", {}))
        self.assertEqual(
            sorted(result["status_code"] for result in results.values()),
            [302, 302],
        )
        stock_layers = list(
            Stock.objects.filter(
                item=self.item,
                location=self.location,
                batch_lot=self.batch_lot,
                sumber_dana=self.funding,
            ).values_list("source_document_number", "quantity")
        )
        self.assertEqual(len({number for number, _quantity in stock_layers}), 2)
        self.assertTrue(
            all(number.startswith("RCV-2026-") for number, _quantity in stock_layers)
        )
        self.assertEqual(
            {quantity for _number, quantity in stock_layers},
            {Decimal("3.00"), Decimal("4.00")},
        )
        self.assertEqual(Receiving.objects.count(), 2)
        self.assertEqual(ReceivingItem.objects.count(), 2)
        self.assertEqual(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.RECEIVING,
            ).count(),
            2,
        )

    def test_increment_receiving_stock_detects_expiry_mismatch_after_create_race(self):
        from apps.receiving import models as receiving_models

        class _PreReadQuerySet:
            def values(self, *args, **kwargs):
                return self

            def first(self):
                return None

        class _UpdateQuerySet:
            def update(self, **kwargs):
                return 0

        class _PostReadQuerySet:
            def values(self, *args, **kwargs):
                return self

            def first(self):
                return {
                    "pk": 99,
                    "expiry_date": date(2031, 1, 1),
                    "quantity": Decimal("3"),
                    "reserved": Decimal("0"),
                    "unit_price": Decimal("1500"),
                }

        with (
            patch(
                'apps.stock.models.Stock.objects.filter',
                side_effect=[
                    _PreReadQuerySet(),
                    _UpdateQuerySet(),
                    _PostReadQuerySet(),
                ],
            ) as mock_filter,
            patch(
                'apps.receiving.models._create_receiving_stock_row',
                side_effect=IntegrityError('duplicate key value violates unique constraint'),
            ),
            transaction.atomic(),
        ):
            with self.assertRaises(ValueError) as exc:
                receiving_models.increment_receiving_stock(
                    item=self.item,
                    location=self.location,
                    batch_lot=self.batch_lot,
                    sumber_dana=self.funding,
                    expiry_date=date(2030, 1, 1),
                    quantity=Decimal('3'),
                    unit_price=Decimal('1500'),
                    receiving_ref=None,
                    source_document_number="RCV-RACE",
                )

        self.assertIn('tanggal kedaluwarsa berbeda', str(exc.exception))
        self.assertEqual(mock_filter.call_count, 3)
        _, second_call_kwargs = mock_filter.call_args_list[1]
        self.assertEqual(second_call_kwargs['expiry_date'], date(2030, 1, 1))

    def test_increment_receiving_stock_rejects_zero_layer_metadata_rewrite_without_correction_flag(self):
        from apps.receiving import models as receiving_models

        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot=self.batch_lot,
            sumber_dana=self.funding,
            expiry_date=date(2030, 1, 1),
            quantity=Decimal("0"),
            reserved=Decimal("0"),
            unit_price=Decimal("1000"),
            source_document_number="RCV-ZERO-STRICT",
        )

        with transaction.atomic():
            with self.assertRaises(ValueError) as exc:
                receiving_models.increment_receiving_stock(
                    item=self.item,
                    location=self.location,
                    batch_lot=self.batch_lot,
                    sumber_dana=self.funding,
                    expiry_date=date(2031, 1, 1),
                    quantity=Decimal("3"),
                    unit_price=Decimal("1000"),
                    receiving_ref=None,
                    source_document_number="RCV-ZERO-STRICT",
                )

        self.assertIn("tanggal kedaluwarsa berbeda", str(exc.exception))
        stock = Stock.objects.get(source_document_number="RCV-ZERO-STRICT")
        self.assertEqual(stock.expiry_date, date(2030, 1, 1))
        self.assertEqual(stock.quantity, Decimal("0"))

    def test_increment_receiving_stock_audits_zero_layer_metadata_rewrite(self):
        from apps.receiving import models as receiving_models

        stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot=self.batch_lot,
            sumber_dana=self.funding,
            expiry_date=date(2030, 1, 1),
            quantity=Decimal("0"),
            reserved=Decimal("0"),
            unit_price=Decimal("1000"),
            source_document_number="RCV-ZERO-AUDIT",
        )
        stock_content_type = ContentType.objects.get_for_model(Stock)
        previous_log_count = LogEntry.objects.filter(
            content_type=stock_content_type,
            object_pk=str(stock.pk),
        ).count()

        with set_actor(self.user), transaction.atomic():
            receiving_models.increment_receiving_stock(
                item=self.item,
                location=self.location,
                batch_lot=self.batch_lot,
                sumber_dana=self.funding,
                expiry_date=date(2031, 1, 1),
                quantity=Decimal("3"),
                unit_price=Decimal("1200"),
                receiving_ref=None,
                source_document_number="RCV-ZERO-AUDIT",
                allow_zero_layer_metadata_update=True,
            )

        stock.refresh_from_db()
        self.assertEqual(stock.expiry_date, date(2031, 1, 1))
        self.assertEqual(stock.unit_price, Decimal("1200.0000000000"))
        self.assertEqual(stock.quantity, Decimal("3.00"))

        update_log = (
            LogEntry.objects.filter(
                content_type=stock_content_type,
                object_pk=str(stock.pk),
                action=LogEntry.Action.UPDATE,
            )
            .order_by("-timestamp")
            .first()
        )
        self.assertIsNotNone(update_log)
        self.assertEqual(update_log.actor, self.user)
        self.assertGreater(
            LogEntry.objects.filter(
                content_type=stock_content_type,
                object_pk=str(stock.pk),
            ).count(),
            previous_log_count,
        )
        self.assertIn("expiry_date", update_log.changes)
        self.assertIn("unit_price", update_log.changes)

    def test_planned_receiving_concurrent_posts_create_source_document_layers(self):
        from apps.receiving import models as receiving_models

        Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot=self.batch_lot,
            sumber_dana=self.funding,
            expiry_date=date(2030, 1, 1),
            quantity=Decimal("10"),
            unit_price=Decimal("800"),
        )
        receiving_one = Receiving.objects.create(
            document_number="RCV-2026-RACE-PLAN-1",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )
        receiving_two = Receiving.objects.create(
            document_number="RCV-2026-RACE-PLAN-2",
            receiving_type=Receiving.ReceivingType.PROCUREMENT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.APPROVED,
            is_planned=True,
            created_by=self.user,
            approved_by=self.user,
        )
        order_item_one = ReceivingOrderItem.objects.create(
            receiving=receiving_one,
            item=self.item,
            planned_quantity=Decimal("3"),
            received_quantity=Decimal("0"),
            unit_price=Decimal("1000"),
            is_cancelled=False,
        )
        order_item_two = ReceivingOrderItem.objects.create(
            receiving=receiving_two,
            item=self.item,
            planned_quantity=Decimal("4"),
            received_quantity=Decimal("0"),
            unit_price=Decimal("1000"),
            is_cancelled=False,
        )

        barrier = threading.Barrier(2)

        def synchronized_increment(**kwargs):
            barrier.wait(timeout=5)
            return receiving_models.increment_receiving_stock(**kwargs)

        client_one = Client()
        client_two = Client()
        client_one.force_login(self.user)
        client_two.force_login(self.user)
        results = {}

        with patch(
            "apps.receiving.views.increment_receiving_stock",
            side_effect=synchronized_increment,
        ):
            thread_one = threading.Thread(
                target=self._post_planned_receiving,
                args=(
                    client_one,
                    receiving_one.pk,
                    self._planned_payload(order_item_one, Decimal("3")),
                    results,
                    "one",
                ),
            )
            thread_two = threading.Thread(
                target=self._post_planned_receiving,
                args=(
                    client_two,
                    receiving_two.pk,
                    self._planned_payload(order_item_two, Decimal("4")),
                    results,
                    "two",
                ),
            )
            thread_one.start()
            thread_two.start()
            thread_one.join(timeout=10)
            thread_two.join(timeout=10)

        self.assertFalse(thread_one.is_alive())
        self.assertFalse(thread_two.is_alive())
        self.assertNotIn("error", results.get("one", {}))
        self.assertNotIn("error", results.get("two", {}))
        self.assertEqual(
            sorted(result["status_code"] for result in results.values()),
            [302, 302],
        )
        stock = Stock.objects.get(
            item=self.item,
            location=self.location,
            batch_lot=self.batch_lot,
            sumber_dana=self.funding,
            source_document_number="LEGACY",
        )
        self.assertEqual(stock.quantity, Decimal("10"))
        self.assertEqual(
            list(
                Stock.objects.filter(
                    item=self.item,
                    location=self.location,
                    batch_lot=self.batch_lot,
                    sumber_dana=self.funding,
                )
                .order_by("source_document_number")
                .values_list("source_document_number", "quantity")
            ),
            [
                ("LEGACY", Decimal("10.00")),
                ("RCV-2026-RACE-PLAN-1", Decimal("3.00")),
                ("RCV-2026-RACE-PLAN-2", Decimal("4.00")),
            ],
        )
        order_item_one.refresh_from_db()
        order_item_two.refresh_from_db()
        self.assertEqual(order_item_one.received_quantity, Decimal("3"))
        self.assertEqual(order_item_two.received_quantity, Decimal("4"))
        self.assertEqual(ReceivingItem.objects.filter(batch_lot=self.batch_lot).count(), 2)
        self.assertEqual(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.RECEIVING,
                batch_lot=self.batch_lot,
            ).count(),
            2,
        )

    def test_csv_import_concurrent_runs_create_source_document_layers(self):
        results = {}

        thread_one = threading.Thread(
            target=self._run_csv_import,
            args=(
                self._csv_content("RCV-2026-RACE-CSV-1", Decimal("6")),
                results,
                "one",
            ),
        )
        thread_two = threading.Thread(
            target=self._run_csv_import,
            args=(
                self._csv_content("RCV-2026-RACE-CSV-2", Decimal("8")),
                results,
                "two",
            ),
        )
        thread_one.start()
        thread_two.start()
        thread_one.join(timeout=10)
        thread_two.join(timeout=10)

        self.assertFalse(thread_one.is_alive())
        self.assertFalse(thread_two.is_alive())
        self.assertNotIn("error", results.get("one", {}))
        self.assertNotIn("error", results.get("two", {}))
        self.assertEqual(results["one"]["counts"]["stock"], 1)
        self.assertEqual(results["two"]["counts"]["stock"], 1)
        stock_layers = list(
            Stock.objects.filter(
                item=self.item,
                location=self.location,
                batch_lot=self.batch_lot,
                sumber_dana=self.funding,
            ).values_list("source_document_number", "quantity")
        )
        self.assertEqual(len({number for number, _quantity in stock_layers}), 2)
        self.assertTrue(
            all(number.startswith("RCV-2026-") for number, _quantity in stock_layers)
        )
        self.assertEqual(
            {quantity for _number, quantity in stock_layers},
            {Decimal("6.00"), Decimal("8.00")},
        )
        self.assertEqual(Receiving.objects.count(), 2)
        self.assertEqual(ReceivingItem.objects.count(), 2)
        self.assertEqual(
            Transaction.objects.filter(
                reference_type=Transaction.ReferenceType.RECEIVING,
                batch_lot=self.batch_lot,
            ).count(),
            2,
        )



class ReceivingDocumentUploadValidationTest(TestCase):
    def test_receiving_document_form_rejects_invalid_pdf_content(self):
        from apps.receiving.admin import ReceivingDocumentInlineForm

        form = ReceivingDocumentInlineForm(
            data={"file_name": "", "file_type": ""},
            files={
                "file": SimpleUploadedFile(
                    "dokumen.pdf",
                    b"not-a-pdf",
                    content_type="application/pdf",
                )
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)

    def test_receiving_document_form_sets_detected_metadata(self):
        from apps.receiving.admin import ReceivingDocumentInlineForm

        user = User.objects.create_superuser(
            username="doc-metadata-admin",
            password="secret12345",
        )
        funding = FundingSource.objects.create(code="DOCMETA", name="Doc Metadata")
        receiving = Receiving.objects.create(
            document_number="RCV-2026-DOCMETA",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=funding,
            status=Receiving.Status.DRAFT,
            created_by=user,
        )

        image_buffer = BytesIO()
        from PIL import Image

        Image.new("RGB", (10, 10), (255, 255, 255)).save(image_buffer, format="JPEG")
        image_buffer.seek(0)

        form = ReceivingDocumentInlineForm(
            data={
                "receiving": receiving.pk,
                "file_name": "manual name",
                "file_type": "manual/type",
            },
            files={
                "file": SimpleUploadedFile(
                    "dokumen.jpg",
                    image_buffer.read(),
                    content_type="image/jpeg",
                )
            },
        )

        self.assertTrue(form.is_valid(), form.errors)
        document = form.save(commit=False)
        self.assertEqual(document.file_name, "dokumen.jpg")
        self.assertEqual(document.file_type, "image/jpeg")

    def test_receiving_document_form_accepts_existing_file_without_revalidation(self):
        from apps.receiving.admin import ReceivingDocumentInlineForm

        user = User.objects.create_superuser(
            username="doc-existing-admin",
        )
        funding = FundingSource.objects.create(code="DOCEXIST", name="Doc Existing")
        receiving = Receiving.objects.create(
            document_number="RCV-2026-DOCEXIST",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=funding,
            status=Receiving.Status.DRAFT,
            created_by=user,
        )
        document = ReceivingDocument.objects.create(
            receiving=receiving,
            file="receiving/2026/06/dokumen.pdf",
            file_name="dokumen.pdf",
            file_type="application/pdf",
        )

        form = ReceivingDocumentInlineForm(
            data={
                "receiving": receiving.pk,
                "file_name": document.file_name,
                "file_type": document.file_type,
            },
            instance=document,
        )

        self.assertTrue(form.is_valid(), form.errors)
        saved_document = form.save(commit=False)
        self.assertEqual(saved_document.file_name, "dokumen.pdf")
        self.assertEqual(saved_document.file_type, "application/pdf")


class ReceivingDocumentAccessTest(TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[3] / "test_storage"
        self.media_dir = temp_root / "media"
        self.private_media_dir = temp_root / "private_media"
        shutil.rmtree(temp_root, ignore_errors=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.private_media_dir.mkdir(parents=True, exist_ok=True)
        self.settings_override = override_settings(
            ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"],
            MEDIA_ROOT=str(self.media_dir),
            PRIVATE_MEDIA_ROOT=str(self.private_media_dir),
            SECURE_SSL_REDIRECT=False,
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(lambda: shutil.rmtree(temp_root, ignore_errors=True))

        self.user = User.objects.create_superuser(
            username="receiving-doc-admin",
            password="secret12345",
        )
        self.client.force_login(self.user)
        self.funding = FundingSource.objects.create(code="DOCAUTH", name="Doc Auth")
        self.receiving = Receiving.objects.create(
            document_number="RCV-2026-DOCAUTH",
            receiving_type=Receiving.ReceivingType.GRANT,
            receiving_date=date(2026, 3, 16),
            sumber_dana=self.funding,
            status=Receiving.Status.VERIFIED,
            created_by=self.user,
            verified_by=self.user,
        )
        self.document = ReceivingDocument.objects.create(
            receiving=self.receiving,
            file=SimpleUploadedFile(
                "surat hibah.pdf",
                b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF",
                content_type="application/pdf",
            ),
            file_name="surat hibah.pdf",
            file_type="application/pdf",
        )

    def test_receiving_document_uses_private_storage_root(self):
        stored_path = Path(self.document.file.path)

        self.assertTrue(stored_path.exists())
        self.assertTrue(
            stored_path.is_relative_to(self.private_media_dir)
        )
        self.assertFalse(stored_path.is_relative_to(self.media_dir))

    def test_receiving_detail_shows_document_download_link(self):
        response = self.client.get(
            reverse("receiving:receiving_detail", args=[self.receiving.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lampiran Dokumen")
        self.assertContains(response, self.document.file_name)
        self.assertContains(
            response,
            reverse(
                "receiving:receiving_document_download",
                args=[self.receiving.pk, self.document.pk],
            ),
        )

    def test_receiving_document_download_requires_login(self):
        self.client.logout()

        response = self.client.get(
            reverse(
                "receiving:receiving_document_download",
                args=[self.receiving.pk, self.document.pk],
            )
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_receiving_document_download_requires_view_permission(self):
        restricted_user = User.objects.create_user(
            username="receiving-doc-puskesmas",
            password="secret12345",
            role=User.Role.PUSKESMAS,
        )
        self.client.force_login(restricted_user)

        response = self.client.get(
            reverse(
                "receiving:receiving_document_download",
                args=[self.receiving.pk, self.document.pk],
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_receiving_document_download_returns_attachment_and_logs(self):
        with self.assertLogs("security", level="INFO") as logs:
            response = self.client.get(
                reverse(
                    "receiving:receiving_document_download",
                    args=[self.receiving.pk, self.document.pk],
                )
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertIn('filename="surat hibah.pdf"', response["Content-Disposition"])
        self.assertEqual(
            b"".join(response.streaming_content),
            b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF",
        )
        self.assertTrue(
            any(
                "receiving_document_download_succeeded" in message
                for message in logs.output
            )
        )

