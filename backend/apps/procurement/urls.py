from django.urls import path

from . import views

app_name = "procurement"

urlpatterns = [
    path("", views.contract_list, name="contract_list"),
    path("create/", views.contract_create, name="contract_create"),
    path("<int:pk>/", views.contract_detail, name="contract_detail"),
    path("<int:pk>/edit/", views.contract_edit, name="contract_edit"),
    path("<int:pk>/submit/", views.contract_submit, name="contract_submit"),
    path("<int:pk>/approve/", views.contract_approve, name="contract_approve"),
    path("<int:pk>/close/", views.contract_close, name="contract_close"),
    path("<int:pk>/amend/", views.amendment_create, name="amendment_create"),
    path("amendments/<int:pk>/", views.amendment_detail, name="amendment_detail"),
    path("amendments/<int:pk>/edit/", views.amendment_edit, name="amendment_edit"),
    path("amendments/<int:pk>/submit/", views.amendment_submit, name="amendment_submit"),
    path("amendments/<int:pk>/approve/", views.amendment_approve, name="amendment_approve"),
]
