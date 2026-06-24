from decimal import Decimal
from datetime import timedelta
from datetime import date
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.test import SimpleTestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.csv_exports import SanitizedCSV
from apps.users.models import User
from apps.stock.admin import StockAdmin, StockResource
from apps.items.models import Unit, Category, Item, Location, FundingSource
from apps.stock.models import Stock, StockTransfer, StockTransferItem, Transaction
from apps.core.models import SystemSettings


class StockAdminCsvExportSecurityTest(TestCase):
    def setUp(self):
        self.unit = Unit.objects.create(code='TAB', name='Tablet')
        self.category = Category.objects.create(code='OBAT', name='Obat', sort_order=1)
        self.item = Item.objects.create(
            nama_barang='Paracetamol 500mg',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
        )
        self.location = Location.objects.create(code='GUDANG', name='Gudang Utama')
        self.funding = FundingSource.objects.create(code='APBD', name='APBD')

    def test_stock_admin_uses_sanitized_csv_format(self):
        admin = StockAdmin(Stock, AdminSite())

        self.assertIn(SanitizedCSV, admin.get_export_formats())

    def test_stock_resource_csv_export_neutralizes_formula_prefixed_values(self):
        stock = Stock.objects.create(
            item=self.item,
            location=self.location,
            batch_lot='@BATCH-01',
            expiry_date=date(2027, 1, 1),
            quantity=Decimal('25'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding,
        )

        dataset = StockResource().export(Stock.objects.filter(pk=stock.pk))
        csv_output = SanitizedCSV().export_data(dataset)

        self.assertIn("'@BATCH-01", csv_output)
        self.assertIn(self.item.kode_barang, csv_output)

@override_settings(SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class StockCardTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username='admin_stock',
            password='secret12345',
        )
        self.client.force_login(self.user)

        self.unit = Unit.objects.create(code='TAB', name='Tablet')
        self.category = Category.objects.create(code='OBAT', name='Obat', sort_order=1)
        self.item = Item.objects.create(
            kode_barang='ITM-0001',
            nama_barang='Paracetamol 500mg',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
        )
        self.location = Location.objects.create(code='GUDANG', name='Gudang Utama')
        self.funding = FundingSource.objects.create(code='APBD', name='APBD')
        settings = SystemSettings.get_settings()
        settings.facility_name = "Instalasi Farmasi"
        settings.save()

        # Create transactions for testing running balance
        # TX 1: IN 100
        self.tx1 = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=self.location,
            batch_lot='B01',
            quantity=Decimal('100'),
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=1,
            user=self.user,
        )
        # TX 2: OUT 20
        self.tx2 = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.item,
            location=self.location,
            batch_lot='B01',
            quantity=Decimal('20'),
            reference_type=Transaction.ReferenceType.DISTRIBUTION,
            reference_id=1,
            user=self.user,
        )
        # Shift tx1 dates to be purely sequential
        self.tx1.created_at = timezone.now() - timedelta(days=5)
        self.tx1.save()
        self.tx2.created_at = timezone.now() - timedelta(days=2)
        self.tx2.save()

    def test_stock_card_select_view(self):
        response = self.client.get(reverse('stock:stock_card_select'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'stock/stock_card_select.html')

    def test_api_item_search(self):
        response = self.client.get(reverse('stock:api_item_search'), {'q': 'Parace'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['results']), 1)
        self.assertEqual(data['results'][0]['id'], self.item.id)
        self.assertIn('Paracetamol', data['results'][0]['text'])
        self.assertIsInstance(data['results'][0]['stock'], float)
        self.assertEqual(data['results'][0]['stock'], 0.0)

    def test_stock_card_detail_view_and_balance(self):
        response = self.client.get(reverse('stock:stock_card_detail', args=[self.item.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'stock/stock_card_detail.html')

        # Verify context contains funding_source_cards
        cards = response.context['funding_source_cards']
        self.assertTrue(len(cards) >= 1)

        # All transactions share one sumber_dana (or None), so should be in one card
        card = cards[0]
        transactions = card['transactions']
        self.assertEqual(len(transactions), 2)
        self.assertEqual(card['closing_balance'], Decimal('80'))  # 100 - 20
        self.assertEqual(card['total_in'], Decimal('100'))
        self.assertEqual(card['total_out'], Decimal('20'))

        # Verify running balance on individual objects
        self.assertEqual(transactions[0].running_balance, Decimal('100'))
        self.assertEqual(transactions[1].running_balance, Decimal('80'))

    def test_stock_card_detail_date_filter(self):
        # Filter starting after tx1, so tx1 becomes opening balance
        filter_date = (timezone.now() - timedelta(days=3)).strftime('%Y-%m-%d')
        response = self.client.get(f"{reverse('stock:stock_card_detail', args=[self.item.id])}?date_from={filter_date}")

        self.assertEqual(response.status_code, 200)
        cards = response.context['funding_source_cards']
        self.assertTrue(len(cards) >= 1)

        card = cards[0]
        transactions = card['transactions']

        # Only tx2 should be in list
        self.assertEqual(len(transactions), 1)
        self.assertEqual(card['opening_balance'], Decimal('100'))
        self.assertEqual(card['closing_balance'], Decimal('80'))

        # tx2 running balance should still be 80
        self.assertEqual(transactions[0].running_balance, Decimal('80'))

    def test_stock_card_location_filter_excludes_transfer_from_totals(self):
        destination = Location.objects.create(code='PKM', name='Puskesmas Tujuan')
        transfer = StockTransfer.objects.create(
            source_location=self.location,
            destination_location=destination,
            created_by=self.user,
        )

        transfer_out = Transaction.objects.create(
            transaction_type=Transaction.TransactionType.OUT,
            item=self.item,
            location=self.location,
            batch_lot='B01',
            quantity=Decimal('5'),
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=transfer.id,
            user=self.user,
        )
        Transaction.objects.create(
            transaction_type=Transaction.TransactionType.IN,
            item=self.item,
            location=destination,
            batch_lot='B01',
            quantity=Decimal('5'),
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=transfer.id,
            user=self.user,
        )
        transfer_out.created_at = timezone.now() - timedelta(days=1)
        transfer_out.save(update_fields=['created_at'])

        response = self.client.get(
            reverse('stock:stock_card_detail', args=[self.item.id]),
            {'location': self.location.id},
        )

        self.assertEqual(response.status_code, 200)
        card = response.context['funding_source_cards'][0]
        transactions = card['transactions']

        self.assertEqual(len(transactions), 3)
        self.assertEqual(card['closing_balance'], Decimal('75'))
        self.assertEqual(card['total_in'], Decimal('100'))
        self.assertEqual(card['total_out'], Decimal('20'))
        self.assertEqual(transactions[-1].reference_type, Transaction.ReferenceType.TRANSFER)
        self.assertEqual(transactions[-1].running_balance, Decimal('75'))

    def test_stock_card_transfer_transactions_display_computed_fields(self):
        """Verify transfer transactions have computed display fields for UI rendering."""
        destination = Location.objects.create(code='PKM2', name='Puskesmas Pembantu')
        transfer = StockTransfer.objects.create(
            source_location=self.location,
            destination_location=destination,
            created_by=self.user,
        )

        # Create receiving transaction
        Transaction.objects.create(
            item=self.item,
            transaction_type=Transaction.TransactionType.IN,
            reference_type=Transaction.ReferenceType.RECEIVING,
            reference_id=1,
            quantity=Decimal('100'),
            location=self.location,
            sumber_dana=self.funding,
            user=self.user,
            batch_lot="BATCH-001",
        )

        # Create transfer out (internal move)
        transfer_out = Transaction.objects.create(
            item=self.item,
            transaction_type=Transaction.TransactionType.OUT,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=transfer.id,
            quantity=Decimal('30'),
            location=self.location,
            sumber_dana=self.funding,
            user=self.user,
            batch_lot="BATCH-001",
        )
        transfer_in = Transaction.objects.create(
            item=self.item,
            transaction_type=Transaction.TransactionType.IN,
            reference_type=Transaction.ReferenceType.TRANSFER,
            reference_id=transfer.id,
            quantity=Decimal('30'),
            location=destination,
            sumber_dana=self.funding,
            user=self.user,
            batch_lot="BATCH-001",
        )
        transfer_out.created_at = timezone.now() - timedelta(days=1)
        transfer_out.save(update_fields=['created_at'])
        transfer_in.created_at = timezone.now() - timedelta(hours=12)
        transfer_in.save(update_fields=['created_at'])

        response = self.client.get(
            reverse('stock:stock_card_detail', args=[self.item.id]),
            {'sumber_dana': self.funding.id},
        )

        self.assertEqual(response.status_code, 200)
        cards = response.context['funding_source_cards']
        self.assertGreater(len(cards), 0)

        # Find the card with self.funding sumber_dana
        card = None
        for c in cards:
            if c['sumber_dana'] == self.funding:
                card = c
                break

        self.assertIsNotNone(card)
        transactions = card['transactions']
        self.assertGreater(len(transactions), 0)

        # The transfer_out should be in the transactions (created last, so last in list)
        # Find it by reference_type
        transfer_out_tx = None
        transfer_in_tx = None
        receiving_tx = None
        for tx in transactions:
            if (
                tx.reference_type == Transaction.ReferenceType.TRANSFER
                and tx.transaction_type == Transaction.TransactionType.OUT
            ):
                transfer_out_tx = tx
            elif (
                tx.reference_type == Transaction.ReferenceType.TRANSFER
                and tx.transaction_type == Transaction.TransactionType.IN
            ):
                transfer_in_tx = tx
            elif tx.reference_type == Transaction.ReferenceType.RECEIVING:
                receiving_tx = tx
        self.assertIsNotNone(transfer_out_tx, "Transfer out transaction not found in card")
        self.assertIsNotNone(transfer_in_tx, "Transfer in transaction not found in card")
        self.assertIsNotNone(receiving_tx, "Receiving transaction not found in card")

        # Verify transfer transaction has display fields
        self.assertTrue(hasattr(transfer_out_tx, 'is_transfer_transaction'))
        self.assertTrue(transfer_out_tx.is_transfer_transaction)
        self.assertEqual(transfer_out_tx.transfer_quantity, Decimal('30'))
        self.assertEqual(transfer_out_tx.activity_label, 'Mutasi Keluar')
        self.assertEqual(transfer_out_tx.dari_kepada, 'Instalasi Farmasi')
        self.assertEqual(transfer_out_tx.location_label, self.location.name)

        self.assertTrue(transfer_in_tx.is_transfer_transaction)
        self.assertEqual(transfer_in_tx.transfer_quantity, Decimal('30'))
        self.assertEqual(transfer_in_tx.activity_label, 'Mutasi Masuk')
        self.assertEqual(transfer_in_tx.dari_kepada, 'Instalasi Farmasi')
        self.assertEqual(transfer_in_tx.location_label, destination.name)

        # Verify non-transfer transaction does not have transfer marker
        self.assertTrue(hasattr(receiving_tx, 'is_transfer_transaction'))
        self.assertFalse(receiving_tx.is_transfer_transaction)
        self.assertIsNone(receiving_tx.transfer_quantity)
        self.assertEqual(receiving_tx.activity_label, 'Penerimaan')
        self.assertEqual(receiving_tx.dari_kepada, 'Instalasi Farmasi')
        self.assertEqual(receiving_tx.location_label, self.location.name)

        self.assertContains(response, 'Aktivitas')
        self.assertContains(response, 'Mutasi Masuk')
        self.assertContains(response, 'Mutasi Keluar')
        self.assertContains(response, 'Lokasi Stok')
        self.assertContains(response, 'Harga Satuan: Rp 0')
        self.assertContains(response, 'Instalasi Farmasi')
        self.assertContains(response, 'Gudang Utama')
        self.assertContains(response, 'Kolom <strong>Dari / Kepada</strong> menunjukkan fasilitas atau mitra dokumen', html=False)

        print_response = self.client.get(
            reverse('stock:stock_card_print', args=[self.item.id]),
            {'sumber_dana': self.funding.id},
        )
        self.assertEqual(print_response.status_code, 200)
        self.assertContains(print_response, 'Aktivitas')
        self.assertContains(print_response, 'Mutasi Masuk')
        self.assertContains(print_response, 'Mutasi Keluar')
        self.assertContains(print_response, 'Lokasi')
        self.assertContains(print_response, 'Harga Satuan: Rp 0')
        self.assertContains(print_response, 'Instalasi Farmasi')
        self.assertContains(print_response, 'Kolom Dari / Kepada menunjukkan fasilitas atau mitra dokumen.')


class StockTransferModelTests(SimpleTestCase):
    def test_save_retries_when_auto_generated_document_number_conflicts(self):
        transfer = StockTransfer(
            source_location_id=1,
            destination_location_id=2,
            created_by_id=1,
        )

        with (
            patch.object(
                StockTransfer,
                "generate_document_number",
                side_effect=["TRF-2026-00001", "TRF-2026-00002"],
            ),
            patch(
                "django.db.models.base.Model.save",
                side_effect=[IntegrityError("duplicate key value violates unique constraint stock_transfers_document_number_key"), None],
            ) as mock_save,
        ):
            transfer.save()

        self.assertEqual(mock_save.call_count, 2)
        self.assertEqual(transfer.document_number, "TRF-2026-00002")

    def test_stock_transfer_item_clean_rejects_non_finite_quantity(self):
        transfer_item = StockTransferItem(quantity=Decimal("-Infinity"))

        with self.assertRaises(ValidationError) as exc:
            transfer_item.clean()

        self.assertEqual(
            exc.exception.message_dict["quantity"],
            ["Jumlah mutasi tidak boleh NaN atau Infinity."],
        )

@override_settings(SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class StockListViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username='stock-list-admin',
            password='secret12345',
        )
        self.client.force_login(self.user)

        self.unit = Unit.objects.create(code='TAB2', name='Tablet 2')
        self.category = Category.objects.create(code='OBT2', name='Obat 2', sort_order=1)
        self.location_a = Location.objects.create(code='LOC-A', name='Gudang A')
        self.location_b = Location.objects.create(code='LOC-B', name='Gudang B')
        self.funding_hibah = FundingSource.objects.create(code='HIBAH', name='Hibah')
        self.funding_dau = FundingSource.objects.create(code='DAU', name='Dana Alokasi Umum')
        self.funding_pad = FundingSource.objects.create(code='PAD', name='Pendapatan Asli Daerah')
        self.funding_other = FundingSource.objects.create(code='APBD', name='APBD')
        self.today = timezone.localdate()

        self.item_expired = Item.objects.create(
            kode_barang='ITM-EXPIRED',
            nama_barang='Stok Expired',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
        )
        self.item_expiring = Item.objects.create(
            kode_barang='ITM-EXPIRING',
            nama_barang='Stok Warning',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
        )
        self.item_safe = Item.objects.create(
            kode_barang='ITM-SAFE',
            nama_barang='Stok Aman',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
        )
        self.item_other = Item.objects.create(
            kode_barang='ITM-OTHER',
            nama_barang='Stok Lain',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
        )

        self.expired_stock = Stock.objects.create(
            item=self.item_expired,
            location=self.location_a,
            batch_lot='EXP-01',
            expiry_date=self.today - timedelta(days=3),
            quantity=Decimal('10'),
            reserved=Decimal('2'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding_hibah,
        )
        self.expiring_stock = Stock.objects.create(
            item=self.item_expiring,
            location=self.location_a,
            batch_lot='WARN-01',
            expiry_date=self.today + timedelta(days=10),
            quantity=Decimal('5'),
            reserved=Decimal('1'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding_dau,
        )
        self.safe_stock = Stock.objects.create(
            item=self.item_safe,
            location=self.location_a,
            batch_lot='SAFE-01',
            expiry_date=self.today + timedelta(days=45),
            quantity=Decimal('20'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding_pad,
        )
        self.other_stock = Stock.objects.create(
            item=self.item_other,
            location=self.location_b,
            batch_lot='OTHER-01',
            expiry_date=self.today + timedelta(days=70),
            quantity=Decimal('7'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding_other,
        )
        self.item_today = Item.objects.create(
            kode_barang='ITM-TODAY',
            nama_barang='Stok Hari Ini',
            satuan=self.unit,
            kategori=self.category,
            minimum_stock=Decimal('0'),
        )
        self.today_stock = Stock.objects.create(
            item=self.item_today,
            location=self.location_a,
            batch_lot='TODAY-01',
            expiry_date=self.today,
            quantity=Decimal('9'),
            reserved=Decimal('0'),
            unit_price=Decimal('1000'),
            sumber_dana=self.funding_dau,
        )

    def test_stock_list_exposes_read_only_table_and_whole_number_quantities(self):
        response = self.client.get(reverse('stock:stock_list'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'stock/stock_list.html')
        self.assertEqual(response.context['stock_stats']['total_entries'], 5)
        self.assertEqual(response.context['stock_stats']['total_quantity'], Decimal('51'))
        self.assertEqual(response.context['stock_stats']['total_reserved'], Decimal('3'))
        self.assertEqual(response.context['stock_stats']['total_available'], Decimal('48'))
        self.assertEqual(response.context['stock_stats']['attention_count'], 5)
        self.assertEqual(response.context['quick_counts']['expired'], 2)
        self.assertEqual(response.context['quick_counts']['expiring'], 3)
        self.assertEqual(response.context['quick_counts']['safe'], 0)

        stocks_by_batch = {stock.batch_lot: stock for stock in response.context['stocks'].object_list}
        self.assertEqual(stocks_by_batch['EXP-01'].expiry_badge_class, 'text-bg-danger')
        self.assertEqual(stocks_by_batch['WARN-01'].expiry_badge_class, 'text-bg-warning')
        self.assertEqual(stocks_by_batch['SAFE-01'].expiry_badge_class, 'text-bg-warning')
        self.assertEqual(stocks_by_batch['TODAY-01'].expiry_badge_class, 'text-bg-danger')
        self.assertEqual(stocks_by_batch['EXP-01'].source_fund_badge_class, 'text-bg-warning')
        self.assertEqual(stocks_by_batch['WARN-01'].source_fund_badge_class, 'text-bg-info')
        self.assertEqual(stocks_by_batch['SAFE-01'].source_fund_badge_class, 'text-bg-success')
        self.assertContains(response, 'sticky-top')
        self.assertContains(response, '>51<', html=False)
        self.assertContains(response, '>48<', html=False)
        self.assertContains(response, '>20<', html=False)
        self.assertNotContains(response, 'Ada Reserved')
        self.assertNotContains(response, 'stock-bulk-bar')
        self.assertNotContains(response, 'data-row-actions')
        self.assertNotContains(response, 'data-row-checkbox')
        self.assertNotContains(response, 'Reserved')


    def test_stock_list_treats_today_expiry_as_expired(self):
        response = self.client.get(
            reverse('stock:stock_list'),
            {'quick': 'expired'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_quick'], 'expired')
        self.assertEqual(response.context['quick_counts']['expired'], 2)
        self.assertEqual(
            [stock.batch_lot for stock in response.context['stocks'].object_list],
            ['EXP-01', 'TODAY-01'],
        )
        self.assertContains(response, 'TODAY-01')
        self.assertNotContains(response, 'WARN-01')

    def test_stock_list_filters_by_quick_filter_and_expiry_range(self):
        response = self.client.get(
            reverse('stock:stock_list'),
            {
                'quick': 'expiring',
                'expiry_from': (self.today + timedelta(days=1)).strftime('%Y-%m-%d'),
                'expiry_to': (self.today + timedelta(days=90)).strftime('%Y-%m-%d'),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_quick'], 'expiring')
        self.assertEqual(
            [stock.batch_lot for stock in response.context['stocks'].object_list],
            ['SAFE-01', 'OTHER-01', 'WARN-01'],
        )
        self.assertEqual(response.context['stock_stats']['total_entries'], 3)
        self.assertContains(response, 'WARN-01')
        self.assertContains(response, 'SAFE-01')
        self.assertContains(response, 'OTHER-01')
        self.assertNotContains(response, 'EXP-01')

    def test_stock_list_ignores_invalid_filter_values(self):
        response = self.client.get(
            reverse('stock:stock_list'),
            {
                'location': 'abc',
                'sumber_dana': '999999',
                'expiry_from': '2026-99-99',
                'expiry_to': '0001-01-01',
                'quick': 'unknown',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_location'], '')
        self.assertEqual(response.context['selected_sumber_dana'], '')
        self.assertEqual(response.context['selected_quick'], '')
        self.assertIsNone(response.context['expiry_from'])
        self.assertIsNone(response.context['expiry_to'])
        self.assertEqual(response.context['stocks'].paginator.count, 5)
