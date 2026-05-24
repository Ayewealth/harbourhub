# apps/commerce/tasks.py
import logging
from django.utils import timezone
from celery import shared_task
from django.db import transaction
from django.db.models import Q
from apps.commerce.models import Order, OrderActivity
from apps.notifications.utils import dispatch_tracking_notification

logger = logging.getLogger(__name__)

@shared_task(name="apps.commerce.tasks.advance_rental_order_statuses_task")
def advance_rental_order_statuses_task():
    """
    Periodic task running hourly to auto-advance rental/lease orders statuses:
    1. Query all orders in 'paid' status where order_type is 'rental' or 'lease' and rental_start <= now.
       Advance status to 'active_hire', create OrderActivity, send notifications.
    2. Query all orders in 'hire_started' status where rental_end <= now.
       Advance status to 'hire_ended', create OrderActivity, notify stakeholders.
    """
    now = timezone.now().date()
    logger.info("Starting advance_rental_order_statuses_task for date: %s", now)

    # 1. Paid -> Hire Started
    paid_rentals = Order.objects.filter(
        order_type__in=[Order.OrderType.HIRE, Order.OrderType.LEASE],
        status=Order.Status.PAID,
        rental_start_date__lte=now
    )
    for order in paid_rentals:
        try:
            with transaction.atomic():
                order.status = Order.Status.ACTIVE_HIRE
                order.save(update_fields=['status'])

                OrderActivity.objects.create(
                    order=order,
                    event_type=OrderActivity.EventType.HIRE_STARTED,
                    message="Rental/lease period has officially started."
                )
                dispatch_tracking_notification(OrderActivity.EventType.HIRE_STARTED, order)
                logger.info("Successfully advanced order %s to ACTIVE_HIRE.", order.order_number)
        except Exception as exc:
            logger.exception("Failed to advance order %s to ACTIVE_HIRE: %s", order.order_number, exc)

    # 2. Hire Started -> Hire Ended
    ended_rentals = Order.objects.filter(
        order_type__in=[Order.OrderType.HIRE, Order.OrderType.LEASE],
        status=Order.Status.ACTIVE_HIRE,
        rental_end_date__lte=now
    )
    for order in ended_rentals:
        try:
            with transaction.atomic():
                order.status = Order.Status.HIRE_ENDED
                order.save(update_fields=['status'])

                OrderActivity.objects.create(
                    order=order,
                    event_type=OrderActivity.EventType.HIRE_ENDED,
                    message="Rental/lease period has officially ended. Please arrange item return."
                )
                dispatch_tracking_notification(OrderActivity.EventType.HIRE_ENDED, order)
                logger.info("Successfully advanced order %s to HIRE_ENDED.", order.order_number)
        except Exception as exc:
            logger.exception("Failed to advance order %s to HIRE_ENDED: %s", order.order_number, exc)
