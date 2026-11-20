from django.apps import AppConfig
from django.core.checks import register


class InspectionConfig(AppConfig):
    name = "inspection"

    def ready(self):
        from .checks import check_manage_api_auth, check_origin_settings

        register(check_origin_settings)
        register(check_manage_api_auth, deploy=True)
