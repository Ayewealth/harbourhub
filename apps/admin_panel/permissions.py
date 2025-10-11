from rest_framework import permissions


class IsAdminOrSuperAdmin(permissions.BasePermission):
    """Custom permission: only Admin or Super Admin users can access."""

    def has_permission(self, request, view):
        user = request.user
        return user.is_authenticated and user.role in ["admin", "super_admin"]
