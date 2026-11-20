import os
from pathlib import Path

from django.core.management.utils import get_random_secret_key

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or get_random_secret_key()
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
MANAGE_API_AUTH = os.environ.get("MANAGE_API_AUTH", "0") == "1"
ALLOWED_HOSTS = [
    host for value in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")
    if (host := value.strip())
] or ["localhost", "127.0.0.1", "[::1]"]
ROOT_URLCONF = "healthcheck.urls"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "inspection",
]
MIDDLEWARE = [
    "healthcheck.middleware.RequestTimingMiddleware",
    "django.middleware.common.CommonMiddleware",
]
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"app_console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "healthcheck.request_timing": {
            "handlers": ["app_console"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["app_console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}
TEMPLATES = [
    {"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True}
]
STATIC_URL = "/static/"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
TIME_ZONE = "Asia/Shanghai"
USE_TZ = True
PROBE_ALLOWED_ORIGINS = os.environ.get(
    "PROBE_ALLOWED_ORIGINS", "http://127.0.0.1:9001"
).split()
PROBE_TIMEOUT_SECONDS = 3
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_IGNORE_RESULT = True
PROBE_TOKEN_ENCRYPTION_KEY = os.environ.get("PROBE_TOKEN_ENCRYPTION_KEY")
MANAGED_PROBE_ORIGIN = os.environ.get("MANAGED_PROBE_ORIGIN")
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.BasicAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["inspection.permissions.ManageApiPermission"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}
