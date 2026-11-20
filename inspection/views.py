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
from .origins import allowed_origin_keys, origin_key
from .probe_tokens import is_managed_probe, token_cipher
from .probes import check_service
from .serializers import (
    EnvironmentSerializer,
    InspectionHistoryFilterSerializer,
    InspectionResultSerializer,
    ServiceSerializer,
    TeamSerializer,
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

    @action(detail=True, serializer_class=InspectionResultSerializer)
    def inspections(self, request, pk=None):
        service = self.get_object()
        filters = InspectionHistoryFilterSerializer(data=request.query_params.dict())
        filters.is_valid(raise_exception=True)
        fields = {"outcome": "outcome", "since": "checked_at__gte", "until": "checked_at__lt"}
        results = service.inspections.filter(
            **{fields[name]: value for name, value in filters.validated_data.items()}
        ).order_by("-checked_at", "-pk")
        page = self.paginate_queryset(results)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        return Response(self.get_serializer(results, many=True).data)

    @action(detail=True, methods=["post"])
    def check(self, request, pk=None):
        service = self.get_object()
        if origin_key(service.origin) not in allowed_origin_keys():
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
