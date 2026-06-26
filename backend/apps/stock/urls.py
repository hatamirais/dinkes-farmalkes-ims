from django.urls import path
from . import views

app_name = "stock"

urlpatterns = [
    path("", views.stock_list, name="stock_list"),
    path("puskesmas-stock/", views.puskesmas_stock, name="puskesmas_stock"),
    path("transactions/", views.transaction_list, name="transaction_list"),
    path("transfers/", views.transfer_list, name="transfer_list"),
    path("transfers/create/", views.transfer_create, name="transfer_create"),
    path("transfers/<int:transfer_id>/", views.transfer_detail, name="transfer_detail"),
    path(
        "transfers/<int:transfer_id>/complete/",
        views.transfer_complete,
        name="transfer_complete",
    ),
    path("stock-card/", views.stock_card_select, name="stock_card_select"),
    path(
        "stock-card/<int:item_id>/", views.stock_card_detail, name="stock_card_detail"
    ),
    path(
        "stock-card/<int:item_id>/print/",
        views.stock_card_print,
        name="stock_card_print",
    ),
    path("api/item-search/", views.api_item_search, name="api_item_search"),
    path(
        "api/location-stock-search/",
        views.api_location_stock_search,
        name="api_location_stock_search",
    ),
]
