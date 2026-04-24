from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class SupportTicket(models.Model):

    class TicketType(models.TextChoices):
        SUPPORT = 'support', _('Support')

    class Priority(models.TextChoices):
        LOW = 'low', _('Low')
        MEDIUM = 'medium', _('Medium')
        HIGH = 'high', _('High')

    class Status(models.TextChoices):
        OPEN = 'open', _('Open')
        IN_PROGRESS = 'in_progress', _('In Progress')
        RESOLVED = 'resolved', _('Resolved')
        CLOSED = 'closed', _('Closed')

    class RaisedBy(models.TextChoices):
        BUYER = 'buyer', _('Buyer')
        VENDOR = 'vendor', _('Vendor')

    ticket_type = models.CharField(
        max_length=20,
        choices=TicketType.choices,
        default=TicketType.SUPPORT,
        db_index=True
    )
    raised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='support_tickets'
    )
    raised_by_role = models.CharField(
        max_length=10,
        choices=RaisedBy.choices,
        default=RaisedBy.BUYER
    )
    order = models.ForeignKey(
        'commerce.Order',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='support_tickets'
    )
    listing = models.ForeignKey(
        'listings.Listing',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='support_tickets'
    )
    subject = models.CharField(max_length=255)
    description = models.TextField()
    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
        db_index=True
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True
    )

    # Admin handling
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='assigned_tickets'
    )
    resolution_notes = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'support_tickets'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['ticket_type', '-created_at']),
            models.Index(fields=['priority', '-created_at']),
        ]

    def __str__(self):
        return f"{self.ticket_type} #{self.pk} - {self.subject}"

    def mark_as_resolved(self, admin_user, notes=''):
        from django.utils import timezone
        self.status = self.Status.RESOLVED
        self.resolved_at = timezone.now()
        self.resolution_notes = notes
        self.assigned_to = admin_user
        self.save(update_fields=[
            'status', 'resolved_at',
            'resolution_notes', 'assigned_to'
        ])
