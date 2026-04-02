from datetime import date
from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from apps.distribution.models import Distribution, DistributionItem
from apps.items.models import Category, Facility, FundingSource, Item, Location, Unit
from apps.stock.models import Stock
from apps.users.models import ModuleAccess, User
from apps.lplpo.models import LPLPO, LPLPOItem


class LPLPOTestCase(TestCase):
	def setUp(self):
		self.unit = Unit.objects.create(code="TAB", name="Tablet")
		self.category = Category.objects.create(code="OBT", name="Obat", sort_order=1)
		self.funding_source = FundingSource.objects.create(code="DAK", name="DAK")
		self.location = Location.objects.create(code="GUD", name="Gudang")
		self.facility = Facility.objects.create(
			code="PKM-01",
			name="Puskesmas Satu",
			facility_type=Facility.FacilityType.PUSKESMAS,
		)
		self.other_facility = Facility.objects.create(
			code="PKM-02",
			name="Puskesmas Dua",
			facility_type=Facility.FacilityType.PUSKESMAS,
		)
		self.item_a = Item.objects.create(
			nama_barang="Paracetamol",
			satuan=self.unit,
			kategori=self.category,
			is_active=True,
		)
		self.item_b = Item.objects.create(
			nama_barang="Amoxicillin",
			satuan=self.unit,
			kategori=self.category,
			is_active=True,
		)
		self.inactive_item = Item.objects.create(
			nama_barang="Item Nonaktif",
			satuan=self.unit,
			kategori=self.category,
			is_active=False,
		)

		self.puskesmas_user = User.objects.create_user(
			username="puskesmas",
			password="TestPassword123!",
			role=User.Role.PUSKESMAS,
			facility=self.facility,
		)
		self.other_puskesmas_user = User.objects.create_user(
			username="puskesmas2",
			password="TestPassword123!",
			role=User.Role.PUSKESMAS,
			facility=self.other_facility,
		)
		self.staff_user = User.objects.create_user(
			username="staff",
			password="TestPassword123!",
			role=User.Role.ADMIN,
		)
		self.superuser = User.objects.create_superuser(
			username="root",
			email="root@example.com",
			password="TestPassword123!",
		)

		for user, scope in (
			(self.puskesmas_user, ModuleAccess.Scope.OPERATE),
			(self.other_puskesmas_user, ModuleAccess.Scope.OPERATE),
			(self.staff_user, ModuleAccess.Scope.MANAGE),
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


class LPLPOWorkflowTests(LPLPOTestCase):
	def test_auto_generate_items_on_create(self):
		self.client.force_login(self.puskesmas_user)

		response = self.client.post(
			reverse("lplpo:lplpo_create"),
			{"bulan": "2", "tahun": "2026", "notes": "Draft awal"},
		)

		self.assertEqual(response.status_code, 302)
		lplpo = LPLPO.objects.get(facility=self.facility, bulan=2, tahun=2026)
		items = list(lplpo.items.order_by("item__nama_barang"))

		self.assertEqual(len(items), 2)
		self.assertCountEqual(
			[item.item_id for item in items],
			[self.item_a.id, self.item_b.id],
		)
		self.assertTrue(all(item.item.is_active for item in items))
		self.assertTrue(
			all(item.pemberian_jumlah == item.jumlah_kebutuhan for item in items)
		)

	def test_penerimaan_auto_fill(self):
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

	def test_computed_fields_correct(self):
		lplpo = self.create_lplpo()
		line = LPLPOItem.objects.create(
			lplpo=lplpo,
			item=self.item_a,
			stock_awal=Decimal("10.00"),
			penerimaan=Decimal("5.00"),
			pemakaian=Decimal("8.00"),
			waktu_kosong=Decimal("2.00"),
		)

		self.assertEqual(line.persediaan, Decimal("15.00"))
		self.assertEqual(line.stock_keseluruhan, Decimal("7.00"))
		self.assertEqual(line.stock_optimum, Decimal("8.40"))
		self.assertEqual(line.jumlah_kebutuhan, Decimal("3.40"))

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
		lplpo = self.create_lplpo(status=LPLPO.Status.SUBMITTED)

		self.client.force_login(self.puskesmas_user)
		response = self.client.get(reverse("lplpo:lplpo_review", args=[lplpo.pk]))

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
		lplpo = self.create_lplpo(status=LPLPO.Status.REVIEWED)

		self.client.force_login(self.puskesmas_user)
		response = self.client.get(reverse("lplpo:lplpo_detail", args=[lplpo.pk]))

		self.assertContains(response, "Disetujui / Menunggu Proses Distribusi")
		self.assertNotContains(response, "<strong>Ditinjau</strong>", html=True)

	def test_puskesmas_detail_hides_distribution_navigation(self):
		distribution = Distribution.objects.create(
			distribution_type=Distribution.DistributionType.LPLPO,
			facility=self.facility,
			request_date=date(2026, 2, 1),
			status=Distribution.Status.DRAFT,
			created_by=self.staff_user,
		)
		lplpo = self.create_lplpo(
			status=LPLPO.Status.DISTRIBUTED,
			distribution=distribution,
		)

		self.client.force_login(self.puskesmas_user)
		response = self.client.get(reverse("lplpo:lplpo_detail", args=[lplpo.pk]))

		self.assertContains(response, distribution.document_number)
		self.assertNotContains(response, 'id="view-dist-btn"')
		self.assertNotContains(
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
		self.assertEqual(lplpo.status, LPLPO.Status.DISTRIBUTED)
		self.assertEqual(distribution.distribution_type, Distribution.DistributionType.LPLPO)
		self.assertEqual(distribution.status, Distribution.Status.DRAFT)
		self.assertEqual(distribution.items.count(), 1)

		line = distribution.items.get()
		self.assertEqual(line.item, self.item_a)
		self.assertEqual(line.quantity_requested, Decimal("12.00"))
		self.assertEqual(line.quantity_approved, Decimal("9.00"))

	def test_distribution_distributed_closes_lplpo(self):
		distribution = Distribution.objects.create(
			distribution_type=Distribution.DistributionType.LPLPO,
			facility=self.facility,
			request_date=date(2026, 2, 1),
			status=Distribution.Status.DRAFT,
			created_by=self.staff_user,
		)
		lplpo = self.create_lplpo(
			status=LPLPO.Status.DISTRIBUTED,
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
			"4.00",
		)

	def test_review_uses_available_stock_not_total_stock(self):
		lplpo = self.create_lplpo(status=LPLPO.Status.SUBMITTED, created_by=self.puskesmas_user)
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
