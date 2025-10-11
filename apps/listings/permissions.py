# listings/permissions.py
from rest_framework import permissions


class IsOwnerOrAdminOrReadOnly(permissions.BasePermission):
    """
    Allow read (SAFE_METHODS) for everyone.
    Write permissions require authentication and are limited to the owner or admin.
    """

    def has_permission(self, request, view):
        # Allow read for anyone (including anonymous)
        if request.method in permissions.SAFE_METHODS:
            return True

        # Writes require authentication
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        # Read permissions for any request
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write permissions are only allowed to the owner or admin
        return bool(request.user and request.user.is_authenticated and (obj.user == request.user or request.user.is_admin_user))


class CanCreateListing(permissions.BasePermission):
    """
    Permission to allow creating listings only if the user can create listings
    (e.g. seller/service provider). Requires authentication.
    """

    def has_permission(self, request, view):
        if request.method == "POST":
            return bool(request.user and request.user.is_authenticated and getattr(request.user, "can_create_listings", False))
        return True
