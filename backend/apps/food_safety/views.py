import logging

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsCashier, IsDepartmentManager
from apps.core.mixins import ActivityLogMixin
from apps.departments.models import Department
from . import services
from .models import CleaningLog, TemperatureLog
from .serializers import (
    CleaningLogSerializer,
    CleaningSignoffWriteSerializer,
    EhoExportQuerySerializer,
    MissedChecksQuerySerializer,
    TemperatureCheckWriteSerializer,
    TemperatureLogSerializer,
)

logger = logging.getLogger("apps.food_safety")


def _ok(data, status_code=status.HTTP_200_OK):
    return Response({"success": True, "data": data}, status=status_code)


def _created(data):
    return _ok(data, status.HTTP_201_CREATED)


def _error(errors, status_code=status.HTTP_400_BAD_REQUEST, code="ValidationError"):
    return Response({"success": False, "error": {"code": code, "errors": errors}}, status=status_code)


def _current_staff(request):
    try:
        return request.user.staff_profile
    except Exception:
        return None


class TemperatureLogListCreateView(ActivityLogMixin, APIView):
    permission_classes = [IsCashier]

    @extend_schema(
        summary="List temperature checks",
        description="Filter with ?department, ?result (pass/fail), ?from, ?to (YYYY-MM-DD, matched against checked_at).",
        parameters=[
            OpenApiParameter("department", OpenApiTypes.INT, description="Filter by department ID"),
            OpenApiParameter("result", OpenApiTypes.STR, description="Filter by result (pass/fail)"),
            OpenApiParameter("from", OpenApiTypes.DATE, description="checked_at on/after (YYYY-MM-DD)"),
            OpenApiParameter("to", OpenApiTypes.DATE, description="checked_at on/before (YYYY-MM-DD)"),
        ],
        responses={200: TemperatureLogSerializer(many=True)},
        tags=["Food Safety"],
    )
    def get(self, request):
        qs = TemperatureLog.objects.select_related("department", "performed_by")
        if dept := request.query_params.get("department"):
            qs = qs.filter(department_id=dept)
        if result := request.query_params.get("result"):
            qs = qs.filter(result=result)
        if f := request.query_params.get("from"):
            qs = qs.filter(checked_at__date__gte=f)
        if t := request.query_params.get("to"):
            qs = qs.filter(checked_at__date__lte=t)
        return _ok(TemperatureLogSerializer(qs, many=True).data)

    @extend_schema(
        summary="Log a temperature check",
        description=(
            "Any cashier can log a check at POS. Pass/fail is determined against the "
            "department's configured thresholds — a fail requires corrective_action."
        ),
        request=TemperatureCheckWriteSerializer,
        responses={201: TemperatureLogSerializer, 400: OpenApiResponse(description="Validation error")},
        tags=["Food Safety"],
    )
    def post(self, request):
        serializer = TemperatureCheckWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        department = get_object_or_404(Department, pk=d["department_id"])
        performed_by = _current_staff(request)
        if performed_by is None:
            return _error(["Authenticated user has no staff profile."])

        try:
            log = services.record_temperature_check(
                unit_name=d["unit_name"],
                department=department,
                temperature_celsius=d["temperature_celsius"],
                performed_by=performed_by,
                checked_at=d.get("checked_at"),
                was_offline=d.get("was_offline", False),
                corrective_action=d.get("corrective_action"),
            )
        except ValueError as exc:
            return _error([str(exc)])

        self.log(request, "food_safety.temperature_check.create", "food_safety_temperature_logs", log.id,
                 after_state={"unit_name": log.unit_name, "result": log.result, "department": department.name})
        return _created(TemperatureLogSerializer(log).data)


class CleaningLogListCreateView(ActivityLogMixin, APIView):
    permission_classes = [IsCashier]

    @extend_schema(
        summary="List cleaning sign-offs",
        description="Filter with ?department, ?result (completed/missed/partial), ?from, ?to (matched against cleaned_at).",
        parameters=[
            OpenApiParameter("department", OpenApiTypes.INT, description="Filter by department ID"),
            OpenApiParameter("result", OpenApiTypes.STR, description="Filter by result (completed/missed/partial)"),
            OpenApiParameter("from", OpenApiTypes.DATE, description="cleaned_at on/after (YYYY-MM-DD)"),
            OpenApiParameter("to", OpenApiTypes.DATE, description="cleaned_at on/before (YYYY-MM-DD)"),
        ],
        responses={200: CleaningLogSerializer(many=True)},
        tags=["Food Safety"],
    )
    def get(self, request):
        qs = CleaningLog.objects.select_related("department", "performed_by", "alerted_manager")
        if dept := request.query_params.get("department"):
            qs = qs.filter(department_id=dept)
        if result := request.query_params.get("result"):
            qs = qs.filter(result=result)
        if f := request.query_params.get("from"):
            qs = qs.filter(cleaned_at__date__gte=f)
        if t := request.query_params.get("to"):
            qs = qs.filter(cleaned_at__date__lte=t)
        return _ok(CleaningLogSerializer(qs, many=True).data)

    @extend_schema(
        summary="Log a cleaning sign-off",
        description=(
            "Any cashier can log a sign-off at POS. A 'missed' result auto-resolves "
            "alerted_manager to the department's store_manager (falling back to any admin)."
        ),
        request=CleaningSignoffWriteSerializer,
        responses={201: CleaningLogSerializer, 400: OpenApiResponse(description="Validation error")},
        tags=["Food Safety"],
    )
    def post(self, request):
        serializer = CleaningSignoffWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        department = get_object_or_404(Department, pk=d["department_id"])
        performed_by = _current_staff(request)

        try:
            log = services.record_cleaning_signoff(
                area_name=d["area_name"],
                department=department,
                scheduled_interval_hours=d.get("scheduled_interval_hours", 4),
                result=d["result"],
                performed_by=performed_by,
                notes=d.get("notes", ""),
                cleaned_at=d.get("cleaned_at"),
                was_offline=d.get("was_offline", False),
            )
        except ValueError as exc:
            return _error([str(exc)])

        self.log(request, "food_safety.cleaning_log.create", "food_safety_cleaning_logs", log.id,
                 after_state={"area_name": log.area_name, "result": log.result, "department": department.name})
        return _created(CleaningLogSerializer(log).data)


class MissedChecksView(APIView):
    permission_classes = [IsDepartmentManager]

    @extend_schema(
        summary="Missed checks dashboard",
        description="Missed cleanings and failed temperature checks, for manager dashboards/notifications.",
        parameters=[
            OpenApiParameter("department", OpenApiTypes.INT, description="Filter by department ID"),
            OpenApiParameter("since", OpenApiTypes.DATETIME, description="Only include events on/after this timestamp"),
        ],
        responses={200: OpenApiResponse(description="missed_cleanings and failed_temperature_checks lists")},
        tags=["Food Safety"],
    )
    def get(self, request):
        serializer = MissedChecksQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        department = None
        if d.get("department"):
            department = get_object_or_404(Department, pk=d["department"])

        data = services.get_missed_checks(department=department, since=d.get("since"))
        return _ok(data)


class EhoExportView(APIView):
    permission_classes = [IsDepartmentManager]

    @extend_schema(
        summary="EHO compliance export",
        description="Flat export of temperature and cleaning logs for Environmental Health Officer inspection.",
        parameters=[
            OpenApiParameter("date_from", OpenApiTypes.DATE, required=True),
            OpenApiParameter("date_to", OpenApiTypes.DATE, required=True),
            OpenApiParameter("department", OpenApiTypes.INT, description="Filter by department ID"),
        ],
        responses={200: OpenApiResponse(description="temperature_logs and cleaning_logs lists")},
        tags=["Food Safety"],
    )
    def get(self, request):
        serializer = EhoExportQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        department = None
        if d.get("department"):
            department = get_object_or_404(Department, pk=d["department"])

        data = services.build_eho_export(
            date_from=d["date_from"], date_to=d["date_to"], department=department
        )
        return _ok(data)
