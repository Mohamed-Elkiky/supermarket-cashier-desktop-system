from rest_framework import serializers

from .models import Expense


class ExpenseSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True, default=None)
    recorded_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Expense
        fields = [
            "id", "category", "description", "amount_pence",
            "payee_name", "supplier", "supplier_name",
            "recorded_by", "recorded_by_name",
            "expense_date", "reference", "created_at",
        ]
        read_only_fields = fields

    def get_recorded_by_name(self, obj):
        return f"{obj.recorded_by.first_name} {obj.recorded_by.last_name}".strip()


class ExpenseWriteSerializer(serializers.Serializer):
    """
    Field-level validation only — the description-length and amount_pence
    business rules live in services.record_expense(), which produces the
    specific, helpful error messages.
    """
    category = serializers.ChoiceField(choices=Expense.Category.choices)
    description = serializers.CharField()
    amount_pence = serializers.IntegerField()
    payee_name = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    supplier_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    expense_date = serializers.DateField()
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")


class ExpenseSummaryQuerySerializer(serializers.Serializer):
    date_from = serializers.DateField()
    date_to = serializers.DateField()

    def validate(self, data):
        if data["date_to"] < data["date_from"]:
            raise serializers.ValidationError({"date_to": "date_to cannot be before date_from."})
        return data
