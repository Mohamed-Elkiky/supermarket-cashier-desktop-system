import logging

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, OpenApiResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsCashier, IsDepartmentManager
from apps.core.mixins import ActivityLogMixin
from . import services
from .models import Order
from .serializers import (
    AddItemSerializer,
    CheckoutSerializer,
    OrderSerializer,
    VoidSerializer,
)

logger = logging.getLogger("apps.pos")


def _ok(data, status_code=status.HTTP_200_OK):
    return Response({"success": True, "data": data}, status=status_code)


def _created(data):
    return _ok(data, status.HTTP_201_CREATED)


def _get_order(pk):
    return get_object_or_404(
        Order.objects.prefetch_related(
            "items__variant__product__department",
            "items__promotion",
        ).select_related("cashier"),
        pk=pk,
    )


class OrderCreateView(ActivityLogMixin, APIView):
    permission_classes = [IsCashier]

    @extend_schema(
        summary="Open a new order",
        description="Creates an empty basket assigned to the requesting cashier.",
        responses={201: OrderSerializer},
        tags=["POS"],
    )
    def post(self, request):
        performed_by = None
        try:
            performed_by = request.user.staff_profile
        except Exception:
            pass

        order = services.create_order(cashier=performed_by)
        self.log(request, "order.create", "orders", order.id,
                 after_state={"cashier": getattr(performed_by, "id", None)})
        return _created(OrderSerializer(order).data)


class OrderDetailView(APIView):
    permission_classes = [IsCashier]

    @extend_schema(
        summary="Retrieve order",
        responses={200: OrderSerializer},
        tags=["POS"],
    )
    def get(self, request, pk):
        return _ok(OrderSerializer(_get_order(pk)).data)


class OrderAddItemView(ActivityLogMixin, APIView):
    permission_classes = [IsCashier]

    @extend_schema(
        summary="Add item to basket",
        description=(
            "Adds a variant to an open order. "
            "Blocks expired items. "
            "Supply weight_kg for weight-based variants."
        ),
        request=AddItemSerializer,
        responses={200: OrderSerializer, 400: OpenApiResponse(description="Validation error")},
        tags=["POS"],
    )
    def post(self, request, pk):
        order = _get_order(pk)
        serializer = AddItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            services.add_item(
                order=order,
                variant_id=d["variant_id"],
                quantity=d.get("quantity", 1),
                weight_kg=d.get("weight_kg"),
            )
        except Exception as exc:
            return Response(
                {"success": False, "error": {"code": "ValidationError", "errors": [str(exc)]}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        order = _get_order(pk)
        self.log(request, "order.item.add", "orders", order.id,
                 after_state={"variant_id": d["variant_id"], "quantity": d.get("quantity", 1)})
        return _ok(OrderSerializer(order).data)


class OrderRemoveItemView(ActivityLogMixin, APIView):
    permission_classes = [IsCashier]

    @extend_schema(
        summary="Remove item from basket",
        responses={200: OrderSerializer},
        tags=["POS"],
    )
    def delete(self, request, pk, item_pk):
        order = _get_order(pk)
        try:
            services.remove_item(order=order, item_id=item_pk)
        except ValueError as exc:
            return Response(
                {"success": False, "error": {"code": "ValidationError", "errors": [str(exc)]}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        order = _get_order(pk)
        self.log(request, "order.item.remove", "orders", order.id,
                 after_state={"item_id": item_pk})
        return _ok(OrderSerializer(order).data)


class OrderConfirmView(ActivityLogMixin, APIView):
    permission_classes = [IsCashier]

    @extend_schema(
        summary="Confirm order",
        description=(
            "Locks the basket, applies promotions, calculates final totals. "
            "Moves order from 'open' to 'confirmed'."
        ),
        responses={200: OrderSerializer, 400: OpenApiResponse(description="Validation error")},
        tags=["POS"],
    )
    def post(self, request, pk):
        order = _get_order(pk)
        try:
            order = services.confirm_order(order=order)
        except ValueError as exc:
            return Response(
                {"success": False, "error": {"code": "ValidationError", "errors": [str(exc)]}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        order = _get_order(pk)
        self.log(request, "order.confirm", "orders", order.id,
                 after_state={"total_pence": order.total_pence})
        return _ok(OrderSerializer(order).data)


class OrderCheckoutView(ActivityLogMixin, APIView):
    permission_classes = [IsCashier]

    @extend_schema(
        summary="Checkout — take payment and deduct stock",
        description=(
            "Completes payment and deducts stock in a single atomic transaction. "
            "Order must be in 'confirmed' status. "
            "Returns the paid order with receipt number."
        ),
        request=CheckoutSerializer,
        responses={200: OrderSerializer, 400: OpenApiResponse(description="Validation error")},
        tags=["POS"],
    )
    def post(self, request, pk):
        order = _get_order(pk)
        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            order = services.checkout(
                order=order,
                payment_method=d["payment_method"],
                cash_tendered_pence=d.get("cash_tendered_pence"),
                age_verified=d.get("age_verified", False),
                age_verification_id_type=d.get("age_verification_id_type", ""),
            )
        except ValueError as exc:
            return Response(
                {"success": False, "error": {"code": "ValidationError", "errors": [str(exc)]}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        order = _get_order(pk)
        self.log(request, "order.checkout", "orders", order.id,
                 after_state={
                     "total_pence": order.total_pence,
                     "payment_method": order.payment_method,
                     "receipt_number": order.receipt_number,
                 })
        return _ok(OrderSerializer(order).data)


class OrderReceiptView(APIView):
    permission_classes = [IsCashier]

    @extend_schema(
        summary="Get receipt",
        description="Returns structured receipt data for a paid order.",
        responses={200: OpenApiResponse(description="Receipt data")},
        tags=["POS"],
    )
    def get(self, request, pk):
        order = _get_order(pk)
        try:
            receipt = services.build_receipt(order)
        except ValueError as exc:
            return Response(
                {"success": False, "error": {"code": "ValidationError", "errors": [str(exc)]}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return _ok(receipt)


class OrderVoidView(ActivityLogMixin, APIView):
    permission_classes = [IsDepartmentManager]

    @extend_schema(
        summary="Void order",
        description="Cancels an open or confirmed order. Paid orders require a return instead.",
        request=VoidSerializer,
        responses={200: OrderSerializer, 400: OpenApiResponse(description="Cannot void")},
        tags=["POS"],
    )
    def post(self, request, pk):
        order = _get_order(pk)
        serializer = VoidSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            order = services.void_order(order=order, reason=serializer.validated_data.get("reason", ""))
        except ValueError as exc:
            return Response(
                {"success": False, "error": {"code": "ValidationError", "errors": [str(exc)]}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        order = _get_order(pk)
        self.log(request, "order.void", "orders", order.id,
                 after_state={"reason": serializer.validated_data.get("reason", "")})
        return _ok(OrderSerializer(order).data)