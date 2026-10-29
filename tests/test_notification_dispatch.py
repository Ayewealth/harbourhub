import pytest
from django.core import mail

from apps.notifications.models import Notification, NotificationDelivery
from apps.notifications.utils import notify_order_paid

from .factories import OrderFactory, OrderItemFactory


def _deliver_all():
    from apps.notifications.tasks import deliver_notification_task

    for delivery in NotificationDelivery.objects.all():
        try:
            deliver_notification_task(delivery.id)
        except Exception:
            pass


@pytest.mark.django_db
def test_order_event_creates_a_delivery_per_channel():
    order = OrderFactory()
    OrderItemFactory(order=order)

    notify_order_paid(order)

    notification = Notification.objects.filter(recipient=order.buyer).get()
    channels = set(
        notification.deliveries.values_list("channel", flat=True)
    )
    assert {"email", "sms", "push"} <= channels
    # The notification row itself is the in-app channel.
    assert "in_app" not in channels


@pytest.mark.django_db
def test_email_is_actually_sent(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    order = OrderFactory()
    OrderItemFactory(order=order)

    notify_order_paid(order)
    for delivery in NotificationDelivery.objects.filter(channel="email"):
        from apps.notifications.tasks import deliver_notification_task

        deliver_notification_task(delivery.id)

    assert len(mail.outbox) >= 1
    for delivery in NotificationDelivery.objects.filter(channel="email"):
        delivery.refresh_from_db()
        assert delivery.status == NotificationDelivery.Status.SENT
        assert delivery.attempts == 1


@pytest.mark.django_db
def test_sms_and_push_skip_without_credentials(settings):
    settings.SMS_PROVIDER = ""
    settings.VAPID_PRIVATE_KEY = ""
    order = OrderFactory()
    OrderItemFactory(order=order)

    notify_order_paid(order)

    for delivery in NotificationDelivery.objects.exclude(channel="email"):
        from apps.notifications.tasks import deliver_notification_task

        deliver_notification_task(delivery.id)
        delivery.refresh_from_db()
        assert delivery.status == NotificationDelivery.Status.SKIPPED
        assert delivery.error


@pytest.mark.django_db
def test_staff_webhook_skips_without_a_url(settings):
    from apps.notifications.utils import notify_order_refunded

    settings.OPS_WEBHOOK_URL = ""
    order = OrderFactory()
    OrderItemFactory(order=order)

    notify_order_refunded(order, amount="100.00", reason="Test")

    delivery = NotificationDelivery.objects.filter(
        recipient=order.buyer, channel="staff_webhook"
    ).get()
    from apps.notifications.tasks import deliver_notification_task

    deliver_notification_task(delivery.id)
    delivery.refresh_from_db()
    assert delivery.status == NotificationDelivery.Status.SKIPPED


@pytest.mark.django_db
def test_opted_out_user_gets_a_skipped_row(settings):
    from apps.notifications.models import NotificationPreference

    order = OrderFactory()
    OrderItemFactory(order=order)
    NotificationPreference.objects.create(
        user=order.buyer,
        category=NotificationPreference.Category.TRANSACTIONAL,
        sms=False,
    )

    notify_order_paid(order)

    row = NotificationDelivery.objects.get(
        recipient=order.buyer, channel="sms"
    )
    assert row.status == NotificationDelivery.Status.SKIPPED
    assert "opted out" in row.error.lower()


@pytest.mark.django_db
def test_one_channel_failure_does_not_block_another(monkeypatch, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    order = OrderFactory()
    OrderItemFactory(order=order)

    from apps.notifications import channels

    monkeypatch.setattr(
        channels,
        "send_sms",
        lambda delivery: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    notify_order_paid(order)

    _deliver_all()

    assert Notification.objects.filter(recipient=order.buyer).exists()
    email_rows = NotificationDelivery.objects.filter(
        channel="email", status=NotificationDelivery.Status.SENT
    )
    assert email_rows.exists()
    failed_rows = NotificationDelivery.objects.filter(
        channel="sms", status=NotificationDelivery.Status.FAILED
    )
    assert failed_rows.exists()


@pytest.mark.django_db
def test_a_sent_delivery_is_not_resent(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    order = OrderFactory()
    OrderItemFactory(order=order)

    notify_order_paid(order)
    delivery = NotificationDelivery.objects.filter(channel="email").first()

    from apps.notifications.tasks import deliver_notification_task

    deliver_notification_task(delivery.id)
    deliver_notification_task(delivery.id)

    delivery.refresh_from_db()
    assert delivery.attempts == 1
