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
from .models import Allergen, Product, ProductVariant
from .serializers import (
    AllergenSerializer,
    AllergenWriteSerializer,
    LineTotalSerializer,
    ProductSerializer,
    ProductVariantSerializer,
    ProductVariantWriteSerializer,
    ProductWriteSerializer,
)

logger = logging.getLogger("apps.inventory")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ok(data, status_code=status.HTTP_200_OK):
    return Response({"success": True, "data": data}, status=status_code)


def _created(data):
    return _ok(data, status.HTTP_201_CREATED)


# ── Allergens ─────────────────────────────────────────────────────────────────

class AllergenListView(APIView):
    permission_classes = [IsCashier]

    @extend_schema(
        summary="List all allergens",
        description="Returns the full EU allergen list. Used to populate allergen pickers when creating or editing variants.",
        responses={200: AllergenSerializer(many=True)},
        tags=["Inventory"],
    )
    def get(self, request):
        allergens = Allergen.objects.all()
        return _ok(AllergenSerializer(allergens, many=True).data)


# ── Products ──────────────────────────────────────────────────────────────────

class ProductListCreateView(ActivityLogMixin, APIView):

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsDepartmentManager()]
        return [IsCashier()]

    @extend_schema(
        summary="List products",
        description=(
            "Returns active products by default. "
            "Filter by department with ?department=<id>. "
            "Pass ?active=false to include inactive products."
        ),
        parameters=[
            OpenApiParameter("department", OpenApiTypes.INT, description="Filter by department ID"),
            OpenApiParameter("active", OpenApiTypes.BOOL, description="Include only active products (default: true)"),
        ],
        responses={200: ProductSerializer(many=True)},
        tags=["Inventory"],
    )
    def get(self, request):
        qs = Product.objects.select_related(
            "department", "supplier"
        ).prefetch_related(
            "variants__allergen_links__allergen"
        )

        department_id = request.query_params.get("department")
        if department_id:
            qs = qs.filter(department_id=department_id)

        if request.query_params.get("active", "true").lower() != "false":
            qs = qs.filter(is_active=True)

        return _ok(ProductSerializer(qs, many=True).data)

    @extend_schema(
        summary="Create product",
        description="Creates a product shell. Add variants separately via POST /products/{id}/variants/.",
        request=ProductWriteSerializer,
        responses={201: ProductSerializer},
        tags=["Inventory"],
    )
    def post(self, request):
        serializer = ProductWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        product = services.create_product(
            department=d["department"],
            supplier=d.get("supplier"),
            name=d["name"],
            description=d.get("description", ""),
            is_age_restricted=d.get("is_age_restricted", False),
            age_restriction_years=d.get("age_restriction_years"),
        )
        self.log(
            request, "product.create", "products", product.id,
            after_state={"name": product.name, "department": product.department.name},
        )
        return _created(ProductSerializer(product).data)


class ProductDetailView(ActivityLogMixin, APIView):

    def get_permissions(self):
        if self.request.method == "PATCH":
            return [IsDepartmentManager()]
        return [IsCashier()]

    def _get_product(self, pk):
        return get_object_or_404(
            Product.objects.select_related("department", "supplier")
            .prefetch_related("variants__allergen_links__allergen"),
            pk=pk,
        )

    @extend_schema(
        summary="Retrieve product",
        responses={200: ProductSerializer},
        tags=["Inventory"],
    )
    def get(self, request, pk):
        return _ok(ProductSerializer(self._get_product(pk)).data)

    @extend_schema(
        summary="Update product",
        description="Partial update. Only send the fields you want to change.",
        request=ProductWriteSerializer,
        responses={200: ProductSerializer},
        tags=["Inventory"],
    )
    def patch(self, request, pk):
        product = self._get_product(pk)
        before = {"name": product.name, "is_active": product.is_active}
        serializer = ProductWriteSerializer(product, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        product = services.update_product(product, serializer.validated_data)
        self.log(
            request, "product.update", "products", product.id,
            before_state=before,
            after_state={str(k): str(v) for k, v in serializer.validated_data.items()},
        )
        return _ok(ProductSerializer(product).data)


# ── Variants ──────────────────────────────────────────────────────────────────

class ProductVariantListCreateView(ActivityLogMixin, APIView):

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsDepartmentManager()]
        return [IsCashier()]

    def _get_product(self, pk):
        return get_object_or_404(Product, pk=pk)

    @extend_schema(
        summary="List variants for a product",
        description="Returns all variants (active + inactive) for the given product.",
        responses={200: ProductVariantSerializer(many=True)},
        tags=["Inventory"],
    )
    def get(self, request, pk):
        product = self._get_product(pk)
        variants = product.variants.prefetch_related("allergen_links__allergen")
        return _ok(ProductVariantSerializer(variants, many=True).data)

    @extend_schema(
        summary="Create variant",
        description=(
            "Add a variant to a product. "
            "Set pricing_mode to 'weight_based' for loose items sold by the kg; "
            "sell_price then represents the per-kg rate. "
            "Allergens can be assigned after creation via PUT /variants/{variant_pk}/allergens/."
        ),
        request=ProductVariantWriteSerializer,
        responses={201: ProductVariantSerializer},
        tags=["Inventory"],
    )
    def post(self, request, pk):
        product = self._get_product(pk)
        serializer = ProductVariantWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        variant = services.create_variant(
            product=product,
            sku=d["sku"],
            name=d["name"],
            pricing_mode=d.get("pricing_mode", "fixed"),
            sell_price=d["sell_price"],
            cost_price=d["cost_price"],
            barcode=d.get("barcode"),
            unit_of_measure=d.get("unit_of_measure", "unit"),
            low_stock_threshold=d.get("low_stock_threshold", 0),
            track_expiry=d.get("track_expiry", False),
            expiry_alert_days=d.get("expiry_alert_days", 3),
        )
        self.log(
            request, "variant.create", "product_variants", variant.id,
            after_state={
                "sku": variant.sku,
                "pricing_mode": variant.pricing_mode,
                "sell_price": str(variant.sell_price),
            },
        )
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
            pk=variant_pk,
            product=product,
        )

    @extend_schema(
        summary="Retrieve variant",
        responses={200: ProductVariantSerializer},
        tags=["Inventory"],
    )
    def get(self, request, pk, variant_pk):
        _, variant = self._get_variant(pk, variant_pk)
        return _ok(ProductVariantSerializer(variant).data)

    @extend_schema(
        summary="Update variant",
        description=(
            "Partial update. Changing pricing_mode from fixed to weight_based "
            "also requires changing unit_of_measure to 'kg' or 'g' in the same request."
        ),
        request=ProductVariantWriteSerializer,
        responses={200: ProductVariantSerializer},
        tags=["Inventory"],
    )
    def patch(self, request, pk, variant_pk):
        _, variant = self._get_variant(pk, variant_pk)
        before = {
            "sku": variant.sku,
            "pricing_mode": variant.pricing_mode,
            "sell_price": str(variant.sell_price),
            "is_active": variant.is_active,
        }
        serializer = ProductVariantWriteSerializer(
            variant, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        variant = services.update_variant(variant, serializer.validated_data)
        self.log(
            request, "variant.update", "product_variants", variant.id,
            before_state=before,
            after_state={str(k): str(v) for k, v in serializer.validated_data.items()},
        )
        return _ok(ProductVariantSerializer(variant).data)


# ── Variant allergens ─────────────────────────────────────────────────────────

class ProductVariantAllergenView(ActivityLogMixin, APIView):
    """
    PUT replaces all allergen links atomically.
    Send an empty list to clear all allergens.
    """
    permission_classes = [IsDepartmentManager]

    def _get_variant(self, pk, variant_pk):
        product = get_object_or_404(Product, pk=pk)
        return get_object_or_404(
            ProductVariant.objects.prefetch_related("allergen_links__allergen"),
            pk=variant_pk,
            product=product,
        )

    @extend_schema(
        summary="Replace variant allergens",
        description=(
            "Atomically replaces all allergen links for this variant. "
            "Send an empty list to clear allergens. "
            "Set may_contain=true for 'may contain' warnings."
        ),
        request=AllergenWriteSerializer,
        responses={200: ProductVariantSerializer},
        tags=["Inventory"],
    )
    def put(self, request, pk, variant_pk):
        variant = self._get_variant(pk, variant_pk)
        serializer = AllergenWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        allergen_data = serializer.validated_data["allergens"]

        try:
            services.set_variant_allergens(variant, allergen_data)
        except Allergen.DoesNotExist as e:
            return Response(
                {
                    "success": False,
                    "error": {"code": "NotFound", "errors": [str(e)]},
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        variant = ProductVariant.objects.prefetch_related(
            "allergen_links__allergen"
        ).get(pk=variant.pk)

        self.log(
            request, "variant.allergens.set", "product_variants", variant.id,
            after_state={"allergen_ids": [a["allergen_id"] for a in allergen_data]},
        )
        return _ok(ProductVariantSerializer(variant).data)


# ── Line total ────────────────────────────────────────────────────────────────

class ProductVariantLineTotalView(APIView):
    """
    Calculate line total for a variant without any DB writes.

    Fixed:        POST {"quantity": 3}       -> £3.00 for a £1.00 item
    Weight-based: POST {"weight_kg": 0.456}  -> £2.28 for a £5.00/kg item
    """
    permission_classes = [IsCashier]

    @extend_schema(
        summary="Calculate line total",
        description=(
            "Pure calculation — no DB writes. "
            "For weight_based variants supply weight_kg. "
            "For fixed variants supply quantity (defaults to 1)."
        ),
        request=LineTotalSerializer,
        responses={
            200: OpenApiResponse(description="Line total calculation result"),
            400: OpenApiResponse(description="Missing weight_kg for a weight-based variant"),
        },
        tags=["Inventory"],
    )
    def post(self, request, pk, variant_pk):
        product = get_object_or_404(Product, pk=pk)
        variant = get_object_or_404(ProductVariant, pk=variant_pk, product=product)

        serializer = LineTotalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            result = services.calculate_line_total(
                variant=variant,
                weight_kg=d.get("weight_kg"),
                quantity=d.get("quantity", 1),
            )
        except ValueError as e:
            return Response(
                {
                    "success": False,
                    "error": {"code": "ValidationError", "errors": [str(e)]},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return _ok(result)


# ── Barcode lookup ────────────────────────────────────────────────────────────

class BarcodeLookupView(APIView):
    """
    Cashier scans a barcode -> variant + pricing info returned instantly.
    Hot path during a transaction; keep it fast.
    """
    permission_classes = [IsCashier]

    @extend_schema(
        summary="Look up variant by barcode",
        description=(
            "Primary scanner endpoint. Returns the matching active variant "
            "with its product, pricing mode, and allergen data. "
            "Returns 404 if the barcode is unknown or the variant is inactive."
        ),
        parameters=[
            OpenApiParameter(
                "barcode",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="The scanned barcode string",
            )
        ],
        responses={
            200: ProductVariantSerializer,
            400: OpenApiResponse(description="barcode query parameter is required"),
            404: OpenApiResponse(description="No active variant with this barcode"),
        },
        tags=["Inventory"],
    )
    def get(self, request):
        barcode = request.query_params.get("barcode", "").strip()
        if not barcode:
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "ValidationError",
                        "errors": ["'barcode' query parameter is required."],
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            variant = services.get_variant_by_barcode(barcode)
        except ProductVariant.DoesNotExist:
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "NotFound",
                        "errors": [f"No active product found for barcode '{barcode}'."],
                    },
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        return _ok(ProductVariantSerializer(variant).data)