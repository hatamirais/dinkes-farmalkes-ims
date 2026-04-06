from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.distribution.models import Distribution
from apps.items.models import Category, Facility, Item, Unit
from apps.puskesmas.forms import PuskesmasRequestForm, PuskesmasRequestItemForm
from apps.puskesmas.models import PuskesmasRequest, PuskesmasRequestItem
from apps.users.models import ModuleAccess, User


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
		self.other_user = User.objects.create_user(
			username="operator-other",
			password="TestPassword123!",
			role=User.Role.PUSKESMAS,
			facility=self.other_facility,
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

	def test_edit_shows_operator_facility_as_readonly(self):
		req = PuskesmasRequest.objects.create(
			facility=self.facility,
			created_by=self.user,
		)

		self.client.force_login(self.user)
		response = self.client.get(reverse("puskesmas:request_edit", args=[req.pk]))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, self.facility.name)
		self.assertContains(response, 'type="hidden"', html=False)

	def test_edit_keeps_operator_facility_even_if_post_tampered(self):
		req = PuskesmasRequest.objects.create(
			facility=self.facility,
			created_by=self.user,
		)
		item_line = PuskesmasRequestItem.objects.create(
			request=req,
			item=self.item,
			quantity_requested=5,
		)

		self.client.force_login(self.user)
		response = self.client.post(
			reverse("puskesmas:request_edit", args=[req.pk]),
			{
				"document_number": req.document_number,
				"facility": self.other_facility.pk,
				"request_date": "2026-04-02",
				"program": "",
				"notes": "Permintaan edit",
				"items-TOTAL_FORMS": "1",
				"items-INITIAL_FORMS": "1",
				"items-MIN_NUM_FORMS": "1",
				"items-MAX_NUM_FORMS": "1000",
				"items-0-id": str(item_line.pk),
				"items-0-item": str(self.item.pk),
				"items-0-quantity_requested": "5",
				"items-0-notes": "",
			},
		)

		self.assertEqual(response.status_code, 302)
		req.refresh_from_db()
		self.assertEqual(req.facility, self.facility)

	def test_list_only_shows_operator_facility_requests(self):
		own_request = PuskesmasRequest.objects.create(
			facility=self.facility,
			created_by=self.user,
		)
		other_request = PuskesmasRequest.objects.create(
			facility=self.other_facility,
			created_by=self.other_user,
		)

		self.client.force_login(self.user)
		response = self.client.get(reverse("puskesmas:request_list"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, own_request.document_number)
		self.assertNotContains(response, other_request.document_number)

	def test_detail_redirects_when_operator_accesses_other_facility_request(self):
		other_request = PuskesmasRequest.objects.create(
			facility=self.other_facility,
			created_by=self.other_user,
		)

		self.client.force_login(self.user)
		response = self.client.get(
			reverse("puskesmas:request_detail", args=[other_request.pk])
		)

		self.assertEqual(response.status_code, 302)
		self.assertRedirects(response, reverse("puskesmas:request_list"))

	def test_edit_redirects_when_operator_accesses_other_facility_request(self):
		other_request = PuskesmasRequest.objects.create(
			facility=self.other_facility,
			created_by=self.other_user,
		)

		self.client.force_login(self.user)
		response = self.client.get(
			reverse("puskesmas:request_edit", args=[other_request.pk])
		)

		self.assertEqual(response.status_code, 302)
		self.assertRedirects(response, reverse("puskesmas:request_list"))

	def test_submit_redirects_when_operator_accesses_other_facility_request(self):
		other_request = PuskesmasRequest.objects.create(
			facility=self.other_facility,
			status=PuskesmasRequest.Status.DRAFT,
			created_by=self.other_user,
		)
		PuskesmasRequestItem.objects.create(
			request=other_request,
			item=self.item,
			quantity_requested=Decimal("2.00"),
		)

		self.client.force_login(self.user)
		response = self.client.post(
			reverse("puskesmas:request_submit", args=[other_request.pk])
		)

		self.assertEqual(response.status_code, 302)
		self.assertRedirects(response, reverse("puskesmas:request_list"))
		other_request.refresh_from_db()
		self.assertEqual(other_request.status, PuskesmasRequest.Status.DRAFT)


class PuskesmasRequestApprovalTests(TestCase):
	def setUp(self):
		self.unit = Unit.objects.create(code="TAB", name="Tablet")
		self.category = Category.objects.create(code="OBT", name="Obat", sort_order=1)
		self.facility = Facility.objects.create(
			code="PKM-01",
			name="Puskesmas Satu",
			facility_type=Facility.FacilityType.PUSKESMAS,
		)
		self.item = Item.objects.create(
			nama_barang="Haloperidol 5 mg",
			satuan=self.unit,
			kategori=self.category,
			is_active=True,
		)
		self.requester = User.objects.create_user(
			username="operator-submit",
			password="TestPassword123!",
			role=User.Role.PUSKESMAS,
			facility=self.facility,
		)
		self.approver = User.objects.create_superuser(
			username="approver-root",
			email="approver@example.com",
			password="TestPassword123!",
		)
		ModuleAccess.objects.update_or_create(
			user=self.approver,
			module=ModuleAccess.Module.PUSKESMAS,
			defaults={"scope": ModuleAccess.Scope.APPROVE},
		)

	def test_approve_creates_distribution_with_requested_and_approved_quantities(self):
		req = PuskesmasRequest.objects.create(
			facility=self.facility,
			request_date="2026-04-02",
			status=PuskesmasRequest.Status.SUBMITTED,
			created_by=self.requester,
		)
		item_line = PuskesmasRequestItem.objects.create(
			request=req,
			item=self.item,
			quantity_requested=Decimal("8.00"),
		)

		self.client.force_login(self.approver)
		response = self.client.post(
			reverse("puskesmas:request_approve", args=[req.pk]),
			{
				f"approve_{item_line.pk}-quantity_approved": "5.00",
			},
		)

		self.assertEqual(response.status_code, 302)
		req.refresh_from_db()
		distribution = req.distribution
		self.assertIsNotNone(distribution)
		self.assertEqual(
			distribution.distribution_type,
			Distribution.DistributionType.SPECIAL_REQUEST,
		)
		self.assertTrue(distribution.staff_assignments.filter(user=self.approver).exists())

		line = distribution.items.get()
		self.assertEqual(line.quantity_requested, Decimal("8.00"))
		self.assertEqual(line.quantity_approved, Decimal("5.00"))

	def test_operator_detail_does_not_show_approval_actions(self):
		req = PuskesmasRequest.objects.create(
			facility=self.facility,
			request_date="2026-04-02",
			status=PuskesmasRequest.Status.SUBMITTED,
			created_by=self.requester,
		)
		PuskesmasRequestItem.objects.create(
			request=req,
			item=self.item,
			quantity_requested=Decimal("8.00"),
		)

		self.client.force_login(self.requester)
		response = self.client.get(reverse("puskesmas:request_detail", args=[req.pk]))

		self.assertEqual(response.status_code, 200)
		self.assertNotContains(response, "Setujui Permintaan")
		self.assertNotContains(response, "Tolak")

	def test_operator_cannot_approve_request_directly(self):
		req = PuskesmasRequest.objects.create(
			facility=self.facility,
			request_date="2026-04-02",
			status=PuskesmasRequest.Status.SUBMITTED,
			created_by=self.requester,
		)
		item_line = PuskesmasRequestItem.objects.create(
			request=req,
			item=self.item,
			quantity_requested=Decimal("8.00"),
		)

		self.client.force_login(self.requester)
		response = self.client.post(
			reverse("puskesmas:request_approve", args=[req.pk]),
			{
				f"approve_{item_line.pk}-quantity_approved": "5.00",
			},
		)

		self.assertEqual(response.status_code, 403)
		req.refresh_from_db()
		self.assertEqual(req.status, PuskesmasRequest.Status.SUBMITTED)
		self.assertIsNone(req.distribution)

	def test_operator_cannot_reject_request_directly(self):
		req = PuskesmasRequest.objects.create(
			facility=self.facility,
			request_date="2026-04-02",
			status=PuskesmasRequest.Status.SUBMITTED,
			created_by=self.requester,
		)

		self.client.force_login(self.requester)
		response = self.client.post(
			reverse("puskesmas:request_reject", args=[req.pk]),
			{"rejection_reason": "Tidak valid"},
		)

		self.assertEqual(response.status_code, 403)
		req.refresh_from_db()
		self.assertEqual(req.status, PuskesmasRequest.Status.SUBMITTED)
