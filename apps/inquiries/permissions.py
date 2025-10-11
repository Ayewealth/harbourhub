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
        # listing of user's inquiries requires authentication
        if view.action in ("list", "create", "sent", "received"):
            return request.user and request.user.is_authenticated
        # detail-level actions need object-level check
        return True

    def has_object_permission(self, request, view, obj):
        # Admins allow
        if getattr(request.user, "is_admin_user", False):
            return True
        # sender or recipient allowed
        return obj.from_user_id == request.user.id or obj.to_user_id == request.user.id
