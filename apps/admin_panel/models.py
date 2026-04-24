from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.conf import settings

from .constants import AdminModule, StaffRole

User = get_user_model()


class RolePermission(models.Model):
    """
    One row per (dashboard role, module). VIEW/MANAGE flags match the admin settings UI matrix.
    """

    role = models.CharField(
        max_length=32, choices=StaffRole.choices, db_index=True)
    module = models.CharField(
        max_length=64, choices=AdminModule.choices, db_index=True)
    can_view = models.BooleanField(default=False)
    can_manage = models.BooleanField(default=False)

    class Meta:
        db_table = "admin_role_permissions"
        constraints = [
            models.UniqueConstraint(
                fields=["role", "module"], name="uniq_admin_role_module"),
        ]

    def __str__(self):
        return f"{self.role} / {self.module}"


class AdminProfile(models.Model):
    """Dashboard staff: role, invite state (Add Admin modal)."""

    class InviteStatus(models.TextChoices):
        PENDING = "pending", _("Pending")
        ACTIVE = "active", _("Active")
        REVOKED = "revoked", _("Revoked")

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="admin_profile",
    )
    staff_role = models.CharField(max_length=32, choices=StaffRole.choices)
    invite_status = models.CharField(
        max_length=20,
        choices=InviteStatus.choices,
        default=InviteStatus.ACTIVE,
    )
    invite_token = models.CharField(max_length=64, blank=True, db_index=True)
    invited_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="admin_invites_sent",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "admin_profiles"

    def __str__(self):
        return f"{self.user.email} ({self.staff_role})"


class ReportedContent(models.Model):
    """Model for user-reported content."""

    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending Review')
        REVIEWED = 'reviewed', _('Reviewed')
        RESOLVED = 'resolved', _('Resolved')
        DISMISSED = 'dismissed', _('Dismissed')

    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name='reported_contents'
    )
    object_id = models.PositiveIntegerField()

    reason = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    reported_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='reports_made'
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
        related_name='reports_reviewed'
    )
    admin_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    content_object = GenericForeignKey('content_type', 'object_id')

    class Meta:
        db_table = 'reported_content'
        ordering = ['-created_at']

    def __str__(self):
        return f"Report ({self.content_type} - {self.reason})"

    def mark_as_reviewed(self, admin_user, notes=''):
        self.status = self.Status.REVIEWED
        self.reviewed_by = admin_user
        self.reviewed_at = timezone.now()
        self.admin_notes = notes
        self.save(update_fields=[
            'status', 'reviewed_by', 'reviewed_at', 'admin_notes'
        ])


class AdminActionLog(models.Model):
    class ActionType(models.TextChoices):
        # Content moderation
        CONTENT_REVIEWED = 'content_reviewed', _('Content Reviewed')
        CONTENT_RESOLVED = 'content_resolved', _('Content Resolved')
        CONTENT_DISMISSED = 'content_dismissed', _('Content Dismissed')
        REPORT_SUBMITTED = 'report_submitted', _('Report Submitted')

        # User management
        USER_VERIFIED = 'user_verified', _('User Verified')
        USER_REJECTED = 'user_rejected', _('User Rejected')
        USER_BANNED = 'user_banned', _('User Banned')
        USER_UNBANNED = 'user_unbanned', _('User Unbanned')

        # Admin management
        ADMIN_INVITED = 'admin_invited', _('Admin Invited')
        ADMIN_REVOKED = 'admin_revoked', _('Admin Revoked')
        ADMIN_ACTIVATED = 'admin_activated', _('Admin Activated')

        # Listings
        LISTING_PUBLISHED = 'listing_published', _('Listing Published')
        LISTING_ARCHIVED = 'listing_archived', _('Listing Archived')
        LISTING_REMOVED = 'listing_removed', _('Listing Removed')
        LISTING_FEATURED = 'listing_featured', _('Listing Featured')

        # Bulk actions
        BULK_ACTION_PERFORMED = 'bulk_action_performed', _(
            'Bulk Action Performed')

        # Roles & permissions
        ROLES_MATRIX_UPDATED = 'roles_matrix_updated', _(
            'Roles Matrix Updated')

        # Verification
        VERIFICATION_APPROVED = 'verification_approved', _(
            'Verification Approved')
        VERIFICATION_REJECTED = 'verification_rejected', _(
            'Verification Rejected')

    admin_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    action_type = models.CharField(
        max_length=50, choices=ActionType.choices)
    description = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    extra_data = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.action_type} by {self.admin_user}"

    @classmethod
    def log_action(cls, admin_user, action_type, description, content_object=None, extra_data=None):
        cls.objects.create(
            admin_user=admin_user,
            action_type=action_type,
            description=description,
            extra_data=extra_data or {}
        )


class PlatformConfig(models.Model):
    """
    Global platform settings. Only one row ever exists (singleton).
    """
    # Marketplace mode
    enable_buy = models.BooleanField(default=True)
    enable_rent = models.BooleanField(default=True)
    enable_services = models.BooleanField(default=False)

    # Approval rules
    vendor_approval_required = models.BooleanField(default=True)
    listing_approval_required = models.BooleanField(default=True)

    # Locale
    default_currency = models.CharField(max_length=10, default='NGN')
    timezone = models.CharField(
        max_length=50, default='Africa/Lagos')
    date_format = models.CharField(
        max_length=20, default='DD/MM/YY')

    # Security
    force_password_reset = models.BooleanField(default=False)
    session_timeout = models.BooleanField(default=True)

    # Admin notification preferences
    notify_new_vendor_signup = models.BooleanField(default=True)
    notify_new_dispute = models.BooleanField(default=True)
    notify_contract_expiring = models.BooleanField(default=False)
    notify_failed_payment = models.BooleanField(default=False)
    channel_in_app = models.BooleanField(default=True)
    channel_email = models.BooleanField(default=True)

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True
    )

    class Meta:
        db_table = 'platform_config'

    @classmethod
    def get(cls):
        """Always returns the single config instance."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Platform Configuration"
