import logging
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsCashier, IsDepartmentManager, IsStoreManager
from apps.core.mixins import ActivityLogMixin

from . import services
from .models import Department, DepartmentCategory
from .serializers import (
    DepartmentCategorySerializer, DepartmentCategoryWriteSerializer,
    DepartmentDetailSerializer, DepartmentListSerializer,
    DepartmentPricingRuleSerializer, DepartmentStockSettingsSerializer,
    DepartmentWriteSerializer, PriceInputSerializer, SuggestedPriceSerializer,
)

logger = logging.getLogger("apps.departments")


def _ok(data, status_code=status.HTTP_200_OK):
    return Response({"success": True, "data": data}, status=status_code)


def _created(data):
    return _ok(data, status.HTTP_201_CREATED)


def _active_category_filter():
    return Q(categories__is_active=True)


class DepartmentListCreateView(ActivityLogMixin, APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsStoreManager()]
        return [IsCashier()]

    @extend_schema(summary="List departments", responses={200: DepartmentListSerializer(many=True)}, tags=["Departments"])
    def get(self, request):
        departments = Department.objects.annotate(category_count=Count("categories", filter=_active_category_filter())).order_by("display_order", "name")
        return _ok(DepartmentListSerializer(departments, many=True).data)

    @extend_schema(summary="Create a custom department", request=DepartmentWriteSerializer, responses={201: DepartmentDetailSerializer}, tags=["Departments"])
    def post(self, request):
        serializer = DepartmentWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        try:
            dept = services.create_department(name=d["name"], tax_rate=d.get("tax_rate", 0), display_order=d.get("display_order", 0))
        except ValueError as e:
            return Response({"success": False, "error": {"code": "ValidationError", "errors": [str(e)]}}, status=status.HTTP_400_BAD_REQUEST)
        self.log(request, "department.create", "departments", dept.id, after_state={"name": dept.name, "slug": dept.slug})
        dept = Department.objects.annotate(category_count=Count("categories", filter=_active_category_filter())).get(pk=dept.pk)
        return _created(DepartmentDetailSerializer(dept).data)


class DepartmentDetailView(ActivityLogMixin, APIView):
    def get_permissions(self):
        if self.request.method in ("PATCH", "PUT"):
            return [IsStoreManager()]
        return [IsCashier()]

    @extend_schema(summary="Retrieve department", responses={200: DepartmentDetailSerializer}, tags=["Departments"])
    def get(self, request, pk):
        dept = get_object_or_404(Department, pk=pk)
        return _ok(DepartmentDetailSerializer(dept).data)

    @extend_schema(summary="Update department", request=DepartmentWriteSerializer, responses={200: DepartmentDetailSerializer}, tags=["Departments"])
    def patch(self, request, pk):
        dept = get_object_or_404(Department, pk=pk)
        before = {"name": dept.name, "tax_rate": str(dept.tax_rate), "is_active": dept.is_active}
        serializer = DepartmentWriteSerializer(dept, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        dept = services.update_department(dept, serializer.validated_data)
        self.log(request, "department.update", "departments", dept.id, before_state=before, after_state=serializer.validated_data)
        return _ok(DepartmentDetailSerializer(dept).data)


class DepartmentPricingRuleView(ActivityLogMixin, APIView):
    def get_permissions(self):
        if self.request.method in ("PATCH", "PUT"):
            return [IsStoreManager()]
        return [IsCashier()]

    @extend_schema(summary="Retrieve pricing rule", responses={200: DepartmentPricingRuleSerializer}, tags=["Departments"])
    def get(self, request, pk):
        dept = get_object_or_404(Department, pk=pk)
        return _ok(DepartmentPricingRuleSerializer(dept.pricing_rule).data)

    @extend_schema(summary="Update pricing rule", request=DepartmentPricingRuleSerializer, responses={200: DepartmentPricingRuleSerializer}, tags=["Departments"])
    def patch(self, request, pk):
        dept = get_object_or_404(Department, pk=pk)
        rule = dept.pricing_rule
        before = DepartmentPricingRuleSerializer(rule).data
        serializer = DepartmentPricingRuleSerializer(rule, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        rule = services.update_pricing_rule(rule, serializer.validated_data)
        self.log(request, "department.pricing_rule.update", "department_pricing_rules", rule.id, before_state=dict(before), after_state=serializer.validated_data)
        return _ok(DepartmentPricingRuleSerializer(rule).data)


class DepartmentStockSettingsView(ActivityLogMixin, APIView):
    def get_permissions(self):
        if self.request.method in ("PATCH", "PUT"):
            return [IsStoreManager()]
        return [IsCashier()]

    @extend_schema(summary="Retrieve stock settings", responses={200: DepartmentStockSettingsSerializer}, tags=["Departments"])
    def get(self, request, pk):
        dept = get_object_or_404(Department, pk=pk)
        return _ok(DepartmentStockSettingsSerializer(dept.stock_settings).data)

    @extend_schema(summary="Update stock settings", request=DepartmentStockSettingsSerializer, responses={200: DepartmentStockSettingsSerializer}, tags=["Departments"])
    def patch(self, request, pk):
        dept = get_object_or_404(Department, pk=pk)
        settings = dept.stock_settings
        before = DepartmentStockSettingsSerializer(settings).data
        serializer = DepartmentStockSettingsSerializer(settings, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        settings = services.update_stock_settings(settings, serializer.validated_data)
        self.log(request, "department.stock_settings.update", "department_stock_settings", settings.id, before_state=dict(before), after_state=serializer.validated_data)
        return _ok(DepartmentStockSettingsSerializer(settings).data)


class DepartmentCategoryListCreateView(ActivityLogMixin, APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsDepartmentManager()]
        return [IsCashier()]

    @extend_schema(summary="List category tree", responses={200: DepartmentCategorySerializer(many=True)}, tags=["Departments"])
    def get(self, request, pk):
        dept = get_object_or_404(Department, pk=pk)
        return _ok(services.get_category_tree(dept))

    @extend_schema(summary="Create category", request=DepartmentCategoryWriteSerializer, responses={201: DepartmentCategorySerializer}, tags=["Departments"])
    def post(self, request, pk):
        dept = get_object_or_404(Department, pk=pk)
        serializer = DepartmentCategoryWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        try:
            category = services.create_category(department=dept, name=d["name"], parent_id=d.get("parent_id"), display_order=d.get("display_order", 0))
        except ValueError as e:
            return Response({"success": False, "error": {"code": "ValidationError", "errors": [str(e)]}}, status=status.HTTP_400_BAD_REQUEST)
        self.log(request, "department.category.create", "department_categories", category.id, after_state={"name": category.name, "department": dept.name})
        return _created(DepartmentCategorySerializer(category).data)


class DepartmentCategoryDetailView(ActivityLogMixin, APIView):
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsCashier()]
        return [IsDepartmentManager()]

    def _get_category(self, dept_pk, cat_pk):
        dept = get_object_or_404(Department, pk=dept_pk)
        return dept, get_object_or_404(DepartmentCategory, pk=cat_pk, department=dept)

    @extend_schema(summary="Retrieve category", responses={200: DepartmentCategorySerializer}, tags=["Departments"])
    def get(self, request, pk, cat_pk):
        _, category = self._get_category(pk, cat_pk)
        return _ok(DepartmentCategorySerializer(category).data)

    @extend_schema(summary="Update category", request=DepartmentCategoryWriteSerializer, responses={200: DepartmentCategorySerializer}, tags=["Departments"])
    def patch(self, request, pk, cat_pk):
        _, category = self._get_category(pk, cat_pk)
        before = {"name": category.name, "is_active": category.is_active}
        serializer = DepartmentCategoryWriteSerializer(category, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        category = services.update_category(category, serializer.validated_data)
        self.log(request, "department.category.update", "department_categories", category.id, before_state=before, after_state=serializer.validated_data)
        return _ok(DepartmentCategorySerializer(category).data)

    @extend_schema(summary="Deactivate category", responses={200: OpenApiResponse(description="Category deactivated")}, tags=["Departments"])
    def delete(self, request, pk, cat_pk):
        _, category = self._get_category(pk, cat_pk)
        services.delete_category(category)
        self.log(request, "department.category.deactivate", "department_categories", cat_pk, before_state={"name": category.name, "is_active": True})
        return _ok({"message": f"Category '{category.name}' has been deactivated."})


class DepartmentPriceSuggestionView(APIView):
    permission_classes = [IsCashier]

    @extend_schema(summary="Suggest sell price", request=PriceInputSerializer, responses={200: SuggestedPriceSerializer}, tags=["Departments"])
    def post(self, request, pk):
        dept = get_object_or_404(Department, pk=pk)
        rule = dept.pricing_rule
        serializer = PriceInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cost_pence = serializer.validated_data["cost_price_pence"]
        try:
            sell_pence = services.calculate_sell_price(cost_pence, rule)
        except ValueError as e:
            return Response({"success": False, "error": {"code": "ValidationError", "errors": [str(e)]}}, status=status.HTTP_400_BAD_REQUEST)
        return _ok({"cost_price_pence": cost_pence, "suggested_sell_price_pence": sell_pence, "suggested_sell_price_display": f"£{sell_pence / 100:.2f}", "markup_percent": str(rule.default_markup_percent), "rounding_strategy": rule.rounding_strategy})