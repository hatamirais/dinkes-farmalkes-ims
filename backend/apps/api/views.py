import logging

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from .authentication import ReportingApiAuthentication
from .permissions import ReportingApiEnabled
from .serializers import (
    ErrorResponseSerializer,
    PuskesmasStockResponseSerializer,
    WarehouseStockResponseSerializer,
)
from .services import (
    build_latest_puskesmas_stock_payload,
    build_latest_warehouse_stock_payload,
)


logger = logging.getLogger(__name__)


def _cached_payload(cache_key, builder):
    try:
        cached = cache.get(cache_key)
    except Exception:
        logger.warning(
            "Reporting API cache read failed for key %s",
            cache_key,
            exc_info=True,
        )
        cached = None

    if cached is not None:
        return cached

    payload = builder()

    try:
        cache.set(cache_key, payload, settings.REPORTING_API_CACHE_TTL_SECONDS)
    except Exception:
        logger.warning(
            "Reporting API cache write failed for key %s",
            cache_key,
            exc_info=True,
        )

    return payload


class ReportingApiView(APIView):
    authentication_classes = [ReportingApiAuthentication]
    permission_classes = [ReportingApiEnabled]


class LatestWarehouseStockView(ReportingApiView):
    @extend_schema(
        summary="Latest warehouse stock by item",
        description="Returns one row per active item, including active items without current stock.",
        auth=[{"ReportingApiBearerAuth": []}],
        responses={
            200: WarehouseStockResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
    )
    def get(self, request):
        payload = _cached_payload(
            "reporting_api:stocks:latest:v1",
            build_latest_warehouse_stock_payload,
        )
        return Response(WarehouseStockResponseSerializer(payload).data)


class LatestPuskesmasStockView(ReportingApiView):
    @extend_schema(
        summary="Latest Puskesmas stock by facility and item",
        description="Returns the LPLPO-derived current stock snapshot for active Puskesmas facilities.",
        auth=[{"ReportingApiBearerAuth": []}],
        parameters=[
            OpenApiParameter(
                name="year",
                description="LPLPO/reporting year. Defaults to the current local server year.",
                required=False,
                type=int,
            )
        ],
        responses={
            200: PuskesmasStockResponseSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
    )
    def get(self, request):
        raw_year = request.query_params.get("year")
        if raw_year:
            try:
                year = int(raw_year)
            except (TypeError, ValueError):
                return Response({"detail": "Invalid year."}, status=400)
            if year < 1000 or year > 9999:
                return Response({"detail": "Invalid year."}, status=400)
        else:
            year = timezone.localdate().year

        payload = _cached_payload(
            f"reporting_api:puskesmas_stocks:latest:{year}:v1",
            lambda: build_latest_puskesmas_stock_payload(year=year),
        )
        return Response(PuskesmasStockResponseSerializer(payload).data)
