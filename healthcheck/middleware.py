import logging
from time import perf_counter_ns


logger = logging.getLogger("healthcheck.request_timing")


class RequestTimingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started_at = perf_counter_ns()
        response = self.get_response(request)
        duration_ms = (perf_counter_ns() - started_at) / 1_000_000

        timing = f"app;dur={duration_ms:.3f}"
        existing_timing = response.get("Server-Timing")
        response["Server-Timing"] = f"{existing_timing}, {timing}" if existing_timing else timing

        match = request.resolver_match
        route = match.route if match is not None else "<unmatched>"
        logger.info(
            "method=%s route=%s status=%d duration_ms=%.3f",
            request.method, route, response.status_code, duration_ms,
        )
        return response
