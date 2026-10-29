from datetime import timedelta

from celery import shared_task
from django.utils import timezone

import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def deliver_notification_task(self, delivery_id):
    """Deliver one queued notification over one channel."""
    from . import channels
    from .models import NotificationDelivery

    try:
        delivery = NotificationDelivery.objects.select_related(
            "notification", "recipient"
        ).get(pk=delivery_id)
    except NotificationDelivery.DoesNotExist:
        return

    if delivery.status == NotificationDelivery.Status.SENT:
        return

    senders = {
        NotificationDelivery.Channel.EMAIL: channels.send_email,
        NotificationDelivery.Channel.SMS: channels.send_sms,
        NotificationDelivery.Channel.PUSH: channels.send_push,
        NotificationDelivery.Channel.STAFF_WEBHOOK: channels.send_staff_webhook,
    }
    sender = senders.get(delivery.channel)
    if sender is None:
        delivery.status = NotificationDelivery.Status.SKIPPED
        delivery.save(update_fields=["status", "updated_at"])
        return

    delivery.attempts += 1
    try:
        status, provider_id, error = sender(delivery)
        delivery.status = status
        delivery.provider_id = provider_id
        delivery.error = error
        delivery.save(
            update_fields=[
                "status", "provider_id", "error", "attempts", "updated_at"
            ]
        )
    except Exception as exc:
        logger.exception(
            "Notification %s failed on %s", delivery_id, delivery.channel)
        delivery.status = NotificationDelivery.Status.FAILED
        delivery.error = str(exc)
        delivery.save(
            update_fields=["status", "error", "attempts", "updated_at"]
        )
        raise self.retry(exc=exc)


@shared_task
def send_rental_reminders_task():
    """
    Send a reminder one and three days before each hire/lease period ends.

    Rental dates live on OrderItem, not Order: one order can contain a
    purchase plus a hire, and P2 makes one order per cart item anyway.
    Run daily via Celery Beat.
    """
    from apps.commerce.constants import ACTIVE_RENTAL_STATUSES
    from apps.commerce.models import OrderItem
    from .utils import notify_rental_reminder

    today = timezone.now().date()

    for days in (1, 3):
        target_date = today + timedelta(days=days)
        items = (
            OrderItem.objects.filter(
                purchase_type__in=["hire", "lease"],
                rental_end_date=target_date,
                order__status__in=ACTIVE_RENTAL_STATUSES,
            )
            .select_related("order", "order__buyer", "listing")
            .order_by("order_id")
        )

        notified_order_ids = set()
        for item in items:
            # One notification per order, no matter how many hire items it has.
            if item.order_id in notified_order_ids:
                continue
            notified_order_ids.add(item.order_id)
            notify_rental_reminder(item.order, days_left=days)
            logger.info(
                "Rental reminder sent for order %s (%d days left)",
                item.order.order_number,
                days,
            )
