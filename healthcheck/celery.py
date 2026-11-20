import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "healthcheck.settings")

app = Celery("healthcheck")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
app.conf.beat_schedule = {
    "rotate-probe-tokens": {
        "task": "inspection.tasks.rotate_probe_tokens",
        "schedule": crontab(minute=0, hour="*/8"),
    },
    "catch-up-daily-health-rates": {
        "task": "inspection.tasks.catch_up_daily_health_rates",
        "schedule": crontab(minute=0),
    },
}
