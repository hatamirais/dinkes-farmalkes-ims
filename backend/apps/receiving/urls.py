from django.urls import path
from . import views

app_name = 'receiving'

urlpatterns = [
    path('', views.receiving_list, name='receiving_list'),
    path('create/', views.receiving_create, name='receiving_create'),
    path('<int:pk>/', views.receiving_detail, name='receiving_detail'),
]
