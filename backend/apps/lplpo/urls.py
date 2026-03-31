from django.urls import path
from . import views

app_name = "lplpo"

urlpatterns = [
    path("", views.lplpo_list, name="lplpo_list"),
    path("my/", views.lplpo_my_list, name="lplpo_my_list"),
    path("create/", views.lplpo_create, name="lplpo_create"),
    path("<int:pk>/", views.lplpo_detail, name="lplpo_detail"),
    path("<int:pk>/edit/", views.lplpo_edit, name="lplpo_edit"),
    path("<int:pk>/submit/", views.lplpo_submit, name="lplpo_submit"),
    path("<int:pk>/review/", views.lplpo_review, name="lplpo_review"),
    path("<int:pk>/finalize/", views.lplpo_finalize, name="lplpo_finalize"),
    path("<int:pk>/delete/", views.lplpo_delete, name="lplpo_delete"),
    path("<int:pk>/print/", views.lplpo_print, name="lplpo_print"),
]
