from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('settings/', views.SystemSettingsUpdateView.as_view(), name='settings'),
    path(
        'settings/numbering/',
        views.DocumentNumberSettingsUpdateView.as_view(),
        name='numbering_settings',
    ),
]
