
from django.db import transaction
from django.utils import timezone
from datetime import timedelta

from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import User, PasswordResetToken, VerificationRequest


class UserRegistrationSerializer(serializers.ModelSerializer):
    """Serializer for user registration"""

    password = serializers.CharField(
        write_only=True,
        validators=[validate_password],
        style={'input_type': 'password'}
    )
    password_confirm = serializers.CharField(
        write_only=True,
        style={'input_type': 'password'}
    )

    class Meta:
        model = User
        fields = (
            'username', 'email', 'password', 'password_confirm',
            'first_name', 'last_name', 'role', 'company',
            'phone', 'location'
        )
        extra_kwargs = {
            'email': {'required': True},
            'first_name': {'required': True},
            'last_name': {'required': True},
        }

    def validate_email(self, value):
        """Check if email is unique (case-insensitive)"""
        value = value.lower().strip()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(
                "A user with this email already exists.")
        return value

    def validate_role(self, value):
        """Prevent direct admin role assignment during registration"""
        if value in [User.Role.ADMIN, User.Role.SUPER_ADMIN]:
            raise serializers.ValidationError(
                "Admin roles cannot be assigned during registration.")
        return value

    def validate(self, attrs):
        """Validate password confirmation"""
        if attrs.get('password') != attrs.get('password_confirm'):
            raise serializers.ValidationError({
                'password_confirm': "Password confirmation doesn't match."
            })
        return attrs

    def create(self, validated_data):
        """Create new user using manager helper"""
        validated_data.pop('password_confirm', None)
        password = validated_data.pop('password')

        # normalize email
        if 'email' in validated_data:
            validated_data['email'] = validated_data['email'].lower().strip()

        user = User.objects.create_user(password=password, **validated_data)
        return user


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Custom JWT token serializer with additional user data"""

    username_field = 'email'

    def validate(self, attrs):
        """Validate credentials and add user data to token response"""
        data = super().validate(attrs)

        # Add user information to response (read-only info)
        data.update({
            'user': {
                'id': self.user.id,
                'username': self.user.username,
                'email': self.user.email,
                'first_name': self.user.first_name,
                'last_name': self.user.last_name,
                'role': self.user.role,
                'company': self.user.company,
                'phone': self.user.phone,
                'location': self.user.location,
                'is_verified': self.user.is_verified,
                'date_joined': self.user.date_joined,
            }
        })
        return data

    @classmethod
    def get_token(cls, user):
        """Add custom claims to token"""
        token = super().get_token(user)

        # Add custom claims
        token['user_id'] = user.id
        token['email'] = user.email
        token['role'] = user.role
        token['username'] = user.username

        return token


class UserProfileSerializer(serializers.ModelSerializer):
    """Serializer for user profile management"""

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'first_name', 'last_name',
            'role', 'company', 'phone', 'location', 'is_verified',
            'profile_image',
            'date_joined', 'last_login'
        )
        read_only_fields = ('id', 'role', 'is_verified',
                            'date_joined', 'last_login')


class UserProfileUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating user profile"""

    class Meta:
        model = User
        fields = (
            'first_name', 'last_name', 'company', 'phone', 'location', 'profile_image'
        )


class PasswordChangeSerializer(serializers.Serializer):
    """Serializer for changing password"""

    old_password = serializers.CharField(
        required=True,
        style={'input_type': 'password'}
    )
    new_password = serializers.CharField(
        required=True,
        validators=[validate_password],
        style={'input_type': 'password'}
    )
    new_password_confirm = serializers.CharField(
        required=True,
        style={'input_type': 'password'}
    )

    def validate_old_password(self, value):
        """Validate old password"""
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect.")
        return value

    def validate(self, attrs):
        """Validate password confirmation"""
        if attrs.get('new_password') != attrs.get('new_password_confirm'):
            raise serializers.ValidationError({
                'new_password_confirm': "New password confirmation doesn't match."
            })
        return attrs

    def save(self):
        """Update user password"""
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save()
        return user


class PasswordResetRequestSerializer(serializers.Serializer):
    """Serializer for password reset request"""

    email = serializers.EmailField(required=True)

    def validate_email(self, value):
        """Normalize email for lookup"""
        return value.lower().strip()

    def save(self):
        """
        Create password reset token and trigger email sending.
        Does not reveal whether an account exists (security).
        Returns the reset token instance for development/testing only.
        In production: enqueue a mail task and DO NOT return token in API response.
        """
        email = self.validated_data['email']
        try:
            user = User.objects.get(email__iexact=email, is_active=True)
        except User.DoesNotExist:
            # Do not reveal existence. Return None / no-op.
            return None

        # create token using model helper (secure + TTL)
        with transaction.atomic():
            reset_token = PasswordResetToken.create_for_user(
                user, ttl_hours=24)

            # TODO: send email (use Celery task in production)
            # send_password_reset_email(user.email, reset_token.token)

        return reset_token


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Serializer for password reset confirmation"""

    token = serializers.CharField(required=True)
    new_password = serializers.CharField(
        required=True,
        validators=[validate_password],
        style={'input_type': 'password'}
    )
    new_password_confirm = serializers.CharField(
        required=True,
        style={'input_type': 'password'}
    )

    def validate_token(self, value):
        """Validate reset token"""
        try:
            reset_token = PasswordResetToken.objects.get(token=value)
        except PasswordResetToken.DoesNotExist:
            raise serializers.ValidationError("Invalid token.")

        if not reset_token.is_valid():
            raise serializers.ValidationError(
                "Token has expired or been used.")

        self.reset_token = reset_token
        return value

    def validate(self, attrs):
        """Validate password confirmation"""
        if attrs.get('new_password') != attrs.get('new_password_confirm'):
            raise serializers.ValidationError({
                'new_password_confirm': "Password confirmation doesn't match."
            })
        return attrs

    def save(self):
        """Reset user password and mark token used"""
        with transaction.atomic():
            user = self.reset_token.user
            user.set_password(self.validated_data['new_password'])
            user.save()

            # Mark token as used (model helper or direct flag)
            self.reset_token.mark_used()

        return user


class UserListSerializer(serializers.ModelSerializer):
    """Serializer for user list (admin use)"""

    full_name = serializers.CharField(source='get_full_name', read_only=True)
    listings_count = serializers.SerializerMethodField()
    inquiries_sent_count = serializers.SerializerMethodField()
    inquiries_received_count = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'full_name', 'first_name', 'last_name',
            'role', 'company', 'phone', 'location', 'is_active', 'is_verified', 'profile_image',
            'date_joined', 'last_login', 'listings_count',
            'inquiries_sent_count', 'inquiries_received_count'
        )

    def get_listings_count(self, obj):
        """Get user's listing count (guard if related_name missing)"""
        return getattr(obj, 'listings', obj).__class__.objects.filter(user=obj).count() if hasattr(obj, 'listings') else 0

    def get_inquiries_sent_count(self, obj):
        return getattr(obj, 'sent_inquiries', obj).__class__.objects.filter(sender=obj).count() if hasattr(obj, 'sent_inquiries') else 0

    def get_inquiries_received_count(self, obj):
        return getattr(obj, 'received_inquiries', obj).__class__.objects.filter(recipient=obj).count() if hasattr(obj, 'received_inquiries') else 0


class UserRoleUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating user role (admin only)"""

    class Meta:
        model = User
        fields = ('role', 'is_verified')

    def validate_role(self, value):
        """Validate role assignment permissions"""
        request_user = self.context['request'].user

        # Only SUPER_ADMIN can assign ADMIN or SUPER_ADMIN
        if value in [User.Role.ADMIN, User.Role.SUPER_ADMIN]:
            if request_user.role != User.Role.SUPER_ADMIN:
                raise serializers.ValidationError(
                    "Only super admins can assign admin roles.")
        return value

    def update(self, instance, validated_data):
        """Apply role/is_verified updates respecting permission boundaries"""
        request_user = self.context['request'].user

        # Prevent non-super-admin from elevating themselves or others to admin
        new_role = validated_data.get('role', instance.role)
        if new_role in [User.Role.ADMIN, User.Role.SUPER_ADMIN] and request_user.role != User.Role.SUPER_ADMIN:
            raise serializers.ValidationError(
                "You do not have permission to assign that role.")

        # Prevent lowering a super admin unless current user is super admin
        if instance.role == User.Role.SUPER_ADMIN and request_user.role != User.Role.SUPER_ADMIN:
            raise serializers.ValidationError(
                "You cannot modify a super admin.")

        return super().update(instance, validated_data)


class VerificationRequestSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)
    reviewed_by_email = serializers.EmailField(
        source='reviewed_by.email', read_only=True)

    class Meta:
        model = VerificationRequest
        fields = '__all__'
        read_only_fields = ('id', 'user', 'status',
                            'created_at', 'reviewed_at')
