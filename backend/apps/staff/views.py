import logging

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsCashier, IsDepartmentManager, IsStoreManager
from apps.core.mixins import ActivityLogMixin
from . import services
from .models import Rota, Staff
from .serializers import (
    ClockEventSerializer,
    ClockInOutWriteSerializer,
    PayrollExportQuerySerializer,
    RotaSerializer,
    RotaWeekQuerySerializer,
    RotaWriteSerializer,
    StaffSerializer,
    StaffWriteSerializer,
)

logger = logging.getLogger("apps.staff")


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


def _get_department(department_id):
    if not department_id:
        return None
    from apps.departments.models import Department
    return get_object_or_404(Department, pk=department_id)


# ── Staff CRUD ────────────────────────────────────────────────────────────────

class StaffListCreateView(ActivityLogMixin, APIView):
    permission_classes = [IsStoreManager]

    @extend_schema(
        summary="List staff",
        description="Filter with ?is_active=, ?role=, ?department=.",
        parameters=[
            OpenApiParameter("is_active", OpenApiTypes.BOOL, description="Filter by active status"),
            OpenApiParameter("role", OpenApiTypes.STR, description="Filter by role"),
            OpenApiParameter("department", OpenApiTypes.INT, description="Filter by department ID"),
        ],
        responses={200: StaffSerializer(many=True)},
        tags=["Staff"],
    )
    def get(self, request):
        qs = Staff.objects.select_related("department")
        is_active = request.query_params.get("is_active")
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() in ("1", "true", "yes"))
        if role := request.query_params.get("role"):
            qs = qs.filter(role=role)
        if dept := request.query_params.get("department"):
            qs = qs.filter(department_id=dept)
        return _ok(StaffSerializer(qs, many=True).data)

    @extend_schema(
        summary="Create staff member",
        request=StaffWriteSerializer,
        responses={201: StaffSerializer, 400: OpenApiResponse(description="Validation error")},
        tags=["Staff"],
    )
    def post(self, request):
        serializer = StaffWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        department = _get_department(d.get("department_id"))
        staff = services.create_staff(
            first_name=d["first_name"], last_name=d["last_name"], email=d["email"],
            phone=d.get("phone", ""), role=d.get("role", "cashier"), department=department,
            commission_rate=d.get("commission_rate"), hourly_wage=d.get("hourly_wage"),
            hired_at=d.get("hired_at"),
        )
        self.log(request, "staff.create", "staff", staff.id,
                 after_state={"email": staff.email, "role": staff.role})
        return _created(StaffSerializer(staff).data)


class StaffDetailView(ActivityLogMixin, APIView):
    permission_classes = [IsStoreManager]

    @extend_schema(summary="Retrieve staff member", responses={200: StaffSerializer}, tags=["Staff"])
    def get(self, request, pk):
        return _ok(StaffSerializer(get_object_or_404(Staff, pk=pk)).data)

    @extend_schema(
        summary="Update staff member",
        request=StaffWriteSerializer,
        responses={200: StaffSerializer, 400: OpenApiResponse(description="Validation error")},
        tags=["Staff"],
    )
    def patch(self, request, pk):
        staff = get_object_or_404(Staff, pk=pk)
        before = {"role": staff.role, "is_active": staff.is_active}

        serializer = StaffWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        d = dict(serializer.validated_data)
        if "department_id" in d:
            d["department"] = _get_department(d.pop("department_id"))

        staff = services.update_staff(staff, d)
        self.log(request, "staff.update", "staff", staff.id,
                 before_state=before, after_state={"role": staff.role, "is_active": staff.is_active})
        return _ok(StaffSerializer(staff).data)


# ── Clock events ──────────────────────────────────────────────────────────────

class ClockInView(ActivityLogMixin, APIView):
    permission_classes = [IsCashier]

    @extend_schema(
        summary="Clock in",
        description="Clocks in the authenticated staff member — you can only clock yourself in.",
        request=ClockInOutWriteSerializer,
        responses={201: ClockEventSerializer, 400: OpenApiResponse(description="Validation error")},
        tags=["Staff"],
    )
    def post(self, request):
        serializer = ClockInOutWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        staff = _current_staff(request)

        try:
            event = services.clock_in(staff=staff, was_offline=serializer.validated_data["was_offline"])
        except ValueError as exc:
            return _error([str(exc)])

        self.log(request, "staff.clock_in", "staff_clock_events", event.id, after_state={"staff_id": staff.id})
        return _created(ClockEventSerializer(event).data)


class ClockOutView(ActivityLogMixin, APIView):
    permission_classes = [IsCashier]

    @extend_schema(
        summary="Clock out",
        description="Clocks out the authenticated staff member — you can only clock yourself out.",
        request=ClockInOutWriteSerializer,
        responses={201: ClockEventSerializer, 400: OpenApiResponse(description="Validation error")},
        tags=["Staff"],
    )
    def post(self, request):
        serializer = ClockInOutWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        staff = _current_staff(request)

        try:
            event = services.clock_out(staff=staff, was_offline=serializer.validated_data["was_offline"])
        except ValueError as exc:
            return _error([str(exc)])

        self.log(request, "staff.clock_out", "staff_clock_events", event.id, after_state={"staff_id": staff.id})
        return _created(ClockEventSerializer(event).data)


class ClockStatusView(APIView):
    permission_classes = [IsCashier]

    @extend_schema(
        summary="Current clock status",
        description="clocked_in / clocked_out for the authenticated staff member.",
        responses={200: OpenApiResponse(description="{'status': 'clocked_in' | 'clocked_out'}")},
        tags=["Staff"],
    )
    def get(self, request):
        staff = _current_staff(request)
        return _ok({"status": services.get_current_clock_status(staff)})


# ── Rota CRUD ─────────────────────────────────────────────────────────────────

class RotaListCreateView(ActivityLogMixin, APIView):
    permission_classes = [IsDepartmentManager]

    @extend_schema(
        summary="List rota entries",
        description="Filter with ?staff=, ?department=, ?week_commencing=.",
        parameters=[
            OpenApiParameter("staff", OpenApiTypes.INT, description="Filter by staff ID"),
            OpenApiParameter("department", OpenApiTypes.INT, description="Filter by department ID"),
            OpenApiParameter("week_commencing", OpenApiTypes.DATE, description="Filter by week (YYYY-MM-DD, must be a Monday)"),
        ],
        responses={200: RotaSerializer(many=True)},
        tags=["Staff"],
    )
    def get(self, request):
        qs = Rota.objects.select_related("staff", "department")
        if staff_id := request.query_params.get("staff"):
            qs = qs.filter(staff_id=staff_id)
        if dept := request.query_params.get("department"):
            qs = qs.filter(department_id=dept)
        if week := request.query_params.get("week_commencing"):
            qs = qs.filter(week_commencing=week)
        return _ok(RotaSerializer(qs, many=True).data)

    @extend_schema(
        summary="Create rota entry",
        request=RotaWriteSerializer,
        responses={201: RotaSerializer, 400: OpenApiResponse(description="Validation error")},
        tags=["Staff"],
    )
    def post(self, request):
        serializer = RotaWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        staff = get_object_or_404(Staff, pk=d["staff_id"])
        department = _get_department(d.get("department_id"))
        created_by = _current_staff(request)

        try:
            rota = services.create_rota_entry(
                staff=staff, department=department,
                week_commencing=d["week_commencing"], shift_date=d["shift_date"],
                shift_start=d["shift_start"], shift_end=d["shift_end"],
                notes=d.get("notes", ""), created_by=created_by,
            )
        except ValueError as exc:
            return _error([str(exc)])

        self.log(request, "rota.create", "rotas", rota.id,
                 after_state={"staff_id": staff.id, "shift_date": str(rota.shift_date)})
        return _created(RotaSerializer(rota).data)


class RotaDetailView(ActivityLogMixin, APIView):
    permission_classes = [IsDepartmentManager]

    @extend_schema(summary="Retrieve rota entry", responses={200: RotaSerializer}, tags=["Staff"])
    def get(self, request, pk):
        return _ok(RotaSerializer(get_object_or_404(Rota, pk=pk)).data)

    @extend_schema(
        summary="Update rota entry",
        request=RotaWriteSerializer,
        responses={200: RotaSerializer, 400: OpenApiResponse(description="Validation error")},
        tags=["Staff"],
    )
    def patch(self, request, pk):
        rota = get_object_or_404(Rota, pk=pk)
        before = {"shift_date": str(rota.shift_date), "shift_start": str(rota.shift_start), "shift_end": str(rota.shift_end)}

        serializer = RotaWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        d = dict(serializer.validated_data)
        if "staff_id" in d:
            d["staff"] = get_object_or_404(Staff, pk=d.pop("staff_id"))
        if "department_id" in d:
            d["department"] = _get_department(d.pop("department_id"))

        try:
            rota = services.update_rota_entry(rota, d)
        except ValueError as exc:
            return _error([str(exc)])

        self.log(request, "rota.update", "rotas", rota.id, before_state=before,
                 after_state={"shift_date": str(rota.shift_date), "shift_start": str(rota.shift_start), "shift_end": str(rota.shift_end)})
        return _ok(RotaSerializer(rota).data)

    @extend_schema(summary="Delete rota entry", responses={200: OpenApiResponse(description="Deleted")}, tags=["Staff"])
    def delete(self, request, pk):
        rota = get_object_or_404(Rota, pk=pk)
        before = {"staff_id": rota.staff_id, "shift_date": str(rota.shift_date)}
        services.delete_rota_entry(rota)
        self.log(request, "rota.delete", "rotas", pk, before_state=before)
        return _ok({"message": "Rota entry deleted."})


class RotaWeekView(APIView):
    permission_classes = [IsDepartmentManager]

    @extend_schema(
        summary="Weekly rota grid",
        parameters=[
            OpenApiParameter("week_commencing", OpenApiTypes.DATE, required=True),
            OpenApiParameter("department", OpenApiTypes.INT, description="Filter by department ID"),
        ],
        responses={200: RotaSerializer(many=True)},
        tags=["Staff"],
    )
    def get(self, request):
        serializer = RotaWeekQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        department = _get_department(d.get("department"))
        rows = services.get_rota_for_week(week_commencing=d["week_commencing"], department=department)
        return _ok(RotaSerializer(rows, many=True).data)


# ── Payroll ───────────────────────────────────────────────────────────────────

class PayrollExportView(APIView):
    permission_classes = [IsStoreManager]

    @extend_schema(
        summary="Payroll export",
        description="Per-staff hours worked, wages, commission and total for a date range.",
        parameters=[
            OpenApiParameter("date_from", OpenApiTypes.DATE, required=True),
            OpenApiParameter("date_to", OpenApiTypes.DATE, required=True),
            OpenApiParameter("department", OpenApiTypes.INT, description="Filter by department ID"),
        ],
        responses={200: OpenApiResponse(description="Flat list of per-staff payroll rows")},
        tags=["Staff"],
    )
    def get(self, request):
        serializer = PayrollExportQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        department = _get_department(d.get("department"))
        data = services.build_payroll_export(date_from=d["date_from"], date_to=d["date_to"], department=department)
        return _ok(data)
