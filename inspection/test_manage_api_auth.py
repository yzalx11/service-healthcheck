from base64 import b64encode
from io import StringIO

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from .models import Environment, Service, Team


class ManageApiConfigurationTests(SimpleTestCase):
    def test_disabled_auth_warns_only_on_deploy_check_and_allows_anonymous_access(self):
        with self.settings(DEBUG=False, MANAGE_API_AUTH=False):
            regular_output = StringIO()
            call_command("check", stdout=StringIO(), stderr=regular_output)
            self.assertNotIn("inspection.W003", regular_output.getvalue())
            output = StringIO()
            call_command("check", "--deploy", stdout=StringIO(), stderr=output)
            self.assertIn("MANAGE_API_AUTH: (inspection.W003)", output.getvalue())
            self.assertEqual(self.client.get("/api/").status_code, 200)

    def test_enabled_auth_does_not_warn_on_deploy_check_with_debug_on(self):
        with self.settings(DEBUG=True, MANAGE_API_AUTH=True):
            output = StringIO()
            call_command("check", "--deploy", stdout=StringIO(), stderr=output)
            self.assertNotIn("inspection.W003", output.getvalue())
            self.assertEqual(self.client.get("/api/").status_code, 401)


@override_settings(MANAGE_API_AUTH=True)
class ManageApiAuthenticationTests(TestCase):
    username = "operator"
    password = "test-local-password"

    @classmethod
    def setUpTestData(cls):
        get_user_model().objects.create_user(username=cls.username, password=cls.password)
        cls.service = Service.objects.create(
            name="gateway", environment=Environment.objects.create(name="dev"),
            team=Team.objects.create(name="Platform"), origin="http://127.0.0.1:9001",
        )

    def basic_header(self, password):
        credentials = b64encode(f"{self.username}:{password}".encode("utf-8")).decode("ascii")
        return f"Basic {credentials}"

    def test_anonymous_requests_cannot_read_or_write_management_api(self):
        requests = (
            ("get", "/api/"),
            ("get", "/api/environments/"),
            ("get", "/api/teams/"),
            ("get", "/api/services/"),
            ("get", "/api/reports/"),
            ("get", reverse("service-inspections", args=[self.service.pk])),
            ("post", reverse("service-check", args=[self.service.pk])),
            ("delete", reverse("service-detail", args=[self.service.pk])),
        )
        for method, url in requests:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, 401)
                self.assertTrue(response["WWW-Authenticate"].startswith("Basic "))
        self.assertTrue(Service.objects.filter(pk=self.service.pk).exists())

    def test_valid_django_credentials_allow_read_and_write(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=self.basic_header("wrong-password"))
        self.assertEqual(client.get("/api/").status_code, 401)

        client.credentials(HTTP_AUTHORIZATION=self.basic_header(self.password))
        self.assertEqual(client.get("/api/reports/").status_code, 200)
        self.assertEqual(client.get(reverse("service-inspections", args=[self.service.pk])).status_code, 200)
        response = client.post("/api/teams/", {"name": "Operations"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(Team.objects.filter(name="Operations").exists())

    def test_managed_probe_token_and_management_credentials_are_independent(self):
        key = Fernet.generate_key()
        token = "test-probe-token"
        url = reverse("managed-probe-health", args=[self.service.pk])
        self.service.health_path = url
        self.service.token_ciphertext = Fernet(key).encrypt(token.encode("ascii"))
        self.service.save(update_fields=["health_path", "token_ciphertext"])

        with self.settings(MANAGED_PROBE_ORIGIN=self.service.origin, PROBE_TOKEN_ENCRYPTION_KEY=key):
            self.assertEqual(self.client.get(url).status_code, 401)
            response = self.client.get(url, HTTP_AUTHORIZATION=self.basic_header(self.password))
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response["WWW-Authenticate"], "Bearer")
            self.assertEqual(self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {token}").status_code, 204)
            self.assertEqual(
                self.client.get("/api/services/", HTTP_AUTHORIZATION=f"Bearer {token}").status_code, 401
            )
