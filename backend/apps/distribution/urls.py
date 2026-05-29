from django.urls import path
from . import views

app_name = "distribution"

urlpatterns = [
    path("", views.distribution_list, name="distribution_list"),
    path("report/", views.distribution_report, name="distribution_report"),
    path(
        "report/special-requests/",
        views.distribution_report_special_request,
        name="distribution_report_special_request",
    ),
    path(
        "report/allocation/",
        views.distribution_report_allocation,
        name="distribution_report_allocation",
    ),
    path(
        "report/lplpo/",
        views.distribution_report_lplpo,
        name="distribution_report_lplpo",
    ),
    path(
        "special-requests/",
        views.special_request_list,
        name="special_request_list",
    ),
    path("create/", views.distribution_create, name="distribution_create"),
    path(
        "special-requests/create/",
        views.special_request_create,
        name="special_request_create",
    ),
    path("<int:pk>/", views.distribution_detail, name="distribution_detail"),
    path("<int:pk>/edit/", views.distribution_edit, name="distribution_edit"),
    path("<int:pk>/delete/", views.distribution_delete, name="distribution_delete"),
    path(
        "<int:pk>/reset-to-draft/",
        views.distribution_reset_to_draft,
        name="distribution_reset_to_draft",
    ),
    path(
        "<int:pk>/step-back/",
        views.distribution_step_back,
        name="distribution_step_back",
    ),
    path("<int:pk>/submit/", views.distribution_submit, name="distribution_submit"),
    path("<int:pk>/verify/", views.distribution_verify, name="distribution_verify"),
    path("<int:pk>/prepare/", views.distribution_prepare, name="distribution_prepare"),
    path(
        "<int:pk>/distribute/",
        views.distribution_distribute,
        name="distribution_distribute",
    ),
    path(
        "<int:pk>/return-lplpo-to-puskesmas/",
        views.distribution_return_lplpo_to_puskesmas,
        name="distribution_return_lplpo_to_puskesmas",
    ),
    path("<int:pk>/reject/", views.distribution_reject, name="distribution_reject"),
]
