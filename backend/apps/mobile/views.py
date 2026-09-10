from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.core.decorators import perm_required
from apps.items.models import Item
from apps.stock.services import (
    StockListOptions,
    build_mobile_stock_detail_context,
    build_mobile_stock_search_context,
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
    }
    return render(request, "mobile/stock_card.html", context)
