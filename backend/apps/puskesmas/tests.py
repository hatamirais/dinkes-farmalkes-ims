from django.test import TestCase
from django.urls import reverse

from apps.items.models import Category, Facility, Item, Unit
from apps.puskesmas.forms import PuskesmasRequestForm, PuskesmasRequestItemForm
from apps.puskesmas.models import PuskesmasRequest
from apps.users.models import User


class PuskesmasRequestFormTests(TestCase):
	def setUp(self):
		self.unit = Unit.objects.create(code="TAB", name="Tablet")
		self.category = Category.objects.create(code="OBT", name="Obat", sort_order=1)
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
		self.item = Item.objects.create(
			nama_barang="Haloperidol 5 mg",
			satuan=self.unit,
			kategori=self.category,
			is_active=True,
		)
		self.user = User.objects.create_user(
			username="operator-puskesmas",
			password="TestPassword123!",
			role=User.Role.PUSKESMAS,
			facility=self.facility,
		)

	def test_operator_form_hides_facility_and_uses_account_facility(self):
		form = PuskesmasRequestForm(user=self.user)

		self.assertEqual(form.fields["facility"].widget.__class__.__name__, "HiddenInput")
		self.assertEqual(form.fields["facility"].initial, self.facility.pk)

	def test_operator_form_ignores_posted_other_facility(self):
		form = PuskesmasRequestForm(
			data={
				"document_number": "",
				"facility": self.other_facility.pk,
				"request_date": "2026-04-02",
				"program": "",
				"notes": "",
			},
			user=self.user,
		)

		self.assertTrue(form.is_valid())
		self.assertEqual(form.cleaned_data["facility"], self.facility)

	def test_item_label_shows_name_only(self):
		form = PuskesmasRequestItemForm()

		self.assertEqual(form.fields["item"].label_from_instance(self.item), self.item.nama_barang)


class PuskesmasRequestCreateViewTests(TestCase):
	def setUp(self):
		self.unit = Unit.objects.create(code="TAB", name="Tablet")
		self.category = Category.objects.create(code="OBT", name="Obat", sort_order=1)
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
		self.item = Item.objects.create(
			nama_barang="Haloperidol 5 mg",
			satuan=self.unit,
			kategori=self.category,
			is_active=True,
		)
		self.user = User.objects.create_user(
			username="operator-view",
			password="TestPassword123!",
			role=User.Role.PUSKESMAS,
			facility=self.facility,
		)

	def test_create_binds_request_to_logged_in_facility(self):
		self.client.force_login(self.user)

		response = self.client.post(
			reverse("puskesmas:request_create"),
			{
				"document_number": "",
				"facility": self.other_facility.pk,
				"request_date": "2026-04-02",
				"program": "",
				"notes": "Permintaan uji",
				"items-TOTAL_FORMS": "3",
				"items-INITIAL_FORMS": "0",
				"items-MIN_NUM_FORMS": "1",
				"items-MAX_NUM_FORMS": "1000",
				"items-0-item": str(self.item.pk),
				"items-0-quantity_requested": "5",
				"items-0-notes": "",
				"items-1-item": "",
				"items-1-quantity_requested": "",
				"items-1-notes": "",
				"items-2-item": "",
				"items-2-quantity_requested": "",
				"items-2-notes": "",
			},
		)

		self.assertEqual(response.status_code, 302)
		req = PuskesmasRequest.objects.get()
		self.assertEqual(req.facility, self.facility)
		self.assertEqual(req.created_by, self.user)
