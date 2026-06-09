from decimal import Decimal
from io import BytesIO

from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from apps.core.tests.mixins import SecureClientDefaultsMixin
from apps.distribution.models import Distribution
from apps.items.models import Category, Facility, Item, Unit
from apps.puskesmas.exports import export_puskesmas_penerimaan_excel
from apps.puskesmas.forms import PuskesmasRequestForm, PuskesmasRequestItemForm
from apps.puskesmas.models import PuskesmasRequest, PuskesmasRequestItem
from apps.users.access import ensure_default_module_access
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


class PuskesmasRequestCreateViewTests(SecureClientDefaultsMixin, TestCase):
	def setUp(self):
		super().setUp()
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
		self.staff_facility_user = User.objects.create_user(
			username="admin-umum-facility",
			password="TestPassword123!",
			role=User.Role.ADMIN_UMUM,
			facility=self.facility,
		)
		ensure_default_module_access(self.staff_facility_user, overwrite=True)

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

	def test_detail_returns_403_when_operator_accesses_other_facility_request(self):
		other_request = PuskesmasRequest.objects.create(
			facility=self.other_facility,
			created_by=self.other_user,
		)

		self.client.force_login(self.user)
		response = self.client.get(
			reverse("puskesmas:request_detail", args=[other_request.pk])
		)

		self.assertEqual(response.status_code, 403)

	def test_edit_returns_403_when_operator_accesses_other_facility_request(self):
		other_request = PuskesmasRequest.objects.create(
			facility=self.other_facility,
			created_by=self.other_user,
		)

		self.client.force_login(self.user)
		response = self.client.get(
			reverse("puskesmas:request_edit", args=[other_request.pk])
		)

		self.assertEqual(response.status_code, 403)

	def test_submit_returns_403_when_operator_accesses_other_facility_request(self):
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

		self.assertEqual(response.status_code, 403)
		other_request.refresh_from_db()
		self.assertEqual(other_request.status, PuskesmasRequest.Status.DRAFT)

	def test_non_superuser_without_facility_cannot_view_request_list(self):
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

		self.assertEqual(response.status_code, 403)

	def test_non_superuser_without_facility_cannot_view_request_detail(self):
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

		self.assertEqual(response.status_code, 403)

	def test_non_superuser_with_facility_list_is_scoped(self):
		own_request = PuskesmasRequest.objects.create(
			facility=self.facility,
			created_by=self.user,
		)
		other_request = PuskesmasRequest.objects.create(
			facility=self.other_facility,
			created_by=self.other_user,
		)

		self.client.force_login(self.staff_facility_user)
		response = self.client.get(reverse("puskesmas:request_list"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, own_request.document_number)
		self.assertNotContains(response, other_request.document_number)

	def test_non_superuser_with_facility_cannot_view_other_facility_request(self):
		other_request = PuskesmasRequest.objects.create(
			facility=self.other_facility,
			created_by=self.other_user,
		)

		self.client.force_login(self.staff_facility_user)
		response = self.client.get(reverse("puskesmas:request_detail", args=[other_request.pk]))

		self.assertEqual(response.status_code, 403)

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


class PuskesmasRequestApprovalTests(SecureClientDefaultsMixin, TestCase):
	def setUp(self):
		super().setUp()
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
			facility=self.facility,
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
		self.other_facility = Facility.objects.create(
			code="PKM-02",
			name="Puskesmas Dua",
			facility_type=Facility.FacilityType.PUSKESMAS,
		)
		self.other_requester = User.objects.create_user(
			username="operator-submit-other",
			password="TestPassword123!",
			role=User.Role.PUSKESMAS,
			facility=self.other_facility,
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

	def test_approver_cannot_approve_other_facility_request(self):
		req = PuskesmasRequest.objects.create(
			facility=self.other_facility,
			request_date="2026-04-02",
			status=PuskesmasRequest.Status.SUBMITTED,
			created_by=self.other_requester,
		)
		item_line = PuskesmasRequestItem.objects.create(
			request=req,
			item=self.item,
			quantity_requested=Decimal("8.00"),
		)

		self.client.force_login(self.approver)
		response = self.client.post(
			reverse("puskesmas:request_approve", args=[req.pk]),
			{f"approve_{item_line.pk}-quantity_approved": "5.00"},
		)

		self.assertEqual(response.status_code, 403)
		req.refresh_from_db()
		self.assertEqual(req.status, PuskesmasRequest.Status.SUBMITTED)
		self.assertIsNone(req.distribution)


class PuskesmasReportViewTests(SecureClientDefaultsMixin, TestCase):
	"""Tests for the Puskesmas report views and facility isolation rules."""

	def setUp(self):
		super().setUp()
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
		self.report_operator = User.objects.create_user(
			username="operator-report-enabled",
			password="TestPassword123!",
			role=User.Role.PUSKESMAS,
			facility=self.facility,
		)
		ensure_default_module_access(self.report_operator, overwrite=True)
		ModuleAccess.objects.update_or_create(
			user=self.report_operator,
			module=ModuleAccess.Module.REPORTS,
			defaults={"scope": ModuleAccess.Scope.VIEW},
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
		self.staff_with_facility = User.objects.create_user(
			username="gudang-report",
			password="TestPassword123!",
			role=User.Role.GUDANG,
			facility=self.facility,
		)
		ensure_default_module_access(self.staff_with_facility, overwrite=True)
		self.staff_without_facility = User.objects.create_user(
			username="gudang-no-facility",
			password="TestPassword123!",
			role=User.Role.GUDANG,
		)
		ensure_default_module_access(self.staff_without_facility, overwrite=True)
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

	def test_puskesmas_operator_without_reports_scope_cannot_access_penerimaan(self):
		self.client.force_login(self.operator)
		response = self.client.get(reverse("puskesmas:report_penerimaan"))
		self.assertEqual(response.status_code, 403)

	def test_puskesmas_operator_without_reports_scope_cannot_access_pemakaian(self):
		self.client.force_login(self.operator)
		response = self.client.get(reverse("puskesmas:report_pemakaian"))
		self.assertEqual(response.status_code, 403)

	def test_puskesmas_operator_without_reports_scope_cannot_access_persediaan(self):
		self.client.force_login(self.operator)
		response = self.client.get(reverse("puskesmas:report_persediaan"))
		self.assertEqual(response.status_code, 403)

	def test_report_enabled_puskesmas_operator_can_access_all_four_reports(self):
		self.client.force_login(self.report_operator)
		for url_name in (
			"report_penerimaan",
			"report_pemakaian",
			"report_persediaan",
			"report_rekap_persediaan",
		):
			with self.subTest(url_name=url_name):
				response = self.client.get(reverse(f"puskesmas:{url_name}"))
				self.assertEqual(response.status_code, 200)

	def test_puskesmas_report_sidebar_requires_reports_scope(self):
		self.client.force_login(self.operator)
		response = self.client.get(reverse("puskesmas:request_list"))
		self.assertEqual(response.status_code, 200)
		self.assertNotContains(response, "Laporan Puskesmas")

		self.client.force_login(self.report_operator)
		response = self.client.get(reverse("puskesmas:request_list"))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Laporan Puskesmas")

	def test_admin_can_access_all_three_reports(self):
		self.client.force_login(self.admin)
		for url_name in (
			"report_penerimaan",
			"report_pemakaian",
			"report_persediaan",
			"report_rekap_persediaan",
		):
			with self.subTest(url_name=url_name):
				response = self.client.get(reverse(f"puskesmas:{url_name}"))
				self.assertEqual(response.status_code, 200)

	def test_non_superuser_report_scope_defaults_to_linked_facility(self):
		from apps.distribution.models import DistributionItem
		from datetime import date as dt

		dist_own = self._make_distribution(
			self.facility, Distribution.Status.DISTRIBUTED, distributed_date=dt(2026, 3, 15)
		)
		DistributionItem.objects.create(
			distribution=dist_own, item=self.item,
			quantity_requested=10, quantity_approved=10,
		)
		dist_other = self._make_distribution(
			self.other_facility, Distribution.Status.DISTRIBUTED, distributed_date=dt(2026, 3, 15)
		)
		DistributionItem.objects.create(
			distribution=dist_other, item=self.item,
			quantity_requested=5, quantity_approved=5,
		)

		self.client.force_login(self.report_operator)
		response = self.client.get(
			reverse("puskesmas:report_penerimaan"),
			{"start_date": "2026-03-01", "end_date": "2026-03-31"},
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context["selected_facility_name"], self.facility.name)
		document_numbers = [row["document_number"] for row in response.context["report_data"]]
		self.assertEqual(document_numbers, [dist_own.document_number])

	def test_non_superuser_report_scope_ignores_mismatched_facility_query(self):
		from apps.distribution.models import DistributionItem
		from datetime import date as dt

		dist_own = self._make_distribution(
			self.facility, Distribution.Status.DISTRIBUTED, distributed_date=dt(2026, 3, 15)
		)
		DistributionItem.objects.create(
			distribution=dist_own, item=self.item,
			quantity_requested=10, quantity_approved=10,
		)
		dist_other = self._make_distribution(
			self.other_facility, Distribution.Status.DISTRIBUTED, distributed_date=dt(2026, 3, 15)
		)
		DistributionItem.objects.create(
			distribution=dist_other, item=self.item,
			quantity_requested=5, quantity_approved=5,
		)

		self.client.force_login(self.report_operator)
		response = self.client.get(
			reverse("puskesmas:report_penerimaan"),
			{
				"facility": str(self.other_facility.pk),
				"start_date": "2026-03-01",
				"end_date": "2026-03-31",
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context["selected_facility_name"], self.facility.name)
		document_numbers = [row["document_number"] for row in response.context["report_data"]]
		self.assertEqual(document_numbers, [dist_own.document_number])

	def test_non_superuser_without_linked_facility_gets_403_on_all_reports(self):
		self.client.force_login(self.staff_without_facility)

		for url_name in (
			"report_penerimaan",
			"report_pemakaian",
			"report_persediaan",
			"report_rekap_persediaan",
		):
			with self.subTest(url_name=url_name):
				response = self.client.get(reverse(f"puskesmas:{url_name}"))
				self.assertEqual(response.status_code, 403)

	def test_report_endpoints_deny_excel_exports_without_reports_scope(self):
		self.client.force_login(self.operator)

		for url_name, query in (
			("report_penerimaan", {"format": "excel"}),
			("report_pemakaian", {"format": "excel"}),
			("report_persediaan", {"format": "excel"}),
			("report_rekap_persediaan", {"format": "excel"}),
		):
			with self.subTest(url_name=url_name):
				response = self.client.get(reverse(f"puskesmas:{url_name}"), query)
				self.assertEqual(response.status_code, 403)

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

		self.client.force_login(self.report_operator)
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

		self.client.force_login(self.report_operator)
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

		self.client.force_login(self.report_operator)
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

		self.client.force_login(self.report_operator)
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

		self.client.force_login(self.report_operator)
		response = self.client.get(
			reverse("puskesmas:report_pemakaian"),
			{"year": "2026"},
		)
		self.assertEqual(response.status_code, 200)
		report_data = response.context["report_data"]
		periods = [r["period_display"] for r in report_data]
		self.assertIn("Februari 2026", periods)

	# ────────────── Persediaan LPLPO-based check ──────────────

	def test_persediaan_returns_200_with_form_for_operator(self):
		self.client.force_login(self.report_operator)
		response = self.client.get(reverse("puskesmas:report_persediaan"))
		self.assertEqual(response.status_code, 200)
		self.assertIn("form", response.context)

	def test_persediaan_returns_200_with_form_for_admin(self):
		self.client.force_login(self.admin)
		response = self.client.get(reverse("puskesmas:report_persediaan"))
		self.assertEqual(response.status_code, 200)
		self.assertIn("form", response.context)

	def test_persediaan_isolates_facility_via_lplpo(self):
		"""Operator sees only their facility's LPLPO stock, not other facilities."""
		from apps.items.models import Item, Unit, Category
		from apps.lplpo.models import LPLPO, LPLPOItem

		lplpo_own = LPLPO.objects.create(
			facility=self.facility,
			bulan=4,
			tahun=2026,
			status=LPLPO.Status.CLOSED,
			created_by=self.admin,
		)
		LPLPOItem.objects.create(
			lplpo=lplpo_own,
			item=self.item,
			stock_awal=50,
			penerimaan=20,
			pemakaian=10,
		)

		lplpo_other = LPLPO.objects.create(
			facility=self.other_facility,
			bulan=4,
			tahun=2026,
			status=LPLPO.Status.CLOSED,
			created_by=self.admin,
		)
		LPLPOItem.objects.create(
			lplpo=lplpo_other,
			item=self.item,
			stock_awal=999,
			penerimaan=999,
			pemakaian=0,
		)

		self.client.force_login(self.report_operator)
		response = self.client.get(
			reverse("puskesmas:report_persediaan"),
			{"year": "2026", "period": "q2"},
			follow=True,
		)
		self.assertEqual(response.status_code, 200)
		report_data = response.context["report_data"]
		# Only one item row, from operator's facility LPLPO (stock_keseluruhan = 50+20-10=60)
		self.assertEqual(len(report_data), 1)
		self.assertEqual(report_data[0]["stock_keseluruhan"], 60)
		self.assertEqual(response.context["period_label"], "Triwulan II")

	def test_persediaan_period_filter_uses_period_end_month(self):
		from apps.lplpo.models import LPLPO, LPLPOItem

		march = LPLPO.objects.create(
			facility=self.facility,
			bulan=3,
			tahun=2026,
			status=LPLPO.Status.CLOSED,
			created_by=self.admin,
		)
		LPLPOItem.objects.create(
			lplpo=march,
			item=self.item,
			stock_awal=10,
			penerimaan=5,
			pemakaian=2,
		)

		june = LPLPO.objects.create(
			facility=self.facility,
			bulan=6,
			tahun=2026,
			status=LPLPO.Status.CLOSED,
			created_by=self.admin,
		)
		LPLPOItem.objects.create(
			lplpo=june,
			item=self.item,
			stock_awal=13,
			penerimaan=4,
			pemakaian=3,
		)

		self.client.force_login(self.report_operator)
		response = self.client.get(
			reverse("puskesmas:report_persediaan"),
			{"year": "2026", "period": "q1"},
			follow=True,
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context["period_label"], "Triwulan I")
		self.assertEqual(response.context["report_data"][0]["stock_keseluruhan"], 13)

	def test_rekap_persediaan_aggregates_asset_valuation_by_category(self):
		from apps.lplpo.models import LPLPO, LPLPOItem
		other_category = Category.objects.create(
			code="RGN",
			name="Reagen",
			sort_order=2,
		)
		item_same_category = Item.objects.create(
			nama_barang="Paracetamol 500 mg",
			satuan=self.unit,
			kategori=self.category,
			is_active=True,
		)
		item_other_category = Item.objects.create(
			nama_barang="Reagen A",
			satuan=self.unit,
			kategori=other_category,
			is_active=True,
		)

		january = LPLPO.objects.create(
			facility=self.facility,
			bulan=1,
			tahun=2026,
			status=LPLPO.Status.CLOSED,
			created_by=self.admin,
		)
		LPLPOItem.objects.create(
			lplpo=january,
			item=self.item,
			stock_awal=10,
			penerimaan=0,
			harga_satuan=Decimal("1000.00"),
			pemakaian=4,
		)
		LPLPOItem.objects.create(
			lplpo=january,
			item=item_same_category,
			stock_awal=5,
			penerimaan=0,
			harga_satuan=Decimal("2000.00"),
			pemakaian=1,
		)
		LPLPOItem.objects.create(
			lplpo=january,
			item=item_other_category,
			stock_awal=3,
			penerimaan=1,
			harga_satuan=Decimal("500.00"),
			pemakaian=1,
		)

		february = LPLPO.objects.create(
			facility=self.facility,
			bulan=2,
			tahun=2026,
			status=LPLPO.Status.CLOSED,
			created_by=self.admin,
		)
		LPLPOItem.objects.create(
			lplpo=february,
			item=self.item,
			stock_awal=6,
			penerimaan=5,
			harga_satuan=Decimal("1200.00"),
			pemakaian=3,
		)
		LPLPOItem.objects.create(
			lplpo=february,
			item=item_same_category,
			stock_awal=4,
			penerimaan=2,
			harga_satuan=Decimal("2500.00"),
			pemakaian=1,
		)
		LPLPOItem.objects.create(
			lplpo=february,
			item=item_other_category,
			stock_awal=3,
			penerimaan=2,
			harga_satuan=Decimal("700.00"),
			pemakaian=1,
		)

		self.client.force_login(self.report_operator)
		response = self.client.get(
			reverse("puskesmas:report_rekap_persediaan"),
			{"year": "2026", "period": "q1"},
			follow=True,
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(len(response.context["rekap_data"]), 2)
		obat_row = response.context["rekap_data"][0]
		reagen_row = response.context["rekap_data"][1]
		self.assertEqual(obat_row["kategori"], self.category.name)
		self.assertEqual(obat_row["saldo_awal"], Decimal("20000.00"))
		self.assertEqual(obat_row["nilai_terima"], Decimal("11000.00"))
		self.assertEqual(obat_row["nilai_keluar"], Decimal("12100.00"))
		self.assertEqual(obat_row["saldo_akhir"], Decimal("22100.00"))
		self.assertEqual(reagen_row["kategori"], other_category.name)
		self.assertEqual(reagen_row["saldo_awal"], Decimal("1500.00"))
		self.assertEqual(reagen_row["nilai_terima"], Decimal("1900.00"))
		self.assertEqual(reagen_row["nilai_keluar"], Decimal("1200.00"))
		self.assertEqual(reagen_row["saldo_akhir"], Decimal("2800.00"))
		self.assertEqual(response.context["totals"]["saldo_awal"], Decimal("21500.00"))
		self.assertEqual(response.context["totals"]["nilai_terima"], Decimal("12900.00"))
		self.assertEqual(response.context["totals"]["nilai_keluar"], Decimal("13300.00"))
		self.assertEqual(response.context["totals"]["saldo_akhir"], Decimal("24900.00"))
		self.assertContains(response, "URAIAN")
		self.assertContains(response, "SALDO AWAL 2026")
		self.assertContains(response, "Rp 22.100,00")
		self.assertContains(response, "Triwulan I")

	def test_rekap_persediaan_excel_export_uses_category_summary_headers(self):
		from apps.puskesmas.exports import export_puskesmas_rekap_persediaan_excel

		response = export_puskesmas_rekap_persediaan_excel(
			rekap_data=[
				{
					"kategori": self.category.name,
					"saldo_awal": Decimal("10000.00"),
					"nilai_terima": Decimal("6000.00"),
					"nilai_keluar": Decimal("7600.00"),
					"saldo_akhir": Decimal("9600.00"),
				}
			],
			totals={
				"saldo_awal": Decimal("10000.00"),
				"nilai_terima": Decimal("6000.00"),
				"nilai_keluar": Decimal("7600.00"),
				"saldo_akhir": Decimal("9600.00"),
			},
			year=2026,
			period_label="Triwulan I",
			facility_name=self.facility.name,
		)

		self.assertEqual(
			response["Content-Type"],
			"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
		)
		workbook = load_workbook(BytesIO(response.content))
		sheet = workbook.active
		headers = [sheet.cell(row=4, column=idx).value for idx in range(1, 7)]
		self.assertEqual(
			headers,
			[
				"No",
				"Uraian",
				"Saldo Awal 2026\n(Rp)",
				"Nilai Terima 2026\n(Rp)",
				"Nilai Keluar 2026\n(Rp)",
				"Saldo Akhir 2026\n(Rp)",
			],
		)
		self.assertEqual(sheet.cell(row=5, column=2).value, self.category.name)
		self.assertEqual(sheet.cell(row=6, column=2).value, "TOTAL")

	def test_penerimaan_excel_neutralizes_formula_prefixed_text_and_keeps_numeric_cells(self):
		response = export_puskesmas_penerimaan_excel(
			[
				{
					"distributed_date": None,
					"document_number": "=DIST-001",
					"distribution_type_label": "+LPLPO",
					"nama_barang": "@Amoxicillin 500 mg",
					"satuan": "-Tablet",
					"issued_batch_lot": "=BATCH-01",
					"quantity": Decimal("5"),
					"issued_unit_price": Decimal("2500"),
				}
			],
			"2026-03-01",
			"2026-03-31",
			"=Puskesmas Formula",
		)

		workbook = load_workbook(BytesIO(response.content))
		sheet = workbook.active

		self.assertEqual(
			sheet["A2"].value,
			"Fasilitas: =Puskesmas Formula | Periode: 2026-03-01 s/d 2026-03-31",
		)
		self.assertEqual(sheet["C5"].value, "'=DIST-001")
		self.assertEqual(sheet["D5"].value, "'+LPLPO")
		self.assertEqual(sheet["E5"].value, "'@Amoxicillin 500 mg")
		self.assertEqual(sheet["F5"].value, "'-Tablet")
		self.assertEqual(sheet["G5"].value, "'=BATCH-01")
		self.assertEqual(sheet["A2"].data_type, "s")
		self.assertEqual(sheet["H5"].value, 5)
		self.assertEqual(sheet["I5"].value, 2500)
		self.assertEqual(sheet["J5"].value, 12500)
		self.assertEqual(sheet["H5"].data_type, "n")
		self.assertEqual(sheet["I5"].data_type, "n")
		self.assertEqual(sheet["J5"].data_type, "n")

