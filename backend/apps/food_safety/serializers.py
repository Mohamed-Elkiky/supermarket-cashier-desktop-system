from rest_framework import serializers

from .models import CleaningLog, TemperatureLog


class TemperatureLogSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True)
    performed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = TemperatureLog
        fields = [
            "id", "unit_name", "department", "department_name",
            "temperature_celsius", "result", "corrective_action",
            "performed_by", "performed_by_name",
            "checked_at", "was_offline", "created_at",
        ]
        read_only_fields = fields

    def get_performed_by_name(self, obj):
        return f"{obj.performed_by.first_name} {obj.performed_by.last_name}".strip()


class TemperatureCheckWriteSerializer(serializers.Serializer):
    """
    Field-level validation only — the pass/fail determination and the
    fail-requires-corrective_action rule live in services.record_temperature_check().
    """
    unit_name = serializers.CharField(max_length=100)
    department_id = serializers.IntegerField()
    temperature_celsius = serializers.DecimalField(max_digits=5, decimal_places=2)
    corrective_action = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    checked_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    was_offline = serializers.BooleanField(default=False)


class CleaningLogSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True)
    performed_by_name = serializers.SerializerMethodField()
    alerted_manager_name = serializers.SerializerMethodField()

    class Meta:
        model = CleaningLog
        fields = [
            "id", "area_name", "department", "department_name",
            "scheduled_interval_hours", "result", "notes",
            "performed_by", "performed_by_name",
            "alerted_manager", "alerted_manager_name",
            "cleaned_at", "was_offline", "created_at",
        ]
        read_only_fields = fields

    def get_performed_by_name(self, obj):
        if obj.performed_by:
            return f"{obj.performed_by.first_name} {obj.performed_by.last_name}".strip()
        return None

    def get_alerted_manager_name(self, obj):
        if obj.alerted_manager:
            return f"{obj.alerted_manager.first_name} {obj.alerted_manager.last_name}".strip()
        return None


class CleaningSignoffWriteSerializer(serializers.Serializer):
    """
    Field-level validation only — the missed-requires-alerted_manager rule
    (and looking up that manager) lives in services.record_cleaning_signoff().
    """
    area_name = serializers.CharField(max_length=200)
    department_id = serializers.IntegerField()
    scheduled_interval_hours = serializers.IntegerField(default=4, min_value=1)
    result = serializers.ChoiceField(choices=CleaningLog.Result.choices)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    cleaned_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    was_offline = serializers.BooleanField(default=False)


class MissedChecksQuerySerializer(serializers.Serializer):
    department = serializers.IntegerField(required=False, allow_null=True)
    since = serializers.DateTimeField(required=False, allow_null=True, default=None)


class EhoExportQuerySerializer(serializers.Serializer):
    date_from = serializers.DateField()
    date_to = serializers.DateField()
    department = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, data):
        if data["date_to"] < data["date_from"]:
            raise serializers.ValidationError({"date_to": "date_to cannot be before date_from."})
        return data
