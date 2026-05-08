from django.urls import path

from . import views

app_name = "users"

urlpatterns = [
    path("", views.user_list, name="user_list"),
    path("create/", views.user_create, name="user_create"),
    path("export/", views.user_export_csv, name="user_export_csv"),
    path("bulk-action/", views.user_bulk_action, name="user_bulk_action"),
    path("<int:pk>/", views.user_detail, name="user_detail"),
    path("<int:pk>/edit/", views.user_update, name="user_update"),
    path("<int:pk>/delete/", views.user_delete, name="user_delete"),
    path(
        "<int:pk>/toggle-active/", views.user_toggle_active, name="user_toggle_active"
    ),
    path(
        "<int:pk>/reset-password/",
        views.user_reset_password,
        name="user_reset_password",
    ),
]
