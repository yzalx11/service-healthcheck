from datetime import datetime, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Environment, InspectionResult, Service, Team


class InspectionHistoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        environment = Environment.objects.create(name="dev")
        team = Team.objects.create(name="Platform")
        cls.service = Service.objects.create(
            name="gateway", environment=environment, team=team, origin="http://127.0.0.1:9001"
        )
        cls.other_service = Service.objects.create(
            name="jobs", environment=environment, team=team, origin="http://127.0.0.1:9001"
        )

    def setUp(self):
        self.url = reverse("service-inspections", args=[self.service.pk])

    def test_lists_only_requested_service_in_stable_newest_first_order(self):
        outcome = InspectionResult.Outcome
        older, healthy, timeout, unrelated = InspectionResult.objects.bulk_create([
            InspectionResult(
                service=service, outcome=state, status_code=status_code, duration_ms=duration,
            )
            for service, state, status_code, duration in (
                (self.service, outcome.HTTP_ERROR, 503, 10),
                (self.service, outcome.HEALTHY, 200, 7),
                (self.service, outcome.TIMEOUT, None, 3000),
                (self.other_service, outcome.HEALTHY, 204, 2),
            )
        ])
        now = timezone.make_aware(datetime(2026, 11, 21, 9))
        InspectionResult.objects.filter(pk=older.pk).update(checked_at=now - timedelta(hours=1))
        InspectionResult.objects.filter(pk__in=[healthy.pk, timeout.pk]).update(checked_at=now)
        InspectionResult.objects.filter(pk=unrelated.pk).update(checked_at=now + timedelta(hours=1))

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        rows = payload["results"]
        self.assertEqual(payload["count"], 3)
        self.assertEqual([row["id"] for row in rows], [timeout.pk, healthy.pk, older.pk])
        self.assertEqual(rows[0], {
            "id": timeout.pk,
            "service": self.service.pk,
            "checked_at": now.isoformat(),
            "outcome": "timeout",
            "status_code": None,
            "duration_ms": 3000,
        })
        self.assertEqual(rows[1]["status_code"], 200)
        self.assertEqual(rows[2]["status_code"], 503)

    def test_history_is_paginated(self):
        records = InspectionResult.objects.bulk_create([
            InspectionResult(
                service=self.service, outcome=InspectionResult.Outcome.HEALTHY,
                status_code=200, duration_ms=5,
            )
            for _ in range(21)
        ])
        InspectionResult.objects.filter(service=self.service).update(checked_at=timezone.now())
        first = self.client.get(self.url)
        second = self.client.get(self.url, {"page": 2})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["count"], 21)
        self.assertEqual(len(first.json()["results"]), 20)
        self.assertEqual([row["id"] for row in second.json()["results"]], [records[0].pk])

    def test_combines_outcome_and_half_open_time_filters(self):
        start = timezone.make_aware(datetime(2026, 11, 21, 9))
        end = start + timedelta(hours=1)
        records = {}
        for label, checked_at, outcome in (
            ("before", start - timedelta(microseconds=1), "timeout"),
            ("start", start, "timeout"),
            ("inside", end - timedelta(microseconds=1), "timeout"),
            ("end", end, "timeout"),
            ("healthy", start, "healthy"),
        ):
            result = InspectionResult.objects.create(
                service=self.service, outcome=outcome, duration_ms=5
            )
            InspectionResult.objects.filter(pk=result.pk).update(checked_at=checked_at)
            records[label] = result.pk

        for params, labels in (
            (
                {"outcome": "timeout", "since": "2026-11-21T01:00:00Z", "until": end.isoformat()},
                ["inside", "start"],
            ),
            ({"outcome": "healthy"}, ["healthy"]),
            ({"since": end.isoformat()}, ["end"]),
            ({"until": start.isoformat()}, ["before"]),
        ):
            with self.subTest(params=params):
                response = self.client.get(self.url, params)
                self.assertEqual(response.status_code, 200, response.content)
                payload = response.json()
                self.assertEqual(payload["count"], len(labels))
                self.assertEqual(
                    [row["id"] for row in payload["results"]], [records[label] for label in labels]
                )

    def test_invalid_history_filters_return_400(self):
        for params, field in (
            ({"outcome": "unknown"}, "outcome"),
            ({"since": "not-a-datetime"}, "since"),
            ({"until": ""}, "until"),
            ({"since": "2026-11-21T10:00:00+08:00", "until": "2026-11-21T09:00:00+08:00"}, "until"),
            ({"since": "2026-11-21T09:00:00+08:00", "until": "2026-11-21T01:00:00Z"}, "until"),
        ):
            with self.subTest(params=params):
                response = self.client.get(self.url, params)
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn(field, response.json())

    def test_service_without_inspections_returns_empty_history(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])

    def test_missing_service_returns_404(self):
        response = self.client.get(reverse("service-inspections", args=[self.other_service.pk + 1]))
        self.assertEqual(response.status_code, 404)

    def test_history_does_not_accept_write_methods(self):
        for method in (self.client.post, self.client.put, self.client.patch, self.client.delete):
            with self.subTest(method=method.__name__):
                self.assertEqual(method(self.url).status_code, 405)
        self.assertFalse(InspectionResult.objects.exists())
