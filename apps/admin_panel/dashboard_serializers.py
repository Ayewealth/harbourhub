from django.contrib.auth import get_user_model
from rest_framework import serializers

from .constants import AdminModule, StaffRole, DEFAULT_ROLE_MATRIX
from .models import AdminProfile, RolePermission

User = get_user_model()


class RolePermissionSerializer(serializers.ModelSerializer):
    module_label = serializers.CharField(
        source="get_module_display", read_only=True)

    class Meta:
        model = RolePermission
        fields = ("id", "role", "module", "module_label",
                  "can_view", "can_manage")


class RolesMatrixSerializer(serializers.Serializer):
    """Bulk read/write shape: { role: { module: { view, manage } } }"""

    matrix = serializers.DictField(
        child=serializers.DictField(), required=True)

    def validate_matrix(self, value):
        valid_roles = {c[0] for c in StaffRole.choices}
        valid_modules = {c[0] for c in AdminModule.choices}
        for role, modules in value.items():
            if role not in valid_roles:
                raise serializers.ValidationError(f"Invalid role: {role}")
            if not isinstance(modules, dict):
                raise serializers.ValidationError(
                    f"Invalid modules for {role}")
            for mod, flags in modules.items():
                if mod not in valid_modules:
                    raise serializers.ValidationError(f"Invalid module: {mod}")
                if not isinstance(flags, dict):
                    raise serializers.ValidationError(
                        f"Invalid flags for {role}/{mod}")
                if "view" not in flags or "manage" not in flags:
                    raise serializers.ValidationError(
                        "Each module needs 'view' and 'manage' booleans"
                    )
        return value

    def save_matrix(self):
        data = self.validated_data["matrix"]
        for role, modules in data.items():
            for module, flags in modules.items():
                RolePermission.objects.update_or_create(
                    role=role,
                    module=module,
                    defaults={
                        "can_view": bool(flags["view"]),
                        "can_manage": bool(flags["manage"]),
                    },
                )


def matrix_from_db() -> dict:
    out: dict = {r: {} for r, _ in StaffRole.choices}
    for rp in RolePermission.objects.all().order_by("role", "module"):
        if rp.role not in out:
            out[rp.role] = {}
        out[rp.role][rp.module] = {
            "view": rp.can_view, "manage": rp.can_manage}
    return out


class InviteAdminSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    staff_role = serializers.ChoiceField(
        choices=StaffRole.choices, help_text=f"Available roles: {', '.join([c[0] for c in StaffRole.choices])}")

    def validate_email(self, value):
        return value.lower().strip()

    def create(self, validated_data):
        import secrets
        inviter = self.context["request"].user
        email = validated_data["email"]

        # Get existing user or create new one
        user = User.objects.filter(email__iexact=email).first()
        if user:
            # Promote existing user to admin
            user.role = User.Role.ADMIN
            user.is_staff = True
            user.save(update_fields=['role', 'is_staff'])
        else:
            # Create brand new user
            user = User(
                email=email,
                username=email[:150],
                full_name=validated_data["full_name"],
                role=User.Role.ADMIN,
                is_staff=True,
                is_active=True,
            )
            user.set_unusable_password()
            user.save()

        token = secrets.token_urlsafe(32)
        AdminProfile.objects.update_or_create(
            user=user,
            defaults={
                'staff_role': validated_data["staff_role"],
                'invite_status': AdminProfile.InviteStatus.PENDING,
                'invite_token': token,
                'invited_by': inviter,
            }
        )

        try:
            from .tasks import send_admin_invite_email
            send_admin_invite_email.delay(user.id, token)
        except Exception:
            pass

        return user


class AcceptAdminInviteSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(min_length=8, write_only=True)

    def validate_token(self, value):
        try:
            self._profile = AdminProfile.objects.select_related('user').get(
                invite_token=value,
                invite_status=AdminProfile.InviteStatus.PENDING
            )
        except AdminProfile.DoesNotExist:
            raise serializers.ValidationError(
                "Invalid or expired invite token.")
        return value

    def save(self):
        user = self._profile.user
        user.set_password(self.validated_data['password'])
        user.save(update_fields=['password'])

        self._profile.invite_status = AdminProfile.InviteStatus.ACTIVE
        self._profile.invite_token = ''  # invalidate so it can't be reused
        self._profile.save(update_fields=['invite_status', 'invite_token'])
        return user


class AdminUserListSerializer(serializers.ModelSerializer):
    staff_role = serializers.CharField(
        source="admin_profile.staff_role", read_only=True)
    invite_status = serializers.CharField(
        source="admin_profile.invite_status", read_only=True
    )

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "full_name",
            "is_staff",
            "staff_role",
            "invite_status",
            "created_at",
        )
