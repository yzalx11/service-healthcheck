from unittest.mock import patch

from django.test import SimpleTestCase


class RequestTimingTests(SimpleTestCase):
    def test_success_logs_route_and_excludes_query_string(self):
        with patch("healthcheck.middleware.perf_counter_ns", side_effect=[0, 1_234_567]):
            with self.assertLogs("healthcheck.request_timing", level="INFO") as logs:
                response = self.client.get("/api/?token=not-for-logs", HTTP_ACCEPT="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Server-Timing"], "app;dur=1.235")
        self.assertEqual(
            logs.output,
            ["INFO:healthcheck.request_timing:method=GET route=api/ status=200 duration_ms=1.235"],
        )

    def test_unmatched_route_logs_404_and_still_has_timing(self):
        with patch("healthcheck.middleware.perf_counter_ns", side_effect=[0, 500_000]):
            with self.assertLogs("healthcheck.request_timing", level="INFO") as logs:
                response = self.client.get("/missing-route/")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response["Server-Timing"], "app;dur=0.500")
        self.assertEqual(
            logs.output,
            ["INFO:healthcheck.request_timing:method=GET route=<unmatched> status=404 duration_ms=0.500"],
        )
