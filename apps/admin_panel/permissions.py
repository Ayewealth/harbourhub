from rest_framework import permissions

from .auth import is_dashboard_staff


class IsDashboardStaff(permissions.BasePermission):
    """Accept superusers, role=super_admin, and active AdminProfile rows."""

    def has_permission(self, request, view):
        return is_dashboard_staff(request.user)


# Kept temporarily so existing imports keep working while every admin view is
# migrated to IsDashboardStaff + HasAdminModulePermission.
IsAdminOrSuperAdmin = IsDashboardStaff
