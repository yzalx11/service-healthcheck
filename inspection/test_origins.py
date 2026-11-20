from io import StringIO

from django.core.management import call_command
from django.forms import modelform_factory
from django.test import SimpleTestCase, override_settings

from .models import Service


class OriginConfigurationTests(SimpleTestCase):
    @override_settings(
        PROBE_ALLOWED_ORIGINS=["http://paysvc:8080", "http://secret-user@paysvc:8080"],
        MANAGED_PROBE_ORIGIN="http://paysvc:8080/health",
    )
    def test_django_check_warns_about_invalid_origins_without_echoing_values(self):
        stderr = StringIO()
        call_command("check", stdout=StringIO(), stderr=stderr)
        output = stderr.getvalue()
        self.assertIn("PROBE_ALLOWED_ORIGINS: (inspection.W001) Entry 2", output)
        self.assertIn("MANAGED_PROBE_ORIGIN: (inspection.W002)", output)
        self.assertNotIn("secret-user", output)
        self.assertNotIn("http://paysvc:8080/health", output)

    def test_model_form_accepts_short_hostname_and_rejects_invalid_origin(self):
        form_class = modelform_factory(Service, fields=["origin"])
        valid = form_class({"origin": "http://paysvc:8080"})
        self.assertTrue(valid.is_valid(), valid.errors)
        self.assertEqual(valid.save(commit=False).origin, "http://paysvc:8080")
        invalid = form_class({"origin": "http://paysvc:8080/health"})
        self.assertFalse(invalid.is_valid())
        self.assertTrue(invalid.has_error("origin", "invalid"))
