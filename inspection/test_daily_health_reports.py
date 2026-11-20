from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse

from .models import DailyHealthRate, Environment, Service, Team


class DailyHealthReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        dev = Environment.objects.create(name="dev")
        cls.prod = Environment.objects.create(name="prod")
        platform = Team.objects.create(name="Platform")
        cls.ops = Team.objects.create(name="Site Operations")
        cls.service = Service.objects.create(
            name="gateway", environment=dev, team=platform, origin="http://127.0.0.1:9001"
        )
        cls.ops_service = Service.objects.create(
            name="jobs", environment=dev, team=cls.ops, origin="http://127.0.0.1:9001"
        )
        cls.prod_service = Service.objects.create(
            name="public-gateway", environment=cls.prod, team=platform, origin="http://127.0.0.1:9001"
        )
        cls.day = date(2026, 11, 20)
        previous_day = cls.day - timedelta(days=1)
        DailyHealthRate.objects.bulk_create([
            DailyHealthRate(
                service=service, date=report_date,
                environment_name=service.environment.name, team_name=service.team.name,
                successful_checks=successes, total_checks=total,
            )
            for service, report_date, successes, total in (
                (cls.service, previous_day, 1, 1),
                (cls.prod_service, cls.day, 0, 1),
                (cls.ops_service, cls.day, 0, 0),
                (cls.service, cls.day, 3, 4),
            )
        ])

    def setUp(self):
        self.url = reverse("report-list")

    def test_list_returns_report_totals_and_null_for_no_inspections(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        rows = payload["results"]
        self.assertEqual(payload["count"], 4)
        self.assertEqual(
            [row["service"] for row in rows],
            [self.service.pk, self.ops_service.pk, self.prod_service.pk, self.service.pk],
        )
        self.assertEqual(rows[0], {
            "date": self.day.isoformat(),
            "service": self.service.pk,
            "environment_name": "dev",
            "team_name": "Platform",
            "successful_checks": 3,
            "total_checks": 4,
            "health_rate": 0.75,
        })
        self.assertIsNone(rows[1]["health_rate"])
        self.assertEqual(rows[2]["health_rate"], 0.0)

    def test_filters_apply_to_individual_and_combined_report_fields(self):
        for filters, expected_count in (
            ({"date": self.day.isoformat()}, 3),
            ({"environment": "dev"}, 3),
            ({"team": "Platform"}, 3),
            ({"date": self.day.isoformat(), "environment": "dev", "team": "Site Operations"}, 1),
            ({"team": "Missing"}, 0),
        ):
            with self.subTest(filters=filters):
                response = self.client.get(self.url, filters)
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["count"], expected_count)
                if len(filters) == 3:
                    self.assertEqual(payload["results"][0]["service"], self.ops_service.pk)

    def test_filters_use_historical_names_after_service_reassignment(self):
        Service.objects.filter(pk=self.service.pk).update(environment=self.prod, team=self.ops)
        response = self.client.get(self.url, {
            "date": self.day.isoformat(), "environment": "dev", "team": "Platform",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["service"] for row in response.json()["results"]], [self.service.pk]
        )

    def test_invalid_query_returns_field_error(self):
        for field, value in (
            ("date", "2026-02-30"), ("date", ""), ("environment", "staging"),
            ("team", ""), ("team", "x" * 101),
        ):
            with self.subTest(field=field, value=value):
                response = self.client.get(self.url, {field: value})
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())

    def test_list_is_paginated_and_read_only(self):
        DailyHealthRate.objects.bulk_create([
            DailyHealthRate(
                service=self.service, date=self.day - timedelta(days=offset),
                environment_name="dev", team_name="Platform",
                successful_checks=0, total_checks=0,
            )
            for offset in range(2, 20)
        ])
        first = self.client.get(self.url)
        second = self.client.get(self.url, {"page": 2})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["count"], 22)
        self.assertEqual(len(first.json()["results"]), 20)
        self.assertEqual(len(second.json()["results"]), 2)

        for method in (self.client.post, self.client.put, self.client.patch, self.client.delete):
            with self.subTest(method=method.__name__):
                self.assertEqual(method(self.url).status_code, 405)
        self.assertEqual(DailyHealthRate.objects.count(), 22)
