import json
import logging
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from django.views.decorators.csrf import requires_csrf_token

from django.db.models import Count, Sum, Q, F, DecimalField, ExpressionWrapper, Value
from django.db.models.functions import Coalesce

from apps.items.models import Item
from apps.lplpo.models import LPLPO
from apps.puskesmas.models import PuskesmasRequest
from apps.stock.models import Stock, Transaction
from apps.users.models import User
from apps.users.access import has_module_scope
from apps.users.models import ModuleAccess
from django.urls import reverse, reverse_lazy
from django.views.generic.edit import UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django_ratelimit.exceptions import Ratelimited
from apps.core.models import SystemSettings
from apps.core.forms import SystemSettingsForm

security_logger = logging.getLogger("security")
app_logger = logging.getLogger("core")


def _get_client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _get_error_fallback(request):
    if getattr(request.user, "is_authenticated", False):
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
    username = (
        request.user.username
        if getattr(request.user, "is_authenticated", False)
        else "anonymous"
    )
    message = (
        f"event={event} status_code={status_code} method={request.method} "
        f"path={request.path} username={username} ip={_get_client_ip(request)}"
    )
    if exception:
        message = f"{message} exception={exception.__class__.__name__}"
    log_method(message)


def _render_error_page(request, template_name, response_status, **context):
    return render(request, template_name, context, status=response_status)


def _can_access_global_dashboard(user):
    if not getattr(user, "is_authenticated", False):
        return False

    return user.is_superuser or has_module_scope(
        user, ModuleAccess.Module.STOCK, ModuleAccess.Scope.VIEW
    )


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
            return render(
                request,
                "dashboard_puskesmas.html",
                {
                    "facility": None,
                    "draft_lplpo_count": 0,
                    "submitted_lplpo_count": 0,
                    "reviewed_lplpo_count": 0,
                    "recent_lplpos": [],
                    "recent_requests": [],
                    "latest_lplpo": None,
                },
            )

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

    can_view_items = has_module_scope(
        request.user, ModuleAccess.Module.ITEMS, ModuleAccess.Scope.VIEW
    )
    can_view_expired = has_module_scope(
        request.user, ModuleAccess.Module.EXPIRED, ModuleAccess.Scope.VIEW
    )
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
    has_quick_actions = any(
        [can_create_receiving, can_create_distribution, can_create_transfer]
    )

    today = timezone.now().date()
    three_months_later = today + timedelta(days=90)
    thirty_days_ago = today - timedelta(days=29)
    zero_decimal = Value(Decimal("0"), output_field=DecimalField(max_digits=18, decimal_places=2))
    available_stock_expression = ExpressionWrapper(
        F("quantity") - F("reserved"),
        output_field=DecimalField(max_digits=18, decimal_places=2),
    )
    stock_queryset = Stock.objects.filter(quantity__gt=0)
    stock_totals = stock_queryset.aggregate(
        total_stock_entries=Count("pk"),
        total_stock_quantity=Coalesce(Sum(available_stock_expression), zero_decimal),
        total_stock_value=Coalesce(
            Sum(
                ExpressionWrapper(
                    F("quantity") * F("unit_price"),
                    output_field=DecimalField(max_digits=18, decimal_places=2),
                )
            ),
            zero_decimal,
        ),
    )

    # Stats
    total_items = Item.objects.filter(is_active=True).count() if can_view_items else None
    total_stock_entries = stock_totals["total_stock_entries"]
    total_stock_quantity = stock_totals["total_stock_quantity"]
    total_stock_value = stock_totals["total_stock_value"]

    # Low stock: items where total stock quantity is below minimum_stock
    low_stock_count = None
    if can_view_items:
        low_stock_items = (
            Item.objects.filter(is_active=True)
            .annotate(total_qty=Sum("stock_entries__quantity"))
            .filter(
                Q(total_qty__lt=F("minimum_stock")) | Q(total_qty__isnull=True),
                minimum_stock__gt=0,
            )
        )
        low_stock_count = low_stock_items.count()

    # Expiring soon: stock entries expiring within 3 months
    expiring_soon = []
    expiring_soon_count = None
    if can_view_expired:
        expiring_soon_queryset = stock_queryset.filter(
            expiry_date__gte=today,
            expiry_date__lte=three_months_later,
        )
        expiring_soon = expiring_soon_queryset.select_related("item").order_by(
            "expiry_date"
        )[:10]
        expiring_soon_count = expiring_soon_queryset.count()

    non_transfer_filter = ~Q(reference_type=Transaction.ReferenceType.TRANSFER)
    today_tx_filter = Q(created_at__date=today) & non_transfer_filter
    tx_last_30_days = Transaction.objects.filter(
        created_at__date__gte=thirty_days_ago
    )
    tx_summary = tx_last_30_days.aggregate(
        today_transaction_count=Count("pk", filter=today_tx_filter),
        inbound_30_days=Coalesce(
            Sum(
                "quantity",
                filter=Q(transaction_type=Transaction.TransactionType.IN)
                & non_transfer_filter,
            ),
            zero_decimal,
        ),
        outbound_30_days=Coalesce(
            Sum(
                "quantity",
                filter=Q(transaction_type=Transaction.TransactionType.OUT)
                & non_transfer_filter,
            ),
            zero_decimal,
        ),
    )
    today_transaction_count = tx_summary["today_transaction_count"]
    inbound_30_days = tx_summary["inbound_30_days"]
    outbound_30_days = tx_summary["outbound_30_days"]
    movement_total_30_days = inbound_30_days + outbound_30_days
    if movement_total_30_days > 0:
        inbound_percent_30_days = int((inbound_30_days / movement_total_30_days) * 100)
        outbound_percent_30_days = 100 - inbound_percent_30_days
    else:
        inbound_percent_30_days = 0
        outbound_percent_30_days = 0

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
            "total_items": total_items,
            "total_stock_entries": total_stock_entries,
            "total_stock_quantity": total_stock_quantity,
            "total_stock_value": total_stock_value,
            "low_stock_count": low_stock_count,
            "expiring_soon_count": expiring_soon_count,
            "expiring_soon": expiring_soon,
            "show_items_metrics": can_view_items,
            "show_expiring_metrics": can_view_expired,
            "show_receiving_quick_action": can_create_receiving,
            "show_distribution_quick_action": can_create_distribution,
            "show_transfer_quick_action": can_create_transfer,
            "has_quick_actions": has_quick_actions,
            "today_transaction_count": today_transaction_count,
            "inbound_30_days": inbound_30_days,
            "outbound_30_days": outbound_30_days,
            "inbound_percent_30_days": inbound_percent_30_days,
            "outbound_percent_30_days": outbound_percent_30_days,
            "thirty_days_ago": thirty_days_ago,
            "today": today,
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


@login_required
def administration_receiving_history(request):
    if not _can_access_administration_history(request.user):
        raise PermissionDenied

    return render(
        request,
        "core/document_history_placeholder.html",
        {
            "page_title": "Riwayat Penerimaan Administrasi",
            "title": "Riwayat Penerimaan",
            "history_scope": "Penerimaan",
            "source_url": reverse_lazy("receiving:receiving_list"),
            "source_label": "Buka daftar penerimaan aktif",
            "next_focus": [
                "Pisahkan histori dokumen dari halaman transaksi operasional.",
                "Tambahkan filter nomor dokumen, status, sumber dana, dan rentang tanggal.",
                "Siapkan ekspor dan print layout yang mengikuti pola laporan lain.",
            ],
        },
    )


@login_required
def administration_distribution_history(request):
    if not _can_access_administration_history(request.user):
        raise PermissionDenied

    return render(
        request,
        "core/document_history_placeholder.html",
        {
            "page_title": "Riwayat Pengeluaran Administrasi",
            "title": "Riwayat Pengeluaran",
            "history_scope": "Pengeluaran",
            "source_url": reverse_lazy("distribution:distribution_list"),
            "source_label": "Buka daftar pengeluaran aktif",
            "next_focus": [
                "Pisahkan riwayat distribusi operasional dari arsip administrasi final.",
                "Tambahkan filter tipe dokumen, fasilitas, dan status distribusi.",
                "Sambungkan ke format cetak dan ekspor yang konsisten dengan modul laporan.",
            ],
        },
    )


class SystemSettingsUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = SystemSettings
    form_class = SystemSettingsForm
    template_name = "core/settings_form.html"
    success_url = reverse_lazy('dashboard')
    login_url = reverse_lazy('login')

    def test_func(self):
        user = self.request.user
        return user.is_superuser or has_module_scope(
            user, ModuleAccess.Module.ADMIN_PANEL, ModuleAccess.Scope.MANAGE
        )

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
