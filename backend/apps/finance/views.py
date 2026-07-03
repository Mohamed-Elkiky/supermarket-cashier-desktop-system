import logging

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsDepartmentManager
from apps.core.mixins import ActivityLogMixin
from apps.inventory.models import Supplier
from . import services
from .serializers import ExpenseSerializer, ExpenseSummaryQuerySerializer, ExpenseWriteSerializer

logger = logging.getLogger("apps.finance")


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


class ExpenseListCreateView(ActivityLogMixin, APIView):
    permission_classes = [IsDepartmentManager]

    @extend_schema(
        summary="List expenses",
        description="Filter with ?category=, ?date_from=, ?date_to=, ?supplier=.",
        parameters=[
            OpenApiParameter("category", OpenApiTypes.STR, description="Filter by expense category"),
            OpenApiParameter("date_from", OpenApiTypes.DATE, description="expense_date on/after (YYYY-MM-DD)"),
            OpenApiParameter("date_to", OpenApiTypes.DATE, description="expense_date on/before (YYYY-MM-DD)"),
            OpenApiParameter("supplier", OpenApiTypes.INT, description="Filter by supplier ID"),
        ],
        responses={200: ExpenseSerializer(many=True)},
        tags=["Finance"],
    )
    def get(self, request):
        supplier = None
        supplier_id = request.query_params.get("supplier")
        if supplier_id:
            supplier = get_object_or_404(Supplier, pk=supplier_id)

        expenses = services.get_expenses(
            category=request.query_params.get("category"),
            date_from=request.query_params.get("date_from"),
            date_to=request.query_params.get("date_to"),
            supplier=supplier,
        )
        return _ok(ExpenseSerializer(expenses, many=True).data)

    @extend_schema(
        summary="Record an expense",
        description=(
            "Permanent, append-only record — there is no edit or delete path. "
            "description must fully explain who/what/why/amount (minimum 20 characters)."
        ),
        request=ExpenseWriteSerializer,
        responses={201: ExpenseSerializer, 400: OpenApiResponse(description="Validation error")},
        tags=["Finance"],
    )
    def post(self, request):
        serializer = ExpenseWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        recorded_by = _current_staff(request)
        if recorded_by is None:
            return _error(["Authenticated user has no staff profile."])

        supplier = None
        if d.get("supplier_id"):
            supplier = get_object_or_404(Supplier, pk=d["supplier_id"])

        try:
            expense = services.record_expense(
                category=d["category"],
                description=d["description"],
                amount_pence=d["amount_pence"],
                recorded_by=recorded_by,
                expense_date=d["expense_date"],
                payee_name=d.get("payee_name", ""),
                supplier=supplier,
                reference=d.get("reference", ""),
            )
        except ValueError as exc:
            return _error([str(exc)])

        self.log(request, "expense.create", "expenses", expense.id,
                 after_state={"category": expense.category, "amount_pence": expense.amount_pence})
        return _created(ExpenseSerializer(expense).data)


class ExpenseSummaryView(APIView):
    permission_classes = [IsDepartmentManager]

    @extend_schema(
        summary="Expense summary by category",
        description="Total pence and count per category for a date range. Requires date_from/date_to.",
        parameters=[
            OpenApiParameter("date_from", OpenApiTypes.DATE, required=True),
            OpenApiParameter("date_to", OpenApiTypes.DATE, required=True),
        ],
        responses={200: OpenApiResponse(description="List of {category, total_pence, count}")},
        tags=["Finance"],
    )
    def get(self, request):
        serializer = ExpenseSummaryQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        data = services.get_expense_summary_by_category(date_from=d["date_from"], date_to=d["date_to"])
        return _ok(data)
