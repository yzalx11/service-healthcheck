from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse


def token_cipher():
    key = settings.PROBE_TOKEN_ENCRYPTION_KEY
    if not key:
        raise ImproperlyConfigured("Set PROBE_TOKEN_ENCRYPTION_KEY before using probe tokens.")
    try:
        return Fernet(key)
    except ValueError:
        raise ImproperlyConfigured("PROBE_TOKEN_ENCRYPTION_KEY must be a valid Fernet key.") from None


def is_managed_probe(service):
    if service.origin != settings.MANAGED_PROBE_ORIGIN:
        return False
    origin = urlsplit(service.origin)
    if origin.scheme != "https" and origin.hostname not in {"127.0.0.1", "::1"}:
        return False
    return service.health_path == reverse("managed-probe-health", args=[service.pk])
