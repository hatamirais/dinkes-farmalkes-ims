from django.urls import path
from . import views

app_name = 'items'

urlpatterns = [
    path('', views.item_list, name='item_list'),
    path('create/', views.item_create, name='item_create'),
    path('units/create/', views.unit_create, name='unit_create'),
    path('categories/create/', views.category_create, name='category_create'),
    path('programs/create/', views.program_create, name='program_create'),
    path('<int:pk>/edit/', views.item_update, name='item_update'),
    path('<int:pk>/delete/', views.item_delete, name='item_delete'),
]
