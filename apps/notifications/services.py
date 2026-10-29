"""Notification dispatcher: decides the channels, then queues deliveries.

Sending lives in ``channels.py``; this module never calls a provider.
"""
import logging

from django.db import transaction

logger = logging.getLogger(__name__)

CHANNELS_BY_EVENT = {
    "order_placed": {"in_app", "email", "sms", "push"},
    "order_paid": {"in_app", "email", "sms", "push"},
    "payment_success": {"in_app", "email", "sms", "push"},
    "payment_failed": {"in_app", "email", "sms", "push"},
    "order_confirmed": {"in_app", "email", "push"},
    "order_shipped": {"in_app", "email", "sms", "push"},
    "order_delivered": {"in_app", "email", "push"},
    "order_completed": {"in_app", "email", "push"},
    "order_cancelled": {"in_app", "email", "sms", "push"},
    "order_refunded": {"in_app", "email", "sms", "push", "staff_webhook"},
    "rental_reminder": {"in_app", "email", "sms", "push"},
    "rental_extended": {"in_app", "email", "push"},
    "payout_processed": {"in_app", "email", "sms", "push"},
    "payout_failed": {"in_app", "email", "sms", "push", "staff_webhook"},
    "verification_approved": {"in_app", "email", "sms", "push"},
    "verification_rejected": {"in_app", "email", "sms", "push"},
    "new_review": {"in_app", "email", "push"},
    "new_message": {"in_app", "push"},
    "new_inquiry": {"in_app", "email", "push"},
    "inquiry_replied": {"in_app", "email", "push"},
    "quote_received": {"in_app", "email", "sms", "push"},
    "quote_responded": {"in_app", "email", "sms", "push"},
}
DEFAULT_CHANNELS = {"in_app", "email", "push"}
TRANSACTIONAL = set(CHANNELS_BY_EVENT)
ALWAYS_ON = {"in_app", "email"}


def channels_for(event_key):
    return CHANNELS_BY_EVENT.get(event_key, DEFAULT_CHANNELS)


def _preference_allows(user, channel, event_key):
    # Transactional in-app and email are not opt-out-able: a buyer must still
    # receive the record of their own order.
    if channel in ALWAYS_ON and event_key in TRANSACTIONAL:
        return True

    from .models import NotificationPreference

    category = (
        NotificationPreference.Category.TRANSACTIONAL
        if event_key in TRANSACTIONAL
        else NotificationPreference.Category.MESSAGES
    )
    pref = NotificationPreference.objects.filter(
        user=user, category=category
    ).first()
    if pref is None:
        return True
    return getattr(pref, channel, True)


def enqueue_deliveries(notification, event_key=None):
    """Create a ledger row per enabled channel and return the rows."""
    from .models import NotificationDelivery

    event_key = event_key or notification.notification_type
    queued = []

    for channel in sorted(channels_for(event_key)):
        # The Notification row itself is the in-app channel.
        if channel == "in_app":
            continue

        if not _preference_allows(notification.recipient, channel, event_key):
            queued.append(
                NotificationDelivery.objects.create(
                    notification=notification,
                    recipient=notification.recipient,
                    event_key=event_key,
                    channel=channel,
                    status=NotificationDelivery.Status.SKIPPED,
                    error="Recipient opted out.",
                )
            )
            continue

        delivery = NotificationDelivery.objects.create(
            notification=notification,
            recipient=notification.recipient,
            event_key=event_key,
            channel=channel,
        )
        queued.append(delivery)
        transaction.on_commit(
            lambda delivery_id=delivery.id: _schedule(delivery_id)
        )

    return queued


def _schedule(delivery_id):
    from .tasks import deliver_notification_task

    try:
        deliver_notification_task.delay(delivery_id)
    except Exception as exc:  # broker unavailable must not break the request
        logger.warning(
            "Could not queue notification %s: %s", delivery_id, exc)
