from django.urls import path
from . import views

app_name = 'distribution'

urlpatterns = [
    path('', views.distribution_list, name='distribution_list'),
    path('create/', views.distribution_create, name='distribution_create'),
    path('<int:pk>/', views.distribution_detail, name='distribution_detail'),
]
