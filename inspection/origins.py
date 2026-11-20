import re
from ipaddress import IPv4Address, IPv6Address
from unicodedata import category
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError


_AUTHORITY = re.compile(r"(?:\[[0-9a-fA-F:.]+\]|[^:\[\]@]+)(?::[0-9]+)?")
_DNS_LABEL = re.compile(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?")


def origin_key(value):
    if not isinstance(value, str) or not value:
        return None
    # urlsplit discards some whitespace and controls before parsing.
    if any(
        character in "?#\\" or character.isspace() or category(character) in {"Cc", "Cf"}
        for character in value
    ):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None

    if (
        parsed.scheme not in {"http", "https"}
        or not _AUTHORITY.fullmatch(parsed.netloc)
        or port == 0
        or parsed.path not in {"", "/"}
    ):
        return None

    host = parsed.hostname
    if parsed.netloc.startswith("["):
        host = IPv6Address(host).compressed
    else:
        host = _dns_host_key(host)
        if host is None:
            return None
    return parsed.scheme, host, port


def _dns_host_key(host):
    try:
        hostname = host.removesuffix(".").encode("idna").decode("ascii").lower()
        labels = hostname.split(".")
        if len(labels) > 1 and all(label.isdigit() for label in labels):
            IPv4Address(hostname)
    except (UnicodeError, ValueError):
        return None
    if len(hostname) > 253 or not all(_DNS_LABEL.fullmatch(label) for label in labels):
        return None
    return hostname + "." if host.endswith(".") else hostname


def validate_origin_syntax(value):
    if origin_key(value) is None:
        raise ValidationError(
            "Use an HTTP(S) origin with a valid host and optional port, without a path or credentials.",
            code="invalid",
        )


def allowed_origin_keys():
    return {
        key for value in settings.PROBE_ALLOWED_ORIGINS
        if (key := origin_key(value)) is not None
    }
