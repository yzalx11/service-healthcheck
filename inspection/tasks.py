import secrets
from datetime import date, datetime, time, timedelta

from celery import shared_task
from django.db import OperationalError, transaction
from django.db.models import Count, FilteredRelation, Max, Min, Q
from django.utils import timezone

from .models import DailyHealthRate, DailyHealthReportRun, InspectionResult, Service
from .probe_tokens import token_cipher


@shared_task(autoretry_for=(OperationalError,), retry_backoff=True)
def rotate_probe_tokens():
    cipher = token_cipher()

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
    return _write_report(day, zone)


def _write_report(day, zone):
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
    in_window = Q(inspections__checked_at__gte=start, inspections__checked_at__lt=end)
    with transaction.atomic():
        services = Service.objects.select_related("environment", "team").alias(
            daily_inspections=FilteredRelation("inspections", condition=in_window),
        ).annotate(
            total=Count("daily_inspections"),
            successful=Count(
                "daily_inspections",
                filter=Q(daily_inspections__outcome=InspectionResult.Outcome.HEALTHY),
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


@shared_task(autoretry_for=(OperationalError,), retry_backoff=True)
def catch_up_daily_health_rates():
    zone = timezone.get_default_timezone()
    yesterday = timezone.localdate(timezone=zone) - timedelta(days=1)
    last_completed = DailyHealthReportRun.objects.aggregate(last=Max("date"))["last"]
    if last_completed is not None:
        first_date = last_completed + timedelta(days=1)
    else:
        earliest = InspectionResult.objects.aggregate(first=Min("checked_at"))["first"]
        first_date = min(timezone.localdate(earliest, zone), yesterday) if earliest else yesterday

    completed = 0
    for offset in range(min(7, (yesterday - first_date).days + 1)):
        day = first_date + timedelta(days=offset)
        with transaction.atomic():
            _, created = DailyHealthReportRun.objects.get_or_create(date=day)
            if created:
                _write_report(day, zone)
                completed += 1
    return completed
