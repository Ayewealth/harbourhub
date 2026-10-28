from datetime import timedelta

import pytest
from django.utils import timezone

from apps.commerce.models import Order
from apps.notifications.models import Notification
from apps.notifications.tasks import send_rental_reminders_task

from .factories import OrderFactory, OrderItemFactory


@pytest.mark.django_db
def test_rental_reminder_uses_order_item_dates():
    today = timezone.now().date()
    order = OrderFactory(status=Order.Status.ACTIVE_HIRE)
    OrderItemFactory(
        order=order,
        purchase_type=Order.OrderType.HIRE,
        rental_start_date=today - timedelta(days=2),
        rental_end_date=today + timedelta(days=1),
        duration_days=3,
    )

    send_rental_reminders_task()

    assert Notification.objects.filter(
        recipient=order.buyer,
        notification_type="rental_reminder",
    ).exists()


@pytest.mark.django_db
def test_rental_reminder_does_not_send_for_finished_orders():
    today = timezone.now().date()
    order = OrderFactory(status=Order.Status.FULFILLED)
    OrderItemFactory(
        order=order,
        purchase_type=Order.OrderType.HIRE,
        rental_start_date=today - timedelta(days=2),
        rental_end_date=today + timedelta(days=1),
        duration_days=3,
    )

    send_rental_reminders_task()

    assert not Notification.objects.filter(
        recipient=order.buyer,
        notification_type="rental_reminder",
    ).exists()
