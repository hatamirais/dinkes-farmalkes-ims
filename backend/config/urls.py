from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.core.urls')),
    path('items/', include('apps.items.urls')),
    path('stock/', include('apps.stock.urls')),
    path('receiving/', include('apps.receiving.urls')),
    path('distribution/', include('apps.distribution.urls')),
    path('reports/', include('apps.reports.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
