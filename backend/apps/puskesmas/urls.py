from django.urls import path
from . import views

app_name = "puskesmas"

urlpatterns = [
    # Subunit Puskesmas
    path("subunit/", views.subunit_list, name="subunit_list"),
    path("subunit/buat/", views.subunit_create, name="subunit_create"),
    path("subunit/<int:pk>/edit/", views.subunit_edit, name="subunit_edit"),
    path("subunit/<int:pk>/delete/", views.subunit_delete, name="subunit_delete"),
    # Pemakaian Rinci
    path("pemakaian/", views.consumption_list, name="consumption_list"),
    path("pemakaian/buat/", views.consumption_create, name="consumption_create"),
    path("pemakaian/<int:pk>/", views.consumption_detail, name="consumption_detail"),
    path("pemakaian/<int:pk>/edit/", views.consumption_edit, name="consumption_edit"),
    path("pemakaian/<int:pk>/delete/", views.consumption_delete, name="consumption_delete"),
    # Penerimaan SBBK
    path("penerimaan/", views.receiving_list, name="receiving_list"),
    path("penerimaan/buat/", views.receiving_create, name="receiving_create"),
    path("penerimaan/<int:pk>/", views.receiving_detail, name="receiving_detail"),
    path("penerimaan/<int:pk>/edit/", views.receiving_edit, name="receiving_edit"),
    path("penerimaan/<int:pk>/delete/", views.receiving_delete, name="receiving_delete"),
    # Permintaan Barang
    path("permintaan/", views.request_list, name="request_list"),
    path("permintaan/buat/", views.request_create, name="request_create"),
    path("permintaan/<int:pk>/", views.request_detail, name="request_detail"),
    path("permintaan/<int:pk>/edit/", views.request_edit, name="request_edit"),
    path("permintaan/<int:pk>/delete/", views.request_delete, name="request_delete"),
    path("permintaan/<int:pk>/submit/", views.request_submit, name="request_submit"),
    path("permintaan/<int:pk>/approve/", views.request_approve, name="request_approve"),
    path("permintaan/<int:pk>/reject/", views.request_reject, name="request_reject"),
    path("permintaan/<int:pk>/reset-draft/", views.request_reset_draft, name="request_reset_draft"),
    # Laporan Puskesmas
    path("laporan/penerimaan/", views.puskesmas_report_penerimaan, name="report_penerimaan"),
    path("laporan/pemakaian/", views.puskesmas_report_pemakaian, name="report_pemakaian"),
    path("laporan/persediaan/", views.puskesmas_report_persediaan, name="report_persediaan"),
    path("laporan/rekap-persediaan/", views.puskesmas_report_rekap_persediaan, name="report_rekap_persediaan"),
]

