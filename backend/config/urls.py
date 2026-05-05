from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views

from apps.core.views import (
    SystemSettingsUpdateView,
    administration_distribution_history,
    administration_receiving_history,
    dashboard,
)


urlpatterns = [
    path("admin/", admin.site.urls),
    # Dashboard (root)
    path("", dashboard, name="dashboard"),
    path("settings/", SystemSettingsUpdateView.as_view(), name="settings"),
    path(
        "administration/history/receiving/",
        administration_receiving_history,
        name="administration_receiving_history",
    ),
    path(
        "administration/history/distribution/",
        administration_distribution_history,
        name="administration_distribution_history",
    ),

    # Auth
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    # Password change
    path(
        "password/change/",
        auth_views.PasswordChangeView.as_view(
            template_name="registration/password_change.html",
        ),
        name="password_change",
    ),
    path(
        "password/change/done/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="registration/password_change_done.html",
        ),
        name="password_change_done",
    ),
    # Apps
    path("users/", include("apps.users.urls")),
    path("items/", include("apps.items.urls")),
    path("stock/", include("apps.stock.urls")),
    path("receiving/", include("apps.receiving.urls")),
    path("distribution/", include("apps.distribution.urls")),
    path("allocation/", include("apps.allocation.urls")),
    path("recall/", include("apps.recall.urls")),
    path("expired/", include("apps.expired.urls")),
    path("reports/", include("apps.reports.urls")),
    path("stock-opname/", include("apps.stock_opname.urls")),
    path("puskesmas/", include("apps.puskesmas.urls")),
    path("lplpo/", include("apps.lplpo.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
