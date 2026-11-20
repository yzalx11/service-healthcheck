from unittest.mock import patch

from cryptography.fernet import Fernet
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import Environment, InspectionResult, Service, Team
from .origins import origin_key


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

    def test_service_name_is_unique_per_environment(self):
        payload = {**self.payload, "name": self.service.name}
        response = self.client.post("/api/services/", payload, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("non_field_errors", response.data)

        other = Environment.objects.create(name="test")
        response = self.client.post(
            "/api/services/", {**payload, "environment": other.pk}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_service_list_paginates_in_id_order(self):
        Service.objects.bulk_create([
            Service(
                name=f"service-{index}", environment=self.environment, team=self.team,
                origin=self.service.origin,
            )
            for index in range(26)
        ])
        first = self.client.get("/api/services/")
        second = self.client.get("/api/services/?page=2")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data["count"], 27)
        self.assertEqual((len(first.data["results"]), len(second.data["results"])), (20, 7))
        all_items = first.data["results"] + second.data["results"]
        self.assertEqual(
            [item["id"] for item in all_items],
            list(Service.objects.order_by("id").values_list("id", flat=True)),
        )

    def test_check_for_missing_service_returns_404_without_inspection(self):
        missing_pk = self.service.pk + 1
        with patch("inspection.views.check_service") as check_service:
            response = self.client.post(f"/api/services/{missing_pk}/check/")
        self.assertEqual(response.status_code, 404)
        check_service.assert_not_called()
        self.assertFalse(InspectionResult.objects.exists())

    def test_put_rejects_disallowed_origin_and_preserves_existing_service(self):
        payload = {**self.payload, "origin": "http://127.0.0.1:9002", "health_path": "/ready"}
        response = self.client.put(self.service_url, payload, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("origin", response.data)
        self.service.refresh_from_db()
        self.assertEqual(self.service.origin, "http://127.0.0.1:9001")
        self.assertEqual(self.service.health_path, "/health")
        self.assertEqual(self.service.name, "existing")

    def test_environment_rejects_unknown_name(self):
        response = self.client.post("/api/environments/", {"name": "staging"}, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["name"][0].code, "invalid_choice")
        self.assertFalse(Environment.objects.filter(name="staging").exists())

    def test_origin_comparison_ignores_scheme_and_hostname_case(self):
        with override_settings(PROBE_ALLOWED_ORIGINS=["HTTP://LOCALHOST:9001/"]):
            payload = {**self.payload, "origin": "http://localhost:9001"}
            response = self.client.post("/api/services/", payload, format="json")
            self.assertEqual(response.status_code, 201, response.data)

        with override_settings(PROBE_ALLOWED_ORIGINS=["http://localhost:9001"]):
            payload = {**self.payload, "origin": "HTTP://LOCALHOST:9001/"}
            url = f"/api/services/{response.data['id']}/"
            response = self.client.put(url, payload, format="json")
            self.assertEqual(response.status_code, 200, response.data)

    def test_ipv6_allowlist_matches_compressed_and_expanded_forms(self):
        compressed = "http://[::1]:8080"
        expanded = "http://[0:0:0:0:0:0:0:1]:8080"
        for allowed, submitted in ((compressed, expanded), (expanded, compressed)):
            with self.subTest(allowed=allowed), override_settings(PROBE_ALLOWED_ORIGINS=[allowed]):
                payload = {**self.payload, "origin": submitted}
                response = self.client.put(self.service_url, payload, format="json")
                self.assertEqual(response.status_code, 200, response.data)

    def test_expanded_ipv6_loopback_sends_managed_probe_token(self):
        origin = "http://[0:0:0:0:0:0:0:1]:8080"
        path = f"/probe-health/{self.service.pk}/"
        key = Fernet.generate_key()
        self.service.origin = origin
        self.service.health_path = path
        self.service.token_ciphertext = Fernet(key).encrypt(b"test-token")
        self.service.save(update_fields=["origin", "health_path", "token_ciphertext"])

        with override_settings(
            MANAGED_PROBE_ORIGIN=origin,
            PROBE_ALLOWED_ORIGINS=[origin],
            PROBE_TOKEN_ENCRYPTION_KEY=key,
        ), patch("inspection.probes.HTTPConnection") as connection:
            upstream = connection.return_value
            upstream.getresponse.return_value.__enter__.return_value.status = 204
            response = self.client.post(self.service_url + "check/")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status_code"], 204)
        upstream.request.assert_called_once_with(
            "GET", path, headers={"Authorization": "Bearer test-token"},
        )

    def test_short_hostname_can_be_registered_and_checked(self):
        with override_settings(PROBE_ALLOWED_ORIGINS=["HTTP://PAYSVC:8080/"]):
            created = self.client.post(
                "/api/services/", {**self.payload, "origin": "http://paysvc:8080"},
                format="json",
            )
            self.assertEqual(created.status_code, 201, created.data)
            service_id = created.data["id"]
            with patch("inspection.probes.HTTPConnection") as connection:
                upstream = connection.return_value
                upstream.getresponse.return_value.__enter__.return_value.status = 200
                checked = self.client.post(f"/api/services/{service_id}/check/")

        self.assertEqual(checked.status_code, 201, checked.data)
        connection.assert_called_once_with("paysvc", 8080, timeout=3)
        upstream.request.assert_called_once_with("GET", "/health", headers={})
        result = InspectionResult.objects.get(service_id=service_id)
        self.assertEqual((result.outcome, result.status_code), ("healthy", 200))

    def test_idn_allowlist_matches_unicode_and_punycode_in_both_directions(self):
        unicode_origin = "http://例子.中国:8080"
        ascii_origin = "http://xn--fsqu00a.xn--fiqs8s:8080"
        for allowed, submitted in ((ascii_origin, unicode_origin), (unicode_origin, ascii_origin)):
            with self.subTest(allowed=allowed), override_settings(PROBE_ALLOWED_ORIGINS=[allowed]):
                response = self.client.put(
                    self.service_url, {**self.payload, "origin": submitted}, format="json"
                )
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data["origin"], submitted)

                with patch("inspection.probes.HTTPConnection") as connection:
                    upstream = connection.return_value
                    upstream.getresponse.return_value.__enter__.return_value.status = 200
                    checked = self.client.post(self.service_url + "check/")
                self.assertEqual(checked.status_code, 201, checked.data)
                self.assertEqual(checked.data["outcome"], "healthy")

    def test_short_hostname_trailing_dot_is_preserved_and_requires_exact_allowlist(self):
        payload = {**self.payload, "origin": "https://svc-01.:8443/"}
        with override_settings(PROBE_ALLOWED_ORIGINS=["https://svc-01:8443"]):
            rejected = self.client.post("/api/services/", payload, format="json")
        self.assertEqual(rejected.status_code, 400, rejected.data)

        with override_settings(PROBE_ALLOWED_ORIGINS=["https://SVC-01.:8443"]):
            created = self.client.post("/api/services/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(Service.objects.get(pk=created.data["id"]).origin, "https://svc-01.:8443")

    def test_rejects_malformed_hosts_ports_and_raw_whitespace(self):
        invalid_origins = (
            "http://...:8080",
            "http://-bad:8080",
            "http://a..b:8080",
            "http://999.999.999.999:8080",
            "http://svc..:8080",
            "http://[gggg::1]:8080",
            "http://[::1]suffix:8080",
            "http://svc:",
            "http://svc:0",
            "http://svc:-1",
            "http://svc:65536",
            "http://svc:abc",
            "http://sv c:8080",
            "http://sv\tc:8080",
            "http://svc:80\n80",
            "http://svc:\x008080",
            " http://svc:8080",
        )
        for origin in invalid_origins:
            with self.subTest(origin=origin), override_settings(
                PROBE_ALLOWED_ORIGINS=[origin, "http://svc:8080"],
            ):
                self.assertIsNone(origin_key(origin))
                response = self.client.post(
                    "/api/services/", {**self.payload, "origin": origin}, format="json"
                )
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn("origin", response.data)
        self.assertEqual(Service.objects.count(), 1)

    def test_invalid_configured_origin_cannot_authorize_its_host(self):
        for configured in (
            "http://127.0.0.1:9001/health",
            "http://127.0.0.1:9001?query",
            "http://127.0.0.1:9001#fragment",
            "http://user@127.0.0.1:9001",
            "http://localhost:9001",
        ):
            with self.subTest(configured=configured), override_settings(
                PROBE_ALLOWED_ORIGINS=[configured],
            ):
                response = self.client.post("/api/services/", self.payload, format="json")
                self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(Service.objects.count(), 1)

    def test_omitted_and_explicit_ports_are_distinct_in_allowlist(self):
        with override_settings(PROBE_ALLOWED_ORIGINS=["http://localhost"]):
            response = self.client.post(
                "/api/services/", {**self.payload, "origin": "http://localhost:80"}, format="json"
            )
        self.assertEqual(response.status_code, 400, response.data)

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
