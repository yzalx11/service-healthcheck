from http.client import HTTPConnection, HTTPException, HTTPSConnection
from time import perf_counter
from urllib.parse import urlsplit

from django.conf import settings

from .models import InspectionResult


def check_service(service):
    origin = urlsplit(service.origin)
    connection_type = HTTPSConnection if origin.scheme == "https" else HTTPConnection
    connection = connection_type(
        origin.hostname, origin.port, timeout=settings.PROBE_TIMEOUT_SECONDS
    )
    started_at = perf_counter()
    status_code = None
    outcomes = InspectionResult.Outcome

    try:
        connection.request("GET", service.health_path)
        with connection.getresponse() as response:
            status_code = response.status
        outcome = outcomes.HEALTHY if 200 <= status_code < 300 else outcomes.HTTP_ERROR
    except TimeoutError:
        outcome = outcomes.TIMEOUT
    except (OSError, HTTPException):
        outcome = outcomes.CONNECTION_ERROR
    finally:
        connection.close()

    return InspectionResult.objects.create(
        service=service,
        outcome=outcome,
        status_code=status_code,
        duration_ms=round((perf_counter() - started_at) * 1000),
    )
