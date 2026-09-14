from django.urls import path

from . import views


app_name = "mobile"

urlpatterns = [
    path("", views.home, name="home"),
    path("stocks/", views.stock_list, name="stock_list"),
    path("stocks/<int:item_id>/card/", views.stock_card, name="stock_card"),
    path("manifest.webmanifest/", views.manifest, name="manifest"),
    path("service-worker.js/", views.service_worker, name="service_worker"),
]
