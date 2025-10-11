from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from apps.listings.models import Listing


class Inquiry(models.Model):
    """Inquiry model for buyer-seller communication"""

    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        READ = 'read', _('Read')
        REPLIED = 'replied', _('Replied')
        CLOSED = 'closed', _('Closed')
        SPAM = 'spam', _('Spam')

    # Core fields
    listing = models.ForeignKey(
        Listing,
        on_delete=models.CASCADE,
        related_name='inquiries',
        help_text=_('The listing this inquiry is about')
    )
    from_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_inquiries',
        help_text=_('User who sent the inquiry')
    )
    to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='received_inquiries',
        help_text=_('User who received the inquiry (listing owner)')
    )

    # Inquiry content
    subject = models.CharField(
        max_length=200,
        help_text=_('Inquiry subject')
    )
    message = models.TextField(
        help_text=_('Inquiry message')
    )

    # Contact information (from inquiry form)
    contact_name = models.CharField(
        max_length=100,
        help_text=_('Inquirer contact name')
    )
    contact_email = models.EmailField(
        help_text=_('Inquirer contact email')
    )
    contact_phone = models.CharField(
        max_length=30,
        blank=True,
        help_text=_('Inquirer contact phone')
    )
    contact_company = models.CharField(
        max_length=200,
        blank=True,
        help_text=_('Inquirer company')
    )

    # Status and metadata
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
        help_text=_('Inquiry status')
    )
    is_urgent = models.BooleanField(
        default=False,
        help_text=_('Whether this is marked as urgent')
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('When the inquiry was first read')
    )
    replied_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('When the inquiry was replied to')
    )

    # IP tracking for spam prevention
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text=_('IP address of inquirer')
    )
    user_agent = models.TextField(
        blank=True,
        help_text=_('User agent of inquirer')
    )

    class Meta:
        db_table = 'inquiries'
        verbose_name = _('Inquiry')
        verbose_name_plural = _('Inquiries')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['listing', '-created_at']),
            models.Index(fields=['from_user', '-created_at']),
            models.Index(fields=['to_user', '-created_at']),
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return f"Inquiry from {self.contact_name} about {self.listing.title}"

    @property
    def is_read(self):
        return self.read_at is not None

    @property
    def is_replied(self):
        return self.replied_at is not None

    def mark_as_read(self):
        """Mark inquiry as read"""
        if not self.is_read:
            from django.utils import timezone
            self.read_at = timezone.now()
            self.status = self.Status.READ
            self.save(update_fields=['read_at', 'status'])

    def mark_as_replied(self):
        """Mark inquiry as replied"""
        if not self.is_replied:
            from django.utils import timezone
            self.replied_at = timezone.now()
            self.status = self.Status.REPLIED
            self.save(update_fields=['replied_at', 'status'])

    def save(self, *args, **kwargs):
        # Auto-set to_user from listing owner
        if not self.to_user_id and self.listing_id:
            self.to_user = self.listing.user
        super().save(*args, **kwargs)


class InquiryReply(models.Model):
    """Replies to inquiries"""

    inquiry = models.ForeignKey(
        Inquiry,
        on_delete=models.CASCADE,
        related_name='replies',
        help_text=_('The inquiry this reply belongs to')
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='inquiry_replies',
        help_text=_('User who sent the reply')
    )
    message = models.TextField(
        help_text=_('Reply message')
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'inquiry_replies'
        verbose_name = _('Inquiry Reply')
        verbose_name_plural = _('Inquiry Replies')
        ordering = ['created_at']

    def __str__(self):
        return f"Reply to inquiry #{self.inquiry.id}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Mark original inquiry as replied
        self.inquiry.mark_as_replied()


class InquiryAttachment(models.Model):
    """File attachments for inquiries"""

    inquiry = models.ForeignKey(
        Inquiry,
        on_delete=models.CASCADE,
        related_name='attachments',
        help_text=_('The inquiry this attachment belongs to')
    )
    file = models.FileField(
        upload_to='inquiries/attachments/',
        help_text=_('Attached file')
    )
    original_name = models.CharField(
        max_length=255,
        help_text=_('Original filename')
    )
    file_size = models.PositiveIntegerField(
        help_text=_('File size in bytes')
    )
    content_type = models.CharField(
        max_length=100,
        blank=True,
        help_text=_('MIME type')
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'inquiry_attachments'
        verbose_name = _('Inquiry Attachment')
        verbose_name_plural = _('Inquiry Attachments')

    def __str__(self):
        return f"Attachment: {self.original_name}"

    def save(self, *args, **kwargs):
        if self.file and not self.original_name:
            self.original_name = self.file.name
        if self.file and not self.file_size:
            self.file_size = self.file.size
        super().save(*args, **kwargs)
