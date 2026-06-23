from django.urls import path
from . import views

app_name = "items"

urlpatterns = [
    path("", views.item_list, name="item_list"),
    path("create/", views.item_create, name="item_create"),
    path("units/create/", views.unit_create, name="unit_create"),
    path("categories/create/", views.category_create, name="category_create"),
    path("programs/create/", views.program_create, name="program_create"),
    path("therapeutic-classes/create/", views.therapeutic_class_create, name="therapeutic_class_create"),
    path("<int:pk>/edit/", views.item_update, name="item_update"),
    path("<int:pk>/delete/", views.item_delete, name="item_delete"),
    path("api/quick-create-unit/", views.quick_create_unit, name="quick_create_unit"),
    path(
        "api/quick-create-category/",
        views.quick_create_category,
        name="quick_create_category",
    ),
    path(
        "api/quick-create-program/",
        views.quick_create_program,
        name="quick_create_program",
    ),
    path(
        "api/quick-create-therapeutic-class/",
        views.quick_create_therapeutic_class,
        name="quick_create_therapeutic_class",
    ),
    path(
        "api/quick-create-facility/",
        views.quick_create_facility,
        name="quick_create_facility",
    ),
]
