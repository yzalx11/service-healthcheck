from django.urls import include, path
from rest_framework.routers import DefaultRouter

from inspection.views import EnvironmentViewSet, ServiceViewSet, TeamViewSet, managed_probe_health

router = DefaultRouter()
router.register("environments", EnvironmentViewSet)
router.register("teams", TeamViewSet)
router.register("services", ServiceViewSet)

urlpatterns = [
    path("api/", include(router.urls)),
    path("probe-health/<int:service_id>/", managed_probe_health, name="managed-probe-health"),
]
