from rest_framework import serializers


class DateRangeQuerySerializer(serializers.Serializer):
    date_from = serializers.DateField()
    date_to = serializers.DateField()

    def validate(self, data):
        if data["date_to"] < data["date_from"]:
            raise serializers.ValidationError({"date_to": "date_to cannot be before date_from."})
        return data


class SalesDashboardQuerySerializer(DateRangeQuerySerializer):
    department = serializers.IntegerField(required=False, allow_null=True, default=None)


class DepartmentPerformanceQuerySerializer(DateRangeQuerySerializer):
    pass


class BestSellersQuerySerializer(DateRangeQuerySerializer):
    department = serializers.IntegerField(required=False, allow_null=True, default=None)
    metric = serializers.ChoiceField(choices=["units", "margin"], default="units")
    limit = serializers.IntegerField(required=False, default=20, min_value=1, max_value=200)


class WasteCostQuerySerializer(DateRangeQuerySerializer):
    department = serializers.IntegerField(required=False, allow_null=True, default=None)


class StaffPerformanceQuerySerializer(DateRangeQuerySerializer):
    staff = serializers.IntegerField(required=False, allow_null=True, default=None)
