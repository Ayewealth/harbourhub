from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

User = get_user_model()


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
    """Admin action audit log"""

    class ActionType(models.TextChoices):
        CONTENT_REVIEWED = 'content_reviewed', _('Content Reviewed')
        USER_VERIFIED = 'user_verified', _('User Verified')
        BULK_ACTION_PERFORMED = 'bulk_action_performed', _(
            'Bulk Action Performed')

    admin_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    action_type = models.CharField(max_length=50, choices=ActionType.choices)
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
