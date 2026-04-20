"""Dashboard permission checks (roles matrix)."""
from django.contrib.auth import get_user_model
from rest_framework import permissions

from apps.accounts.models import User

from .constants import StaffRole
from .models import AdminProfile, RolePermission

User = get_user_model()


def get_dashboard_staff_role(user) -> str | None:
    """Resolve StaffRole for permission lookup."""
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return StaffRole.SUPER_ADMIN
    if getattr(user, "role", None) == User.Role.SUPER_ADMIN:
        return StaffRole.SUPER_ADMIN
    profile = getattr(user, "admin_profile", None)
    if profile and profile.invite_status == AdminProfile.InviteStatus.ACTIVE:
        return profile.staff_role
    return None


def has_admin_module_permission(
    user, module: str, *, require_manage: bool = False
) -> bool:
    """
    Check VIEW (default) or MANAGE for a dashboard module slug
    (AdminModule value, e.g. 'listings_management').
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    role = get_dashboard_staff_role(user)
    if role is None:
        return False
    try:
        rp = RolePermission.objects.get(role=role, module=module)
    except RolePermission.DoesNotExist:
        return False
    if require_manage:
        return rp.can_manage
    return rp.can_view or rp.can_manage


class HasAdminModulePermission(permissions.BasePermission):
    """
    Set on a view: admin_module = 'analytics' (AdminModule value),
    admin_require_manage = True/False
    """

    def has_permission(self, request, view):
        module = getattr(view, "admin_module", None)
        if not module:
            return False
        require_manage = getattr(view, "admin_require_manage", False)
        return has_admin_module_permission(
            request.user, module, require_manage=require_manage
        )


def is_dashboard_staff(user) -> bool:
    return get_dashboard_staff_role(user) is not None


def can_edit_dashboard_matrix(user) -> bool:
    """Who may load/save the roles matrix (settings UI)."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return has_admin_module_permission(
        user,
        "overview_dashboard",
        require_manage=True,
    ) and get_dashboard_staff_role(user) == StaffRole.SUPER_ADMIN
