from django.db import models


class Environment(models.Model):
    class Name(models.TextChoices):
        DEV = "dev"
        TEST = "test"
        PROD = "prod"

    name = models.CharField(max_length=4, choices=Name.choices, unique=True)

    class Meta:
        ordering = ["id"]


class Team(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["id"]


class Service(models.Model):
    name = models.CharField(max_length=100)
    environment = models.ForeignKey(Environment, on_delete=models.PROTECT)
    team = models.ForeignKey(Team, on_delete=models.PROTECT)
    origin = models.URLField()
    health_path = models.CharField(max_length=255, default="/health")

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["environment", "name"], name="unique_service_name_per_environment"
            )
        ]


class InspectionResult(models.Model):
    class Outcome(models.TextChoices):
        HEALTHY = "healthy"
        HTTP_ERROR = "http_error"
        TIMEOUT = "timeout"
        CONNECTION_ERROR = "connection_error"

    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="inspections")
    checked_at = models.DateTimeField(auto_now_add=True)
    outcome = models.CharField(max_length=16, choices=Outcome.choices)
    status_code = models.PositiveSmallIntegerField(null=True)
    duration_ms = models.PositiveIntegerField()

    class Meta:
        indexes = [models.Index(fields=["service", "checked_at"], name="inspection_service_time")]
