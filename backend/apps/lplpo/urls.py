from django.urls import path
from . import views

app_name = "lplpo"

urlpatterns = [
    path("", views.lplpo_list, name="lplpo_list"),
    path("my/", views.lplpo_my_list, name="lplpo_my_list"),
    path("create/", views.lplpo_create, name="lplpo_create"),
    path("print-report/", views.lplpo_print_report, name="lplpo_print_report"),
    path(
        "api/prefill-penerimaan/",
        views.api_prefill_penerimaan,
        name="api_prefill_penerimaan",
    ),
    path("<int:pk>/", views.lplpo_detail, name="lplpo_detail"),
    path("<int:pk>/edit/", views.lplpo_edit, name="lplpo_edit"),
    path("<int:pk>/submit/", views.lplpo_submit, name="lplpo_submit"),
    path("<int:pk>/verify/", views.lplpo_verify, name="lplpo_verify"),
    path("<int:pk>/reject/", views.lplpo_reject, name="lplpo_reject"),
    path("<int:pk>/review/", views.lplpo_review, name="lplpo_review"),
    path("<int:pk>/finalize/", views.lplpo_finalize, name="lplpo_finalize"),
    path("<int:pk>/delete/", views.lplpo_delete, name="lplpo_delete"),
    path("<int:pk>/print/", views.lplpo_print, name="lplpo_print"),
]
