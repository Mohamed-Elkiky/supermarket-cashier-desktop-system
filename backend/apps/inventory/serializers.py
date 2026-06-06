from decimal import Decimal

from rest_framework import serializers

from .models import (
    Allergen,
    InventoryLedger,
    LedgerLocation,
    Product,
    ProductVariant,
    ProductVariantAllergen,
    Supplier,
)


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "name", "contact_name", "contact_email", "contact_phone", "is_active"]


class AllergenSerializer(serializers.ModelSerializer):
    class Meta:
        model = Allergen
        fields = ["id", "name", "eu_code"]


class ProductVariantAllergenSerializer(serializers.ModelSerializer):
    allergen = AllergenSerializer(read_only=True)
    allergen_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = ProductVariantAllergen
        fields = ["allergen", "allergen_id", "may_contain"]


class ProductVariantSerializer(serializers.ModelSerializer):
    allergens = ProductVariantAllergenSerializer(source="allergen_links", many=True, read_only=True)
    line_total_example = serializers.SerializerMethodField()
    margin_percent = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = [
            "id", "product", "sku", "barcode", "name",
            "pricing_mode", "sell_price", "cost_price",
            "unit_of_measure", "low_stock_threshold",
            "track_expiry", "expiry_alert_days",
            "is_active", "allergens",
            "line_total_example", "margin_percent",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_line_total_example(self, obj):
        if obj.pricing_mode == "weight_based":
            return f"£{float(obj.sell_price):.2f} per kg"
        return f"£{float(obj.sell_price):.2f}"

    def get_margin_percent(self, obj):
        if obj.sell_price and obj.sell_price > 0:
            margin = ((obj.sell_price - obj.cost_price) / obj.sell_price) * 100
            return f"{float(margin):.1f}%"
        return None


class ProductVariantWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductVariant
        fields = [
            "sku", "barcode", "name", "pricing_mode",
            "sell_price", "cost_price", "unit_of_measure",
            "low_stock_threshold", "track_expiry",
            "expiry_alert_days", "is_active",
        ]

    def validate(self, data):
        instance = self.instance
        pricing_mode = data.get("pricing_mode", instance.pricing_mode if instance else "fixed")
        unit = data.get("unit_of_measure", instance.unit_of_measure if instance else "unit")
        sell = data.get("sell_price", instance.sell_price if instance else Decimal("0"))
        cost = data.get("cost_price", instance.cost_price if instance else Decimal("0"))

        if pricing_mode == "weight_based" and unit not in ("kg", "g"):
            raise serializers.ValidationError(
                {"unit_of_measure": "Weight-based products must use 'kg' or 'g'."}
            )
        if pricing_mode == "fixed" and unit in ("kg", "g"):
            raise serializers.ValidationError(
                {"unit_of_measure": "Fixed-price products should not use 'kg' or 'g'."}
            )
        if sell < cost:
            raise serializers.ValidationError(
                {"sell_price": "sell_price cannot be less than cost_price."}
            )
        return data


class ProductSerializer(serializers.ModelSerializer):
    variants = ProductVariantSerializer(many=True, read_only=True)
    variant_count = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id", "department", "supplier", "name", "description",
            "is_age_restricted", "age_restriction_years",
            "is_active", "variant_count", "variants",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_variant_count(self, obj):
        return obj.variants.filter(is_active=True).count()


class ProductWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [
            "department", "supplier", "name", "description",
            "is_age_restricted", "age_restriction_years", "is_active",
        ]

    def validate(self, data):
        instance = self.instance
        is_age_restricted = data.get("is_age_restricted", instance.is_age_restricted if instance else False)
        age_years = data.get("age_restriction_years", instance.age_restriction_years if instance else None)
        if is_age_restricted and not age_years:
            raise serializers.ValidationError(
                {"age_restriction_years": "Required when is_age_restricted is True."}
            )
        return data


class LineTotalSerializer(serializers.Serializer):
    weight_kg = serializers.FloatField(required=False, min_value=0.001)
    quantity = serializers.IntegerField(required=False, min_value=1, default=1)


class AllergenWriteSerializer(serializers.Serializer):
    allergens = serializers.ListField(child=serializers.DictField(), allow_empty=True)

    def validate_allergens(self, value):
        for item in value:
            if "allergen_id" not in item:
                raise serializers.ValidationError("Each entry must include 'allergen_id'.")
            if not isinstance(item["allergen_id"], int):
                raise serializers.ValidationError("'allergen_id' must be an integer.")
            if not isinstance(item.get("may_contain", False), bool):
                raise serializers.ValidationError("'may_contain' must be a boolean.")
        return value


# ── Ledger serializers ────────────────────────────────────────────────────────

class LedgerLocationSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True)

    class Meta:
        model = LedgerLocation
        fields = ["id", "name", "department", "department_name", "is_active"]


class InventoryLedgerSerializer(serializers.ModelSerializer):
    """Read-only. Returned by GET /ledger/ and after a successful POST movement."""
    variant_sku = serializers.CharField(source="variant.sku", read_only=True)
    variant_name = serializers.CharField(source="variant.name", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)
    location_name = serializers.CharField(source="location.name", read_only=True, default=None)
    performed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = InventoryLedger
        fields = [
            "id",
            "variant", "variant_sku", "variant_name",
            "department", "department_name",
            "location", "location_name",
            "movement_type",
            "quantity", "weight_kg",
            "batch_ref", "best_before_date", "use_by_date",
            "order_id", "return_id",
            "performed_by", "performed_by_name",
            "reason",
            "recorded_at",
        ]
        read_only_fields = fields

    def get_performed_by_name(self, obj):
        if obj.performed_by_id:
            return f"{obj.performed_by.first_name} {obj.performed_by.last_name}".strip()
        return None


class LedgerMovementWriteSerializer(serializers.Serializer):
    """Validates POST /inventory/ledger/movements/. Clean data goes to services.record_movement()."""
    variant_id    = serializers.IntegerField()
    department_id = serializers.IntegerField()
    location_id   = serializers.IntegerField(required=False, allow_null=True)
    movement_type = serializers.ChoiceField(choices=InventoryLedger.MOVEMENT_CHOICES)
    quantity      = serializers.DecimalField(max_digits=10, decimal_places=3)
    weight_kg     = serializers.DecimalField(
        max_digits=10, decimal_places=3, required=False, allow_null=True, min_value=Decimal("0.001")
    )
    batch_ref        = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    best_before_date = serializers.DateField(required=False, allow_null=True)
    use_by_date      = serializers.DateField(required=False, allow_null=True)
    order_id         = serializers.IntegerField(required=False, allow_null=True)
    return_id        = serializers.IntegerField(required=False, allow_null=True)
    reason           = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_quantity(self, value):
        if value == 0:
            raise serializers.ValidationError("quantity cannot be zero.")
        return value

    def validate(self, data):
        movement_type = data.get("movement_type")
        quantity = data.get("quantity", Decimal("0"))
        reason = data.get("reason", "")

        if movement_type in InventoryLedger.OUTBOUND_TYPES and quantity >= 0:
            raise serializers.ValidationError(
                {"quantity": f"'{movement_type}' is an outbound movement; quantity must be negative."}
            )
        if movement_type in InventoryLedger.INBOUND_TYPES and quantity <= 0:
            raise serializers.ValidationError(
                {"quantity": f"'{movement_type}' is an inbound movement; quantity must be positive."}
            )
        if movement_type == "adjustment" and not reason.strip():
            raise serializers.ValidationError(
                {"reason": "Adjustment entries require a non-empty reason."}
            )

        bb = data.get("best_before_date")
        ub = data.get("use_by_date")
        if bb and ub and ub < bb:
            raise serializers.ValidationError(
                {"use_by_date": "use_by_date cannot be before best_before_date."}
            )
        return data


class StockLevelSerializer(serializers.Serializer):
    variant_id          = serializers.IntegerField()
    sku                 = serializers.CharField()
    name                = serializers.CharField()
    department_id       = serializers.IntegerField(allow_null=True)
    stock_quantity      = serializers.FloatField()
    unit_of_measure     = serializers.CharField()
    low_stock_threshold = serializers.IntegerField()
    is_low_stock        = serializers.BooleanField()


class BulkStockLevelRequestSerializer(serializers.Serializer):
    variant_ids   = serializers.ListField(
        child=serializers.IntegerField(min_value=1), min_length=1, max_length=200
    )
    department_id = serializers.IntegerField(required=False, allow_null=True)


class ExpiryAlertSerializer(serializers.Serializer):
    variant_id       = serializers.IntegerField()
    sku              = serializers.CharField()
    name             = serializers.CharField()
    batch_ref        = serializers.CharField(allow_null=True)
    best_before_date = serializers.CharField(allow_null=True)
    use_by_date      = serializers.CharField(allow_null=True)
    days_remaining   = serializers.IntegerField()
    net_quantity     = serializers.FloatField()
    is_expired       = serializers.BooleanField()