from rest_framework import serializers

from .models import Customer, LoyaltyAccount, LoyaltyTransaction


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = [
            "id", "first_name", "last_name", "email", "phone",
            "date_of_birth", "address_line1", "address_line2", "city", "postcode",
            "allergen_preferences", "marketing_consent", "marketing_consent_at",
            "is_active", "created_at", "updated_at",
        ]
        read_only_fields = fields


class CustomerWriteSerializer(serializers.Serializer):
    """
    Field-level validation only — Customer creation/update (including the
    auto-created LoyaltyAccount) lives in services.create_customer()/
    update_customer().
    """
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    email = serializers.EmailField(required=False, allow_null=True, default=None)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    date_of_birth = serializers.DateField(required=False, allow_null=True, default=None)
    address_line1 = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True, default=None)
    address_line2 = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True, default=None)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True, allow_null=True, default=None)
    postcode = serializers.CharField(max_length=20, required=False, allow_blank=True, allow_null=True, default=None)
    allergen_preferences = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list,
    )
    marketing_consent = serializers.BooleanField(default=False)


class LoyaltyTransactionSerializer(serializers.ModelSerializer):
    performed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = LoyaltyTransaction
        fields = [
            "id", "transaction_type", "points", "order",
            "reason", "performed_by", "performed_by_name", "created_at",
        ]
        read_only_fields = fields

    def get_performed_by_name(self, obj):
        if obj.performed_by:
            return f"{obj.performed_by.first_name} {obj.performed_by.last_name}".strip()
        return None


class LoyaltyAccountSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    transactions = LoyaltyTransactionSerializer(many=True, read_only=True)

    class Meta:
        model = LoyaltyAccount
        fields = [
            "id", "customer", "customer_name", "tier",
            "lifetime_spend_pence", "points_balance",
            "transactions", "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_customer_name(self, obj):
        return f"{obj.customer.first_name} {obj.customer.last_name}".strip()


class RedeemPointsWriteSerializer(serializers.Serializer):
    points = serializers.IntegerField(min_value=1)


class AdjustPointsWriteSerializer(serializers.Serializer):
    points = serializers.IntegerField()
    reason = serializers.CharField()


class BasketConflictCheckSerializer(serializers.Serializer):
    customer_id = serializers.IntegerField()
    variant_ids = serializers.ListField(child=serializers.IntegerField(), min_length=1)
