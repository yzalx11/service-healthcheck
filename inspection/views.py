from secrets import compare_digest

from cryptography.fernet import InvalidToken
from django.core.exceptions import ImproperlyConfigured
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Environment, Service, Team
from .probe_tokens import is_managed_probe, token_cipher
from .probes import check_service
from .serializers import (
    EnvironmentSerializer,
    InspectionResultSerializer,
    ServiceSerializer,
    TeamSerializer,
    origin_is_allowed,
)


@require_GET
@never_cache
def managed_probe_health(request, service_id):
    service = Service.objects.filter(pk=service_id).first()
    if service is None or not is_managed_probe(service):
        return HttpResponse(status=404)

    scheme, _, supplied = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() == "bearer" and supplied and service.token_ciphertext:
        try:
            expected = token_cipher().decrypt(service.token_ciphertext)
        except (ImproperlyConfigured, InvalidToken):
            return HttpResponse(status=503)
        if compare_digest(supplied.encode("utf-8"), expected):
            return HttpResponse(status=204)
    return HttpResponse(status=401, headers={"WWW-Authenticate": "Bearer"})


class InspectionModelViewSet(viewsets.ModelViewSet):
    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {"detail": "This record is referenced by a service."},
                status=status.HTTP_409_CONFLICT,
            )


class EnvironmentViewSet(InspectionModelViewSet):
    queryset = Environment.objects.all()
    serializer_class = EnvironmentSerializer


class TeamViewSet(InspectionModelViewSet):
    queryset = Team.objects.all()
    serializer_class = TeamSerializer


class ServiceViewSet(InspectionModelViewSet):
    queryset = Service.objects.all()
    serializer_class = ServiceSerializer

    @action(detail=True, methods=["post"])
    def check(self, request, pk=None):
        service = self.get_object()
        if not origin_is_allowed(service.origin):
            return Response(
                {"detail": "Origin is not enabled for inspections."},
                status=status.HTTP_409_CONFLICT,
            )
        try:
            result = check_service(service)
        except (ImproperlyConfigured, InvalidToken):
            return Response(
                {"detail": "The managed probe credential is unavailable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(InspectionResultSerializer(result).data, status=status.HTTP_201_CREATED)
