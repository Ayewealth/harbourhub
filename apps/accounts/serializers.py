
from django.db import transaction
from django.utils import timezone

from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth.password_validation import validate_password

from .models import User, PasswordResetToken, VerificationRequest, OneTimePassword, DeliveryDetail, UserPreference, UserTwoFactor, UserSession


from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from django.utils import timezone


from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from django.utils import timezone


class UserRegistrationSerializer(serializers.ModelSerializer):
    """Serializer for user registration (password optional if OTP verified)."""

    password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        style={'input_type': 'password'}
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        style={'input_type': 'password'}
    )

    class Meta:
        model = User
        fields = (
            'username', 'email', 'password', 'password_confirm',
            'full_name', 'role', 'company', 'phone', 'location'
        )
        extra_kwargs = {
            'email': {'required': True},
            'full_name': {'required': True},
        }

    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")
        password_confirm = attrs.get("password_confirm")

        otp_valid = OneTimePassword.objects.filter(
            email__iexact=email,
            purpose=OneTimePassword.Purpose.REGISTRATION,
            used=True,
            expires_at__gte=timezone.now()
        ).exists()

        if otp_valid:
            if password:
                if password != password_confirm:
                    raise serializers.ValidationError({
                        "password_confirm": "Password confirmation doesn't match."
                    })
                validate_password(password)
        else:
            if not password:
                raise serializers.ValidationError({
                    "password": "Password is required if you haven't verified via OTP."
                })
            if password != password_confirm:
                raise serializers.ValidationError({
                    "password_confirm": "Password confirmation doesn't match."
                })
            validate_password(password)

        return attrs

    def create(self, validated_data):
        validated_data.pop("password_confirm", None)
        password = validated_data.pop("password", None)
        email = validated_data.get("email").lower().strip()

        user = User.objects.create_user(
            password=password or None,
            **validated_data
        )
        return user


class OTPRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    purpose = serializers.ChoiceField(choices=OneTimePassword.Purpose.choices)

    def validate_email(self, value):
        return value.lower().strip()

    def validate(self, attrs):
        email = attrs["email"]
        purpose = attrs["purpose"]

        # For login OTP, user must already exist and be active
        if purpose == OneTimePassword.Purpose.LOGIN:
            user_exists = User.objects.filter(
                email__iexact=email, is_active=True
            ).exists()
            if not user_exists:
                raise serializers.ValidationError({
                    "email": "No active account found with this email address."
                })

        return attrs

    def create(self, validated_data):
        email = validated_data["email"]
        purpose = validated_data["purpose"]
        otp = OneTimePassword.create_otp(email=email, purpose=purpose)
        from .tasks import send_otp_email_task
        send_otp_email_task.delay(email, otp.code, purpose, 30)
        return otp


class OTPVerifySerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(max_length=6)
    purpose = serializers.ChoiceField(choices=OneTimePassword.Purpose.choices)

    def validate(self, attrs):
        email = attrs["email"].lower().strip()
        code = attrs["code"].strip()
        purpose = attrs["purpose"]

        try:
            otp = OneTimePassword.objects.filter(
                email__iexact=email, code=code, purpose=purpose
            ).latest("created_at")
        except OneTimePassword.DoesNotExist:
            raise serializers.ValidationError("Invalid OTP code.")

        if not otp.is_valid():
            raise serializers.ValidationError(
                "OTP has expired or already used.")

        attrs["otp"] = otp
        return attrs

    def create(self, validated_data):
        otp = validated_data["otp"]
        otp.mark_used()
        return otp


class SetPasswordSerializer(serializers.Serializer):
    """Serializer for setting or updating password for OTP-based accounts."""

    new_password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
        style={'input_type': 'password'},
    )
    new_password_confirm = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
    )

    def validate(self, attrs):
        """Ensure both passwords match"""
        if attrs.get("new_password") != attrs.get("new_password_confirm"):
            raise serializers.ValidationError({
                "new_password_confirm": "Passwords do not match."
            })
        return attrs

    def save(self, **kwargs):
        """Set the new password for the authenticated user"""
        user = self.context["request"].user
        new_password = self.validated_data["new_password"]

        user.set_password(new_password)
        user.save(update_fields=["password"])
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
                'full_name': self.user.full_name,
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
            'id', 'username', 'email', 'full_name',
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
            'full_name', 'company', 'phone', 'location', 'profile_image'
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
            'id', 'username', 'email', 'full_name',
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


class DeliveryDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryDetail
        fields = (
            'id',
            'contact_person',
            'country',
            'address',
            'state',
            'city',
            'zip_code',
            'phone',
            'is_default',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')


class UserPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserPreference
        fields = (
            'id',
            'language',
            'interested_categories',
            'email_newsletter',
            'email_promotions',
            'email_order_updates',
            'email_unsubscribe_all',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        # If unsubscribe_all is True, turn off all other email prefs
        if attrs.get('email_unsubscribe_all'):
            attrs['email_newsletter'] = False
            attrs['email_promotions'] = False
            attrs['email_order_updates'] = False
        return attrs


class TwoFactorStatusSerializer(serializers.Serializer):
    is_enabled = serializers.BooleanField(read_only=True)


class TwoFactorSetupSerializer(serializers.Serializer):
    """Returns QR URI and secret for setup."""
    secret = serializers.CharField(read_only=True)
    qr_uri = serializers.CharField(read_only=True)
    is_enabled = serializers.BooleanField(read_only=True)


class TwoFactorEnableSerializer(serializers.Serializer):
    """Verify TOTP code to enable 2FA."""
    code = serializers.CharField(max_length=6, min_length=6)

    def validate_code(self, value):
        user = self.context['request'].user
        try:
            tf = UserTwoFactor.objects.get(user=user)
        except UserTwoFactor.DoesNotExist:
            raise serializers.ValidationError(
                "2FA not set up. Please request setup first.")
        if not tf.verify_code(value):
            raise serializers.ValidationError("Invalid code.")
        self._tf = tf
        return value

    def save(self):
        self._tf.is_enabled = True
        self._tf.save(update_fields=['is_enabled'])
        self._clear_other_sessions()
        return self._tf
        
    def _clear_other_sessions(self):
        request = self.context.get('request')
        if request:
            try:
                from rest_framework_simplejwt.authentication import JWTAuthentication
                from .models import UserSession
                auth = JWTAuthentication()
                raw_token = auth.get_raw_token(auth.get_header(request))
                if raw_token:
                    validated = auth.get_validated_token(raw_token)
                    current_jti = str(validated.get('jti', ''))
                    UserSession.objects.filter(user=request.user).exclude(token_jti=current_jti).delete()
            except Exception as e:
                import logging
                logging.getLogger(__name__).exception("Failed to clear sessions on 2FA toggle.")


class TwoFactorDisableSerializer(serializers.Serializer):
    """Verify TOTP code to disable 2FA."""
    code = serializers.CharField(max_length=6, min_length=6)

    def validate_code(self, value):
        user = self.context['request'].user
        try:
            tf = UserTwoFactor.objects.get(user=user, is_enabled=True)
        except UserTwoFactor.DoesNotExist:
            raise serializers.ValidationError("2FA is not enabled.")
        if not tf.verify_code(value):
            raise serializers.ValidationError("Invalid code.")
        self._tf = tf
        return value

    def save(self):
        self._tf.is_enabled = False
        self._tf.save(update_fields=['is_enabled'])
        
        # We can reuse the same session clearing logic
        request = self.context.get('request')
        if request:
            try:
                from rest_framework_simplejwt.authentication import JWTAuthentication
                from .models import UserSession
                auth = JWTAuthentication()
                raw_token = auth.get_raw_token(auth.get_header(request))
                if raw_token:
                    validated = auth.get_validated_token(raw_token)
                    current_jti = str(validated.get('jti', ''))
                    UserSession.objects.filter(user=request.user).exclude(token_jti=current_jti).delete()
            except Exception as e:
                pass
                
        return self._tf


class TwoFactorVerifyLoginSerializer(serializers.Serializer):
    """Verify TOTP code during login (if 2FA is enabled)."""
    code = serializers.CharField(max_length=6, min_length=6)
    token = serializers.CharField()

    def validate(self, attrs):
        from django.contrib.auth import get_user_model
        from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
        
        User = get_user_model()
        signer = TimestampSigner()
        
        try:
            # Token is valid for 5 minutes (300 seconds)
            user_id = signer.unsign(attrs['token'], max_age=300)
        except SignatureExpired:
            raise serializers.ValidationError("2FA session expired. Please log in again.")
        except BadSignature:
            raise serializers.ValidationError("Invalid 2FA session token.")

        try:
            user = User.objects.get(pk=user_id)
            tf = UserTwoFactor.objects.get(user=user, is_enabled=True)
        except (User.DoesNotExist, UserTwoFactor.DoesNotExist):
            raise serializers.ValidationError(
                "Invalid user or 2FA not enabled.")
            
        if not tf.verify_code(attrs['code']):
            raise serializers.ValidationError("Invalid 2FA code.")
            
        self._user = user
        return attrs

    def get_user(self):
        return self._user


class UserSessionSerializer(serializers.ModelSerializer):
    is_current = serializers.SerializerMethodField()

    class Meta:
        model = UserSession
        fields = (
            'id', 'device_name', 'device_type',
            'ip_address', 'is_active', 'is_current',
            'last_active', 'created_at',
        )
        read_only_fields = fields

    def get_is_current(self, obj):
        request = self.context.get('request')
        if request:
            current_jti = self._get_current_jti(request)
            return obj.token_jti == current_jti
        return False

    def _get_current_jti(self, request):
        try:
            from rest_framework_simplejwt.authentication import (
                JWTAuthentication)
            auth = JWTAuthentication()
            validated = auth.get_validated_token(
                auth.get_raw_token(
                    auth.get_header(request)))
            return str(validated.get('jti', ''))
        except Exception:
            return ''


class SellerOnboardingStep1Serializer(serializers.Serializer):
    """Step 1: Business details."""
    business_name = serializers.CharField(max_length=255)
    phone = serializers.CharField(max_length=30)
    email = serializers.EmailField()
    country = serializers.CharField(max_length=100)

    def save(self, user):
        # Update user profile
        user.phone = self.validated_data['phone']
        user.company = self.validated_data['business_name']
        user.save(update_fields=['phone', 'company'])

        # Create or update store
        from apps.store.models import Store
        import re
        from django.utils.text import slugify
        base_slug = slugify(self.validated_data['business_name'])
        slug = base_slug
        counter = 1
        while Store.objects.filter(
                slug=slug).exclude(user=user).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        store, _ = Store.objects.update_or_create(
            user=user,
            defaults={
                'name': self.validated_data['business_name'],
                'email': self.validated_data['email'],
                'country': self.validated_data['country'],
                'slug': slug,
                'policy': '',
            }
        )
        return store


class SellerOnboardingStep2Serializer(serializers.Serializer):
    """Step 2: What do you sell — category selection."""
    category_ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=1,
        help_text="List of category IDs"
    )

    def validate_category_ids(self, value):
        from apps.categories.models import Category
        categories = Category.objects.filter(
            pk__in=value, is_active=True)
        if not categories.exists():
            raise serializers.ValidationError(
                "No valid categories found.")
        self._categories = categories
        return value

    def save(self, user):
        from apps.store.models import Store
        store = Store.objects.get(user=user)
        store.categories.set(self._categories)
        return store


class SellerOnboardingStep3Serializer(serializers.Serializer):
    """Step 3: Verification details."""
    business_type = serializers.ChoiceField(choices=[
        ('sole_proprietorship', 'Sole Proprietorship'),
        ('partnership', 'Partnership'),
        ('limited_liability', 'Limited Liability Company'),
        ('corporation', 'Corporation'),
        ('ngo', 'NGO / Non-profit'),
    ])
    government_id = serializers.FileField()
    proof_of_registration = serializers.FileField()
    confirmed = serializers.BooleanField()

    def validate_confirmed(self, value):
        if not value:
            raise serializers.ValidationError(
                "You must confirm documents are valid.")
        return value

    def save(self, user):
        from apps.accounts.models import VerificationRequest
        # Create verification request
        vr, _ = VerificationRequest.objects.update_or_create(
            user=user,
            defaults={
                'business_license': self.validated_data[
                    'proof_of_registration'],
                'additional_info': self.validated_data['business_type'],
            }
        )

        # Promote user to seller role if not already
        if user.role not in ['seller', 'service_provider']:
            user.role = 'seller'
            user.save(update_fields=['role'])

        return vr


class BecomeSellerSerializer(serializers.Serializer):
    """
    One-shot: promote an existing buyer to seller.
    Used when buyer clicks 'Become a seller' button.
    """
    business_name = serializers.CharField(max_length=255)
    phone = serializers.CharField(max_length=30)
    country = serializers.CharField(max_length=100)

    def save(self, user):
        user.role = 'seller'
        user.company = self.validated_data['business_name']
        user.phone = self.validated_data['phone']
        user.save(update_fields=['role', 'company', 'phone'])
        return user
