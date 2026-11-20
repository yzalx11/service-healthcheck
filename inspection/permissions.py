from django.conf import settings
from rest_framework.permissions import BasePermission


class ManageApiPermission(BasePermission):
    def has_permission(self, request, view):
        return not settings.MANAGE_API_AUTH or request.user.is_authenticated
