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
from .models import Allergen, InventoryLedger, LedgerLocation, Product, ProductVariant
from .serializers import (
    AllergenSerializer,
    AllergenWriteSerializer,
    BasketExpiryCheckSerializer,
    BulkStockLevelRequestSerializer,
    ExpiryAlertSerializer,
    InventoryLedgerSerializer,
    LedgerLocationSerializer,
    LedgerMovementWriteSerializer,
    LineTotalSerializer,
    LowStockAlertSerializer,
    ProductSerializer,
    ProductVariantSerializer,
    ProductVariantWriteSerializer,
    ProductWriteSerializer,
    StockLevelSerializer,
    VariantExpiryStatusSerializer,
)

logger = logging.getLogger("apps.inventory")


def _ok(data, status_code=status.HTTP_200_OK):
    return Response({"success": True, "data": data}, status=status_code)


def _created(data):
    return _ok(data, status.HTTP_201_CREATED)


# ── Allergens ─────────────────────────────────────────────────────────────────

class AllergenListView(APIView):
    permission_classes = [IsCashier]

    @extend_schema(summary="List all allergens", responses={200: AllergenSerializer(many=True)}, tags=["Inventory"])
    def get(self, request):
        return _ok(AllergenSerializer(Allergen.objects.all(), many=True).data)


# ── Products ──────────────────────────────────────────────────────────────────

class ProductListCreateView(ActivityLogMixin, APIView):

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsDepartmentManager()]
        return [IsCashier()]

    @extend_schema(
        summary="List products",
        parameters=[
            OpenApiParameter("department", OpenApiTypes.INT, description="Filter by department ID"),
            OpenApiParameter("active", OpenApiTypes.BOOL, description="Include only active (default: true)"),
        ],
        responses={200: ProductSerializer(many=True)},
        tags=["Inventory"],
    )
    def get(self, request):
        qs = Product.objects.select_related("department", "supplier").prefetch_related(
            "variants__allergen_links__allergen"
        )
        if dept := request.query_params.get("department"):
            qs = qs.filter(department_id=dept)
        if request.query_params.get("active", "true").lower() != "false":
            qs = qs.filter(is_active=True)
        return _ok(ProductSerializer(qs, many=True).data)

    @extend_schema(summary="Create product", request=ProductWriteSerializer, responses={201: ProductSerializer}, tags=["Inventory"])
    def post(self, request):
        serializer = ProductWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        product = services.create_product(
            department=d["department"], supplier=d.get("supplier"),
            name=d["name"], description=d.get("description", ""),
            is_age_restricted=d.get("is_age_restricted", False),
            age_restriction_years=d.get("age_restriction_years"),
        )
        self.log(request, "product.create", "products", product.id,
                 after_state={"name": product.name, "department": product.department.name})
        return _created(ProductSerializer(product).data)


class ProductDetailView(ActivityLogMixin, APIView):

    def get_permissions(self):
        if self.request.method == "PATCH":
            return [IsDepartmentManager()]
        return [IsCashier()]

    def _get_product(self, pk):
        return get_object_or_404(
            Product.objects.select_related("department", "supplier")
            .prefetch_related("variants__allergen_links__allergen"), pk=pk
        )

    @extend_schema(summary="Retrieve product", responses={200: ProductSerializer}, tags=["Inventory"])
    def get(self, request, pk):
        return _ok(ProductSerializer(self._get_product(pk)).data)

    @extend_schema(summary="Update product", request=ProductWriteSerializer, responses={200: ProductSerializer}, tags=["Inventory"])
    def patch(self, request, pk):
        product = self._get_product(pk)
        before = {"name": product.name, "is_active": product.is_active}
        serializer = ProductWriteSerializer(product, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        product = services.update_product(product, serializer.validated_data)
        self.log(request, "product.update", "products", product.id,
                 before_state=before, after_state={str(k): str(v) for k, v in serializer.validated_data.items()})
        return _ok(ProductSerializer(product).data)


# ── Variants ──────────────────────────────────────────────────────────────────

class ProductVariantListCreateView(ActivityLogMixin, APIView):

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsDepartmentManager()]
        return [IsCashier()]

    @extend_schema(summary="List variants", responses={200: ProductVariantSerializer(many=True)}, tags=["Inventory"])
    def get(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        return _ok(ProductVariantSerializer(
            product.variants.prefetch_related("allergen_links__allergen"), many=True
        ).data)

    @extend_schema(summary="Create variant", request=ProductVariantWriteSerializer, responses={201: ProductVariantSerializer}, tags=["Inventory"])
    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        serializer = ProductVariantWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        variant = services.create_variant(
            product=product, sku=d["sku"], name=d["name"],
            pricing_mode=d.get("pricing_mode", "fixed"),
            sell_price=d["sell_price"], cost_price=d["cost_price"],
            barcode=d.get("barcode"), unit_of_measure=d.get("unit_of_measure", "unit"),
            low_stock_threshold=d.get("low_stock_threshold", 0),
            track_expiry=d.get("track_expiry", False), expiry_alert_days=d.get("expiry_alert_days", 3),
        )
        self.log(request, "variant.create", "product_variants", variant.id,
                 after_state={"sku": variant.sku, "pricing_mode": variant.pricing_mode})
        return _created(ProductVariantSerializer(variant).data)


class ProductVariantDetailView(ActivityLogMixin, APIView):

    def get_permissions(self):
        if self.request.method == "PATCH":
            return [IsDepartmentManager()]
        return [IsCashier()]

    def _get_variant(self, pk, variant_pk):
        product = get_object_or_404(Product, pk=pk)
        return product, get_object_or_404(
            ProductVariant.objects.prefetch_related("allergen_links__allergen"),
            pk=variant_pk, product=product,
        )

    @extend_schema(summary="Retrieve variant", responses={200: ProductVariantSerializer}, tags=["Inventory"])
    def get(self, request, pk, variant_pk):
        _, variant = self._get_variant(pk, variant_pk)
        return _ok(ProductVariantSerializer(variant).data)

    @extend_schema(summary="Update variant", request=ProductVariantWriteSerializer, responses={200: ProductVariantSerializer}, tags=["Inventory"])
    def patch(self, request, pk, variant_pk):
        _, variant = self._get_variant(pk, variant_pk)
        before = {"sku": variant.sku, "sell_price": str(variant.sell_price)}
        serializer = ProductVariantWriteSerializer(variant, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        variant = services.update_variant(variant, serializer.validated_data)
        self.log(request, "variant.update", "product_variants", variant.id,
                 before_state=before, after_state={str(k): str(v) for k, v in serializer.validated_data.items()})
        return _ok(ProductVariantSerializer(variant).data)


class ProductVariantAllergenView(ActivityLogMixin, APIView):
    permission_classes = [IsDepartmentManager]

    def _get_variant(self, pk, variant_pk):
        product = get_object_or_404(Product, pk=pk)
        return get_object_or_404(
            ProductVariant.objects.prefetch_related("allergen_links__allergen"),
            pk=variant_pk, product=product,
        )

    @extend_schema(summary="Replace variant allergens", request=AllergenWriteSerializer, responses={200: ProductVariantSerializer}, tags=["Inventory"])
    def put(self, request, pk, variant_pk):
        variant = self._get_variant(pk, variant_pk)
        serializer = AllergenWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.set_variant_allergens(variant, serializer.validated_data["allergens"])
        except Allergen.DoesNotExist as e:
            return Response({"success": False, "error": {"code": "NotFound", "errors": [str(e)]}},
                            status=status.HTTP_404_NOT_FOUND)
        variant = ProductVariant.objects.prefetch_related("allergen_links__allergen").get(pk=variant.pk)
        self.log(request, "variant.allergens.set", "product_variants", variant.id,
                 after_state={"allergen_ids": [a["allergen_id"] for a in serializer.validated_data["allergens"]]})
        return _ok(ProductVariantSerializer(variant).data)


class ProductVariantLineTotalView(APIView):
    permission_classes = [IsCashier]

    @extend_schema(summary="Calculate line total", request=LineTotalSerializer,
                   responses={200: OpenApiResponse(description="Line total result")}, tags=["Inventory"])
    def post(self, request, pk, variant_pk):
        product = get_object_or_404(Product, pk=pk)
        variant = get_object_or_404(ProductVariant, pk=variant_pk, product=product)
        serializer = LineTotalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = services.calculate_line_total(
                variant=variant, weight_kg=serializer.validated_data.get("weight_kg"),
                quantity=serializer.validated_data.get("quantity", 1),
            )
        except ValueError as e:
            return Response({"success": False, "error": {"code": "ValidationError", "errors": [str(e)]}},
                            status=status.HTTP_400_BAD_REQUEST)
        return _ok(result)


class BarcodeLookupView(APIView):
    permission_classes = [IsCashier]

    @extend_schema(
        summary="Look up variant by barcode",
        parameters=[OpenApiParameter("barcode", OpenApiTypes.STR, location=OpenApiParameter.QUERY, required=True)],
        responses={200: ProductVariantSerializer, 404: OpenApiResponse(description="Not found")},
        tags=["Inventory"],
    )
    def get(self, request):
        barcode = request.query_params.get("barcode", "").strip()
        if not barcode:
            return Response(
                {"success": False, "error": {"code": "ValidationError", "errors": ["'barcode' query parameter is required."]}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            variant = services.get_variant_by_barcode(barcode)
        except ProductVariant.DoesNotExist:
            return Response(
                {"success": False, "error": {"code": "NotFound", "errors": [f"No active product found for barcode '{barcode}'."]}},
                status=status.HTTP_404_NOT_FOUND,
            )
        return _ok(ProductVariantSerializer(variant).data)


# ── Ledger ────────────────────────────────────────────────────────────────────

class LedgerLocationListView(APIView):
    permission_classes = [IsCashier]

    @extend_schema(
        summary="List ledger locations",
        parameters=[OpenApiParameter("department", OpenApiTypes.INT, description="Filter by department ID")],
        responses={200: LedgerLocationSerializer(many=True)},
        tags=["Inventory"],
    )
    def get(self, request):
        qs = LedgerLocation.objects.select_related("department").filter(is_active=True)
        if dept := request.query_params.get("department"):
            qs = qs.filter(department_id=dept)
        return _ok(LedgerLocationSerializer(qs, many=True).data)


class LedgerListView(APIView):
    permission_classes = [IsDepartmentManager]

    @extend_schema(
        summary="List ledger entries",
        description="Immutable event log. Filter with ?variant, ?department, ?movement_type, ?from, ?to.",
        parameters=[
            OpenApiParameter("variant",       OpenApiTypes.INT,  description="Filter by variant ID"),
            OpenApiParameter("department",    OpenApiTypes.INT,  description="Filter by department ID"),
            OpenApiParameter("movement_type", OpenApiTypes.STR,  description="Filter by movement type"),
            OpenApiParameter("from",          OpenApiTypes.DATE, description="Recorded on or after (YYYY-MM-DD)"),
            OpenApiParameter("to",            OpenApiTypes.DATE, description="Recorded on or before (YYYY-MM-DD)"),
        ],
        responses={200: InventoryLedgerSerializer(many=True)},
        tags=["Inventory"],
    )
    def get(self, request):
        qs = InventoryLedger.objects.select_related(
            "variant__product", "department", "location", "performed_by"
        ).order_by("-recorded_at")

        if v := request.query_params.get("variant"):
            qs = qs.filter(variant_id=v)
        if d := request.query_params.get("department"):
            qs = qs.filter(department_id=d)
        if mt := request.query_params.get("movement_type"):
            qs = qs.filter(movement_type=mt)
        if f := request.query_params.get("from"):
            qs = qs.filter(recorded_at__date__gte=f)
        if t := request.query_params.get("to"):
            qs = qs.filter(recorded_at__date__lte=t)

        return _ok(InventoryLedgerSerializer(qs, many=True).data)


class LedgerMovementView(ActivityLogMixin, APIView):
    permission_classes = [IsDepartmentManager]

    @extend_schema(
        summary="Record a stock movement",
        description=(
            "Immutable write. Outbound types require negative quantity; "
            "inbound require positive. Adjustment requires a reason and store_manager role."
        ),
        request=LedgerMovementWriteSerializer,
        responses={201: InventoryLedgerSerializer, 400: OpenApiResponse(description="Validation error")},
        tags=["Inventory"],
    )
    def post(self, request):
        serializer = LedgerMovementWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        if d["movement_type"] == "adjustment" and not IsStoreManager().has_permission(request, self):
            return Response(
                {"success": False, "error": {"code": "PermissionDenied", "status": 403,
                                             "errors": ["Adjustment entries require store_manager role or above."]}},
                status=status.HTTP_403_FORBIDDEN,
            )

        variant = get_object_or_404(ProductVariant, pk=d["variant_id"], is_active=True)

        from apps.departments.models import Department
        department = get_object_or_404(Department, pk=d["department_id"])

        location = None
        if d.get("location_id"):
            location = get_object_or_404(LedgerLocation, pk=d["location_id"], department=department, is_active=True)

        performed_by = None
        if request.user.is_authenticated:
            try:
                performed_by = request.user.staff_profile
            except Exception:
                pass

        try:
            entry = services.record_movement(
                variant=variant, department=department, movement_type=d["movement_type"],
                quantity=d["quantity"], performed_by=performed_by, location=location,
                weight_kg=d.get("weight_kg"), batch_ref=d.get("batch_ref", ""),
                best_before_date=d.get("best_before_date"), use_by_date=d.get("use_by_date"),
                order_id=d.get("order_id"), return_id=d.get("return_id"), reason=d.get("reason", ""),
            )
        except ValueError as exc:
            return Response(
                {"success": False, "error": {"code": "ValidationError", "errors": [str(exc)]}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        self.log(request, f"ledger.{entry.movement_type}", "inventory_ledger", entry.id,
                 after_state={"variant_sku": variant.sku, "quantity": str(entry.quantity),
                              "department": department.name, "movement_type": entry.movement_type})

        out = InventoryLedger.objects.select_related(
            "variant__product", "department", "location", "performed_by"
        ).get(pk=entry.pk)
        return _created(InventoryLedgerSerializer(out).data)


class StockLevelView(APIView):
    permission_classes = [IsCashier]

    @extend_schema(
        summary="Get stock level",
        description="Derived from SUM(quantity) on the ledger. Scope to a department with ?department=<id>.",
        parameters=[OpenApiParameter("department", OpenApiTypes.INT, description="Scope to department ID")],
        responses={200: StockLevelSerializer},
        tags=["Inventory"],
    )
    def get(self, request, variant_pk):
        get_object_or_404(ProductVariant, pk=variant_pk, is_active=True)
        dept_id = request.query_params.get("department")
        try:
            data = services.get_stock_level(variant_id=variant_pk, department_id=int(dept_id) if dept_id else None)
        except ValueError as exc:
            return Response({"success": False, "error": {"code": "NotFound", "errors": [str(exc)]}},
                            status=status.HTTP_404_NOT_FOUND)
        return _ok(data)


class StockLevelBulkView(APIView):
    permission_classes = [IsCashier]

    @extend_schema(
        summary="Bulk stock level check",
        request=BulkStockLevelRequestSerializer,
        responses={200: StockLevelSerializer(many=True)},
        tags=["Inventory"],
    )
    def post(self, request):
        serializer = BulkStockLevelRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        return _ok(services.get_stock_levels_bulk(
            variant_ids=d["variant_ids"], department_id=d.get("department_id")
        ))


class ExpiryAlertView(APIView):
    permission_classes = [IsDepartmentManager]

    @extend_schema(
        summary="Expiry alerts",
        description="Batches within the alert window with net remaining stock. Override window with ?days_ahead=<n>.",
        parameters=[OpenApiParameter("days_ahead", OpenApiTypes.INT, description="Look-ahead window in days")],
        responses={200: ExpiryAlertSerializer(many=True)},
        tags=["Inventory"],
    )
    def get(self, request, department_pk):
        from apps.departments.models import Department
        get_object_or_404(Department, pk=department_pk)

        days_ahead = request.query_params.get("days_ahead")
        if days_ahead is not None:
            try:
                days_ahead = int(days_ahead)
            except ValueError:
                return Response(
                    {"success": False, "error": {"code": "ValidationError", "errors": ["days_ahead must be an integer."]}},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        return _ok(services.get_expiry_alerts(department_id=department_pk, days_ahead=days_ahead))
    
class LowStockAlertView(APIView):
    """
    Returns all variants in a department where current stock is at or
    below their configured low_stock_threshold. Sorted by most critical first.
    Variants with threshold=0 are excluded (alerts disabled).
    """
    permission_classes = [IsDepartmentManager]

    @extend_schema(
        summary="Low stock alerts",
        description=(
            "Returns variants at or below their low_stock_threshold, "
            "sorted by how far below threshold they are. "
            "Variants with threshold=0 are excluded."
        ),
        responses={200: LowStockAlertSerializer(many=True)},
        tags=["Inventory"],
    )
    def get(self, request, department_pk):
        from apps.departments.models import Department
        get_object_or_404(Department, pk=department_pk)
        alerts = services.get_low_stock_variants(department_id=department_pk)
        return _ok(alerts)


class VariantExpiryStatusView(APIView):
    """
    Expiry status for every batch of a variant in a department.
    Called during barcode scan to block expired items before basket entry.
    """
    permission_classes = [IsCashier]

    @extend_schema(
        summary="Variant expiry status",
        description=(
            "Returns per-batch expiry status for a variant. "
            "has_expired_stock=true means at least one batch is expired — "
            "the POS must block this variant from being added to the basket."
        ),
        parameters=[
            OpenApiParameter("department", OpenApiTypes.INT, required=True, description="Department ID"),
        ],
        responses={200: VariantExpiryStatusSerializer},
        tags=["Inventory"],
    )
    def get(self, request, variant_pk):
        dept_id = request.query_params.get("department")
        if not dept_id:
            return Response(
                {"success": False, "error": {"code": "ValidationError", "errors": ["'department' query parameter is required."]}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            data = services.get_variant_expiry_status(
                variant_id=variant_pk, department_id=int(dept_id)
            )
        except ValueError as exc:
            return Response(
                {"success": False, "error": {"code": "NotFound", "errors": [str(exc)]}},
                status=status.HTTP_404_NOT_FOUND,
            )
        return _ok(data)


class BasketExpiryCheckView(APIView):
    """
    POST the basket lines before checkout. Returns any blocked lines.
    Empty blocked list = basket is clear to proceed.
    The POS calls this before confirming payment.
    """
    permission_classes = [IsCashier]

    @extend_schema(
        summary="Basket expiry check",
        description=(
            "Validates all basket lines for expiry before checkout. "
            "Returns blocked lines with reasons. "
            "Empty list means the basket is clear."
        ),
        request=BasketExpiryCheckSerializer,
        responses={
            200: OpenApiResponse(description="Validation result — check 'blocked' list"),
        },
        tags=["Inventory"],
    )
    def post(self, request):
        serializer = BasketExpiryCheckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lines = serializer.validated_data["lines"]
        blocked = services.check_basket_for_expired(lines)
        return _ok({
            "basket_clear": len(blocked) == 0,
            "blocked_count": len(blocked),
            "blocked": blocked,
        })