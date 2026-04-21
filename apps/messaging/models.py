from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Conversation(models.Model):
    """
    A conversation between a buyer and a vendor,
    optionally tied to a listing or store.
    """
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='conversations_as_buyer'
    )
    vendor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='conversations_as_vendor'
    )
    listing = models.ForeignKey(
        'listings.Listing',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='conversations'
    )
    store = models.ForeignKey(
        'store.Store',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='conversations'
    )
    # Track last message for sorting conversation list
    last_message_at = models.DateTimeField(null=True, blank=True)
    last_message_preview = models.CharField(
        max_length=200, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'conversations'
        ordering = ['-last_message_at']
        # One conversation per buyer-vendor-listing combo
        constraints = [
            models.UniqueConstraint(
                fields=['buyer', 'vendor', 'listing'],
                name='unique_conversation'
            )
        ]
        indexes = [
            models.Index(fields=['buyer', '-last_message_at']),
            models.Index(fields=['vendor', '-last_message_at']),
        ]

    def __str__(self):
        return (f"Conversation between {self.buyer.email} "
                f"and {self.vendor.email}")

    def get_other_participant(self, user):
        return self.vendor if user == self.buyer else self.buyer

    def unread_count_for(self, user):
        return self.messages.filter(
            is_read=False
        ).exclude(sender=user).count()


class Message(models.Model):
    """A message in a conversation."""

    class MessageType(models.TextChoices):
        TEXT = 'text', _('Text')
        QUOTE = 'quote', _('Quote')
        CHANGE_REQUEST = 'change_request', _('Change Request')
        SYSTEM = 'system', _('System')

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='messages'
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_messages'
    )
    message_type = models.CharField(
        max_length=20,
        choices=MessageType.choices,
        default=MessageType.TEXT
    )
    body = models.TextField(blank=True)

    # For quote messages — link to QuoteRequest
    quote_request = models.ForeignKey(
        'commerce.QuoteRequest',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='messages'
    )

    # For reply threading
    reply_to = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='replies'
    )

    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'messages'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
            models.Index(fields=['conversation', 'is_read']),
        ]

    def __str__(self):
        return (f"Message from {self.sender.email} "
                f"in conversation {self.conversation_id}")

    def mark_as_read(self):
        if not self.is_read:
            from django.utils import timezone
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])
