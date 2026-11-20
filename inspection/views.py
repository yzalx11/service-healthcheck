from django.db.models.deletion import ProtectedError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Environment, Service, Team
from .probes import check_service
from .serializers import (
    EnvironmentSerializer,
    InspectionResultSerializer,
    ServiceSerializer,
    TeamSerializer,
    origin_is_allowed,
)


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
        result = check_service(service)
        return Response(InspectionResultSerializer(result).data, status=status.HTTP_201_CREATED)
