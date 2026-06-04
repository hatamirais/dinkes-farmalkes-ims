from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views

from apps.users.views import RateLimitedPasswordChangeView
from apps.core.views import (
    SystemSettingsUpdateView,
    administration_distribution_history,
    administration_receiving_history,
    bad_request,
    dashboard,
    debug_page_not_found,
    maintenance_mode,
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
    path("maintenance/", maintenance_mode, name="maintenance_mode"),

    # Auth
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    # Password change
    path(
        "password/change/",
        RateLimitedPasswordChangeView.as_view(
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


handler400 = "apps.core.views.bad_request"
handler403 = "apps.core.views.permission_denied_handler"
handler404 = "apps.core.views.page_not_found_handler"
handler500 = "apps.core.views.server_error_handler"

# Debug catch-all route - only active in DEBUG mode
# This must be conditional to avoid interfering with APPEND_SLASH middleware
# which needs to redirect URLs without trailing slashes to their slash-terminated versions
if settings.DEBUG:
    urlpatterns += [
        re_path(r"^(?P<unmatched_path>.*)$", debug_page_not_found, name="debug_page_not_found")
    ]
