import secrets
from datetime import date, datetime, time, timedelta

from celery import shared_task
from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import OperationalError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import DailyHealthRate, InspectionResult, Service


@shared_task(autoretry_for=(OperationalError,), retry_backoff=True)
def rotate_probe_tokens():
    key = settings.PROBE_TOKEN_ENCRYPTION_KEY
    if not key:
        raise ImproperlyConfigured("Set PROBE_TOKEN_ENCRYPTION_KEY before rotating tokens.")
    try:
        cipher = Fernet(key)
    except ValueError:
        raise ImproperlyConfigured("PROBE_TOKEN_ENCRYPTION_KEY must be a valid Fernet key.") from None

    now = timezone.localtime(timezone.now(), timezone.get_default_timezone())
    window = now.replace(hour=now.hour // 8 * 8, minute=0, second=0, microsecond=0)
    eligible = Service.objects.filter(
        Q(token_rotation_window__isnull=True) | Q(token_rotation_window__lt=window)
    )
    rotated = 0
    for service_id in list(eligible.values_list("pk", flat=True)):
        ciphertext = cipher.encrypt(secrets.token_urlsafe(32).encode("ascii"))
        rotated += eligible.filter(pk=service_id).update(
            token_ciphertext=ciphertext, token_rotation_window=window
        )
    return rotated


@shared_task(autoretry_for=(OperationalError,), retry_backoff=True)
def write_daily_health_rates(report_date=None):
    zone = timezone.get_default_timezone()
    today = timezone.localdate(timezone=zone)
    day = date.fromisoformat(report_date) if report_date else today - timedelta(days=1)
    if day >= today:
        raise ValueError("The report date must be a completed calendar day.")

    start = datetime.combine(day, time.min, tzinfo=zone)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
    in_window = Q(inspections__checked_at__gte=start, inspections__checked_at__lt=end)
    with transaction.atomic():
        services = Service.objects.select_related("environment", "team").annotate(
            total=Count("inspections", filter=in_window),
            successful=Count(
                "inspections",
                filter=in_window & Q(inspections__outcome=InspectionResult.Outcome.HEALTHY),
            ),
        )
        rows = [
            DailyHealthRate(
                service_id=service.pk,
                date=day,
                environment_name=service.environment.name,
                team_name=service.team.name,
                successful_checks=service.successful,
                total_checks=service.total,
            )
            for service in services
        ]
        DailyHealthRate.objects.bulk_create(
            rows,
            update_conflicts=True,
            unique_fields=["date", "service"],
            update_fields=["environment_name", "team_name", "successful_checks", "total_checks"],
        )
    return len(rows)
