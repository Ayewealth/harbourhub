# apps/inquiries/permissions.py
from rest_framework import permissions
from django.contrib.auth import get_user_model
User = get_user_model()


class IsInquiryParticipant(permissions.BasePermission):
    """
    Only allow the sender (from_user), recipient (to_user) or admins to access the inquiry.
    List/create are allowed for authenticated users (create is checked in serializer).
    """

    def has_permission(self, request, view):
        if view.action in ("list", "create", "sent", "received"):
            return request.user and request.user.is_authenticated
        return True

    def has_object_permission(self, request, view, obj):
        if getattr(request.user, "is_admin_user", False):
            return True
        if view.action == 'destroy':
            return obj.from_user_id == request.user.id
        return obj.from_user_id == request.user.id or obj.to_user_id == request.user.id
