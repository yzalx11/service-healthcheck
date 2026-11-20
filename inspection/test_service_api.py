from unittest.mock import patch

from cryptography.fernet import Fernet
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import Environment, InspectionResult, Service, Team


@override_settings(PROBE_ALLOWED_ORIGINS=["http://127.0.0.1:9001/"])
class ServiceApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.environment = Environment.objects.create(name="dev")
        cls.team = Team.objects.create(name="Platform")
        cls.service = Service.objects.create(
            name="existing",
            environment=cls.environment,
            team=cls.team,
            origin="http://127.0.0.1:9001",
        )

    def setUp(self):
        self.client = APIClient()
        self.service_url = f"/api/services/{self.service.pk}/"
        self.payload = {
            "name": "new-service",
            "environment": self.environment.pk,
            "team": self.team.pk,
            "origin": "http://127.0.0.1:9001/",
            "health_path": "/health",
        }

    def test_service_crud_normalizes_allowed_origin(self):
        response = self.client.post("/api/services/", self.payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["origin"], "http://127.0.0.1:9001")
        url = f"/api/services/{response.data['id']}/"
        self.assertEqual(self.client.get(url).data["name"], "new-service")
        response = self.client.patch(url, {"health_path": "/ready"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.client.get(url).data["health_path"], "/ready")
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)

    def test_rejects_invalid_origins_and_health_paths(self):
        cases = {
            "origin": [
                "http://127.0.0.1:9002",
                "http://127.0.0.1:9001/health",
                "http://user@127.0.0.1:9001",
            ],
            "health_path": ["//health", "/健康", "/bad\\path"],
        }
        for field, invalid_values in cases.items():
            for value in invalid_values:
                with self.subTest(field=field, value=value):
                    response = self.client.post(
                        "/api/services/", {**self.payload, field: value}, format="json"
                    )
                    self.assertEqual(response.status_code, 400, response.data)
                    self.assertIn(field, response.data)
        self.assertEqual(Service.objects.count(), 1)

    def test_referenced_environment_and_team_cannot_be_deleted(self):
        for resource, pk in (("environments", self.environment.pk), ("teams", self.team.pk)):
            with self.subTest(resource=resource):
                url = f"/api/{resource}/{pk}/"
                self.assertEqual(self.client.delete(url).status_code, 409)
                self.assertEqual(self.client.get(url).status_code, 200)
        self.assertTrue(Service.objects.filter(pk=self.service.pk).exists())

    def test_removed_origin_blocks_existing_service_without_recording_inspection(self):
        with override_settings(PROBE_ALLOWED_ORIGINS=[]):
            with patch("inspection.views.check_service") as check_service:
                response = self.client.post(self.service_url + "check/")
        self.assertEqual(response.status_code, 409)
        check_service.assert_not_called()
        self.assertFalse(InspectionResult.objects.exists())

    def test_invalid_managed_credentials_return_503_without_recording_inspection(self):
        self.service.health_path = f"/probe-health/{self.service.pk}/"
        self.service.token_ciphertext = b"invalid ciphertext"
        self.service.save(update_fields=["health_path", "token_ciphertext"])
        for key in (None, Fernet.generate_key()):
            with self.subTest(key_configured=key is not None), override_settings(
                MANAGED_PROBE_ORIGIN=self.service.origin + "/",
                PROBE_TOKEN_ENCRYPTION_KEY=key,
            ):
                response = self.client.post(self.service_url + "check/")
                self.assertEqual(response.status_code, 503, response.data)
        self.assertFalse(InspectionResult.objects.exists())
