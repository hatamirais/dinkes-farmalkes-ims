from django.test import TestCase
from django.urls import reverse

from apps.distribution.models import Distribution
from apps.items.models import Category, Facility, FundingSource, Item, Location, Unit
from apps.stock.models import Stock
from apps.users.models import User


class NumberingHistoryReportTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.user = User.objects.create_superuser(
			username="reports-admin",
			password="secret12345",
		)
		cls.unit = Unit.objects.create(code="TAB", name="Tablet")
		cls.category = Category.objects.create(
			code="REPORT-CAT", name="Report Category", sort_order=1
		)
		cls.item = Item.objects.create(
			nama_barang="Paracetamol 500mg",
			satuan=cls.unit,
			kategori=cls.category,
		)
		cls.location = Location.objects.create(code="REP-LOC", name="Gudang Laporan")
		cls.funding_source = FundingSource.objects.create(code="BOK", name="BOK")
		cls.facility = Facility.objects.create(code="PKM-REP", name="Puskesmas Laporan")
		cls.stock = Stock.objects.create(
			item=cls.item,
			location=cls.location,
			batch_lot="REP-01",
			expiry_date="2027-12-31",
			quantity=10,
			reserved=0,
			unit_price=1000,
			sumber_dana=cls.funding_source,
		)

	def setUp(self):
		self.client.force_login(self.user)

	def _create_distribution(self, distribution_type, document_number=None):
		dist = Distribution.objects.create(
			distribution_type=distribution_type,
			document_number=document_number or "",
			request_date="2026-04-01",
			facility=self.facility,
			status=Distribution.Status.DRAFT,
			created_by=self.user,
			notes="Catatan ringkas",
		)
		dist.items.create(
			item=self.item,
			quantity_requested=5,
			quantity_approved=5,
			stock=self.stock,
		)
		return dist

	def test_numbering_history_page_lists_lplpo_and_special_request(self):
		lplpo_dist = self._create_distribution(Distribution.DistributionType.LPLPO)
		special_dist = self._create_distribution(Distribution.DistributionType.SPECIAL_REQUEST)

		response = self.client.get(reverse('reports:numbering_history'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, lplpo_dist.document_number)
		self.assertContains(response, special_dist.document_number)
		self.assertContains(response, "Riwayat Penomoran")
		self.assertContains(response, "Lihat Dokumen")

	def test_numbering_history_page_filters_by_document_type(self):
		lplpo_dist = self._create_distribution(Distribution.DistributionType.LPLPO)
		self._create_distribution(Distribution.DistributionType.SPECIAL_REQUEST)

		response = self.client.get(
			reverse('reports:numbering_history'),
			{'distribution_type': Distribution.DistributionType.LPLPO, 'year': 2026},
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, lplpo_dist.document_number)
		self.assertNotContains(response, 'KD.F/2026')

	def test_numbering_history_page_shows_print_and_export_actions(self):
		self._create_distribution(Distribution.DistributionType.LPLPO)

		response = self.client.get(reverse('reports:numbering_history'))

		self.assertContains(response, 'Cetak Laporan')
		self.assertContains(response, 'Export Excel')

	def test_numbering_history_excel_export_returns_workbook(self):
		self._create_distribution(Distribution.DistributionType.LPLPO)

		response = self.client.get(
			reverse('reports:numbering_history'),
			{'year': 2026, 'format': 'excel'},
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(
			response['Content-Type'],
			'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
		)
		self.assertIn('Riwayat_Penomoran_2026.xlsx', response['Content-Disposition'])


class PengeluaranReportTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.user = User.objects.create_superuser(
			username="pengeluaran-admin",
			password="secret12345",
		)
		cls.unit = Unit.objects.create(code="BOT", name="Botol")
		cls.category = Category.objects.create(
			code="OUT-CAT", name="Outbound Category", sort_order=1
		)
		cls.item = Item.objects.create(
			nama_barang="Amoxicillin Syrup",
			satuan=cls.unit,
			kategori=cls.category,
		)
		cls.location = Location.objects.create(code="OUT-LOC", name="Gudang Pengeluaran")
		cls.funding_source = FundingSource.objects.create(code="DAU", name="DAU")
		cls.facility = Facility.objects.create(code="PKM-OUT", name="Puskesmas Pengeluaran")
		cls.other_facility = Facility.objects.create(code="PKM-ALT", name="Puskesmas Alternatif")
		cls.stock = Stock.objects.create(
			item=cls.item,
			location=cls.location,
			batch_lot="OUT-01",
			expiry_date="2027-10-31",
			quantity=50,
			reserved=0,
			unit_price=2500,
			sumber_dana=cls.funding_source,
		)

	def setUp(self):
		self.client.force_login(self.user)

	def _create_distribution(self, distribution_type, facility=None, document_number=None):
		dist = Distribution.objects.create(
			distribution_type=distribution_type,
			document_number=document_number or "",
			request_date="2026-04-15",
			facility=facility or self.facility,
			status=Distribution.Status.DISTRIBUTED,
			created_by=self.user,
			notes="Pengeluaran terverifikasi",
		)
		dist.items.create(
			item=self.item,
			quantity_requested=7,
			quantity_approved=5,
			stock=self.stock,
		)
		return dist

	def test_pengeluaran_report_filters_by_distribution_type(self):
		allocation_dist = self._create_distribution(
			Distribution.DistributionType.ALLOCATION,
			document_number="ALLOC-REP-001",
		)
		self._create_distribution(
			Distribution.DistributionType.LPLPO,
			document_number="LPLPO-REP-001",
		)

		response = self.client.get(
			reverse('reports:pengeluaran'),
			{
				'start_date': '2026-04-01',
				'end_date': '2026-04-30',
				'distribution_type': Distribution.DistributionType.ALLOCATION,
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, allocation_dist.document_number)
		self.assertNotContains(response, 'LPLPO-REP-001')

	def test_pengeluaran_report_combined_view_remains_available(self):
		allocation_dist = self._create_distribution(
			Distribution.DistributionType.ALLOCATION,
			document_number="ALLOC-REP-ALL",
		)
		lplpo_dist = self._create_distribution(
			Distribution.DistributionType.LPLPO,
			document_number="LPLPO-REP-ALL",
		)

		response = self.client.get(
			reverse('reports:pengeluaran'),
			{
				'start_date': '2026-04-01',
				'end_date': '2026-04-30',
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, allocation_dist.document_number)
		self.assertContains(response, lplpo_dist.document_number)
		self.assertContains(response, 'Semua Distribusi')
		self.assertContains(response, 'Permintaan Khusus')
		self.assertContains(response, 'Alokasi')
		self.assertContains(response, 'LPLPO')

	def test_pengeluaran_report_combines_facility_and_distribution_type_filters(self):
		matching_dist = self._create_distribution(
			Distribution.DistributionType.SPECIAL_REQUEST,
			facility=self.facility,
			document_number="SPEC-REP-001",
		)
		self._create_distribution(
			Distribution.DistributionType.SPECIAL_REQUEST,
			facility=self.other_facility,
			document_number="SPEC-REP-ALT",
		)
		self._create_distribution(
			Distribution.DistributionType.ALLOCATION,
			facility=self.facility,
			document_number="ALLOC-REP-FAC",
		)

		response = self.client.get(
			reverse('reports:pengeluaran'),
			{
				'start_date': '2026-04-01',
				'end_date': '2026-04-30',
				'facility': self.facility.pk,
				'distribution_type': Distribution.DistributionType.SPECIAL_REQUEST,
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, matching_dist.document_number)
		self.assertNotContains(response, 'SPEC-REP-ALT')
		self.assertNotContains(response, 'ALLOC-REP-FAC')

	def test_pengeluaran_report_invalid_distribution_type_keeps_report_empty(self):
		self._create_distribution(
			Distribution.DistributionType.ALLOCATION,
			document_number="ALLOC-REP-INVALID",
		)

		response = self.client.get(
			reverse('reports:pengeluaran'),
			{
				'start_date': '2026-04-01',
				'end_date': '2026-04-30',
				'distribution_type': 'NOT_A_REAL_TYPE',
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertFalse(response.context['form'].is_valid())
		self.assertEqual(response.context['report_data'], [])
		self.assertNotContains(response, 'ALLOC-REP-INVALID')

	def test_pengeluaran_report_excel_export_uses_active_tab_label(self):
		self._create_distribution(
			Distribution.DistributionType.ALLOCATION,
			document_number="ALLOC-REP-EXPORT",
		)

		response = self.client.get(
			reverse('reports:pengeluaran'),
			{
				'start_date': '2026-04-01',
				'end_date': '2026-04-30',
				'distribution_type': Distribution.DistributionType.ALLOCATION,
				'format': 'excel',
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(
			response['Content-Type'],
			'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
		)
		self.assertIn(
			'Laporan_Pengeluaran_Alokasi_2026-04-01_2026-04-30.xlsx',
			response['Content-Disposition'],
		)

	def test_pengeluaran_report_tabs_include_distribution_type_query(self):
		response = self.client.get(
			reverse('reports:pengeluaran'),
			{
				'start_date': '2026-04-01',
				'end_date': '2026-04-30',
			},
		)

		self.assertEqual(response.status_code, 200)
		tabs = response.context['tabs']
		self.assertTrue(any(tab['value'] == '' for tab in tabs))
		self.assertTrue(any(tab['value'] == Distribution.DistributionType.ALLOCATION for tab in tabs))

		allocation_tab = next(
			tab for tab in tabs if tab['value'] == Distribution.DistributionType.ALLOCATION
		)
		self.assertIn('distribution_type=ALLOCATION', allocation_tab['url'])
		self.assertIn('start_date=2026-04-01', allocation_tab['url'])
		self.assertIn('end_date=2026-04-30', allocation_tab['url'])
