import json
import logging
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import HttpResponsePermanentRedirect
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.utils.http import escape_leading_slashes
from datetime import timedelta
from django.views.decorators.csrf import requires_csrf_token

from django.db.models import Count, Q

from apps.lplpo.models import LPLPO
from apps.puskesmas.models import PuskesmasRequest
from apps.stock.models import Stock, Transaction
from apps.users.models import User
from apps.users.access import has_module_permission, has_module_scope
from apps.users.models import ModuleAccess
from django.urls import Resolver404, resolve, reverse, reverse_lazy
from django.views.generic.edit import UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django_ratelimit.exceptions import Ratelimited
from apps.core.client_ip import get_client_ip
from apps.core.models import SystemSettings
from apps.core.forms import SystemSettingsForm

security_logger = logging.getLogger("security")
app_logger = logging.getLogger("core")


def _get_error_fallback(request):
    request_user = getattr(request, "user", None)
    if getattr(request_user, "is_authenticated", False):
        return reverse("dashboard"), "Buka Dashboard"
    return reverse("login"), "Buka Login"


def _build_error_context(request, status_code, title, message, icon, tone, help_text):
    fallback_url, fallback_label = _get_error_fallback(request)
    return {
        "status_code": str(status_code),
        "title": title,
        "message": message,
        "icon": icon,
        "tone": tone,
        "help_text": help_text,
        "fallback_url": fallback_url,
        "fallback_label": fallback_label,
        "requested_path": request.get_full_path(),
    }


def _log_error_event(logger, level, event, request, status_code, exception=None):
    log_method = getattr(logger, level)
    request_user = getattr(request, "user", None)
    username = (
        request_user.username
        if getattr(request_user, "is_authenticated", False)
        else "anonymous"
    )
    message = (
        f"event={event} status_code={status_code} method={request.method} "
        f"path={request.path} username={username} ip={get_client_ip(request)}"
    )
    if exception:
        message = f"{message} exception={exception.__class__.__name__}"
    log_method(message)


def _render_error_page(request, template_name, response_status, **context):
    return render(request, template_name, context, status=response_status)


def _can_access_global_dashboard(user):
    if not getattr(user, "is_authenticated", False):
        return False

    if getattr(user, "role", None) == User.Role.AUDITOR:
        return _can_view_reports(user)

    return user.is_superuser or has_module_scope(
        user, ModuleAccess.Module.STOCK, ModuleAccess.Scope.VIEW
    )


def _can_view_reports(user):
    return user.is_superuser or user.has_perm(
        "reports.view_reports"
    ) or has_module_permission(user, "reports.view_reports")


def maintenance_mode(request):
    _log_error_event(app_logger, "warning", "service_unavailable", request, 503)
    context = _build_error_context(
        request,
        503,
        "Layanan sedang dalam perawatan",
        "Aplikasi untuk sementara tidak tersedia karena pemeliharaan atau deployment sedang berlangsung. Silakan kembali ke halaman sebelumnya atau coba lagi beberapa saat lagi.",
        "bi bi-tools",
        "info",
        "Gunakan halaman ini sebagai fallback maintenance manual atau endpoint preview untuk pesan downtime yang konsisten.",
    )
    return _render_error_page(request, "503.html", 503, **context)


def bad_request(request, exception):
    _log_error_event(security_logger, "warning", "bad_request", request, 400, exception)
    context = _build_error_context(
        request,
        400,
        "Permintaan tidak dapat diproses",
        "Server menerima permintaan yang tidak lengkap atau tidak valid. Kembali ke halaman sebelumnya untuk memeriksa data yang terakhir Anda kirim.",
        "bi bi-slash-circle",
        "info",
        "Periksa kembali parameter, filter, atau data formulir sebelum mencoba lagi.",
    )
    return _render_error_page(request, "400.html", 400, **context)


@requires_csrf_token
def permission_denied_handler(request, exception):
    if isinstance(exception, Ratelimited):
        _log_error_event(security_logger, "warning", "rate_limited", request, 429, exception)
        context = _build_error_context(
            request,
            429,
            "Terlalu banyak percobaan pada aksi ini",
            "Permintaan Anda untuk aksi sensitif ini melebihi batas keamanan sementara. Tunggu sejenak lalu coba lagi.",
            "bi bi-hourglass-split",
            "warning",
            "Batas ini diterapkan untuk mencegah penyalahgunaan pada perubahan akun dan aksi sensitif lain. Jika Anda terus diblokir, periksa kembali apakah langkah yang sama terkirim berulang kali.",
        )
        return _render_error_page(request, "429.html", 429, **context)

    message = str(exception).strip() if exception and str(exception).strip() else (
        "Hak akses Anda tidak mencukupi untuk membuka halaman ini atau melakukan aksi yang diminta."
    )
    _log_error_event(security_logger, "warning", "permission_denied", request, 403, exception)
    context = _build_error_context(
        request,
        403,
        "Anda tidak memiliki akses ke halaman ini",
        message,
        "bi bi-lock",
        "warning",
        "Kembali ke halaman sebelumnya untuk melanjutkan pekerjaan yang diizinkan, atau gunakan dashboard untuk memilih modul yang sesuai dengan izin Anda.",
    )
    return _render_error_page(request, "403.html", 403, **context)


@requires_csrf_token
def page_not_found_handler(request, exception):
    _log_error_event(app_logger, "info", "page_not_found", request, 404, exception)
    context = _build_error_context(
        request,
        404,
        "Halaman yang Anda cari tidak ditemukan",
        "Alamat yang diminta tidak tersedia, mungkin sudah dipindahkan, dihapus, atau URL yang dibuka tidak lengkap.",
        "bi bi-signpost-split",
        "warning",
        "Kembali ke halaman sebelumnya untuk melanjutkan alur terakhir Anda, atau buka tujuan fallback untuk mulai dari titik yang aman.",
    )
    return _render_error_page(request, "404.html", 404, **context)


def debug_page_not_found(request, unmatched_path=""):
    if (
        request.method in {"GET", "HEAD"}
        and settings.APPEND_SLASH
        and not request.path_info.endswith("/")
    ):
        slash_path = f"{request.path_info}/"
        try:
            match = resolve(slash_path)
        except Resolver404:
            match = None

        if match and match.view_name != "debug_page_not_found":
            redirect_path = escape_leading_slashes(slash_path)
            query_string = request.META.get("QUERY_STRING")
            if query_string:
                redirect_path = f"{redirect_path}?{query_string}"
            return HttpResponsePermanentRedirect(redirect_path)

    return page_not_found_handler(request, FileNotFoundError(unmatched_path or request.path))


@requires_csrf_token
def server_error_handler(request):
    _log_error_event(app_logger, "error", "server_error", request, 500)
    context = _build_error_context(
        request,
        500,
        "Terjadi kesalahan pada server",
        "Permintaan Anda sudah sampai ke server, tetapi sistem gagal menyelesaikannya. Muat ulang dari halaman sebelumnya atau kembali ke tujuan fallback.",
        "bi bi-server",
        "danger",
        "Jika error ini terus muncul pada langkah yang sama, catat aktivitas terakhir Anda lalu periksa log aplikasi untuk diagnosis lebih lanjut.",
    )
    return _render_error_page(request, "500.html", 500, **context)

@login_required
def dashboard(request):
    if request.user.role == User.Role.PUSKESMAS:
        facility = request.user.facility
        if not facility:
            raise PermissionDenied("Akun Anda belum terhubung ke fasilitas puskesmas.")
        lplpo_queryset = LPLPO.objects.filter(facility=facility).select_related(
            "facility"
        )
        request_queryset = PuskesmasRequest.objects.filter(
            facility=facility
        ).select_related("program")
        lplpo_counts = lplpo_queryset.aggregate(
            draft_lplpo_count=Count("pk", filter=Q(status=LPLPO.Status.DRAFT)),
            submitted_lplpo_count=Count(
                "pk", filter=Q(status=LPLPO.Status.SUBMITTED)
            ),
            reviewed_lplpo_count=Count("pk", filter=Q(status=LPLPO.Status.REVIEWED)),
        )

        latest_lplpo = lplpo_queryset.order_by("-tahun", "-bulan", "-created_at").first()
        recent_lplpos = lplpo_queryset.order_by("-tahun", "-bulan", "-created_at")[:5]
        recent_requests = request_queryset.order_by("-request_date", "-created_at")[:5]

        return render(
            request,
            "dashboard_puskesmas.html",
            {
                "facility": facility,
                **lplpo_counts,
                "recent_lplpos": recent_lplpos,
                "recent_requests": recent_requests,
                "latest_lplpo": latest_lplpo,
            },
        )

    if not _can_access_global_dashboard(request.user):
        raise PermissionDenied(
            "Anda tidak memiliki izin untuk mengakses dashboard inventaris."
        )

    can_view_expired = has_module_scope(
        request.user, ModuleAccess.Module.EXPIRED, ModuleAccess.Scope.VIEW
    )
    can_view_reports = _can_view_reports(request.user)
    can_create_receiving = has_module_scope(
        request.user, ModuleAccess.Module.RECEIVING, ModuleAccess.Scope.OPERATE
    )
    can_create_distribution = has_module_scope(
        request.user, ModuleAccess.Module.DISTRIBUTION, ModuleAccess.Scope.OPERATE
    )
    can_create_transfer = has_module_scope(
        request.user, ModuleAccess.Module.STOCK, ModuleAccess.Scope.OPERATE
    )
    can_view_transaction_user = _can_access_administration_history(request.user)
    show_linked_dashboard_sections = request.user.role != User.Role.AUDITOR

    today = timezone.now().date()
    three_months_later = today + timedelta(days=90)
    stock_queryset = Stock.objects.filter(quantity__gt=0)

    # Expiring soon: stock entries expiring within 3 months
    expiring_soon = []
    if can_view_expired and show_linked_dashboard_sections:
        expiring_soon_queryset = stock_queryset.filter(
            expiry_date__gte=today,
            expiry_date__lte=three_months_later,
        )
        expiring_soon = expiring_soon_queryset.select_related("item").order_by(
            "expiry_date"
        )[:10]

    # Recent transactions
    recent_transactions_queryset = Transaction.objects.exclude(
        reference_type=Transaction.ReferenceType.TRANSFER
    ).select_related("item")
    if can_view_transaction_user:
        recent_transactions_queryset = recent_transactions_queryset.select_related(
            "user"
        )
    recent_transactions = recent_transactions_queryset.order_by("-created_at")[:10]

    return render(
        request,
        "dashboard.html",
        {
            "expiring_soon": expiring_soon,
            "show_expiring_metrics": can_view_expired and show_linked_dashboard_sections,
            "show_reports_landing": can_view_reports and not show_linked_dashboard_sections,
            "show_linked_dashboard_sections": show_linked_dashboard_sections,
            "show_receiving_quick_action": can_create_receiving,
            "show_distribution_quick_action": can_create_distribution,
            "show_transfer_quick_action": can_create_transfer,
            "show_transaction_user": can_view_transaction_user,
            "recent_transactions": recent_transactions,
        },
    )


def _can_access_administration_history(user):
    if not getattr(user, "is_authenticated", False):
        return False

    return user.is_superuser or has_module_scope(
        user, ModuleAccess.Module.USERS, ModuleAccess.Scope.VIEW
    ) or has_module_scope(
        user, ModuleAccess.Module.ADMIN_PANEL, ModuleAccess.Scope.MANAGE
    )


class SystemSettingsUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = SystemSettings
    form_class = SystemSettingsForm
    template_name = "core/settings_form.html"
    success_url = reverse_lazy('dashboard')
    login_url = reverse_lazy('login')

    def test_func(self):
        user = self.request.user
        return user.is_superuser or user.role in {
            User.Role.ADMIN,
            User.Role.KEPALA,
        }

    def get_object(self, queryset=None):
        return SystemSettings.get_settings()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = context.get("form")
        sample_year = str(timezone.now().year)
        sample_sequence = "12"
        lplpo_template = form["lplpo_distribution_number_template"].value()
        special_request_template = form[
            "special_request_distribution_number_template"
        ].value()
        context["numbering_preview_cards"] = [
            {
                "title": "Preview LPLPO",
                "template": lplpo_template,
                "example": self._render_numbering_preview(
                    lplpo_template,
                    sample_sequence,
                    sample_year,
                ),
            },
            {
                "title": "Preview Permintaan Khusus",
                "template": special_request_template,
                "example": self._render_numbering_preview(
                    special_request_template,
                    sample_sequence,
                    sample_year,
                ),
            },
        ]
        context["numbering_preview_sample_year"] = sample_year
        context["numbering_preview_sample_sequence"] = sample_sequence
        return context

    @staticmethod
    def _render_numbering_preview(template, sequence, year):
        return (template or "").replace("{seq}", sequence).replace("{year}", year)

    def form_valid(self, form):
        logo = form.cleaned_data.get("logo")
        if logo and hasattr(logo, "read") and not hasattr(logo, "url"):
            security_logger.info(
                json.dumps(
                    {
                        "event": "system_settings_logo_upload_succeeded",
                        "filename": logo.name,
                        "mime_type": getattr(form, "cleaned_logo_mime_type", "unknown"),
                        "username": self.request.user.username,
                    },
                    sort_keys=True,
                )
            )
        messages.success(self.request, "Pengaturan sistem berhasil diperbarui.")
        return super().form_valid(form)

    def form_invalid(self, form):
        if self.request.method == "POST" and self.request.FILES.get("logo"):
            security_logger.warning(
                json.dumps(
                    {
                        "event": "system_settings_logo_upload_failed",
                        "errors": json.loads(form.errors.as_json()),
                        "filename": self.request.FILES["logo"].name,
                        "username": self.request.user.username,
                    },
                    sort_keys=True,
                )
            )
        return super().form_invalid(form)

