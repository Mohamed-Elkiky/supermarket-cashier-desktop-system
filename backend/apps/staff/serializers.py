from decimal import Decimal

from rest_framework import serializers

from .models import ClockEvent, Rota, Staff


class StaffSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True, default=None)

    class Meta:
        model = Staff
        fields = [
            "id", "first_name", "last_name", "email", "phone", "role",
            "department", "department_name", "commission_rate", "hourly_wage",
            "is_active", "hired_at", "created_at", "updated_at",
        ]
        read_only_fields = fields


class StaffWriteSerializer(serializers.Serializer):
    """Field-level validation only — persistence lives in services.create_staff()/update_staff()."""
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    role = serializers.ChoiceField(choices=Staff.ROLE_CHOICES, default="cashier")
    department_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    commission_rate = serializers.DecimalField(max_digits=5, decimal_places=4, required=False, default=Decimal("0"))
    hourly_wage = serializers.DecimalField(max_digits=8, decimal_places=2, required=False, default=Decimal("0"))
    hired_at = serializers.DateField(required=False, allow_null=True, default=None)
    is_active = serializers.BooleanField(required=False, default=True)


class ClockEventSerializer(serializers.ModelSerializer):
    staff_name = serializers.SerializerMethodField()

    class Meta:
        model = ClockEvent
        fields = ["id", "staff", "staff_name", "event_type", "event_at", "was_offline", "created_at"]
        read_only_fields = fields

    def get_staff_name(self, obj):
        return f"{obj.staff.first_name} {obj.staff.last_name}".strip()


class ClockInOutWriteSerializer(serializers.Serializer):
    was_offline = serializers.BooleanField(default=False)


class RotaSerializer(serializers.ModelSerializer):
    staff_name = serializers.SerializerMethodField()
    department_name = serializers.CharField(source="department.name", read_only=True, default=None)

    class Meta:
        model = Rota
        fields = [
            "id", "staff", "staff_name", "department", "department_name",
            "week_commencing", "shift_date", "shift_start", "shift_end",
            "notes", "created_by", "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_staff_name(self, obj):
        return f"{obj.staff.first_name} {obj.staff.last_name}".strip()


class RotaWriteSerializer(serializers.Serializer):
    """Field-level validation only — shift_end > shift_start and the Monday
    rule for week_commencing live in services.create_rota_entry()/update_rota_entry()."""
    staff_id = serializers.IntegerField()
    department_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    week_commencing = serializers.DateField()
    shift_date = serializers.DateField()
    shift_start = serializers.TimeField()
    shift_end = serializers.TimeField()
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class RotaWeekQuerySerializer(serializers.Serializer):
    week_commencing = serializers.DateField()
    department = serializers.IntegerField(required=False, allow_null=True, default=None)


class PayrollExportQuerySerializer(serializers.Serializer):
    date_from = serializers.DateField()
    date_to = serializers.DateField()
    department = serializers.IntegerField(required=False, allow_null=True, default=None)

    def validate(self, data):
        if data["date_to"] < data["date_from"]:
            raise serializers.ValidationError({"date_to": "date_to cannot be before date_from."})
        return data
