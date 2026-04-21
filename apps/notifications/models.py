from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Notification(models.Model):
    """In-app notification for a user."""

    class NotificationType(models.TextChoices):
        # Orders
        ORDER_PLACED = 'order_placed', _('Order Placed')
        ORDER_PAID = 'order_paid', _('Order Paid')
        ORDER_SHIPPED = 'order_shipped', _('Order Shipped')
        ORDER_DELIVERED = 'order_delivered', _('Order Delivered')
        ORDER_CANCELLED = 'order_cancelled', _('Order Cancelled')
        ORDER_COMPLETED = 'order_completed', _('Order Completed')

        # Quotes
        QUOTE_RECEIVED = 'quote_received', _('Quote Received')
        QUOTE_RESPONDED = 'quote_responded', _('Quote Responded')
        QUOTE_CANCELLED = 'quote_cancelled', _('Quote Cancelled')
        QUOTE_CONVERTED = 'quote_converted', _('Quote Converted')

        # Messages
        NEW_MESSAGE = 'new_message', _('New Message')
        NEW_INQUIRY = 'new_inquiry', _('New Inquiry')
        INQUIRY_REPLIED = 'inquiry_replied', _('Inquiry Replied')

        # Reviews
        NEW_REVIEW = 'new_review', _('New Review')

        # Payments
        PAYMENT_SUCCESS = 'payment_success', _('Payment Successful')
        PAYMENT_FAILED = 'payment_failed', _('Payment Failed')
        PAYOUT_PROCESSED = 'payout_processed', _('Payout Processed')
        PAYOUT_FAILED = 'payout_failed', _('Payout Failed')

        # Store / Listings
        LISTING_APPROVED = 'listing_approved', _('Listing Approved')
        LISTING_REJECTED = 'listing_rejected', _('Listing Rejected')
        STORE_VERIFIED = 'store_verified', _('Store Verified')

        # Account
        VERIFICATION_APPROVED = 'verification_approved', _(
            'Verification Approved')
        VERIFICATION_REJECTED = 'verification_rejected', _(
            'Verification Rejected')

        # Rental
        RENTAL_REMINDER = 'rental_reminder', _('Rental Reminder')
        RENTAL_EXTENDED = 'rental_extended', _('Rental Extended')

    class Priority(models.TextChoices):
        LOW = 'low', _('Low')
        MEDIUM = 'medium', _('Medium')
        HIGH = 'high', _('High')

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    notification_type = models.CharField(
        max_length=50,
        choices=NotificationType.choices,
        db_index=True
    )
    title = models.CharField(max_length=255)
    message = models.TextField()
    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM
    )

    # Optional link data so frontend can navigate to the right page
    action_url = models.CharField(
        max_length=500, blank=True,
        help_text="Frontend route e.g. /orders/123"
    )
    action_label = models.CharField(
        max_length=100, blank=True,
        help_text="e.g. 'View Order'"
    )

    # Optional related object metadata
    related_object_type = models.CharField(max_length=50, blank=True)
    related_object_id = models.PositiveIntegerField(null=True, blank=True)

    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', '-created_at']),
            models.Index(fields=['recipient', 'is_read']),
        ]

    def __str__(self):
        return f"{self.notification_type} → {self.recipient.email}"

    def mark_as_read(self):
        if not self.is_read:
            from django.utils import timezone
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])
