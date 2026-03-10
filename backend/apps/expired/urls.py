from django.urls import path
from . import views

app_name = 'expired'

urlpatterns = [
    path('', views.expired_list, name='expired_list'),
    path('create/', views.expired_create, name='expired_create'),
    path('<int:pk>/', views.expired_detail, name='expired_detail'),
    path('<int:pk>/edit/', views.expired_edit, name='expired_edit'),
    path('<int:pk>/submit/', views.expired_submit, name='expired_submit'),
    path('<int:pk>/verify/', views.expired_verify, name='expired_verify'),
    path('<int:pk>/dispose/', views.expired_dispose, name='expired_dispose'),
    path('<int:pk>/delete/', views.expired_delete, name='expired_delete'),
]
