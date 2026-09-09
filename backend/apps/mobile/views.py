from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.decorators import perm_required
from apps.items.models import Item
from apps.stock.services import StockListOptions, build_stock_list_context
from apps.stock.views import _build_stock_card_data, _parse_filter_date


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


@login_required
@perm_required("stock.view_stock")
def stock_list(request):
    context = build_stock_list_context(
        request.GET,
        options=StockListOptions(page_size=20),
    )
    context["today"] = timezone.localdate()
    return render(request, "mobile/stock_list.html", context)


@login_required
@perm_required("stock.view_stock")
def stock_card(request, item_id):
    item = get_object_or_404(Item, pk=item_id)
    location_id = request.GET.get("location")
    sumber_dana_id = request.GET.get("sumber_dana")
    date_from_raw = request.GET.get("date_from", "").strip()
    date_to_raw = request.GET.get("date_to", "").strip()
    date_from = _parse_filter_date(date_from_raw)
    date_to = _parse_filter_date(date_to_raw)

    data = _build_stock_card_data(
        item,
        location_id=location_id,
        sumber_dana_id=sumber_dana_id,
        date_from=date_from,
        date_to=date_to,
    )
    context = {
        "item": item,
        **data,
        "date_from": date_from.strftime("%d/%m/%Y")
        if date_from
        else (date_from_raw or ""),
        "date_to": date_to.strftime("%d/%m/%Y") if date_to else (date_to_raw or ""),
        "selected_location": location_id or "",
        "selected_sumber_dana": sumber_dana_id or "",
    }
    return render(request, "mobile/stock_card.html", context)
