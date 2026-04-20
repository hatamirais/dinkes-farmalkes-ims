from django.urls import path
from . import views

app_name = "distribution"

urlpatterns = [
    path("", views.distribution_list, name="distribution_list"),
    path("create/", views.distribution_create, name="distribution_create"),
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
    path("<int:pk>/reject/", views.distribution_reject, name="distribution_reject"),
]
