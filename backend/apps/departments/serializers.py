from decimal import Decimal
from rest_framework import serializers
from .models import Department, DepartmentCategory, DepartmentPricingRule, DepartmentStockSettings


class DepartmentPricingRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = DepartmentPricingRule
        fields = ["id", "default_markup_percent", "rounding_strategy", "minimum_margin_percent", "max_discount_percent", "display_prices_inclusive_of_tax", "updated_at"]
        read_only_fields = ["id", "updated_at"]

    def validate(self, data):
        markup = data.get("default_markup_percent", self.instance.default_markup_percent if self.instance else Decimal("0"))
        min_margin = data.get("minimum_margin_percent", self.instance.minimum_margin_percent if self.instance else Decimal("0"))
        if min_margin > 0 and markup > 0:
            implied_margin = (markup / (100 + markup)) * 100
            if min_margin > implied_margin:
                raise serializers.ValidationError({"minimum_margin_percent": f"A markup of {markup}% implies a margin of {implied_margin:.1f}%. minimum_margin_percent ({min_margin}%) cannot exceed this."})
        return data


class DepartmentStockSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = DepartmentStockSettings
        fields = ["id", "default_low_stock_threshold", "track_expiry_by_default", "default_expiry_alert_days", "default_pricing_mode", "requires_temperature_checks", "temperature_min_celsius", "temperature_max_celsius", "updated_at"]
        read_only_fields = ["id", "updated_at"]

    def validate(self, data):
        requires_checks = data.get("requires_temperature_checks", self.instance.requires_temperature_checks if self.instance else False)
        temp_min = data.get("temperature_min_celsius", self.instance.temperature_min_celsius if self.instance else None)
        temp_max = data.get("temperature_max_celsius", self.instance.temperature_max_celsius if self.instance else None)
        if requires_checks and (temp_min is None or temp_max is None):
            raise serializers.ValidationError("temperature_min_celsius and temperature_max_celsius are required when requires_temperature_checks is True.")
        if temp_min is not None and temp_max is not None and temp_min >= temp_max:
            raise serializers.ValidationError({"temperature_min_celsius": "Must be less than temperature_max_celsius."})
        return data


class DepartmentCategoryChildSerializer(serializers.ModelSerializer):
    class Meta:
        model = DepartmentCategory
        fields = ["id", "name", "slug", "display_order", "is_active"]
        read_only_fields = fields


class DepartmentCategorySerializer(serializers.ModelSerializer):
    children = DepartmentCategoryChildSerializer(many=True, read_only=True)

    class Meta:
        model = DepartmentCategory
        fields = ["id", "name", "slug", "display_order", "is_active", "children"]
        read_only_fields = fields


class DepartmentCategoryWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    parent_id = serializers.IntegerField(required=False, allow_null=True)
    display_order = serializers.IntegerField(default=0, min_value=0)
    is_active = serializers.BooleanField(default=True)

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Category name must not be blank.")
        return value.strip()


class DepartmentListSerializer(serializers.ModelSerializer):
    tax_rate_display = serializers.SerializerMethodField()
    category_count = serializers.SerializerMethodField()

    class Meta:
        model = Department
        fields = ["id", "name", "slug", "tax_rate", "tax_rate_display", "is_active", "display_order", "category_count", "updated_at"]
        read_only_fields = fields

    def get_tax_rate_display(self, obj) -> str:
        return f"{float(obj.tax_rate) * 100:.2f}%"

    def get_category_count(self, obj) -> int:
        return getattr(obj, "category_count", obj.categories.filter(is_active=True).count())


class DepartmentDetailSerializer(serializers.ModelSerializer):
    tax_rate_display = serializers.SerializerMethodField()
    pricing_rule = DepartmentPricingRuleSerializer(read_only=True)
    stock_settings = DepartmentStockSettingsSerializer(read_only=True)
    categories = serializers.SerializerMethodField()

    class Meta:
        model = Department
        fields = ["id", "name", "slug", "tax_rate", "tax_rate_display", "is_active", "display_order", "pricing_rule", "stock_settings", "categories", "created_at", "updated_at"]
        read_only_fields = fields

    def get_tax_rate_display(self, obj) -> str:
        return f"{float(obj.tax_rate) * 100:.2f}%"

    def get_categories(self, obj):
        from .services import get_category_tree
        return get_category_tree(obj)


class DepartmentWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ["name", "tax_rate", "display_order", "is_active"]

    def validate_tax_rate(self, value):
        if value < 0 or value > 1:
            raise serializers.ValidationError("tax_rate must be a decimal fraction between 0 and 1 (e.g. 0.2000 for 20% VAT).")
        return value

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Department name must not be blank.")
        return value


class SuggestedPriceSerializer(serializers.Serializer):
    cost_price_pence = serializers.IntegerField()
    suggested_sell_price_pence = serializers.IntegerField()
    suggested_sell_price_display = serializers.CharField()
    markup_percent = serializers.DecimalField(max_digits=6, decimal_places=2)
    rounding_strategy = serializers.CharField()


class PriceInputSerializer(serializers.Serializer):
    cost_price_pence = serializers.IntegerField(min_value=1)