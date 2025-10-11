# accounts/models.py
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from datetime import timedelta
import secrets


class UserManager(BaseUserManager):
    """
    Custom manager where email is the unique identifier
    for auth instead of usernames.
    """

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("The given email must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.SUPER_ADMIN)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Custom user model with role-based access"""

    class Role(models.TextChoices):
        BUYER = 'buyer', _('Buyer')
        SELLER = 'seller', _('Seller')
        SERVICE_PROVIDER = 'service_provider', _('Service Provider')
        ADMIN = 'admin', _('Admin')
        SUPER_ADMIN = 'super_admin', _('Super Admin')

    # Keep username if you want a display handle, but we use email for login
    username = models.CharField(max_length=150, blank=True)
    email = models.EmailField(_('email address'), unique=True, db_index=True)

    role = models.CharField(
        max_length=30,
        choices=Role.choices,
        default=Role.BUYER,
        help_text=_('User role in the marketplace'),
        db_index=True,
    )
    company = models.CharField(
        max_length=200, blank=True, help_text=_('Company name (optional)'))
    phone = models.CharField(max_length=30, blank=True,
                             help_text=_('Phone number'))
    location = models.CharField(
        max_length=200, blank=True, help_text=_('User location'))
    profile_image = models.ImageField(
        upload_to='profiles/',
        blank=True,
        null=True,
        help_text=_('Profile picture of the user'),
    )
    is_verified = models.BooleanField(default=False, help_text=_(
        'Whether the user is verified (for service providers)'), db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    # tell Django to use email as the unique identifier
    USERNAME_FIELD = 'email'
    # required when using createsuperuser; adjust if you don't want username
    REQUIRED_FIELDS = ['username']

    objects = UserManager()

    class Meta:
        db_table = 'users'
        verbose_name = _('User')
        verbose_name_plural = _('Users')
        ordering = ['-created_at']

    def __str__(self):
        display = self.get_role_display() or self.email
        return f"{self.email} ({display})"

    # convenience properties
    @property
    def is_buyer(self):
        return self.role == self.Role.BUYER

    @property
    def is_seller(self):
        return self.role == self.Role.SELLER

    @property
    def is_service_provider(self):
        return self.role == self.Role.SERVICE_PROVIDER

    @property
    def is_admin_user(self):
        return self.role in [self.Role.ADMIN, self.Role.SUPER_ADMIN]

    @property
    def can_create_listings(self):
        return self.role in [self.Role.SELLER, self.Role.SERVICE_PROVIDER]

    def can_manage_user(self, user):
        """Check if current user can manage another user"""
        if self.role == self.Role.SUPER_ADMIN:
            return True
        if self.role == self.Role.ADMIN:
            return user.role not in [self.Role.ADMIN, self.Role.SUPER_ADMIN]
        return False

    def save(self, *args, **kwargs):
        # normalize email to lowercase
        if self.email:
            self.email = self.email.lower()
        super().save(*args, **kwargs)


class PasswordResetToken(models.Model):
    """Token model for password reset functionality"""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='reset_tokens')
    token = models.CharField(max_length=128, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = 'password_reset_tokens'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['expires_at']),
            models.Index(fields=['user', 'used']),
        ]

    def __str__(self):
        return f"Reset token for {self.user.email}"

    def is_expired(self):
        return timezone.now() > self.expires_at

    def is_valid(self):
        return not self.used and not self.is_expired()

    def mark_used(self):
        self.used = True
        self.save(update_fields=['used'])

    @classmethod
    def create_for_user(cls, user, ttl_hours=1):
        """Create and return a token for the given user. TTL in hours (default=1)."""
        token = secrets.token_urlsafe(48)  # secure, url-safe token
        expires = timezone.now() + timedelta(hours=ttl_hours)
        return cls.objects.create(user=user, token=token, expires_at=expires)


class VerificationRequest(models.Model):
    """Service provider verification request"""

    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending Review')
        APPROVED = 'approved', _('Approved')
        REJECTED = 'rejected', _('Rejected')
        REQUIRES_MORE_INFO = 'requires_more_info', _(
            'Requires More Information')

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='verification_requests'
    )
    company_name = models.CharField(max_length=200)
    business_license = models.FileField(
        upload_to='verification/licenses/',
        help_text=_('Business license document')
    )
    insurance_certificate = models.FileField(
        upload_to='verification/insurance/',
        help_text=_('Insurance certificate')
    )
    certifications = models.TextField(
        blank=True,
        help_text=_('Industry certifications and qualifications')
    )
    references = models.TextField(
        blank=True,
        help_text=_('Business references')
    )
    additional_info = models.TextField(
        blank=True,
        help_text=_('Additional information')
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_verifications'
    )
    admin_notes = models.TextField(
        blank=True,
        help_text=_('Admin review notes')
    )

    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'verification_requests'
        ordering = ['-created_at']
        verbose_name = _('Verification Request')
        verbose_name_plural = _('Verification Requests')

    def __str__(self):
        return f"Verification request for {self.user.email}"

    def approve(self, admin_user, notes=''):
        """Approve verification request"""
        self.status = self.Status.APPROVED
        self.reviewed_by = admin_user
        self.reviewed_at = timezone.now()
        self.admin_notes = notes
        self.save()

        # Update user verification status
        self.user.is_verified = True
        self.user.save(update_fields=['is_verified'])

    def reject(self, admin_user, notes=''):
        """Reject verification request"""
        self.status = self.Status.REJECTED
        self.reviewed_by = admin_user
        self.reviewed_at = timezone.now()
        self.admin_notes = notes
        self.save()
