import logging

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsCashier, IsDepartmentManager
from apps.core.mixins import ActivityLogMixin
from . import services
from .models import Customer, LoyaltyAccount
from .serializers import (
    AdjustPointsWriteSerializer,
    BasketConflictCheckSerializer,
    CustomerSerializer,
    CustomerWriteSerializer,
    LoyaltyAccountSerializer,
    RedeemPointsWriteSerializer,
)

logger = logging.getLogger("apps.loyalty")


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


def _get_loyalty_account(customer_pk):
    customer = get_object_or_404(Customer, pk=customer_pk)
    account = get_object_or_404(
        LoyaltyAccount.objects.select_related("customer").prefetch_related("transactions"),
        customer=customer,
    )
    return customer, account


class CustomerListCreateView(ActivityLogMixin, APIView):
    permission_classes = [IsCashier]

    @extend_schema(
        summary="List customers",
        description="Filter with ?is_active= (default: all).",
        parameters=[OpenApiParameter("is_active", OpenApiTypes.BOOL, description="Filter by active status")],
        responses={200: CustomerSerializer(many=True)},
        tags=["Loyalty"],
    )
    def get(self, request):
        qs = Customer.objects.all()
        is_active = request.query_params.get("is_active")
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() in ("1", "true", "yes"))
        return _ok(CustomerSerializer(qs, many=True).data)

    @extend_schema(
        summary="Create customer",
        description="Registers a customer and auto-creates their LoyaltyAccount at bronze tier.",
        request=CustomerWriteSerializer,
        responses={201: CustomerSerializer, 400: OpenApiResponse(description="Validation error")},
        tags=["Loyalty"],
    )
    def post(self, request):
        serializer = CustomerWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            customer = services.create_customer(**serializer.validated_data)
        except ValueError as exc:
            return _error([str(exc)])

        self.log(request, "customer.create", "customers", customer.id,
                 after_state={"email": customer.email})
        return _created(CustomerSerializer(customer).data)


class CustomerDetailView(ActivityLogMixin, APIView):
    permission_classes = [IsCashier]

    @extend_schema(summary="Retrieve customer", responses={200: CustomerSerializer}, tags=["Loyalty"])
    def get(self, request, pk):
        return _ok(CustomerSerializer(get_object_or_404(Customer, pk=pk)).data)

    @extend_schema(
        summary="Update customer",
        request=CustomerWriteSerializer,
        responses={200: CustomerSerializer, 400: OpenApiResponse(description="Validation error")},
        tags=["Loyalty"],
    )
    def patch(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        before = {"email": customer.email, "is_active": customer.is_active}

        serializer = CustomerWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        try:
            customer = services.update_customer(customer, serializer.validated_data)
        except ValueError as exc:
            return _error([str(exc)])

        self.log(request, "customer.update", "customers", customer.id,
                 before_state=before, after_state={"is_active": customer.is_active})
        return _ok(CustomerSerializer(customer).data)


class CustomerSearchView(APIView):
    permission_classes = [IsCashier]

    @extend_schema(
        summary="Search customers",
        description=(
            "Search by email/phone (plaintext, indexed) or name "
            "(decrypted in Python — see services.search_customers)."
        ),
        parameters=[OpenApiParameter("q", OpenApiTypes.STR, required=True)],
        responses={200: CustomerSerializer(many=True)},
        tags=["Loyalty"],
    )
    def get(self, request):
        query = request.query_params.get("q", "")
        results = services.search_customers(query)
        return _ok(CustomerSerializer(results, many=True).data)


class LoyaltyProfileView(APIView):
    permission_classes = [IsCashier]

    @extend_schema(
        summary="Loyalty profile",
        description="Tier, points balance, lifetime spend and transaction history.",
        responses={200: LoyaltyAccountSerializer},
        tags=["Loyalty"],
    )
    def get(self, request, pk):
        _, account = _get_loyalty_account(pk)
        return _ok(LoyaltyAccountSerializer(account).data)


class RedeemPointsView(ActivityLogMixin, APIView):
    permission_classes = [IsCashier]

    @extend_schema(
        summary="Redeem loyalty points",
        request=RedeemPointsWriteSerializer,
        responses={201: LoyaltyAccountSerializer, 400: OpenApiResponse(description="Validation error")},
        tags=["Loyalty"],
    )
    def post(self, request, pk):
        _, account = _get_loyalty_account(pk)
        serializer = RedeemPointsWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        points = serializer.validated_data["points"]

        try:
            services.redeem_points(loyalty_account=account, points=points)
        except ValueError as exc:
            return _error([str(exc)])

        account.refresh_from_db()
        self.log(request, "loyalty.points.redeem", "loyalty_accounts", account.id,
                 after_state={"points": points})
        return _created(LoyaltyAccountSerializer(account).data)


class AdjustPointsView(ActivityLogMixin, APIView):
    permission_classes = [IsDepartmentManager]

    @extend_schema(
        summary="Manually adjust loyalty points",
        description="Manager-only correction/goodwill adjustment. reason is mandatory.",
        request=AdjustPointsWriteSerializer,
        responses={201: LoyaltyAccountSerializer, 400: OpenApiResponse(description="Validation error")},
        tags=["Loyalty"],
    )
    def post(self, request, pk):
        _, account = _get_loyalty_account(pk)
        serializer = AdjustPointsWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        performed_by = _current_staff(request)
        try:
            services.adjust_points(
                loyalty_account=account, points=d["points"],
                reason=d["reason"], performed_by=performed_by,
            )
        except ValueError as exc:
            return _error([str(exc)])

        account.refresh_from_db()
        self.log(request, "loyalty.points.adjust", "loyalty_accounts", account.id,
                 after_state={"points": d["points"], "reason": d["reason"]})
        return _created(LoyaltyAccountSerializer(account).data)


class BasketConflictCheckView(APIView):
    permission_classes = [IsCashier]

    @extend_schema(
        summary="Basket allergen conflict check",
        description="Cross-references the customer's allergen_preferences against the basket's variants.",
        request=BasketConflictCheckSerializer,
        responses={200: OpenApiResponse(description="conflicts list and has_conflicts flag")},
        tags=["Loyalty"],
    )
    def post(self, request):
        serializer = BasketConflictCheckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        customer = get_object_or_404(Customer, pk=d["customer_id"])
        conflicts = services.check_basket_allergen_conflicts(
            customer=customer, basket_variant_ids=d["variant_ids"],
        )
        return _ok({"conflicts": conflicts, "has_conflicts": len(conflicts) > 0})
