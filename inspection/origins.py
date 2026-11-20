import re
from ipaddress import IPv4Address, IPv6Address
from unicodedata import category
from urllib.parse import urlsplit

from django.conf import settings


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
    elif not _valid_dns_host(host):
        return None
    return parsed.scheme, host, port


def _valid_dns_host(host):
    try:
        hostname = host.removesuffix(".").encode("idna").decode("ascii")
        labels = hostname.split(".")
        if len(labels) > 1 and all(label.isdigit() for label in labels):
            IPv4Address(hostname)
    except (UnicodeError, ValueError):
        return False
    return len(hostname) <= 253 and all(_DNS_LABEL.fullmatch(label) for label in labels)


def allowed_origin_keys():
    return {
        key for value in settings.PROBE_ALLOWED_ORIGINS
        if (key := origin_key(value)) is not None
    }
