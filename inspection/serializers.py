from urllib.parse import urlsplit

from django.conf import settings
from rest_framework import serializers

from .models import Environment, InspectionResult, Service, Team


def origin_is_allowed(origin):
    return origin in settings.PROBE_ALLOWED_ORIGINS


class EnvironmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Environment
        fields = ["id", "name"]


class TeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = ["id", "name"]


class ServiceSerializer(serializers.ModelSerializer):
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
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as exc:
            raise serializers.ValidationError("Invalid origin.") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or port == 0
            or parsed.path not in {"", "/"}
            or "?" in value
            or "#" in value
            or "\\" in value
        ):
            raise serializers.ValidationError("Use an HTTP(S) origin without a path or credentials.")
        origin = value.rstrip("/")
        if not origin_is_allowed(origin):
            raise serializers.ValidationError("Origin is not enabled for inspections.")
        return origin

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
