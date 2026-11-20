from django.test import SimpleTestCase, override_settings
from django.urls import path


def failing_view(request):
    raise RuntimeError("server-only error detail")


urlpatterns = [path("test-error/", failing_view)]


@override_settings(DEBUG=False)
class ErrorResponseTests(SimpleTestCase):
    def test_browsable_api_still_renders_with_debug_off(self):
        response = self.client.get("/api/", HTTP_ACCEPT="text/html")

        self.assertContains(response, "Django REST framework")
        self.assertContains(response, "/static/rest_framework/css/bootstrap.min.css")

    def test_unmatched_url_does_not_show_router_or_settings(self):
        response = self.client.get("/missing-private-route/", HTTP_ACCEPT="text/html")

        self.assertContains(response, "Not Found", status_code=404)
        for detail in ("missing-private-route", "healthcheck.urls", "URLconf", "DEBUG"):
            self.assertNotContains(response, detail, status_code=404)

    @override_settings(ROOT_URLCONF=__name__)
    def test_unhandled_exception_stays_in_server_log(self):
        self.client.raise_request_exception = False
        with self.assertLogs("django.request", level="ERROR") as logs:
            response = self.client.get("/test-error/", HTTP_ACCEPT="text/html")

        self.assertContains(response, "Server Error", status_code=500)
        for detail in ("server-only error detail", "test-error", "Traceback", "SECRET_KEY"):
            self.assertNotContains(response, detail, status_code=500)
        self.assertIsInstance(logs.records[0].exc_info[1], RuntimeError)
        self.assertIn("server-only error detail", logs.output[0])
