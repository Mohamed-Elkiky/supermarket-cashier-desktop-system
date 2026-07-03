import logging

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsDepartmentManager
from . import services
from .serializers import (
    BestSellersQuerySerializer,
    DepartmentPerformanceQuerySerializer,
    SalesDashboardQuerySerializer,
    StaffPerformanceQuerySerializer,
    WasteCostQuerySerializer,
)

logger = logging.getLogger("apps.reporting")


def _ok(data):
    return Response({"success": True, "data": data})


def _get_department(department_id):
    if not department_id:
        return None
    from apps.departments.models import Department
    return get_object_or_404(Department, pk=department_id)


class SalesDashboardView(APIView):
    permission_classes = [IsDepartmentManager]

    @extend_schema(
        summary="Sales dashboard",
        description="Revenue, order count, average basket, revenue by day and by payment method.",
        parameters=[
            OpenApiParameter("date_from", OpenApiTypes.DATE, required=True),
            OpenApiParameter("date_to", OpenApiTypes.DATE, required=True),
            OpenApiParameter("department", OpenApiTypes.INT, description="Filter by department ID"),
        ],
        responses={200: OpenApiResponse(description="Sales dashboard data")},
        tags=["Reporting"],
    )
    def get(self, request):
        serializer = SalesDashboardQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        department = _get_department(d.get("department"))
        data = services.get_sales_dashboard(date_from=d["date_from"], date_to=d["date_to"], department=department)
        return _ok(data)


class DepartmentPerformanceView(APIView):
    permission_classes = [IsDepartmentManager]

    @extend_schema(
        summary="Department performance",
        description="Per-department revenue, margin and transaction count, ranked by revenue descending.",
        parameters=[
            OpenApiParameter("date_from", OpenApiTypes.DATE, required=True),
            OpenApiParameter("date_to", OpenApiTypes.DATE, required=True),
        ],
        responses={200: OpenApiResponse(description="List of per-department performance rows")},
        tags=["Reporting"],
    )
    def get(self, request):
        serializer = DepartmentPerformanceQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        data = services.get_department_performance(date_from=d["date_from"], date_to=d["date_to"])
        return _ok(data)


class BestSellersView(APIView):
    permission_classes = [IsDepartmentManager]

    @extend_schema(
        summary="Best sellers",
        description="Top variants by units sold or margin.",
        parameters=[
            OpenApiParameter("date_from", OpenApiTypes.DATE, required=True),
            OpenApiParameter("date_to", OpenApiTypes.DATE, required=True),
            OpenApiParameter("department", OpenApiTypes.INT, description="Filter by department ID"),
            OpenApiParameter("metric", OpenApiTypes.STR, description="'units' (default) or 'margin'"),
            OpenApiParameter("limit", OpenApiTypes.INT, description="Top N results (default 20)"),
        ],
        responses={200: OpenApiResponse(description="Ranked list of best-selling variants")},
        tags=["Reporting"],
    )
    def get(self, request):
        serializer = BestSellersQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        department = _get_department(d.get("department"))
        data = services.get_best_sellers(
            date_from=d["date_from"], date_to=d["date_to"], department=department,
            metric=d["metric"], limit=d["limit"],
        )
        return _ok(data)


class WasteCostView(APIView):
    permission_classes = [IsDepartmentManager]

    @extend_schema(
        summary="Waste / markdown cost",
        description="Cost of waste and markdown stock movements, by department and by variant, plus a grand total.",
        parameters=[
            OpenApiParameter("date_from", OpenApiTypes.DATE, required=True),
            OpenApiParameter("date_to", OpenApiTypes.DATE, required=True),
            OpenApiParameter("department", OpenApiTypes.INT, description="Filter by department ID"),
        ],
        responses={200: OpenApiResponse(description="grand_total_pence, by_department, by_variant")},
        tags=["Reporting"],
    )
    def get(self, request):
        serializer = WasteCostQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        department = _get_department(d.get("department"))
        data = services.get_waste_cost(date_from=d["date_from"], date_to=d["date_to"], department=department)
        return _ok(data)


class StaffPerformanceView(APIView):
    permission_classes = [IsDepartmentManager]

    @extend_schema(
        summary="Staff performance",
        description="Per-staff total sales, transaction count, average basket and commission earned.",
        parameters=[
            OpenApiParameter("date_from", OpenApiTypes.DATE, required=True),
            OpenApiParameter("date_to", OpenApiTypes.DATE, required=True),
            OpenApiParameter("staff", OpenApiTypes.INT, description="Filter to a single staff ID"),
        ],
        responses={200: OpenApiResponse(description="List of per-staff performance rows")},
        tags=["Reporting"],
    )
    def get(self, request):
        serializer = StaffPerformanceQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        staff = None
        if d.get("staff"):
            from apps.staff.models import Staff
            staff = get_object_or_404(Staff, pk=d["staff"])

        data = services.get_staff_performance(date_from=d["date_from"], date_to=d["date_to"], staff=staff)
        return _ok(data)
