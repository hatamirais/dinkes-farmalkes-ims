import importlib
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.messages import get_messages
from django.apps import apps as django_apps
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.tests.mixins import SecureClientDefaultsMixin
from apps.distribution.models import Distribution, DistributionItem
from apps.items.models import Category, Facility, FundingSource, Item, Location, Unit
from apps.stock.models import Stock
from apps.users.models import ModuleAccess, User
from apps.lplpo.models import (
	LPLPO,
	LPLPOItem,
	format_lplpo_period_label,
	get_active_lplpo_year,
	get_indonesian_month_name,
	is_january_bootstrap_period,
)


class LPLPOTestCase(SecureClientDefaultsMixin, TestCase):

	@classmethod
	def setUpTestData(cls):
		cls.unit = Unit.objects.create(code="TAB", name="Tablet")
		cls.category = Category.objects.create(code="OBT", name="Obat", sort_order=1)
		cls.funding_source = FundingSource.objects.create(code="DAK", name="DAK")
		cls.location = Location.objects.create(code="GUD", name="Gudang")
		cls.facility = Facility.objects.create(
			code="PKM-01",
			name="Puskesmas Satu",
			facility_type=Facility.FacilityType.PUSKESMAS,
		)
		cls.other_facility = Facility.objects.create(
			code="PKM-02",
			name="Puskesmas Dua",
			facility_type=Facility.FacilityType.PUSKESMAS,
		)
		cls.item_a = Item.objects.create(
			nama_barang="Paracetamol",
			satuan=cls.unit,
			kategori=cls.category,
			is_active=True,
		)
		cls.item_b = Item.objects.create(
			nama_barang="Amoxicillin",
			satuan=cls.unit,
			kategori=cls.category,
			is_active=True,
		)
		cls.inactive_item = Item.objects.create(
			nama_barang="Item Nonaktif",
			satuan=cls.unit,
			kategori=cls.category,
			is_active=False,
		)

		cls.puskesmas_user = User.objects.create_user(
			username="puskesmas",
			password="TestPassword123!",
			role=User.Role.PUSKESMAS,
			facility=cls.facility,
		)
		cls.other_puskesmas_user = User.objects.create_user(
			username="puskesmas2",
			password="TestPassword123!",
			role=User.Role.PUSKESMAS,
			facility=cls.other_facility,
		)
		cls.gudang_user = User.objects.create_user(
			username="gudang",
			password="TestPassword123!",
			role=User.Role.GUDANG,
		)
		cls.staff_user = User.objects.create_superuser(
			username="staff",
			email="staff@example.com",
			password="TestPassword123!",
		)
		cls.superuser = User.objects.create_superuser(
			username="root",
			email="root@example.com",
			password="TestPassword123!",
		)

		for user, scope in (
			(cls.puskesmas_user, ModuleAccess.Scope.OPERATE),
			(cls.other_puskesmas_user, ModuleAccess.Scope.OPERATE),
			(cls.gudang_user, ModuleAccess.Scope.OPERATE),
			(cls.staff_user, ModuleAccess.Scope.MANAGE),
		):
			ModuleAccess.objects.update_or_create(
				user=user,
				module=ModuleAccess.Module.LPLPO,
				defaults={"scope": scope},
			)

	def create_distribution(
		self,
		*,
		facility,
		distributed_date,
		item_quantities,
		status=Distribution.Status.DISTRIBUTED,
	):
		distribution = Distribution.objects.create(
			distribution_type=Distribution.DistributionType.LPLPO,
			facility=facility,
			request_date=distributed_date,
			distributed_date=distributed_date,
			status=status,
			created_by=self.staff_user,
		)
		DistributionItem.objects.bulk_create(
			[
				DistributionItem(
					distribution=distribution,
					item=item,
					quantity_requested=quantity,
					quantity_approved=quantity,
				)
				for item, quantity in item_quantities
			]
		)
		return distribution

	def create_lplpo(self, **kwargs):
		defaults = {
			"facility": self.facility,
			"bulan": 2,
			"tahun": 2026,
			"status": LPLPO.Status.DRAFT,
			"created_by": self.puskesmas_user,
		}
		defaults.update(kwargs)
		return LPLPO.objects.create(**defaults)

	def set_submitted_at(self, lplpo, year, month, day):
		lplpo.submitted_at = timezone.make_aware(datetime(year, month, day))
		lplpo.save(update_fields=["submitted_at", "updated_at"])

	def setUp(self):
		super().setUp()


class LPLPOWorkflowTests(LPLPOTestCase):
	def test_auto_generate_items_on_create(self):
		self.client.force_login(self.puskesmas_user)
		active_year = get_active_lplpo_year()

		response = self.client.post(
			reverse("lplpo:lplpo_create"),
			{"bulan": "1", "tahun": str(active_year), "notes": "Draft awal"},
		)

		self.assertEqual(response.status_code, 302)
		lplpo = LPLPO.objects.get(facility=self.facility, bulan=1, tahun=active_year)
		items = list(lplpo.items.order_by("item__nama_barang"))

		self.assertEqual(len(items), 2)
		self.assertCountEqual(
			[item.item_id for item in items],
			[self.item_a.id, self.item_b.id],
		)
		self.assertTrue(all(item.item.is_active for item in items))
		self.assertTrue(all(item.pemberian_jumlah is None for item in items))

	def test_create_form_only_offers_next_required_month_for_operator(self):
		self.client.force_login(self.puskesmas_user)
		active_year = get_active_lplpo_year()

		response = self.client.get(reverse("lplpo:lplpo_create"))

		self.assertEqual(response.status_code, 200)
		form = response.context["form"]
		self.assertEqual(list(form.fields["bulan"].choices), [("1", "Januari")])
		self.assertEqual(form.fields["tahun"].initial, active_year)
		self.assertContains(
			response,
			f"Periode berikutnya yang wajib dibuat: {format_lplpo_period_label(1, active_year)}.",
		)
		self.assertContains(response, "Bootstrap Januari Tahun Berjalan")
		self.assertContains(response, "baseline stok awal tahunan")

	def test_create_rejects_skipped_month_when_earlier_month_missing(self):
		self.client.force_login(self.puskesmas_user)
		active_year = get_active_lplpo_year()
		required_period = format_lplpo_period_label(1, active_year)

		response = self.client.post(
			reverse("lplpo:lplpo_create"),
			{"bulan": "3", "tahun": str(active_year), "notes": "Mencoba lompat periode"},
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(
			response,
			f"Periode berikutnya yang wajib dibuat adalah {required_period}.",
		)
		self.assertFalse(
			LPLPO.objects.filter(facility=self.facility, tahun=active_year).exists()
		)

	def test_create_allows_next_month_once_previous_month_exists(self):
		self.client.force_login(self.puskesmas_user)
		active_year = get_active_lplpo_year()

		first_response = self.client.post(
			reverse("lplpo:lplpo_create"),
			{"bulan": "1", "tahun": str(active_year)},
		)
		self.assertEqual(first_response.status_code, 302)

		second_response = self.client.post(
			reverse("lplpo:lplpo_create"),
			{"bulan": "2", "tahun": str(active_year)},
		)

		self.assertEqual(second_response.status_code, 302)
		self.assertTrue(
			LPLPO.objects.filter(facility=self.facility, bulan=1, tahun=active_year).exists()
		)
		self.assertTrue(
			LPLPO.objects.filter(facility=self.facility, bulan=2, tahun=active_year).exists()
		)

	def test_create_rejects_non_active_server_year(self):
		self.client.force_login(self.puskesmas_user)
		active_year = get_active_lplpo_year()
		non_active_year = active_year - 1

		response = self.client.post(
			reverse("lplpo:lplpo_create"),
			{"bulan": "1", "tahun": str(non_active_year)},
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(
			response,
			f"LPLPO baru hanya dapat dibuat untuk tahun server aktif {active_year}.",
		)
		self.assertFalse(
			LPLPO.objects.filter(facility=self.facility, tahun=non_active_year).exists()
		)

	def test_instalasi_farmasi_cannot_create_lplpo(self):
		self.client.force_login(self.gudang_user)

		response = self.client.get(reverse("lplpo:lplpo_create"))

		self.assertEqual(response.status_code, 403)
		self.assertContains(
			response,
			"Hanya operator Puskesmas yang dapat membuat LPLPO.",
			status_code=403,
		)

	def test_super_admin_list_shows_create_button(self):
		self.client.force_login(self.superuser)

		response = self.client.get(reverse("lplpo:lplpo_list"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'id="create-lplpo-btn"')
		self.assertNotContains(response, 'id="print-report-btn"')

	def test_instalasi_farmasi_list_only_shows_submitted_documents(self):
		draft_lplpo = self.create_lplpo(status=LPLPO.Status.DRAFT)
		submitted_lplpo = self.create_lplpo(
			bulan=3,
			tahun=2026,
			status=LPLPO.Status.SUBMITTED,
		)
		self.set_submitted_at(submitted_lplpo, 2026, 4, 5)

		self.client.force_login(self.gudang_user)
		response = self.client.get(reverse("lplpo:lplpo_list"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, submitted_lplpo.document_number)
		self.assertNotContains(response, draft_lplpo.document_number)

	def test_super_admin_list_shows_draft_and_submitted_documents(self):
		draft_lplpo = self.create_lplpo(status=LPLPO.Status.DRAFT)
		submitted_lplpo = self.create_lplpo(
			bulan=3,
			tahun=2026,
			status=LPLPO.Status.SUBMITTED,
		)
		self.set_submitted_at(submitted_lplpo, 2026, 4, 5)

		self.client.force_login(self.superuser)
		response = self.client.get(reverse("lplpo:lplpo_list"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, draft_lplpo.document_number)
		self.assertContains(response, submitted_lplpo.document_number)
		self.assertEqual(
			response.context["submission_month_choices"][0],
			("1", get_indonesian_month_name(1)),
		)

	def test_get_indonesian_month_name_rejects_invalid_month(self):
		with self.assertRaisesMessage(ValueError, "Bulan harus berada pada rentang 1-12."):
			get_indonesian_month_name(0)

	def test_instalasi_farmasi_list_filters_by_submission_month_and_year(self):
		march_submission = self.create_lplpo(status=LPLPO.Status.SUBMITTED, bulan=2, tahun=2026)
		self.set_submitted_at(march_submission, 2026, 3, 15)

		april_submission = self.create_lplpo(status=LPLPO.Status.SUBMITTED, bulan=3, tahun=2026)
		self.set_submitted_at(april_submission, 2026, 4, 10)

		self.client.force_login(self.gudang_user)
		response = self.client.get(
			reverse("lplpo:lplpo_list"),
			{"submitted_month": "4", "submitted_year": "2026"},
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, april_submission.document_number)
		self.assertNotContains(response, march_submission.document_number)

	def test_penerimaan_auto_fill(self):
		self.create_lplpo(bulan=1, tahun=2026, status=LPLPO.Status.CLOSED)
		self.create_distribution(
			facility=self.facility,
			distributed_date=date(2026, 2, 10),
			item_quantities=[
				(self.item_a, Decimal("7.00")),
				(self.item_b, Decimal("2.00")),
			],
		)
		special = self.create_distribution(
			facility=self.facility,
			distributed_date=date(2026, 2, 20),
			item_quantities=[(self.item_a, Decimal("3.00"))],
		)
		special.distribution_type = Distribution.DistributionType.SPECIAL_REQUEST
		special.save(update_fields=["distribution_type", "updated_at"])
		self.create_distribution(
			facility=self.other_facility,
			distributed_date=date(2026, 2, 25),
			item_quantities=[(self.item_a, Decimal("99.00"))],
		)

		self.client.force_login(self.puskesmas_user)
		self.client.post(reverse("lplpo:lplpo_create"), {"bulan": "2", "tahun": "2026"})

		lplpo = LPLPO.objects.get(facility=self.facility, bulan=2, tahun=2026)
		item_a_line = lplpo.items.get(item=self.item_a)
		item_b_line = lplpo.items.get(item=self.item_b)

		self.assertEqual(item_a_line.penerimaan, Decimal("10.00"))
		self.assertEqual(item_b_line.penerimaan, Decimal("2.00"))
		self.assertTrue(item_a_line.penerimaan_auto_filled)
		self.assertTrue(item_b_line.penerimaan_auto_filled)

	def test_january_bootstrap_create_keeps_penerimaan_manual(self):
		self.create_distribution(
			facility=self.facility,
			distributed_date=date(2026, 1, 10),
			item_quantities=[
				(self.item_a, Decimal("7.00")),
				(self.item_b, Decimal("2.00")),
			],
		)
		self.create_distribution(
			facility=self.facility,
			distributed_date=date(2026, 1, 20),
			item_quantities=[(self.item_a, Decimal("3.00"))],
		)

		self.client.force_login(self.puskesmas_user)
		response = self.client.post(
			reverse("lplpo:lplpo_create"),
			{"bulan": "1", "tahun": "2026"},
		)

		self.assertEqual(response.status_code, 302)
		lplpo = LPLPO.objects.get(facility=self.facility, bulan=1, tahun=2026)
		item_a_line = lplpo.items.get(item=self.item_a)
		item_b_line = lplpo.items.get(item=self.item_b)

		self.assertEqual(item_a_line.penerimaan, 0)
		self.assertEqual(item_b_line.penerimaan, 0)
		self.assertFalse(item_a_line.penerimaan_auto_filled)
		self.assertFalse(item_b_line.penerimaan_auto_filled)

	def test_stock_awal_from_previous_lplpo(self):
		previous = self.create_lplpo(bulan=1, tahun=2026, status=LPLPO.Status.CLOSED)
		LPLPOItem.objects.create(
			lplpo=previous,
			item=self.item_a,
			stock_awal=Decimal("5.00"),
			penerimaan=Decimal("5.00"),
			pemakaian=Decimal("0.00"),
		)
		LPLPOItem.objects.create(
			lplpo=previous,
			item=self.item_b,
			stock_awal=Decimal("4.00"),
			penerimaan=Decimal("2.00"),
			pemakaian=Decimal("1.00"),
		)

		self.client.force_login(self.puskesmas_user)
		self.client.post(reverse("lplpo:lplpo_create"), {"bulan": "2", "tahun": "2026"})

		current = LPLPO.objects.get(facility=self.facility, bulan=2, tahun=2026)
		self.assertEqual(
			current.items.get(item=self.item_a).stock_awal,
			Decimal("10.00"),
		)
		self.assertEqual(
			current.items.get(item=self.item_b).stock_awal,
			Decimal("5.00"),
		)

	def test_stock_awal_from_previous_submitted_lplpo(self):
		previous = self.create_lplpo(bulan=1, tahun=2026, status=LPLPO.Status.SUBMITTED)
		LPLPOItem.objects.create(
			lplpo=previous,
			item=self.item_a,
			stock_awal=Decimal("6.00"),
			penerimaan=Decimal("4.00"),
			pemakaian=Decimal("3.00"),
		)

		self.client.force_login(self.puskesmas_user)
		self.client.post(reverse("lplpo:lplpo_create"), {"bulan": "2", "tahun": "2026"})

		current = LPLPO.objects.get(facility=self.facility, bulan=2, tahun=2026)
		self.assertEqual(
			current.items.get(item=self.item_a).stock_awal,
			Decimal("7.00"),
		)

	def test_january_create_skips_stock_awal_carry_from_previous_december(self):
		"""January creation must NOT carry stock_awal from the previous December."""
		active_year = get_active_lplpo_year()
		previous_year = active_year - 1
		december = self.create_lplpo(bulan=12, tahun=previous_year, status=LPLPO.Status.CLOSED)
		LPLPOItem.objects.create(
			lplpo=december,
			item=self.item_a,
			stock_awal=Decimal("10.00"),
			penerimaan=Decimal("5.00"),
			pemakaian=Decimal("3.00"),
		)

		self.client.force_login(self.puskesmas_user)
		response = self.client.post(
			reverse("lplpo:lplpo_create"),
			{"bulan": "1", "tahun": str(active_year)},
		)

		self.assertEqual(response.status_code, 302)
		january = LPLPO.objects.get(facility=self.facility, bulan=1, tahun=active_year)
		self.assertEqual(
			january.items.get(item=self.item_a).stock_awal,
			0,
			"January stock_awal must be 0 (manual entry), not carried from December.",
		)

	def test_edit_renders_previous_stock_awal_without_decimal_places(self):
		previous = self.create_lplpo(bulan=1, tahun=2026, status=LPLPO.Status.CLOSED)
		LPLPOItem.objects.create(
			lplpo=previous,
			item=self.item_a,
			stock_awal=Decimal("5.00"),
			penerimaan=Decimal("5.00"),
			pemakaian=Decimal("0.00"),
		)

		current = self.create_lplpo(bulan=2, tahun=2026)
		LPLPOItem.objects.create(
			lplpo=current,
			item=self.item_a,
			stock_awal=Decimal("10.00"),
			penerimaan=Decimal("0.00"),
			pemakaian=Decimal("0.00"),
		)

		self.client.force_login(self.puskesmas_user)
		response = self.client.get(reverse("lplpo:lplpo_edit", args=[current.pk]), follow=True)

		self.assertEqual(response.status_code, 200)
		html = response.content.decode()
		self.assertIn('type="number" value="10"', html)
		self.assertNotIn('type="number" value="10.00"', html)

	def test_january_bootstrap_edit_keeps_stock_awal_manual_even_with_previous_december(self):
		active_year = get_active_lplpo_year()
		previous_year = active_year - 1
		previous_december = self.create_lplpo(bulan=12, tahun=previous_year, status=LPLPO.Status.CLOSED)
		LPLPOItem.objects.create(
			lplpo=previous_december,
			item=self.item_a,
			stock_awal=Decimal("7.00"),
			penerimaan=Decimal("1.00"),
			pemakaian=Decimal("2.00"),
		)

		january = self.create_lplpo(bulan=1, tahun=active_year)
		line = LPLPOItem.objects.create(
			lplpo=january,
			item=self.item_a,
			stock_awal=Decimal("9.00"),
			penerimaan=Decimal("0.00"),
			pemakaian=Decimal("0.00"),
		)

		self.client.force_login(self.puskesmas_user)
		response = self.client.get(reverse("lplpo:lplpo_edit", args=[january.pk]))

		self.assertEqual(response.status_code, 200)
		self.assertTrue(is_january_bootstrap_period(january.bulan, january.tahun))
		self.assertContains(response, "Dokumen Bootstrap Januari")
		self.assertContains(response, "baseline stok awal tahunan")
		self.assertContains(response, "Penerimaan")
		self.assertContains(response, "diisi manual")
		self.assertContains(response, f'name="item_{line.pk}-stock_awal"')
		self.assertNotContains(
			response,
			f'<input type="hidden" name="item_{line.pk}-stock_awal"',
			html=False,
		)

	def test_computed_fields_correct(self):
		lplpo = self.create_lplpo()
		line = LPLPOItem.objects.create(
			lplpo=lplpo,
			item=self.item_a,
			stock_awal=Decimal("10.00"),
			penerimaan=Decimal("5.00"),
			pembelian_puskesmas=Decimal("2.00"),
			pemakaian=Decimal("8.00"),
			waktu_kosong=Decimal("2.00"),
		)

		self.assertEqual(line.persediaan, Decimal("17.00"))
		self.assertEqual(line.stock_keseluruhan, Decimal("9.00"))
		self.assertEqual(line.stock_optimum, Decimal("9.60"))
		self.assertEqual(line.jumlah_kebutuhan, Decimal("2.60"))

	def test_computed_fields_use_consumption_for_stock_optimum(self):
		lplpo = self.create_lplpo()
		line = LPLPOItem.objects.create(
			lplpo=lplpo,
			item=self.item_a,
			stock_awal=Decimal("10.00"),
			penerimaan=Decimal("0.00"),
			pembelian_puskesmas=Decimal("0.00"),
			pemakaian=Decimal("10.00"),
			waktu_kosong=Decimal("0.00"),
		)

		self.assertEqual(line.persediaan, Decimal("10.00"))
		self.assertEqual(line.stock_keseluruhan, Decimal("0.00"))
		self.assertEqual(line.stock_optimum, Decimal("12.00"))
		self.assertEqual(line.jumlah_kebutuhan, Decimal("12.00"))

	def test_review_form_prefills_pemberian_suggestion_when_stock_is_fully_used(self):
		lplpo = self.create_lplpo()
		line = LPLPOItem.objects.create(
			lplpo=lplpo,
			item=self.item_a,
			stock_awal=Decimal("1.00"),
			penerimaan=Decimal("0.00"),
			pemakaian=Decimal("0.00"),
		)

		line.stock_awal = Decimal("10.00")
		line.pemakaian = Decimal("10.00")
		line.compute_fields()
		line.save()
		lplpo.status = LPLPO.Status.PIC_VERIFIED
		lplpo.submitted_at = timezone.now()
		lplpo.save(update_fields=["status", "submitted_at", "updated_at"])

		self.client.force_login(self.staff_user)
		response = self.client.get(reverse("lplpo:lplpo_review", args=[lplpo.pk]))

		self.assertEqual(response.status_code, 200)
		line.refresh_from_db()
		self.assertEqual(line.stock_keseluruhan, Decimal("0.00"))
		self.assertEqual(line.stock_optimum, Decimal("12.00"))
		self.assertEqual(line.jumlah_kebutuhan, Decimal("12.00"))
		self.assertIsNone(line.pemberian_jumlah)
		review_form = response.context["grouped"][self.category.name][0]["form"]
		self.assertEqual(review_form["pemberian_jumlah"].value(), 12)

	def test_review_rejects_decimal_pemberian_input(self):
		lplpo = self.create_lplpo(status=LPLPO.Status.PIC_VERIFIED, created_by=self.puskesmas_user)
		line = LPLPOItem.objects.create(
			lplpo=lplpo,
			item=self.item_a,
			permintaan_jumlah=Decimal("12.00"),
		)

		self.client.force_login(self.staff_user)
		response = self.client.post(
			reverse("lplpo:lplpo_review", args=[lplpo.pk]),
			{
				f"review_{line.pk}-pemberian_jumlah": "10.5",
				f"review_{line.pk}-pemberian_alasan": "Uji validasi",
			},
		)

		self.assertEqual(response.status_code, 200)
		review_form = response.context["grouped"][self.category.name][0]["form"]
		self.assertIn("pemberian_jumlah", review_form.errors)
		line.refresh_from_db()
		self.assertIsNone(line.pemberian_jumlah)

	def test_review_creates_distribution_immediately(self):
		lplpo = self.create_lplpo(status=LPLPO.Status.PIC_VERIFIED, created_by=self.puskesmas_user)
		line = LPLPOItem.objects.create(
			lplpo=lplpo,
			item=self.item_a,
			permintaan_jumlah=Decimal("12.00"),
		)

		self.client.force_login(self.gudang_user)
		response = self.client.post(
			reverse("lplpo:lplpo_review", args=[lplpo.pk]),
			{
				f"review_{line.pk}-pemberian_jumlah": "9",
				f"review_{line.pk}-pemberian_alasan": "Disesuaikan dengan stok gudang.",
			},
		)

		lplpo.refresh_from_db()
		distribution = lplpo.distribution

		self.assertEqual(response.status_code, 302)
		self.assertRedirects(
			response,
			reverse("distribution:distribution_detail", args=[distribution.pk]),
		)
		self.assertEqual(lplpo.status, LPLPO.Status.APPROVED)
		self.assertEqual(lplpo.reviewed_by, self.gudang_user)
		self.assertEqual(lplpo.approved_by, self.gudang_user)
		self.assertEqual(distribution.status, Distribution.Status.DRAFT)
		self.assertTrue(distribution.staff_assignments.filter(user=self.gudang_user).exists())
		self.assertEqual(distribution.items.count(), 1)
		dist_line = distribution.items.get()
		self.assertEqual(dist_line.item, self.item_a)
		self.assertEqual(dist_line.quantity_requested, Decimal("12.00"))
		self.assertEqual(dist_line.quantity_approved, Decimal("9.00"))

	def test_review_integrity_error_shows_generic_message(self):
		lplpo = self.create_lplpo(status=LPLPO.Status.PIC_VERIFIED, created_by=self.puskesmas_user)
		line = LPLPOItem.objects.create(
			lplpo=lplpo,
			item=self.item_a,
			permintaan_jumlah=Decimal("12.00"),
		)

		self.client.force_login(self.gudang_user)
		with patch(
			"apps.lplpo.views._create_lplpo_distribution",
			side_effect=IntegrityError("duplicate key value violates constraint lplpo_unique"),
		), patch("apps.lplpo.views.logger.exception") as mock_logger:
			response = self.client.post(
				reverse("lplpo:lplpo_review", args=[lplpo.pk]),
				{
					f"review_{line.pk}-pemberian_jumlah": "9",
					f"review_{line.pk}-pemberian_alasan": "Disesuaikan dengan stok gudang.",
				},
				follow=True,
			)

		self.assertRedirects(response, reverse("lplpo:lplpo_detail", args=[lplpo.pk]))
		self.assertEqual(
			[str(message) for message in get_messages(response.wsgi_request)],
			["Terjadi kesalahan saat memproses LPLPO. Silakan coba lagi."],
		)
		mock_logger.assert_called_once_with("LPLPO distribution creation failed")
		lplpo.refresh_from_db()
		self.assertIsNone(lplpo.distribution)
		self.assertEqual(lplpo.status, LPLPO.Status.PIC_VERIFIED)
		self.assertIsNone(lplpo.reviewed_by)
		self.assertIsNone(lplpo.reviewed_at)

	def test_edit_persists_form_and_computed_fields_with_bulk_update(self):
		lplpo = self.create_lplpo()
		line = LPLPOItem.objects.create(
			lplpo=lplpo,
			item=self.item_a,
			stock_awal=Decimal("2.00"),
			penerimaan=Decimal("3.00"),
			pemakaian=Decimal("1.00"),
		)

		self.client.force_login(self.puskesmas_user)
		response = self.client.post(
			reverse("lplpo:lplpo_edit", args=[lplpo.pk]),
			{
				f"item_{line.pk}-stock_awal": "10",
				f"item_{line.pk}-penerimaan": "5",
				f"item_{line.pk}-pembelian_puskesmas": "2",
				f"item_{line.pk}-pemakaian": "8",
				f"item_{line.pk}-stock_gudang_puskesmas": "4",
				f"item_{line.pk}-waktu_kosong": "2",
				f"item_{line.pk}-permintaan_jumlah": "6",
				f"item_{line.pk}-permintaan_alasan": "Buffer stok menipis",
			},
		)

		self.assertEqual(response.status_code, 302)
		line.refresh_from_db()
		self.assertEqual(line.stock_awal, Decimal("10.00"))
		self.assertEqual(line.penerimaan, Decimal("5.00"))
		self.assertEqual(line.pembelian_puskesmas, Decimal("2.00"))
		self.assertEqual(line.pemakaian, Decimal("8.00"))
		self.assertEqual(line.stock_gudang_puskesmas, Decimal("4.00"))
		self.assertEqual(line.waktu_kosong, Decimal("2.00"))
		self.assertEqual(line.permintaan_jumlah, Decimal("6.00"))
		self.assertEqual(line.permintaan_alasan, "Buffer stok menipis")
		self.assertEqual(line.persediaan, Decimal("17.00"))
		self.assertEqual(line.stock_keseluruhan, Decimal("9.00"))
		self.assertEqual(line.stock_optimum, Decimal("9.60"))
		self.assertEqual(line.jumlah_kebutuhan, Decimal("2.60"))
		self.assertIsNone(line.pemberian_jumlah)

	def test_edit_blank_stock_awal_is_treated_as_zero(self):
		lplpo = self.create_lplpo()
		line = LPLPOItem.objects.create(
			lplpo=lplpo,
			item=self.item_a,
			stock_awal=Decimal("2.00"),
			penerimaan=Decimal("3.00"),
			pemakaian=Decimal("1.00"),
		)

		self.client.force_login(self.puskesmas_user)
		response = self.client.post(
			reverse("lplpo:lplpo_edit", args=[lplpo.pk]),
			{
				f"item_{line.pk}-stock_awal": "",
				f"item_{line.pk}-penerimaan": "5",
				f"item_{line.pk}-pembelian_puskesmas": "2",
				f"item_{line.pk}-pemakaian": "8",
				f"item_{line.pk}-stock_gudang_puskesmas": "4",
				f"item_{line.pk}-waktu_kosong": "2",
				f"item_{line.pk}-permintaan_jumlah": "6",
				f"item_{line.pk}-permintaan_alasan": "Buffer stok menipis",
			},
		)

		self.assertEqual(response.status_code, 302)
		line.refresh_from_db()
		self.assertEqual(line.stock_awal, Decimal("0.00"))
		self.assertEqual(line.persediaan, Decimal("7.00"))
		self.assertEqual(line.stock_keseluruhan, Decimal("-1.00"))

	def test_edit_invalid_row_shows_error_message_and_stays_on_edit(self):
		lplpo = self.create_lplpo()
		line = LPLPOItem.objects.create(
			lplpo=lplpo,
			item=self.item_a,
			stock_awal=Decimal("2.00"),
			penerimaan=Decimal("3.00"),
			pemakaian=Decimal("1.00"),
		)

		self.client.force_login(self.puskesmas_user)
		response = self.client.post(
			reverse("lplpo:lplpo_edit", args=[lplpo.pk]),
			{
				f"item_{line.pk}-stock_awal": "2",
				f"item_{line.pk}-penerimaan": "5",
				f"item_{line.pk}-pembelian_puskesmas": "2",
				f"item_{line.pk}-pemakaian": "",
				f"item_{line.pk}-stock_gudang_puskesmas": "4",
				f"item_{line.pk}-waktu_kosong": "2",
				f"item_{line.pk}-permintaan_jumlah": "6",
				f"item_{line.pk}-permintaan_alasan": "Buffer stok menipis",
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertTemplateUsed(response, "lplpo/lplpo_edit.html")
		self.assertContains(response, "Data belum tersimpan")
		self.assertContains(response, "Pemakaian")
		line.refresh_from_db()
		self.assertEqual(line.stock_awal, Decimal("2.00"))

	def test_non_puskesmas_cannot_edit_draft_lplpo(self):
		lplpo = self.create_lplpo()

		self.client.force_login(self.gudang_user)
		response = self.client.get(reverse("lplpo:lplpo_edit", args=[lplpo.pk]))

		self.assertEqual(response.status_code, 403)
		self.assertContains(
			response,
			"Hanya operator Puskesmas yang dapat mengubah LPLPO draft.",
			status_code=403,
		)

	def test_non_puskesmas_cannot_submit_draft_lplpo(self):
		lplpo = self.create_lplpo()

		self.client.force_login(self.gudang_user)
		response = self.client.post(reverse("lplpo:lplpo_submit", args=[lplpo.pk]))

		self.assertEqual(response.status_code, 403)
		self.assertContains(
			response,
			"Hanya operator Puskesmas yang dapat mengubah LPLPO draft.",
			status_code=403,
		)
		lplpo.refresh_from_db()
		self.assertEqual(lplpo.status, LPLPO.Status.DRAFT)

	def test_non_puskesmas_detail_hides_draft_mutation_actions(self):
		lplpo = self.create_lplpo()

		self.client.force_login(self.gudang_user)
		response = self.client.get(reverse("lplpo:lplpo_detail", args=[lplpo.pk]))

		self.assertEqual(response.status_code, 200)
		self.assertNotContains(response, 'id="edit-btn"')
		self.assertNotContains(response, 'id="submit-btn"')
		self.assertNotContains(response, 'id="delete-btn"')

	def test_super_admin_detail_shows_draft_mutation_actions(self):
		lplpo = self.create_lplpo()

		self.client.force_login(self.superuser)
		response = self.client.get(reverse("lplpo:lplpo_detail", args=[lplpo.pk]))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'id="edit-btn"')
		self.assertContains(response, 'id="submit-btn"')
		self.assertContains(response, 'id="delete-btn"')

	def test_non_puskesmas_cannot_delete_draft_lplpo(self):
		lplpo = self.create_lplpo()

		self.client.force_login(self.gudang_user)
		response = self.client.post(reverse("lplpo:lplpo_delete", args=[lplpo.pk]))

		self.assertEqual(response.status_code, 403)
		self.assertContains(
			response,
			"Hanya operator Puskesmas yang dapat mengubah LPLPO draft.",
			status_code=403,
		)
		self.assertTrue(LPLPO.objects.filter(pk=lplpo.pk).exists())

	def test_super_admin_can_create_lplpo_for_any_puskesmas(self):
		self.client.force_login(self.superuser)

		response = self.client.post(
			reverse("lplpo:lplpo_create"),
			{
				"bulan": "1",
				"tahun": "2026",
				"facility": str(self.other_facility.pk),
				"notes": " Dibuat admin pusat ",
			},
		)

		self.assertEqual(response.status_code, 302)
		lplpo = LPLPO.objects.get(facility=self.other_facility, bulan=1, tahun=2026)
		self.assertEqual(lplpo.created_by, self.superuser)
		self.assertEqual(lplpo.notes, "Dibuat admin pusat")

	def test_super_admin_can_edit_submit_and_delete_draft_lplpo(self):
		lplpo = self.create_lplpo(
			facility=self.other_facility,
			created_by=self.other_puskesmas_user,
		)
		line = LPLPOItem.objects.create(
			lplpo=lplpo,
			item=self.item_a,
			stock_awal=Decimal("1.00"),
			penerimaan=Decimal("2.00"),
			pemakaian=Decimal("1.00"),
		)

		self.client.force_login(self.superuser)
		edit_response = self.client.post(
			reverse("lplpo:lplpo_edit", args=[lplpo.pk]),
			{
				f"item_{line.pk}-stock_awal": "5",
				f"item_{line.pk}-penerimaan": "3",
				f"item_{line.pk}-pembelian_puskesmas": "1",
				f"item_{line.pk}-pemakaian": "2",
				f"item_{line.pk}-stock_gudang_puskesmas": "1",
				f"item_{line.pk}-waktu_kosong": "0",
				f"item_{line.pk}-permintaan_jumlah": "4",
				f"item_{line.pk}-permintaan_alasan": " Buffer ",
			},
		)
		self.assertEqual(edit_response.status_code, 302)

		line.refresh_from_db()
		self.assertEqual(line.stock_awal, Decimal("5.00"))
		self.assertEqual(line.permintaan_alasan, "Buffer")

		submit_response = self.client.post(reverse("lplpo:lplpo_submit", args=[lplpo.pk]))
		self.assertEqual(submit_response.status_code, 302)
		lplpo.refresh_from_db()
		self.assertEqual(lplpo.status, LPLPO.Status.SUBMITTED)
		self.assertIsNotNone(lplpo.submitted_at)

		draft_for_delete = self.create_lplpo(
			facility=self.other_facility,
			created_by=self.other_puskesmas_user,
			bulan=3,
			tahun=2026,
		)
		delete_pk = draft_for_delete.pk
		delete_response = self.client.post(
			reverse("lplpo:lplpo_delete", args=[delete_pk])
		)
		self.assertEqual(delete_response.status_code, 302)
		self.assertFalse(LPLPO.objects.filter(pk=delete_pk).exists())

	def test_unique_constraint_facility_period(self):
		self.create_lplpo(bulan=2, tahun=2026)

		with self.assertRaises(IntegrityError):
			self.create_lplpo(bulan=2, tahun=2026)

	def test_puskesmas_cannot_see_other_facility_lplpo(self):
		lplpo = self.create_lplpo(
			facility=self.other_facility,
			created_by=self.other_puskesmas_user,
		)

		self.client.force_login(self.puskesmas_user)
		response = self.client.get(reverse("lplpo:lplpo_detail", args=[lplpo.pk]))

		self.assertEqual(response.status_code, 302)
		self.assertRedirects(response, reverse("lplpo:lplpo_my_list"))

	def test_puskesmas_cannot_access_review(self):
		lplpo = self.create_lplpo(status=LPLPO.Status.PIC_VERIFIED)

		self.client.force_login(self.puskesmas_user)
		response = self.client.get(reverse("lplpo:lplpo_review", args=[lplpo.pk]))

		self.assertEqual(response.status_code, 302)
		self.assertRedirects(response, reverse("lplpo:lplpo_my_list"))

	def test_puskesmas_cannot_access_verify(self):
		lplpo = self.create_lplpo(status=LPLPO.Status.SUBMITTED)

		self.client.force_login(self.puskesmas_user)
		response = self.client.post(reverse("lplpo:lplpo_verify", args=[lplpo.pk]))

		self.assertEqual(response.status_code, 302)
		self.assertRedirects(response, reverse("lplpo:lplpo_my_list"))

	def test_puskesmas_cannot_access_finalize(self):
		lplpo = self.create_lplpo(status=LPLPO.Status.REVIEWED)

		self.client.force_login(self.puskesmas_user)
		response = self.client.post(reverse("lplpo:lplpo_finalize", args=[lplpo.pk]))

		self.assertEqual(response.status_code, 403)

	def test_puskesmas_list_uses_operator_friendly_status_labels(self):
		lplpo = self.create_lplpo(status=LPLPO.Status.DISTRIBUTED)

		self.client.force_login(self.puskesmas_user)
		response = self.client.get(reverse("lplpo:lplpo_my_list"))

		self.assertContains(response, "Dokumen Distribusi Dibuat")
		self.assertNotContains(
			response,
			'<span class="badge text-bg-primary">Didistribusikan</span>',
			html=True,
		)

	def test_puskesmas_detail_uses_operator_friendly_status_labels(self):
		lplpo = self.create_lplpo(status=LPLPO.Status.APPROVED)

		self.client.force_login(self.puskesmas_user)
		response = self.client.get(reverse("lplpo:lplpo_detail", args=[lplpo.pk]))

		self.assertContains(response, "Siap Distribusi")
		self.assertNotContains(response, "<strong>Disetujui Kepala</strong>", html=True)

	def test_operate_scope_user_can_verify_submitted_lplpo(self):
		lplpo = self.create_lplpo(status=LPLPO.Status.SUBMITTED)

		self.client.force_login(self.gudang_user)
		response = self.client.post(reverse("lplpo:lplpo_verify", args=[lplpo.pk]))

		self.assertEqual(response.status_code, 302)
		lplpo.refresh_from_db()
		self.assertEqual(lplpo.status, LPLPO.Status.PIC_VERIFIED)
		self.assertEqual(lplpo.verified_by, self.gudang_user)
		self.assertIsNotNone(lplpo.verified_at)

	def test_approve_scope_user_can_reject_submitted_lplpo(self):
		lplpo = self.create_lplpo(status=LPLPO.Status.SUBMITTED)

		self.client.force_login(self.staff_user)
		response = self.client.post(
			reverse("lplpo:lplpo_reject", args=[lplpo.pk]),
			{"rejection_reason": "Data pemakaian belum lengkap."},
		)

		self.assertEqual(response.status_code, 302)
		lplpo.refresh_from_db()
		self.assertEqual(lplpo.status, LPLPO.Status.REJECTED_PUSKESMAS)
		self.assertEqual(lplpo.rejection_reason, "Data pemakaian belum lengkap.")

	def test_kepala_can_reject_reviewed_lplpo_back_to_pic(self):
		lplpo = self.create_lplpo(status=LPLPO.Status.REVIEWED, reviewed_by=self.gudang_user)

		self.client.force_login(self.staff_user)
		response = self.client.post(
			reverse("lplpo:lplpo_reject", args=[lplpo.pk]),
			{"rejection_reason": "Sesuaikan jumlah pemberian dengan stok tersedia."},
		)

		self.assertEqual(response.status_code, 302)
		lplpo.refresh_from_db()
		self.assertEqual(lplpo.status, LPLPO.Status.REJECTED_PIC)
		self.assertEqual(
			lplpo.rejection_reason,
			"Sesuaikan jumlah pemberian dengan stok tersedia.",
		)

	def test_reject_requires_reason(self):
		lplpo = self.create_lplpo(status=LPLPO.Status.SUBMITTED)

		self.client.force_login(self.staff_user)
		response = self.client.post(reverse("lplpo:lplpo_reject", args=[lplpo.pk]), {})

		self.assertEqual(response.status_code, 302)
		lplpo.refresh_from_db()
		self.assertEqual(lplpo.status, LPLPO.Status.SUBMITTED)
		self.assertEqual(lplpo.rejection_reason, "")

	def test_rejection_reason_is_shown_on_detail(self):
		lplpo = self.create_lplpo(
			status=LPLPO.Status.REJECTED_PUSKESMAS,
			rejection_reason="Mohon perbaiki angka penerimaan dan alasan permintaan.",
		)

		self.client.force_login(self.puskesmas_user)
		response = self.client.get(reverse("lplpo:lplpo_detail", args=[lplpo.pk]))

		self.assertContains(response, "Alasan Penolakan")
		self.assertContains(
			response,
			"Mohon perbaiki angka penerimaan dan alasan permintaan.",
		)

	def test_operator_can_edit_and_resubmit_rejected_lplpo(self):
		lplpo = self.create_lplpo(status=LPLPO.Status.REJECTED_PUSKESMAS)
		line = LPLPOItem.objects.create(
			lplpo=lplpo,
			item=self.item_a,
			stock_awal=Decimal("1.00"),
			penerimaan=Decimal("2.00"),
		)

		self.client.force_login(self.puskesmas_user)
		response = self.client.get(reverse("lplpo:lplpo_detail", args=[lplpo.pk]))

		self.assertContains(response, 'id="edit-rejected-btn"')
		self.assertContains(response, 'id="resubmit-btn"')

		response = self.client.post(
			reverse("lplpo:lplpo_edit", args=[lplpo.pk]),
			{
				f"item_{line.pk}-stock_awal": "2",
				f"item_{line.pk}-penerimaan": "3",
				f"item_{line.pk}-pembelian_puskesmas": "1",
				f"item_{line.pk}-pemakaian": "1",
				f"item_{line.pk}-stock_gudang_puskesmas": "1",
				f"item_{line.pk}-waktu_kosong": "0",
				f"item_{line.pk}-permintaan_jumlah": "2",
				f"item_{line.pk}-permintaan_alasan": "Perbaikan setelah ditolak",
			},
		)
		self.assertEqual(response.status_code, 302)
		line.refresh_from_db()
		self.assertEqual(line.stock_awal, Decimal("2.00"))
		self.assertEqual(line.penerimaan, Decimal("3.00"))
		self.assertEqual(line.pembelian_puskesmas, Decimal("1.00"))

		response = self.client.post(reverse("lplpo:lplpo_submit", args=[lplpo.pk]))
		self.assertEqual(response.status_code, 302)
		lplpo.refresh_from_db()
		self.assertEqual(lplpo.status, LPLPO.Status.SUBMITTED)
		self.assertEqual(lplpo.rejection_reason, "")

	def test_operate_scope_user_sees_verify_and_reject_buttons(self):
		lplpo = self.create_lplpo(status=LPLPO.Status.SUBMITTED)

		self.client.force_login(self.gudang_user)
		response = self.client.get(reverse("lplpo:lplpo_detail", args=[lplpo.pk]))

		self.assertContains(response, 'id="verify-btn"')
		self.assertContains(response, 'id="reject-btn"')

	def test_operate_scope_user_can_review_pic_verified_lplpo(self):
		lplpo = self.create_lplpo(status=LPLPO.Status.PIC_VERIFIED)

		self.client.force_login(self.gudang_user)
		response = self.client.get(reverse("lplpo:lplpo_detail", args=[lplpo.pk]))

		self.assertContains(response, 'id="review-btn"')
		self.assertNotContains(response, 'id="finalize-btn"')

	def test_puskesmas_detail_hides_distribution_navigation(self):
		distribution = Distribution.objects.create(
			distribution_type=Distribution.DistributionType.LPLPO,
			facility=self.facility,
			request_date=date(2026, 2, 1),
			status=Distribution.Status.DRAFT,
			created_by=self.staff_user,
		)
		lplpo = self.create_lplpo(
			status=LPLPO.Status.APPROVED,
			distribution=distribution,
		)

		self.client.force_login(self.puskesmas_user)
		response = self.client.get(reverse("lplpo:lplpo_detail", args=[lplpo.pk]))

		self.assertContains(response, "Dokumen Distribusi Dibuat / Menunggu Distribusi")
		self.assertContains(response, distribution.document_number)
		self.assertNotContains(response, 'id="view-dist-btn"')
		self.assertNotContains(
			response,
			reverse("distribution:distribution_detail", args=[distribution.pk]),
		)

	def test_reviewed_detail_with_distribution_shows_distribution_navigation(self):
		distribution = Distribution.objects.create(
			distribution_type=Distribution.DistributionType.LPLPO,
			facility=self.facility,
			request_date=date(2026, 2, 1),
			status=Distribution.Status.DRAFT,
			created_by=self.staff_user,
		)
		lplpo = self.create_lplpo(
			status=LPLPO.Status.APPROVED,
			distribution=distribution,
		)

		self.client.force_login(self.staff_user)
		response = self.client.get(reverse("lplpo:lplpo_detail", args=[lplpo.pk]))

		self.assertNotContains(response, 'id="finalize-btn"')
		self.assertContains(response, 'id="view-dist-btn"')
		self.assertContains(
			response,
			reverse("distribution:distribution_detail", args=[distribution.pk]),
		)

	def test_finalize_creates_distribution(self):
		lplpo = self.create_lplpo(status=LPLPO.Status.REVIEWED, created_by=self.staff_user)
		LPLPOItem.objects.create(
			lplpo=lplpo,
			item=self.item_a,
			permintaan_jumlah=Decimal("12.00"),
			pemberian_jumlah=Decimal("9.00"),
		)
		LPLPOItem.objects.create(
			lplpo=lplpo,
			item=self.item_b,
			permintaan_jumlah=Decimal("8.00"),
			pemberian_jumlah=Decimal("0.00"),
		)

		self.client.force_login(self.superuser)
		response = self.client.post(reverse("lplpo:lplpo_finalize", args=[lplpo.pk]))

		lplpo.refresh_from_db()
		distribution = lplpo.distribution

		self.assertEqual(response.status_code, 302)
		self.assertRedirects(
			response,
			reverse("distribution:distribution_detail", args=[distribution.pk]),
		)
		self.assertEqual(lplpo.status, LPLPO.Status.APPROVED)
		self.assertEqual(lplpo.approved_by, self.superuser)
		self.assertEqual(distribution.distribution_type, Distribution.DistributionType.LPLPO)
		self.assertEqual(distribution.status, Distribution.Status.DRAFT)
		self.assertEqual(distribution.items.count(), 1)
		self.assertTrue(distribution.staff_assignments.filter(user=self.superuser).exists())

		line = distribution.items.get()
		self.assertEqual(line.item, self.item_a)
		self.assertEqual(line.quantity_requested, Decimal("12.00"))
		self.assertEqual(line.quantity_approved, Decimal("9.00"))

	def test_finalize_integrity_error_shows_generic_message(self):
		lplpo = self.create_lplpo(status=LPLPO.Status.REVIEWED, created_by=self.staff_user)
		LPLPOItem.objects.create(
			lplpo=lplpo,
			item=self.item_a,
			permintaan_jumlah=Decimal("12.00"),
			pemberian_jumlah=Decimal("9.00"),
		)

		self.client.force_login(self.superuser)
		with patch(
			"apps.lplpo.views._create_lplpo_distribution",
			side_effect=IntegrityError("duplicate key value violates constraint lplpo_unique"),
		), patch("apps.lplpo.views.logger.exception") as mock_logger:
			response = self.client.post(
				reverse("lplpo:lplpo_finalize", args=[lplpo.pk]),
				follow=True,
			)

		self.assertRedirects(response, reverse("lplpo:lplpo_detail", args=[lplpo.pk]))
		self.assertEqual(
			[str(message) for message in get_messages(response.wsgi_request)],
			["Terjadi kesalahan saat memproses LPLPO. Silakan coba lagi."],
		)
		mock_logger.assert_called_once_with("LPLPO distribution creation failed")
		lplpo.refresh_from_db()
		self.assertIsNone(lplpo.distribution)
		self.assertEqual(lplpo.status, LPLPO.Status.REVIEWED)
		self.assertIsNone(lplpo.approved_by)
		self.assertIsNone(lplpo.approved_at)

	def test_finalize_reuses_existing_distribution(self):
		distribution = Distribution.objects.create(
			distribution_type=Distribution.DistributionType.LPLPO,
			facility=self.facility,
			request_date=date(2026, 2, 1),
			status=Distribution.Status.DRAFT,
			created_by=self.staff_user,
		)
		lplpo = self.create_lplpo(
			status=LPLPO.Status.REVIEWED,
			distribution=distribution,
			created_by=self.staff_user,
		)

		self.client.force_login(self.superuser)
		response = self.client.post(reverse("lplpo:lplpo_finalize", args=[lplpo.pk]))

		self.assertRedirects(
			response,
			reverse("distribution:distribution_detail", args=[distribution.pk]),
		)
		self.assertEqual(
			Distribution.objects.filter(distribution_type=Distribution.DistributionType.LPLPO).count(),
			1,
		)

	def test_finalize_rechecks_reviewed_status_after_row_lock(self):
		lplpo = self.create_lplpo(status=LPLPO.Status.REVIEWED, created_by=self.staff_user)
		LPLPOItem.objects.create(
			lplpo=lplpo,
			item=self.item_a,
			permintaan_jumlah=Decimal("12.00"),
			pemberian_jumlah=Decimal("9.00"),
		)

		locked_lplpo = LPLPO.objects.get(pk=lplpo.pk)
		locked_lplpo.status = LPLPO.Status.SUBMITTED

		self.client.force_login(self.superuser)
		with patch(
			"apps.lplpo.views.LPLPO.objects.select_for_update",
			return_value=Mock(get=Mock(return_value=locked_lplpo)),
		):
			response = self.client.post(reverse("lplpo:lplpo_finalize", args=[lplpo.pk]))

		self.assertEqual(response.status_code, 302)
		self.assertRedirects(response, reverse("lplpo:lplpo_detail", args=[lplpo.pk]))
		lplpo.refresh_from_db()
		self.assertEqual(lplpo.status, LPLPO.Status.REVIEWED)
		self.assertIsNone(lplpo.distribution)
		self.assertEqual(
			Distribution.objects.filter(distribution_type=Distribution.DistributionType.LPLPO).count(),
			0,
		)

	def test_migration_marks_reviewed_lplpo_with_distribution_as_approved(self):
		distribution = Distribution.objects.create(
			distribution_type=Distribution.DistributionType.LPLPO,
			facility=self.facility,
			request_date=date(2026, 2, 1),
			status=Distribution.Status.DRAFT,
			created_by=self.superuser,
		)
		lplpo = self.create_lplpo(
			status=LPLPO.Status.REVIEWED,
			distribution=distribution,
			created_by=self.staff_user,
		)
		lplpo.approved_by = None
		lplpo.approved_at = None
		lplpo.save(update_fields=["approved_by", "approved_at", "updated_at"])

		migration = importlib.import_module(
			"apps.lplpo.migrations.0008_lplpo_approved_at_lplpo_approved_by_and_more"
		)
		migration.migrate_legacy_statuses(django_apps, None)

		lplpo.refresh_from_db()
		self.assertEqual(lplpo.status, LPLPO.Status.APPROVED)
		self.assertEqual(lplpo.approved_by, distribution.created_by)
		self.assertEqual(lplpo.approved_at, distribution.created_at)

	def test_print_report_uses_current_filters(self):
		matching = self.create_lplpo(status=LPLPO.Status.SUBMITTED, bulan=4, tahun=2026)
		self.set_submitted_at(matching, 2026, 4, 18)

		non_matching = self.create_lplpo(status=LPLPO.Status.SUBMITTED, bulan=5, tahun=2026)
		self.set_submitted_at(non_matching, 2026, 5, 2)

		self.client.force_login(self.staff_user)
		response = self.client.get(
			reverse("lplpo:lplpo_print_report"),
			{"submitted_month": "4", "submitted_year": "2026"},
		)

		self.assertEqual(response.status_code, 200)
		self.assertTemplateUsed(response, "lplpo/lplpo_report_print.html")
		self.assertContains(response, matching.document_number)
		self.assertNotContains(response, non_matching.document_number)

	def test_super_admin_print_report_still_only_shows_submitted_documents(self):
		draft_lplpo = self.create_lplpo(status=LPLPO.Status.DRAFT)
		submitted_lplpo = self.create_lplpo(
			status=LPLPO.Status.SUBMITTED,
			bulan=3,
			tahun=2026,
		)
		self.set_submitted_at(submitted_lplpo, 2026, 4, 5)

		self.client.force_login(self.superuser)
		response = self.client.get(reverse("lplpo:lplpo_print_report"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, submitted_lplpo.document_number)
		self.assertNotContains(response, draft_lplpo.document_number)

	def test_distribution_distributed_closes_lplpo(self):
		distribution = Distribution.objects.create(
			distribution_type=Distribution.DistributionType.LPLPO,
			facility=self.facility,
			request_date=date(2026, 2, 1),
			status=Distribution.Status.DRAFT,
			created_by=self.staff_user,
		)
		lplpo = self.create_lplpo(
			status=LPLPO.Status.APPROVED,
			distribution=distribution,
			created_by=self.staff_user,
		)

		distribution.status = Distribution.Status.DISTRIBUTED
		distribution.distributed_date = date(2026, 2, 28)
		distribution.save(update_fields=["status", "distributed_date", "updated_at"])

		lplpo.refresh_from_db()
		self.assertEqual(lplpo.status, LPLPO.Status.CLOSED)

	def test_api_prefill_penerimaan_returns_expected_totals(self):
		self.create_distribution(
			facility=self.facility,
			distributed_date=date(2026, 2, 11),
			item_quantities=[(self.item_a, Decimal("4.00"))],
		)
		self.client.force_login(self.puskesmas_user)

		response = self.client.get(
			reverse("lplpo:api_prefill_penerimaan"),
			{"bulan": 2, "tahun": 2026},
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(
			response.json()["items"][str(self.item_a.pk)],
			"4",
		)

	def test_api_prefill_penerimaan_returns_empty_for_january_bootstrap(self):
		self.create_distribution(
			facility=self.facility,
			distributed_date=date(2026, 1, 11),
			item_quantities=[(self.item_a, Decimal("4.00"))],
		)
		self.client.force_login(self.puskesmas_user)

		response = self.client.get(
			reverse("lplpo:api_prefill_penerimaan"),
			{"bulan": 1, "tahun": 2026},
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()["items"], {})

	def test_review_uses_available_stock_not_total_stock(self):
		lplpo = self.create_lplpo(status=LPLPO.Status.PIC_VERIFIED, created_by=self.puskesmas_user)
		LPLPOItem.objects.create(lplpo=lplpo, item=self.item_a, pemberian_jumlah=Decimal("1.00"))
		Stock.objects.create(
			item=self.item_a,
			location=self.location,
			batch_lot="BATCH-1",
			expiry_date=date(2027, 1, 1),
			quantity=Decimal("10.00"),
			reserved=Decimal("3.00"),
			unit_price=Decimal("1000.00"),
			sumber_dana=self.funding_source,
		)

		self.client.force_login(self.staff_user)
		response = self.client.get(reverse("lplpo:lplpo_review", args=[lplpo.pk]))

		self.assertEqual(response.status_code, 200)
		grouped = response.context["grouped"]
		first_group = next(iter(grouped.values()))
		self.assertEqual(first_group[0]["stock_gudang"], Decimal("7.00"))

	def test_computed_fields_persediaan_equals_pemakaian_yields_zero_stock(self):
		"""Edge case: persediaan == pemakaian → stock_keseluruhan = 0 (consumption-based optimum still applies)."""
		lplpo = self.create_lplpo()
		line = LPLPOItem.objects.create(
			lplpo=lplpo,
			item=self.item_a,
			stock_awal=Decimal("4.00"),
			penerimaan=Decimal("2.00"),
			pembelian_puskesmas=Decimal("2.00"),
			pemakaian=Decimal("8.00"),  # persediaan == pemakaian == 8
			waktu_kosong=Decimal("0.00"),
		)

		self.assertEqual(line.persediaan, Decimal("8.00"))
		self.assertEqual(line.stock_keseluruhan, Decimal("0.00"))
		self.assertEqual(line.stock_optimum, Decimal("9.60"))
		self.assertEqual(line.jumlah_kebutuhan, Decimal("9.60"))

	def test_edit_blank_pembelian_puskesmas_is_treated_as_zero(self):
		lplpo = self.create_lplpo()
		line = LPLPOItem.objects.create(
			lplpo=lplpo,
			item=self.item_a,
			stock_awal=Decimal("2.00"),
			penerimaan=Decimal("3.00"),
			pemakaian=Decimal("1.00"),
		)

		self.client.force_login(self.puskesmas_user)
		response = self.client.post(
			reverse("lplpo:lplpo_edit", args=[lplpo.pk]),
			{
				f"item_{line.pk}-stock_awal": "2.00",
				f"item_{line.pk}-penerimaan": "3.00",
				f"item_{line.pk}-pembelian_puskesmas": "",
				f"item_{line.pk}-pemakaian": "1.00",
				f"item_{line.pk}-stock_gudang_puskesmas": "0.00",
				f"item_{line.pk}-waktu_kosong": "0.00",
				f"item_{line.pk}-permintaan_jumlah": "0.00",
				f"item_{line.pk}-permintaan_alasan": "",
			},
		)

		self.assertEqual(response.status_code, 302)
		line.refresh_from_db()
		self.assertEqual(line.pembelian_puskesmas, Decimal("0.00"))
		self.assertEqual(line.persediaan, Decimal("5.00"))

	def test_edit_preserves_existing_pemberian_jumlah(self):
		"""lplpo_edit must not overwrite pemberian_jumlah when it was already set by a reviewer."""
		lplpo = self.create_lplpo(status=LPLPO.Status.REJECTED_PUSKESMAS)
		line = LPLPOItem.objects.create(
			lplpo=lplpo,
			item=self.item_a,
			stock_awal=Decimal("1.00"),
			penerimaan=Decimal("2.00"),
			pemakaian=Decimal("1.00"),
			pemberian_jumlah=Decimal("5.00"),  # set by a prior review pass
		)

		self.client.force_login(self.puskesmas_user)
		response = self.client.post(
			reverse("lplpo:lplpo_edit", args=[lplpo.pk]),
			{
				f"item_{line.pk}-stock_awal": "1.00",
				f"item_{line.pk}-penerimaan": "2.00",
				f"item_{line.pk}-pembelian_puskesmas": "0.00",
				f"item_{line.pk}-pemakaian": "1.00",
				f"item_{line.pk}-stock_gudang_puskesmas": "0.00",
				f"item_{line.pk}-waktu_kosong": "0.00",
				f"item_{line.pk}-permintaan_jumlah": "2.00",
				f"item_{line.pk}-permintaan_alasan": "",
			},
		)

		self.assertEqual(response.status_code, 302)
		line.refresh_from_db()
		self.assertEqual(line.pemberian_jumlah, Decimal("5.00"))

	def test_reject_non_submitted_lplpo_returns_error(self):
		"""Rejecting a DRAFT LPLPO must not change status."""
		lplpo = self.create_lplpo(status=LPLPO.Status.DRAFT)

		self.client.force_login(self.staff_user)
		response = self.client.post(
			reverse("lplpo:lplpo_reject", args=[lplpo.pk]),
			{"rejection_reason": "Data tidak valid."},
		)

		self.assertEqual(response.status_code, 302)
		lplpo.refresh_from_db()
		self.assertEqual(lplpo.status, LPLPO.Status.DRAFT)

	def test_submit_wrong_status_returns_error(self):
		"""Submitting an already-SUBMITTED LPLPO must not change submission timestamp."""
		lplpo = self.create_lplpo(status=LPLPO.Status.SUBMITTED)
		original_submitted_at = lplpo.submitted_at

		self.client.force_login(self.puskesmas_user)
		response = self.client.post(reverse("lplpo:lplpo_submit", args=[lplpo.pk]))

		self.assertEqual(response.status_code, 302)
		lplpo.refresh_from_db()
		self.assertEqual(lplpo.status, LPLPO.Status.SUBMITTED)
		self.assertEqual(lplpo.submitted_at, original_submitted_at)

	def test_delete_rejected_lplpo_allowed(self):
		"""A REJECTED LPLPO can be deleted by its Puskesmas operator."""
		lplpo = self.create_lplpo(status=LPLPO.Status.REJECTED_PUSKESMAS)
		pk = lplpo.pk

		self.client.force_login(self.puskesmas_user)
		response = self.client.post(reverse("lplpo:lplpo_delete", args=[pk]))

		self.assertEqual(response.status_code, 302)
		self.assertFalse(LPLPO.objects.filter(pk=pk).exists())
