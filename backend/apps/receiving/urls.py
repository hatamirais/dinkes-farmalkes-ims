from django.urls import path
from . import views

app_name = "receiving"

urlpatterns = [
    path("", views.receiving_list, name="receiving_list"),
    path("plans/", views.receiving_plan_list, name="receiving_plan_list"),
    path("plans/create/", views.receiving_plan_create, name="receiving_plan_create"),
    path("plans/<int:pk>/", views.receiving_plan_detail, name="receiving_plan_detail"),
    path(
        "plans/<int:pk>/submit/",
        views.receiving_plan_submit,
        name="receiving_plan_submit",
    ),
    path(
        "plans/<int:pk>/approve/",
        views.receiving_plan_approve,
        name="receiving_plan_approve",
    ),
    path(
        "plans/<int:pk>/receive/",
        views.receiving_plan_receive,
        name="receiving_plan_receive",
    ),
    path(
        "plans/<int:pk>/close/", views.receiving_plan_close, name="receiving_plan_close"
    ),
    path(
        "plans/<int:pk>/close-items/",
        views.receiving_plan_close_items,
        name="receiving_plan_close_items",
    ),
    path("create/", views.receiving_create, name="receiving_create"),
    path("<int:pk>/", views.receiving_detail, name="receiving_detail"),
    path(
        "api/quick-create-supplier/",
        views.quick_create_supplier,
        name="quick_create_supplier",
    ),
    path(
        "api/quick-create-funding-source/",
        views.quick_create_funding_source,
        name="quick_create_funding_source",
    ),
    path(
        "api/quick-create-receiving-type/",
        views.quick_create_receiving_type,
        name="quick_create_receiving_type",
    ),
]
