from django.urls import path

from . import views


app_name = "mobile"

urlpatterns = [
    path("", views.home, name="home"),
    path("stocks/", views.stock_list, name="stock_list"),
    path("stocks/<int:item_id>/card/", views.stock_card, name="stock_card"),
    path("approvals/", views.approval_inbox, name="approval_inbox"),
    path(
        "approvals/distributions/<int:pk>/",
        views.distribution_approval_detail,
        name="distribution_approval_detail",
    ),
    path(
        "approvals/distributions/<int:pk>/approve/",
        views.distribution_approve,
        name="distribution_approve",
    ),
    path(
        "approvals/distributions/<int:pk>/reject/",
        views.distribution_reject,
        name="distribution_reject",
    ),
    path(
        "approvals/expired/<int:pk>/",
        views.expired_approval_detail,
        name="expired_approval_detail",
    ),
    path(
        "approvals/expired/<int:pk>/approve/",
        views.expired_approve,
        name="expired_approve",
    ),
    path("manifest.webmanifest/", views.manifest, name="manifest"),
    path("service-worker.js/", views.service_worker, name="service_worker"),
]
