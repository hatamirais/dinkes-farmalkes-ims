from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.decorators import perm_required
from apps.distribution.models import Distribution
from apps.distribution.services import (
    DistributionWorkflowError,
    execute_distribution_rejection,
    execute_distribution_verification,
)
from apps.expired.models import Expired
from apps.expired.services import ExpiredWorkflowError, execute_expired_verification
from apps.items.models import Item
from apps.stock.services import (
    StockListOptions,
    build_mobile_stock_detail_context,
    build_mobile_stock_search_context,
)
from apps.users.access import can_approve_workflow
from apps.users.models import ModuleAccess


def _mobile_approval_access(user):
    return {
        "distribution": can_approve_workflow(
            user,
            ModuleAccess.Module.DISTRIBUTION,
        ),
        "expired": can_approve_workflow(
            user,
            ModuleAccess.Module.EXPIRED,
        ),
    }


def _mobile_navigation_context(user):
    access = _mobile_approval_access(user)
    pending_count = 0
    if access["distribution"]:
        pending_count += (
            Distribution.objects.filter(status=Distribution.Status.SUBMITTED)
            .exclude(distribution_type=Distribution.DistributionType.ALLOCATION)
            .count()
        )
    if access["expired"]:
        pending_count += Expired.objects.filter(status=Expired.Status.SUBMITTED).count()
    return {
        "can_view_mobile_approvals": any(access.values()),
        "mobile_pending_approval_count": pending_count,
        "mobile_approval_access": access,
    }


def _require_mobile_approval_access(user, module):
    if not can_approve_workflow(user, module):
        raise PermissionDenied(
            "Hanya Kepala Instalasi atau Admin dengan scope approve yang dapat "
            "mengakses persetujuan ini."
        )


def manifest(request):
    return JsonResponse(
        {
            "name": "Healthcare IMS Mobile",
            "short_name": "IMS Mobile",
            "start_url": "/mobile/stocks/",
            "scope": "/mobile/",
            "display": "standalone",
            "background_color": "#f8fafc",
            "theme_color": "#0f766e",
            "icons": [
                {
                    "src": "/static/img/default-logo.svg",
                    "sizes": "any",
                    "type": "image/svg+xml",
                    "purpose": "any maskable",
                }
            ],
        },
        content_type="application/manifest+json",
    )


def service_worker(request):
    body = """
self.addEventListener("install", event => {
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(self.clients.claim());
});
""".strip()
    response = HttpResponse(body, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/mobile/"
    return response


@login_required
def home(request):
    return redirect("mobile:stock_list")


def _stock_list_return_url(request):
    params = request.GET.copy()
    params.pop("page", None)
    params.pop("partial", None)
    querystring = params.urlencode()
    url = reverse("mobile:stock_list")
    if querystring:
        return f"{url}?{querystring}"
    return url


@login_required
@perm_required("stock.view_stock")
def stock_list(request):
    context = build_mobile_stock_search_context(
        request.GET,
        options=StockListOptions(page_size=20),
    )
    context["today"] = timezone.localdate()
    if request.GET.get("partial") == "1":
        response = render(request, "mobile/partials/stock_item_results.html", context)
        response["X-Has-Next"] = "1" if context["items"].has_next() else "0"
        response["X-Next-Page"] = (
            str(context["items"].next_page_number())
            if context["items"].has_next()
            else ""
        )
        response["X-Result-Count"] = str(context["items"].paginator.count)
        response["X-Entry-Count"] = str(context["stock_stats"]["total_entries"])
        response["X-Quick-Expired"] = str(context["quick_counts"]["expired"])
        response["X-Quick-Expiring"] = str(context["quick_counts"]["expiring"])
        response["X-Quick-Safe"] = str(context["quick_counts"]["safe"])
        return response

    context.update(_mobile_navigation_context(request.user))
    return render(request, "mobile/stock_list.html", context)


@login_required
@perm_required("stock.view_stock")
def stock_card(request, item_id):
    item = get_object_or_404(Item, pk=item_id)
    data = build_mobile_stock_detail_context(
        item,
        request.GET,
        options=StockListOptions(page_size=20),
    )
    context = {
        "item": item,
        "stock_list_return_url": _stock_list_return_url(request),
        **data,
        **_mobile_navigation_context(request.user),
    }
    return render(request, "mobile/stock_card.html", context)


@login_required
def approval_inbox(request):
    access = _mobile_approval_access(request.user)
    if not any(access.values()):
        raise PermissionDenied(
            "Anda tidak memiliki akses ke antrean persetujuan mobile."
        )

    distribution_queryset = Distribution.objects.none()
    if access["distribution"]:
        distribution_queryset = (
            Distribution.objects.filter(status=Distribution.Status.SUBMITTED)
            .exclude(distribution_type=Distribution.DistributionType.ALLOCATION)
            .select_related("facility", "created_by")
            .prefetch_related("staff_assignments")
            .order_by("created_at", "pk")
        )

    expired_queryset = Expired.objects.none()
    if access["expired"]:
        expired_queryset = (
            Expired.objects.filter(status=Expired.Status.SUBMITTED)
            .select_related("created_by")
            .prefetch_related("items")
            .order_by("created_at", "pk")
        )

    distributions = Paginator(distribution_queryset, 20).get_page(
        request.GET.get("distribution_page")
    )
    expired_documents = Paginator(expired_queryset, 20).get_page(
        request.GET.get("expired_page")
    )
    context = {
        "distributions": distributions,
        "expired_documents": expired_documents,
        **_mobile_navigation_context(request.user),
    }
    return render(request, "mobile/approval_inbox.html", context)


def _distribution_approval_queryset():
    return (
        Distribution.objects.exclude(
            distribution_type=Distribution.DistributionType.ALLOCATION
        )
        .select_related("facility", "created_by", "verified_by")
        .prefetch_related(
            "staff_assignments__user",
            "items__item__satuan",
            "items__stock__location",
            "items__stock__sumber_dana",
        )
    )


@login_required
def distribution_approval_detail(request, pk):
    _require_mobile_approval_access(
        request.user,
        ModuleAccess.Module.DISTRIBUTION,
    )
    distribution = get_object_or_404(_distribution_approval_queryset(), pk=pk)
    return render(
        request,
        "mobile/distribution_approval_detail.html",
        {
            "distribution": distribution,
            "items": distribution.items.all(),
            **_mobile_navigation_context(request.user),
        },
    )


@login_required
@require_POST
def distribution_approve(request, pk):
    _require_mobile_approval_access(
        request.user,
        ModuleAccess.Module.DISTRIBUTION,
    )
    distribution = get_object_or_404(_distribution_approval_queryset(), pk=pk)
    try:
        execute_distribution_verification(distribution, request.user)
    except DistributionWorkflowError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"Distribusi {distribution.document_number} berhasil disetujui.",
        )
    return redirect("mobile:distribution_approval_detail", pk=pk)


@login_required
@require_POST
def distribution_reject(request, pk):
    _require_mobile_approval_access(
        request.user,
        ModuleAccess.Module.DISTRIBUTION,
    )
    distribution = get_object_or_404(_distribution_approval_queryset(), pk=pk)
    try:
        execute_distribution_rejection(distribution)
    except DistributionWorkflowError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"Distribusi {distribution.document_number} dikembalikan ke petugas.",
        )
    return redirect("mobile:distribution_approval_detail", pk=pk)


def _expired_approval_queryset():
    return (
        Expired.objects.select_related("created_by", "verified_by")
        .prefetch_related(
            "items__item__satuan",
            "items__stock__location",
            "items__stock__sumber_dana",
        )
    )


@login_required
def expired_approval_detail(request, pk):
    _require_mobile_approval_access(
        request.user,
        ModuleAccess.Module.EXPIRED,
    )
    expired_document = get_object_or_404(_expired_approval_queryset(), pk=pk)
    return render(
        request,
        "mobile/expired_approval_detail.html",
        {
            "expired_document": expired_document,
            "items": expired_document.items.all(),
            **_mobile_navigation_context(request.user),
        },
    )


@login_required
@require_POST
def expired_approve(request, pk):
    _require_mobile_approval_access(
        request.user,
        ModuleAccess.Module.EXPIRED,
    )
    expired_document = get_object_or_404(_expired_approval_queryset(), pk=pk)
    try:
        execute_expired_verification(expired_document, request.user)
    except ExpiredWorkflowError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"Dokumen {expired_document.document_number} berhasil diverifikasi dan stok diperbarui.",
        )
    return redirect("mobile:expired_approval_detail", pk=pk)
