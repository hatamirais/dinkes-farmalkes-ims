from django.urls import path
from . import views

app_name = 'stock'

urlpatterns = [
    path('', views.stock_list, name='stock_list'),
    path('transactions/', views.transaction_list, name='transaction_list'),
]
