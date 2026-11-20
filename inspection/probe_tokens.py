from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse

from .origins import origin_key


def token_cipher():
    key = settings.PROBE_TOKEN_ENCRYPTION_KEY
    if not key:
        raise ImproperlyConfigured("Set PROBE_TOKEN_ENCRYPTION_KEY before using probe tokens.")
    try:
        return Fernet(key)
    except ValueError:
        raise ImproperlyConfigured("PROBE_TOKEN_ENCRYPTION_KEY must be a valid Fernet key.") from None


def is_managed_probe(service):
    key = origin_key(service.origin)
    if key is None or key != origin_key(settings.MANAGED_PROBE_ORIGIN):
        return False
    scheme, host, _ = key
    if scheme != "https" and host not in {"127.0.0.1", "::1"}:
        return False
    return service.health_path == reverse("managed-probe-health", args=[service.pk])
