from django.conf import settings
from django.core.checks import Warning

from .origins import origin_key


def check_origin_settings(app_configs, **kwargs):
    warnings = [
        Warning(
            f"Entry {index} is invalid and will be ignored.",
            hint="Use an HTTP(S) origin with a host and optional port.",
            obj="PROBE_ALLOWED_ORIGINS",
            id="inspection.W001",
        )
        for index, origin in enumerate(settings.PROBE_ALLOWED_ORIGINS, start=1)
        if origin_key(origin) is None
    ]
    managed_origin = settings.MANAGED_PROBE_ORIGIN
    if managed_origin and origin_key(managed_origin) is None:
        warnings.append(
            Warning(
                "The configured origin is invalid and managed probes are disabled.",
                hint="Use an HTTP(S) origin with a host and optional port.",
                obj="MANAGED_PROBE_ORIGIN",
                id="inspection.W002",
            )
        )
    return warnings


def check_manage_api_auth(app_configs, **kwargs):
    if settings.MANAGE_API_AUTH:
        return []
    return [
        Warning(
            "Management API authentication is disabled.",
            hint="This mode is for loopback acceptance. Set MANAGE_API_AUTH=1 to require credentials.",
            obj="MANAGE_API_AUTH",
            id="inspection.W003",
        )
    ]
