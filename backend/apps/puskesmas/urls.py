from django.urls import path
from . import views
from . import inventory_views
from . import consumption_views
from . import expiry_views
from . import opname_views

app_name = "puskesmas"

urlpatterns = [
    path("stock-opname/", opname_views.count_list, name="opname_list"),
    path("stock-opname/mulai/", opname_views.count_start, name="opname_start"),
    path("stock-opname/<int:pk>/", opname_views.count_detail, name="opname_detail"),
    path("stock-opname/<int:pk>/lokasi/<slug:location_key>/", opname_views.count_location, name="opname_location"),
    path("stock-opname/<int:pk>/lokasi/<slug:location_key>/barang/", opname_views.count_observation, name="opname_observation"),
    path("stock-opname/<int:pk>/lokasi/<slug:location_key>/barang/<int:row>/", opname_views.count_observation, name="opname_observation_edit"),
    path("stock-opname/<int:pk>/selisih/<slug:case_key>/", opname_views.count_case, name="opname_case"),
    path("stock-opname/<int:pk>/tindakan/", opname_views.count_action, name="opname_action"),
    path("stock-opname/<int:pk>/tindakan/<int:action_id>/", opname_views.count_decide, name="opname_decide"),
    path("stock-opname/<int:pk>/cetak/<int:number>/", opname_views.count_print, name="opname_print"),
    path("kedaluwarsa/", expiry_views.expiry_list, name="expiry_list"),
    path("kedaluwarsa/buat/", expiry_views.expiry_create, name="expiry_create"),
    path("kedaluwarsa/<int:pk>/", expiry_views.expiry_detail, name="expiry_detail"),
    path("kedaluwarsa/<int:pk>/koreksi/", expiry_views.expiry_edit, name="expiry_edit"),
    path("persediaan/", consumption_views.inventory_report, name="inventory_report"),
    path("lplpo/<int:pk>/adopsi/", consumption_views.opening_adoption, name="opening_adoption"),
    path("pemakaian/<int:pk>/finalisasi/", consumption_views.consumption_finalize, name="consumption_finalize"),
    path("saldo-awal/", inventory_views.opening_list, name="opening_list"),
    path("saldo-awal/template/", inventory_views.opening_template, name="opening_template"),
    path("saldo-awal/buat/", inventory_views.opening_create, name="opening_create"),
    path("saldo-awal/<int:pk>/", inventory_views.opening_detail, name="opening_detail"),
    # Stok Puskesmas
    path("stok/", views.stock_current, name="stock_current"),
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
    path("penerimaan/<int:receipt_id>/koreksi-opname/<int:pk>/", opname_views.count_action, name="receiving_opname_correction"),
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

