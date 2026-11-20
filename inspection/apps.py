from django.apps import AppConfig
from django.core.checks import register


class InspectionConfig(AppConfig):
    name = "inspection"

    def ready(self):
        from .checks import check_origin_settings

        register(check_origin_settings)
