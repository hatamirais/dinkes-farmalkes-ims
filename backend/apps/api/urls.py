from django.urls import path

from . import views

app_name = "reporting_api"

urlpatterns = [
    path("stocks/latest/", views.LatestWarehouseStockView.as_view(), name="stocks_latest"),
    path(
        "puskesmas-stocks/latest/",
        views.LatestPuskesmasStockView.as_view(),
        name="puskesmas_stocks_latest",
    ),
]
