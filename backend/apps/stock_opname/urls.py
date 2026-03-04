from django.urls import path
from . import views

app_name = 'stock_opname'

urlpatterns = [
    path('', views.opname_list, name='opname_list'),
    path('create/', views.opname_create, name='opname_create'),
    path('<int:pk>/', views.opname_detail, name='opname_detail'),
    path('<int:pk>/edit/', views.opname_edit, name='opname_edit'),
    path('<int:pk>/start/', views.opname_start, name='opname_start'),
    path('<int:pk>/input/', views.opname_input, name='opname_input'),
    path('<int:pk>/complete/', views.opname_complete, name='opname_complete'),
    path('<int:pk>/print/', views.opname_print, name='opname_print'),
    path('<int:pk>/delete/', views.opname_delete, name='opname_delete'),
]
