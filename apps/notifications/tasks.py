from datetime import timedelta

from celery import shared_task
from django.utils import timezone

import logging

logger = logging.getLogger(__name__)


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
