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
		self.item.nama_barang = "Haloperidol 5 mg [P]"
		self.item.save(update_fields=["nama_barang", "updated_at"])

		form = PuskesmasRequestItemForm()

		self.assertEqual(form.fields["item"].label_from_instance(self.item), "Haloperidol 5 mg")


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
		self.staff_user = User.objects.create_superuser(
			username="instalasi-admin",
			email="instalasi-admin@example.com",
			password="TestPassword123!",
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

	def test_instalasi_farmasi_cannot_create_request(self):
		self.client.force_login(self.staff_user)

		response = self.client.get(reverse("puskesmas:request_create"))

		self.assertEqual(response.status_code, 403)

	def test_instalasi_farmasi_list_hides_create_button(self):
		self.client.force_login(self.staff_user)

		response = self.client.get(reverse("puskesmas:request_list"))

		self.assertEqual(response.status_code, 200)
		self.assertNotContains(response, 'Buat Permintaan')

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

	def test_kepala_with_missing_module_rows_can_still_view_request_list(self):
		kepala = User.objects.create_user(
			username="kepala-legacy",
			password="TestPassword123!",
			role=User.Role.KEPALA,
		)
		ModuleAccess.objects.filter(user=kepala).delete()
		PuskesmasRequest.objects.create(
			facility=self.facility,
			created_by=self.user,
		)

		self.client.force_login(kepala)
		response = self.client.get(reverse("puskesmas:request_list"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Permintaan Barang Puskesmas")

	def test_admin_umum_with_missing_module_rows_can_view_request_detail(self):
		admin_umum = User.objects.create_user(
			username="admin-umum-legacy",
			password="TestPassword123!",
			role=User.Role.ADMIN_UMUM,
		)
		ModuleAccess.objects.filter(user=admin_umum).delete()
		req = PuskesmasRequest.objects.create(
			facility=self.facility,
			created_by=self.user,
		)

		self.client.force_login(admin_umum)
		response = self.client.get(reverse("puskesmas:request_detail", args=[req.pk]))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, req.document_number)

	def test_explicit_none_scope_cannot_view_request_list(self):
		auditor = User.objects.create_user(
			username="auditor-legacy",
			password="TestPassword123!",
			role=User.Role.AUDITOR,
		)
		ModuleAccess.objects.update_or_create(
			user=auditor,
			module=ModuleAccess.Module.PUSKESMAS,
			defaults={"scope": ModuleAccess.Scope.NONE},
		)

		self.client.force_login(auditor)
		response = self.client.get(reverse("puskesmas:request_list"))

		self.assertEqual(response.status_code, 403)


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
		self.approver = User.objects.create_user(
			username="approver-root",
			password="TestPassword123!",
			role=User.Role.KEPALA,
		)
		self.manager = User.objects.create_superuser(
			username="manager-puskesmas",
			email="manager-puskesmas@example.com",
			password="TestPassword123!",
		)
		ModuleAccess.objects.update_or_create(
			user=self.approver,
			module=ModuleAccess.Module.PUSKESMAS,
			defaults={"scope": ModuleAccess.Scope.APPROVE},
		)
		ModuleAccess.objects.update_or_create(
			user=self.manager,
			module=ModuleAccess.Module.PUSKESMAS,
			defaults={"scope": ModuleAccess.Scope.MANAGE},
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

	def test_approver_can_reset_submitted_request_to_draft(self):
		req = PuskesmasRequest.objects.create(
			facility=self.facility,
			request_date="2026-04-02",
			status=PuskesmasRequest.Status.SUBMITTED,
			created_by=self.requester,
		)
		PuskesmasRequestItem.objects.create(
			request=req,
			item=self.item,
			quantity_requested=Decimal("4.00"),
		)

		self.client.force_login(self.approver)
		response = self.client.post(
			reverse("puskesmas:request_reset_draft", args=[req.pk])
		)

		self.assertEqual(response.status_code, 302)
		req.refresh_from_db()
		self.assertEqual(req.status, PuskesmasRequest.Status.DRAFT)

	def test_approver_detail_hides_draft_actions(self):
		req = PuskesmasRequest.objects.create(
			facility=self.facility,
			request_date="2026-04-02",
			status=PuskesmasRequest.Status.DRAFT,
			created_by=self.requester,
		)
		PuskesmasRequestItem.objects.create(
			request=req,
			item=self.item,
			quantity_requested=Decimal("4.00"),
		)

		self.client.force_login(self.approver)
		response = self.client.get(reverse("puskesmas:request_detail", args=[req.pk]))

		self.assertEqual(response.status_code, 200)
		self.assertNotContains(response, "Ajukan Permintaan")
		self.assertNotContains(response, 'id="edit-btn"', html=False)
		self.assertNotContains(response, 'id="delete-open-btn"', html=False)

	def test_approver_cannot_submit_draft_request(self):
		req = PuskesmasRequest.objects.create(
			facility=self.facility,
			request_date="2026-04-02",
			status=PuskesmasRequest.Status.DRAFT,
			created_by=self.requester,
		)
		PuskesmasRequestItem.objects.create(
			request=req,
			item=self.item,
			quantity_requested=Decimal("4.00"),
		)

		self.client.force_login(self.approver)
		response = self.client.post(reverse("puskesmas:request_submit", args=[req.pk]))

		self.assertEqual(response.status_code, 302)
		self.assertRedirects(response, reverse("puskesmas:request_detail", args=[req.pk]))
		req.refresh_from_db()
		self.assertEqual(req.status, PuskesmasRequest.Status.DRAFT)

	def test_manager_can_submit_draft_request(self):
		req = PuskesmasRequest.objects.create(
			facility=self.facility,
			request_date="2026-04-02",
			status=PuskesmasRequest.Status.DRAFT,
			created_by=self.requester,
		)
		PuskesmasRequestItem.objects.create(
			request=req,
			item=self.item,
			quantity_requested=Decimal("4.00"),
		)

		self.client.force_login(self.manager)
		response = self.client.post(reverse("puskesmas:request_submit", args=[req.pk]))

		self.assertEqual(response.status_code, 302)
		req.refresh_from_db()
		self.assertEqual(req.status, PuskesmasRequest.Status.SUBMITTED)


class PuskesmasReportViewTests(TestCase):
	"""Tests for the three Puskesmas report views (penerimaan, pemakaian, persediaan)."""

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
			nama_barang="Amoxicillin 500 mg",
			satuan=self.unit,
			kategori=self.category,
			is_active=True,
		)
		# Puskesmas operator linked to facility
		self.operator = User.objects.create_user(
			username="operator-report",
			password="TestPassword123!",
			role=User.Role.PUSKESMAS,
			facility=self.facility,
		)
		# Operator from a different facility
		self.other_operator = User.objects.create_user(
			username="operator-other-report",
			password="TestPassword123!",
			role=User.Role.PUSKESMAS,
			facility=self.other_facility,
		)
		# Super admin
		self.admin = User.objects.create_superuser(
			username="admin-report",
			email="admin-report@example.com",
			password="TestPassword123!",
		)
		# Non-puskesmas user without puskesmas perm (AUDITOR with NONE scope)
		self.auditor = User.objects.create_user(
			username="auditor-report",
			password="TestPassword123!",
			role=User.Role.AUDITOR,
		)
		ModuleAccess.objects.update_or_create(
			user=self.auditor,
			module=ModuleAccess.Module.PUSKESMAS,
			defaults={"scope": ModuleAccess.Scope.NONE},
		)

	# ────────────── Permission / Auth checks ──────────────

	def test_penerimaan_requires_login(self):
		response = self.client.get(reverse("puskesmas:report_penerimaan"))
		self.assertEqual(response.status_code, 302)
		self.assertIn("/login/", response["Location"])

	def test_pemakaian_requires_login(self):
		response = self.client.get(reverse("puskesmas:report_pemakaian"))
		self.assertEqual(response.status_code, 302)
		self.assertIn("/login/", response["Location"])

	def test_persediaan_requires_login(self):
		response = self.client.get(reverse("puskesmas:report_persediaan"))
		self.assertEqual(response.status_code, 302)
		self.assertIn("/login/", response["Location"])

	def test_auditor_with_none_scope_cannot_access_penerimaan(self):
		self.client.force_login(self.auditor)
		response = self.client.get(reverse("puskesmas:report_penerimaan"))
		self.assertEqual(response.status_code, 403)

	def test_auditor_with_none_scope_cannot_access_pemakaian(self):
		self.client.force_login(self.auditor)
		response = self.client.get(reverse("puskesmas:report_pemakaian"))
		self.assertEqual(response.status_code, 403)

	def test_auditor_with_none_scope_cannot_access_persediaan(self):
		self.client.force_login(self.auditor)
		response = self.client.get(reverse("puskesmas:report_persediaan"))
		self.assertEqual(response.status_code, 403)

	def test_puskesmas_operator_can_access_penerimaan(self):
		self.client.force_login(self.operator)
		response = self.client.get(reverse("puskesmas:report_penerimaan"))
		self.assertEqual(response.status_code, 200)

	def test_puskesmas_operator_can_access_pemakaian(self):
		self.client.force_login(self.operator)
		response = self.client.get(reverse("puskesmas:report_pemakaian"))
		self.assertEqual(response.status_code, 200)

	def test_puskesmas_operator_can_access_persediaan(self):
		self.client.force_login(self.operator)
		response = self.client.get(reverse("puskesmas:report_persediaan"))
		self.assertEqual(response.status_code, 200)

	def test_admin_can_access_all_three_reports(self):
		self.client.force_login(self.admin)
		for url_name in ("report_penerimaan", "report_pemakaian", "report_persediaan"):
			with self.subTest(url_name=url_name):
				response = self.client.get(reverse(f"puskesmas:{url_name}"))
				self.assertEqual(response.status_code, 200)

	# ────────────── Penerimaan data correctness ──────────────

	def _make_distribution(self, facility, status, dist_type=None, distributed_date=None):
		from datetime import date as dt
		dist = Distribution.objects.create(
			distribution_type=dist_type or Distribution.DistributionType.LPLPO,
			facility=facility,
			request_date=distributed_date or dt(2026, 3, 15),
			status=status,
			distributed_date=distributed_date or dt(2026, 3, 15),
			created_by=self.admin,
		)
		return dist

	def test_penerimaan_only_shows_distributed_status(self):
		from apps.distribution.models import DistributionItem
		from datetime import date as dt

		# DISTRIBUTED dist for operator's facility
		dist_ok = self._make_distribution(
			self.facility, Distribution.Status.DISTRIBUTED, distributed_date=dt(2026, 3, 15)
		)
		DistributionItem.objects.create(
			distribution=dist_ok, item=self.item,
			quantity_requested=10, quantity_approved=10,
		)

		# PREPARED dist — should NOT appear
		dist_bad = self._make_distribution(
			self.facility, Distribution.Status.PREPARED, distributed_date=dt(2026, 3, 10)
		)
		DistributionItem.objects.create(
			distribution=dist_bad, item=self.item,
			quantity_requested=5, quantity_approved=5,
		)

		self.client.force_login(self.operator)
		response = self.client.get(
			reverse("puskesmas:report_penerimaan"),
			{"start_date": "2026-03-01", "end_date": "2026-03-31"},
		)
		self.assertEqual(response.status_code, 200)
		report_data = response.context["report_data"]
		self.assertEqual(len(report_data), 1)
		self.assertEqual(report_data[0]["document_number"], dist_ok.document_number)

	def test_penerimaan_isolates_facility(self):
		from apps.distribution.models import DistributionItem
		from datetime import date as dt

		# Distribution for operator's facility
		dist_own = self._make_distribution(
			self.facility, Distribution.Status.DISTRIBUTED, distributed_date=dt(2026, 3, 15)
		)
		DistributionItem.objects.create(
			distribution=dist_own, item=self.item,
			quantity_requested=10, quantity_approved=10,
		)
		# Distribution for another facility
		dist_other = self._make_distribution(
			self.other_facility, Distribution.Status.DISTRIBUTED, distributed_date=dt(2026, 3, 15)
		)
		DistributionItem.objects.create(
			distribution=dist_other, item=self.item,
			quantity_requested=5, quantity_approved=5,
		)

		self.client.force_login(self.operator)
		response = self.client.get(
			reverse("puskesmas:report_penerimaan"),
			{"start_date": "2026-03-01", "end_date": "2026-03-31"},
		)
		self.assertEqual(response.status_code, 200)
		report_data = response.context["report_data"]
		document_numbers = [r["document_number"] for r in report_data]
		self.assertIn(dist_own.document_number, document_numbers)
		self.assertNotIn(dist_other.document_number, document_numbers)

	# ────────────── Pemakaian data correctness ──────────────

	def _make_lplpo(self, facility, bulan, tahun, status):
		from apps.lplpo.models import LPLPO
		lplpo = LPLPO.objects.create(
			facility=facility,
			bulan=bulan,
			tahun=tahun,
			status=status,
			created_by=self.admin,
		)
		return lplpo

	def test_pemakaian_only_shows_finalized_lplpo(self):
		from apps.lplpo.models import LPLPO, LPLPOItem

		# CLOSED LPLPO — should appear
		lplpo_ok = self._make_lplpo(self.facility, 3, 2026, LPLPO.Status.CLOSED)
		LPLPOItem.objects.create(
			lplpo=lplpo_ok, item=self.item,
			pemakaian=100, stock_awal=50, penerimaan=80,
			stock_keseluruhan=30, permintaan_jumlah=50,
		)

		# SUBMITTED LPLPO — should NOT appear
		lplpo_bad = self._make_lplpo(self.facility, 4, 2026, LPLPO.Status.SUBMITTED)
		LPLPOItem.objects.create(
			lplpo=lplpo_bad, item=self.item,
			pemakaian=20, stock_awal=30,
		)

		self.client.force_login(self.operator)
		response = self.client.get(
			reverse("puskesmas:report_pemakaian"),
			{"year": "2026"},
		)
		self.assertEqual(response.status_code, 200)
		report_data = response.context["report_data"]
		periods = [r["period_display"] for r in report_data]
		self.assertIn("Maret 2026", periods)
		self.assertNotIn("April 2026", periods)

	def test_pemakaian_isolates_facility(self):
		from apps.lplpo.models import LPLPO, LPLPOItem

		lplpo_own = self._make_lplpo(self.facility, 3, 2026, LPLPO.Status.CLOSED)
		LPLPOItem.objects.create(
			lplpo=lplpo_own, item=self.item,
			pemakaian=100, stock_awal=50,
		)
		lplpo_other = self._make_lplpo(self.other_facility, 3, 2026, LPLPO.Status.CLOSED)
		LPLPOItem.objects.create(
			lplpo=lplpo_other, item=self.item,
			pemakaian=200, stock_awal=100,
		)

		self.client.force_login(self.operator)
		response = self.client.get(
			reverse("puskesmas:report_pemakaian"),
			{"year": "2026"},
		)
		self.assertEqual(response.status_code, 200)
		report_data = response.context["report_data"]
		# Each item must belong only to operator's facility
		for row in report_data:
			self.assertEqual(row["period_display"], "Maret 2026")
		# The data from other facility should not appear (only one LPLPO for our facility)
		self.assertEqual(len(report_data), 1)

	def test_pemakaian_distributed_status_included(self):
		from apps.lplpo.models import LPLPO, LPLPOItem

		lplpo = self._make_lplpo(self.facility, 2, 2026, LPLPO.Status.DISTRIBUTED)
		LPLPOItem.objects.create(
			lplpo=lplpo, item=self.item,
			pemakaian=60, stock_awal=80,
		)

		self.client.force_login(self.operator)
		response = self.client.get(
			reverse("puskesmas:report_pemakaian"),
			{"year": "2026"},
		)
		self.assertEqual(response.status_code, 200)
		report_data = response.context["report_data"]
		periods = [r["period_display"] for r in report_data]
		self.assertIn("Februari 2026", periods)

	# ────────────── Persediaan placeholder check ──────────────

	def test_persediaan_returns_200_with_form(self):
		self.client.force_login(self.operator)
		response = self.client.get(reverse("puskesmas:report_persediaan"))
		self.assertEqual(response.status_code, 200)
		self.assertIn("form", response.context)

	def test_persediaan_shows_placeholder_warning(self):
		self.client.force_login(self.operator)
		response = self.client.get(reverse("puskesmas:report_persediaan"))
		self.assertContains(response, "Placeholder")

