from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views

from apps.core.views import dashboard

urlpatterns = [
    path('admin/', admin.site.urls),

    # Dashboard (root)
    path('', dashboard, name='dashboard'),

    # Auth
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),

    # Apps
    path('items/', include('apps.items.urls')),
    path('stock/', include('apps.stock.urls')),
    path('receiving/', include('apps.receiving.urls')),
    path('distribution/', include('apps.distribution.urls')),
    path('reports/', include('apps.reports.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
