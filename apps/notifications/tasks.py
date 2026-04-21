from celery import shared_task
import logging

logger = logging.getLogger(__name__)


@shared_task
def send_rental_reminders_task():
    """
    Check all active hire/lease orders and send reminders
    if rental is ending in 1 or 3 days.
    Run daily via Celery Beat.
    """
    from django.utils import timezone
    from datetime import timedelta
    from apps.commerce.models import Order
    from .utils import notify_rental_reminder

    today = timezone.now().date()
    reminder_days = [1, 3]

    for days in reminder_days:
        target_date = today + timedelta(days=days)
        orders = Order.objects.filter(
            order_type__in=['hire', 'lease'],
            status=Order.Status.PAID,
            rental_end_date=target_date,
        ).select_related('buyer', 'listing')

        for order in orders:
            notify_rental_reminder(order, days_left=days)
            logger.info(
                "Rental reminder sent for order %s (%d days left)",
                order.order_number, days
            )
