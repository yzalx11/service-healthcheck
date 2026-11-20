from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from healthcheck.celery import app

from .models import DailyHealthRate, Environment, InspectionResult, Service, Team
from .tasks import rotate_probe_tokens, write_daily_health_rates


class ScheduledTaskTests(TestCase):
    def test_beat_registers_both_tasks_at_shanghai_times(self):
        app.loader.import_default_modules()
        self.assertEqual(app.conf.timezone, "Asia/Shanghai")
        expected = {
            "rotate-probe-tokens": (rotate_probe_tokens.name, {0, 8, 16}),
            "write-daily-health-rates": (write_daily_health_rates.name, {0}),
        }
        for name, (task, hours) in expected.items():
            with self.subTest(name=name):
                entry = app.conf.beat_schedule[name]
                self.assertEqual(entry["task"], task)
                self.assertIn(task, app.tasks)
                self.assertEqual(entry["schedule"].hour, hours)
                self.assertEqual(entry["schedule"].minute, {0})

    @classmethod
    def setUpTestData(cls):
        environment = Environment.objects.create(name="dev")
        team = Team.objects.create(name="Platform")
        cls.active = Service.objects.create(
            name="active", environment=environment, team=team,
            origin="http://127.0.0.1:9001",
        )
        cls.idle = Service.objects.create(
            name="idle", environment=environment, team=team,
            origin="http://127.0.0.1:9001",
        )

    def test_rotation_rejects_missing_or_invalid_key_before_writing(self):
        for key in (None, "invalid"):
            with self.subTest(key=key), override_settings(PROBE_TOKEN_ENCRYPTION_KEY=key):
                with self.assertRaises(ImproperlyConfigured):
                    rotate_probe_tokens.run()
        self.assertFalse(Service.objects.filter(token_ciphertext__isnull=False).exists())

    def test_rotation_is_encrypted_per_service_and_idempotent_per_window(self):
        key = Fernet.generate_key()
        cipher = Fernet(key)
        now = datetime(2026, 11, 20, 8, tzinfo=ZoneInfo("Asia/Shanghai"))
        with override_settings(PROBE_TOKEN_ENCRYPTION_KEY=key):
            with patch("django.utils.timezone.now", return_value=now) as clock:
                self.assertEqual(rotate_probe_tokens.run(), 2)
                self.active.refresh_from_db()
                self.idle.refresh_from_db()
                before = self.active.token_ciphertext
                plaintext = cipher.decrypt(before)
                self.assertNotIn(plaintext, before)
                self.assertNotEqual(plaintext, cipher.decrypt(self.idle.token_ciphertext))
                self.assertEqual(rotate_probe_tokens.run(), 0)
                self.active.refresh_from_db()
                self.assertEqual(self.active.token_ciphertext, before)
                clock.return_value = now + timedelta(hours=8)
                self.assertEqual(rotate_probe_tokens.run(), 2)
                self.active.refresh_from_db()
                self.assertNotEqual(plaintext, cipher.decrypt(self.active.token_ciphertext))

        response = APIClient().get(f"/api/services/{self.active.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("token_ciphertext", response.json())
        self.assertNotIn("token_rotation_window", response.json())

    def test_report_counts_half_open_window_and_upserts(self):
        start = datetime(2026, 11, 19, tzinfo=ZoneInfo("Asia/Shanghai"))
        end = start + timedelta(days=1)
        tick = timedelta(microseconds=1)
        for checked_at, outcome in (
            (start - tick, InspectionResult.Outcome.HEALTHY),
            (start, InspectionResult.Outcome.HEALTHY),
            (end - tick, InspectionResult.Outcome.TIMEOUT),
            (end, InspectionResult.Outcome.HEALTHY),
        ):
            result = InspectionResult.objects.create(
                service=self.active, duration_ms=5, outcome=outcome
            )
            InspectionResult.objects.filter(pk=result.pk).update(checked_at=checked_at)

        with patch("django.utils.timezone.now", return_value=end):
            self.assertEqual(write_daily_health_rates.run(), 2)
            self.assertEqual(write_daily_health_rates.run("2026-11-19"), 2)
            with self.assertRaises(ValueError):
                write_daily_health_rates.run("2026-11-20")

        self.assertEqual(DailyHealthRate.objects.count(), 2)
        active = DailyHealthRate.objects.get(service=self.active, date=start.date())
        self.assertEqual((active.environment_name, active.team_name), ("dev", "Platform"))
        self.assertEqual((active.successful_checks, active.total_checks, active.health_rate), (1, 2, 0.5))
        idle = DailyHealthRate.objects.get(service=self.idle, date=start.date())
        self.assertEqual((idle.successful_checks, idle.total_checks), (0, 0))
        self.assertIsNone(idle.health_rate)
