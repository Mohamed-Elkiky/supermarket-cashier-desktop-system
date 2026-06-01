from decimal import Decimal
from rest_framework import serializers
from .models import Product, ProductVariant, ProductVariantAllergen, Supplier, Allergen


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
    allergens = ProductVariantAllergenSerializer(
        source="allergen_links", many=True, read_only=True
    )
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
    """
    Used for both POST (create) and PATCH (partial update).

    Allergen links are managed separately via PUT
    /products/{pk}/variants/{variant_pk}/allergens/ so they are
    intentionally excluded here to keep writes atomic and clear.
    """

    class Meta:
        model = ProductVariant
        fields = [
            "sku", "barcode", "name", "pricing_mode",
            "sell_price", "cost_price", "unit_of_measure",
            "low_stock_threshold", "track_expiry",
            "expiry_alert_days", "is_active",
        ]

    def validate(self, data):
        # On PATCH, merge incoming data with instance values so
        # cross-field rules still work when only one field is sent.
        instance = self.instance
        pricing_mode = data.get(
            "pricing_mode",
            instance.pricing_mode if instance else "fixed",
        )
        unit = data.get(
            "unit_of_measure",
            instance.unit_of_measure if instance else "unit",
        )
        sell = data.get(
            "sell_price",
            instance.sell_price if instance else Decimal("0"),
        )
        cost = data.get(
            "cost_price",
            instance.cost_price if instance else Decimal("0"),
        )

        if pricing_mode == "weight_based" and unit not in ("kg", "g"):
            raise serializers.ValidationError(
                {"unit_of_measure": "Weight-based products must use 'kg' or 'g' as unit_of_measure."}
            )

        if pricing_mode == "fixed" and unit in ("kg", "g"):
            raise serializers.ValidationError(
                {"unit_of_measure": "Fixed-price products should not use 'kg' or 'g'. Use 'unit', 'litre', or 'ml'."}
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
        is_age_restricted = data.get(
            "is_age_restricted",
            instance.is_age_restricted if instance else False,
        )
        age_restriction_years = data.get(
            "age_restriction_years",
            instance.age_restriction_years if instance else None,
        )
        if is_age_restricted and not age_restriction_years:
            raise serializers.ValidationError(
                {"age_restriction_years": "Required when is_age_restricted is True."}
            )
        return data


class LineTotalSerializer(serializers.Serializer):
    """
    Request body for the line-total calculation endpoint.
    weight_kg is required for weight_based variants; quantity for fixed.
    """
    weight_kg = serializers.FloatField(required=False, min_value=0.001)
    quantity = serializers.IntegerField(required=False, min_value=1, default=1)


class AllergenWriteSerializer(serializers.Serializer):
    """
    Body for PUT /products/{pk}/variants/{variant_pk}/allergens/
    Replaces all allergen links in one atomic operation.
    """
    allergens = serializers.ListField(
        child=serializers.DictField(),
        allow_empty=True,
    )

    def validate_allergens(self, value):
        for item in value:
            if "allergen_id" not in item:
                raise serializers.ValidationError(
                    "Each entry must include 'allergen_id'."
                )
            if not isinstance(item["allergen_id"], int):
                raise serializers.ValidationError(
                    "'allergen_id' must be an integer."
                )
            may_contain = item.get("may_contain", False)
            if not isinstance(may_contain, bool):
                raise serializers.ValidationError(
                    "'may_contain' must be a boolean."
                )
        return value