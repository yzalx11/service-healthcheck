from datetime import datetime, timedelta
from http.client import HTTPConnection
from unittest.mock import patch
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from django.test import LiveServerTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from .models import Environment, Service, Team
from .tasks import rotate_probe_tokens


class ManagedProbeTests(LiveServerTestCase):
    host = "127.0.0.1"

    def test_probe_sends_current_token_and_rotated_token_replaces_old_token(self):
        key = Fernet.generate_key()
        cipher = Fernet(key)
        now = datetime(2026, 11, 20, 8, tzinfo=ZoneInfo("Asia/Shanghai"))
        service = Service.objects.create(
            name="managed",
            environment=Environment.objects.create(name="test"),
            team=Team.objects.create(name="Platform"),
            origin=self.live_server_url,
        )
        service.health_path = reverse("managed-probe-health", args=[service.pk])
        service.save(update_fields=["health_path"])
        origin = urlsplit(self.live_server_url)

        def target_status(token=None):
            connection = HTTPConnection(origin.hostname, origin.port, timeout=3)
            try:
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                connection.request("GET", service.health_path, headers=headers)
                with connection.getresponse() as response:
                    return response.status
            finally:
                connection.close()

        def check():
            response = APIClient().post(f"/api/services/{service.pk}/check/")
            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(response.data["status_code"], 204)
            self.assertEqual(response.data["outcome"], "healthy")

        with override_settings(
            MANAGED_PROBE_ORIGIN=self.live_server_url.upper() + "/",
            PROBE_ALLOWED_ORIGINS=[self.live_server_url.upper() + "/"],
            PROBE_TOKEN_ENCRYPTION_KEY=key,
        ), patch("django.utils.timezone.now", return_value=now) as clock:
            self.assertEqual(rotate_probe_tokens.run(), 1)
            service.refresh_from_db()
            old = cipher.decrypt(service.token_ciphertext).decode("ascii")
            self.assertEqual(target_status(), 401)
            self.assertEqual(target_status(old), 204)
            check()

            clock.return_value = now + timedelta(hours=8)
            self.assertEqual(rotate_probe_tokens.run(), 1)
            self.assertEqual(target_status(old), 401)
            check()
