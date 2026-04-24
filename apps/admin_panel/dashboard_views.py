from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User

from .auth import can_edit_dashboard_matrix, has_admin_module_permission
from .constants import AdminModule, StaffRole
from .dashboard_serializers import (
    AdminUserListSerializer,
    InviteAdminSerializer,
    RolesMatrixSerializer,
    RolePermissionSerializer,
    matrix_from_db,
    AcceptAdminInviteSerializer
)
from .serializers import PlatformConfigSerializer
from .models import AdminActionLog, AdminProfile, RolePermission, PlatformConfig

User = get_user_model()


class RolesMatrixView(APIView):
    """GET default matrix from DB; PUT bulk-update (super admin / matrix editor)."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Update roles & permissions matrix",
        request=RolesMatrixSerializer,
        description=f"""
Bulk update the roles & permissions matrix.

**Available roles:** `{'`, `'.join([c[0] for c in StaffRole.choices])}`

**Available modules:** `{'`, `'.join([c[0] for c in AdminModule.choices])}`

Each entry needs both `view` and `manage` booleans:
```json
{{
  "matrix": {{
    "support_admin": {{
      "listings_management": {{ "view": true, "manage": false }},
      "supports": {{ "view": true, "manage": true }}
    }}
  }}
}}
```
        """
    )
    def get(self, request):
        if not can_edit_dashboard_matrix(request.user) and not has_admin_module_permission(
            request.user, AdminModule.OVERVIEW_DASHBOARD.value, require_manage=False
        ):
            return Response(status=status.HTTP_403_FORBIDDEN)
        return Response({"matrix": matrix_from_db()})

    @extend_schema(
        summary="Update roles & permissions matrix",
        request=RolesMatrixSerializer,
    )
    def put(self, request):
        if not can_edit_dashboard_matrix(request.user):
            return Response(status=status.HTTP_403_FORBIDDEN)
        ser = RolesMatrixSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save_matrix()
        return Response({"matrix": matrix_from_db()})


class MeDashboardPermissionsView(APIView):
    """Effective permissions for the logged-in dashboard user."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(summary="Current admin dashboard permissions")
    def get(self, request):
        from .auth import get_dashboard_staff_role

        role = get_dashboard_staff_role(request.user)
        if role is None:
            return Response(
                {"dashboard_staff": False, "role": None, "modules": {}},
                status=status.HTTP_200_OK,
            )
        perms = {}
        for rp in RolePermission.objects.filter(role=role):
            perms[rp.module] = {"view": rp.can_view, "manage": rp.can_manage}
        return Response(
            {
                "dashboard_staff": True,
                "role": role,
                "modules": perms,
            }
        )


class InviteAdminView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Invite dashboard admin",
        request=InviteAdminSerializer,
        examples=[
            OpenApiExample(
                'Support Admin Invite',
                value={
                    "full_name": "Jane Smith",
                    "email": "jane@harbourhub.com",
                    "staff_role": "support_admin"
                }
            ),
            OpenApiExample(
                'Finance Admin Invite',
                value={
                    "full_name": "John Doe",
                    "email": "john@harbourhub.com",
                    "staff_role": "finance_admin"
                }
            ),
        ],
        description=f"""
Invite a new or existing user as a dashboard admin.

**Available staff roles:**
| Role | Description |
|------|-------------|
| `super_admin` | Full access to everything |
| `operations_admin` | Manages listings and orders |
| `finance_admin` | Manages payments and finance |
| `support_admin` | Handles support and vendors |
| `compliance_admin` | Manages compliance and contracts |
| `read_only` | View-only access to dashboard |
        """
    )
    def post(self, request):
        if not can_edit_dashboard_matrix(request.user):
            return Response(status=status.HTTP_403_FORBIDDEN)
        ser = InviteAdminSerializer(
            data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        user = ser.save()
        return Response(
            {"id": user.id, "email": user.email, "invite_status": "pending"},
            status=status.HTTP_201_CREATED,
        )


class DashboardAdminListView(generics.ListAPIView):
    """Staff users with an AdminProfile (invited admins)."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AdminUserListSerializer

    def get_queryset(self):
        if not has_admin_module_permission(
            self.request.user, AdminModule.VENDORS_ONBOARDING.value, require_manage=False
        ) and not can_edit_dashboard_matrix(self.request.user):
            return User.objects.none()
        return (
            User.objects.filter(admin_profile__isnull=False)
            .select_related("admin_profile")
            .order_by("-created_at")
        )


class DashboardAdminDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk=None):
        if not can_edit_dashboard_matrix(request.user):
            return Response(status=status.HTTP_403_FORBIDDEN)

        try:
            user = User.objects.select_related('admin_profile').get(pk=pk)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        profile = getattr(user, 'admin_profile', None)
        if not profile:
            return Response(
                {'error': 'User is not a dashboard admin'},
                status=status.HTTP_400_BAD_REQUEST
            )

        profile.invite_status = AdminProfile.InviteStatus.REVOKED
        profile.save(update_fields=['invite_status'])

        AdminActionLog.log_action(
            admin_user=request.user,
            action_type=AdminActionLog.ActionType.ADMIN_REVOKED,
            description=f"Revoked dashboard access for {user.email}",
        )

        return Response({'message': f'Access revoked for {user.email}'})


class AcceptAdminInviteView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="Accept admin invite",
        description="Invited admin sets their password and activates their account.",
        request=AcceptAdminInviteSerializer,
    )
    def post(self, request):
        serializer = AcceptAdminInviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {'message': f'Account activated. You can now log in as {user.email}'},
            status=status.HTTP_200_OK
        )


class PlatformConfigView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not can_edit_dashboard_matrix(request.user):
            return Response(status=status.HTTP_403_FORBIDDEN)
        config = PlatformConfig.get()
        return Response(PlatformConfigSerializer(config).data)

    def patch(self, request):
        if not can_edit_dashboard_matrix(request.user):
            return Response(status=status.HTTP_403_FORBIDDEN)
        config = PlatformConfig.get()
        serializer = PlatformConfigSerializer(
            config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)

        AdminActionLog.log_action(
            admin_user=request.user,
            action_type=AdminActionLog.ActionType.ROLES_MATRIX_UPDATED,
            description="Platform configuration updated",
            extra_data=request.data
        )

        return Response(serializer.data)


class AdminUserEditView(APIView):
    """Edit admin role or disable/enable an admin."""
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk):
        if not can_edit_dashboard_matrix(request.user):
            return Response(status=status.HTTP_403_FORBIDDEN)

        try:
            user = User.objects.select_related(
                'admin_profile').get(pk=pk)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        profile = getattr(user, 'admin_profile', None)
        if not profile:
            return Response(
                {'error': 'User is not an admin'},
                status=status.HTTP_400_BAD_REQUEST
            )

        new_role = request.data.get('staff_role')
        new_status = request.data.get('status')

        if new_role and new_role in [c[0] for c in StaffRole.choices]:
            profile.staff_role = new_role
            profile.save(update_fields=['staff_role'])

        if new_status == 'disabled':
            profile.invite_status = AdminProfile.InviteStatus.REVOKED
            profile.save(update_fields=['invite_status'])
        elif new_status == 'active':
            profile.invite_status = AdminProfile.InviteStatus.ACTIVE
            profile.save(update_fields=['invite_status'])

        AdminActionLog.log_action(
            admin_user=request.user,
            action_type=AdminActionLog.ActionType.ADMIN_REVOKED
            if new_status == 'disabled'
            else AdminActionLog.ActionType.ADMIN_ACTIVATED,
            description=(
                f"Updated admin {user.email}: "
                f"role={new_role}, status={new_status}"
            ),
        )

        return Response({
            'message': 'Admin updated successfully.',
            'staff_role': profile.staff_role,
            'invite_status': profile.invite_status,
        })

    def delete(self, request, pk):
        """Permanently remove an admin."""
        if not can_edit_dashboard_matrix(request.user):
            return Response(status=status.HTTP_403_FORBIDDEN)

        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Remove admin profile and downgrade role
        AdminProfile.objects.filter(user=user).delete()
        user.role = 'buyer'
        user.is_staff = False
        user.save(update_fields=['role', 'is_staff'])

        AdminActionLog.log_action(
            admin_user=request.user,
            action_type=AdminActionLog.ActionType.ADMIN_REVOKED,
            description=f"Removed admin: {user.email}",
        )

        return Response({'message': f'Admin {user.email} removed.'})
