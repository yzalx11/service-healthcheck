from rest_framework import serializers

from .models import DailyHealthRate, Environment, InspectionResult, Service, Team
from .origins import allowed_origin_keys, origin_key


class EnvironmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Environment
        fields = ["id", "name"]


class TeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = ["id", "name"]


class ServiceSerializer(serializers.ModelSerializer):
    origin = serializers.CharField(max_length=200, trim_whitespace=False)

    class Meta:
        model = Service
        fields = ["id", "name", "environment", "team", "origin", "health_path"]

    def update(self, instance, validated_data):
        for field, value in validated_data.items():
            setattr(instance, field, value)
        # A scheduled rotation may have updated the credential since this instance was read.
        instance.save(update_fields=validated_data.keys())
        return instance

    def validate_origin(self, value):
        key = origin_key(value)
        if key is None:
            raise serializers.ValidationError(
                "Use an HTTP(S) origin with a valid host and optional port, without a path or credentials."
            )
        if key not in allowed_origin_keys():
            raise serializers.ValidationError("Origin is not enabled for inspections.")
        return value.removesuffix("/")

    def validate_health_path(self, value):
        if (
            not value.startswith("/")
            or value.startswith("//")
            or "\\" in value
            or "#" in value
            or any(not 33 <= ord(character) <= 126 for character in value)
        ):
            raise serializers.ValidationError("Use an ASCII HTTP path beginning with a single '/'.")
        return value


class InspectionResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = InspectionResult
        fields = ["id", "service", "checked_at", "outcome", "status_code", "duration_ms"]
        read_only_fields = fields


class DailyHealthReportFilterSerializer(serializers.Serializer):
    date = serializers.DateField(required=False)
    environment = serializers.ChoiceField(choices=Environment.Name.choices, required=False)
    team = serializers.CharField(max_length=100, trim_whitespace=False, required=False)


class DailyHealthReportSerializer(serializers.ModelSerializer):
    health_rate = serializers.FloatField(read_only=True, allow_null=True)

    class Meta:
        model = DailyHealthRate
        fields = [
            "date", "service", "environment_name", "team_name",
            "successful_checks", "total_checks", "health_rate",
        ]
        read_only_fields = fields
