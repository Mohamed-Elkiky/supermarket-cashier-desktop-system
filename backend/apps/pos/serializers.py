from rest_framework import serializers

from apps.inventory.models import ProductVariant
from .models import Order, OrderItem, Promotion, PromotionVariant


class PromotionSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True, default=None)
    # Write-only input — linked PromotionVariant rows are managed in create()/update().
    # Current links are re-added to the output in to_representation().
    variant_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=ProductVariant.objects.all(),
        required=False, default=list, write_only=True,
    )

    class Meta:
        model = Promotion
        fields = [
            "id", "name", "promotion_type", "discount_value",
            "department", "department_name", "min_spend_pence",
            "variant_ids",
            "starts_at", "ends_at", "is_active",
            "created_by", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def validate(self, data):
        promotion_type = data.get("promotion_type", getattr(self.instance, "promotion_type", None))

        if promotion_type == "meal_deal":
            min_spend = data.get(
                "min_spend_pence",
                getattr(self.instance, "min_spend_pence", None) if self.instance else None,
            )
            if not min_spend:
                raise serializers.ValidationError(
                    {"min_spend_pence": "min_spend_pence is required for meal_deal promotions."}
                )

            if "variant_ids" in data:
                if not data["variant_ids"]:
                    raise serializers.ValidationError(
                        {"variant_ids": "variant_ids is required for meal_deal promotions."}
                    )
            elif self.instance is None or not self.instance.variant_links.exists():
                raise serializers.ValidationError(
                    {"variant_ids": "variant_ids is required for meal_deal promotions."}
                )

        starts_at = data.get("starts_at", getattr(self.instance, "starts_at", None))
        ends_at = data.get("ends_at", getattr(self.instance, "ends_at", None))
        if starts_at and ends_at and ends_at <= starts_at:
            raise serializers.ValidationError({"ends_at": "ends_at must be after starts_at."})

        return data

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep["variant_ids"] = list(instance.variant_links.values_list("variant_id", flat=True))
        return rep

    def _set_variant_links(self, promotion, variants):
        promotion.variant_links.all().delete()
        if variants:
            PromotionVariant.objects.bulk_create([
                PromotionVariant(promotion=promotion, variant=v) for v in variants
            ])

    def create(self, validated_data):
        variant_ids = validated_data.pop("variant_ids", [])
        promotion = Promotion(**validated_data)
        promotion.full_clean()
        promotion.save()
        self._set_variant_links(promotion, variant_ids)
        return promotion

    def update(self, instance, validated_data):
        variant_ids = validated_data.pop("variant_ids", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.full_clean()
        instance.save()
        if variant_ids is not None:
            self._set_variant_links(instance, variant_ids)
        return instance


class OrderItemSerializer(serializers.ModelSerializer):
    unit_price_display  = serializers.SerializerMethodField()
    discount_display    = serializers.SerializerMethodField()
    line_total_display  = serializers.SerializerMethodField()
    promotion_name      = serializers.CharField(source="promotion.name", read_only=True, default=None)

    class Meta:
        model = OrderItem
        fields = [
            "id", "variant", "variant_name_snapshot",
            "unit_price_pence", "unit_price_display",
            "weight_kg", "quantity",
            "promotion", "promotion_name",
            "discount_pence", "discount_display",
            "line_total_pence", "line_total_display",
        ]

    def get_unit_price_display(self, obj):
        return f"£{obj.unit_price_pence / 100:.2f}"

    def get_discount_display(self, obj):
        return f"-£{obj.discount_pence / 100:.2f}" if obj.discount_pence else None

    def get_line_total_display(self, obj):
        return f"£{obj.line_total_pence / 100:.2f}"


class OrderSerializer(serializers.ModelSerializer):
    items                   = OrderItemSerializer(many=True, read_only=True)
    subtotal_display        = serializers.SerializerMethodField()
    discount_total_display  = serializers.SerializerMethodField()
    tax_total_display       = serializers.SerializerMethodField()
    total_display           = serializers.SerializerMethodField()
    cashier_name            = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id", "status",
            "cashier", "cashier_name",
            "subtotal_pence", "subtotal_display",
            "discount_total_pence", "discount_total_display",
            "tax_total_pence", "tax_total_display",
            "total_pence", "total_display",
            "cash_tendered_pence", "change_given_pence",
            "payment_method",
            "loyalty_points_earned", "loyalty_points_redeemed",
            "age_verified", "age_verification_id_type",
            "receipt_number", "notes",
            "items",
            "created_at", "updated_at", "paid_at", "voided_at",
        ]
        read_only_fields = fields

    def get_subtotal_display(self, obj):
        return f"£{obj.subtotal_pence / 100:.2f}"

    def get_discount_total_display(self, obj):
        return f"-£{obj.discount_total_pence / 100:.2f}"

    def get_tax_total_display(self, obj):
        return f"£{obj.tax_total_pence / 100:.2f}"

    def get_total_display(self, obj):
        return f"£{obj.total_pence / 100:.2f}"

    def get_cashier_name(self, obj):
        if obj.cashier:
            return f"{obj.cashier.first_name} {obj.cashier.last_name}".strip()
        return None


class AddItemSerializer(serializers.Serializer):
    variant_id = serializers.IntegerField()
    quantity   = serializers.IntegerField(min_value=1, default=1)
    weight_kg  = serializers.DecimalField(
        max_digits=10, decimal_places=3, required=False, allow_null=True, min_value=0.001
    )


class CheckoutSerializer(serializers.Serializer):
    payment_method          = serializers.ChoiceField(choices=Order.PAYMENT_METHOD_CHOICES)
    cash_tendered_pence     = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    age_verified            = serializers.BooleanField(default=False)
    age_verification_id_type = serializers.CharField(required=False, allow_blank=True, default="")


class VoidSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")