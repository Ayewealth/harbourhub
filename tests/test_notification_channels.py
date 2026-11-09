import json
import sys
import types
from decimal import Decimal

import pytest

from apps.notifications import channels
from apps.notifications.models import (
    Notification,
    NotificationDelivery,
    PushSubscription,
)

from .factories import UserFactory


def _delivery(user, **kwargs):
    notification = Notification.objects.create(
        recipient=user,
        notification_type="order_paid",
        title="Order paid",
        message="Your payment was received.",
        action_url="/orders/1",
    )
    return NotificationDelivery.objects.create(
        notification=notification,
        recipient=user,
        event_key="order_paid",
        channel=NotificationDelivery.Channel.PUSH,
        **kwargs,
    )


@pytest.mark.django_db
def test_push_is_skipped_without_a_private_key(settings):
    settings.VAPID_PRIVATE_KEY = ""
    status, provider_id, error = channels.send_push(_delivery(UserFactory()))

    assert status == "skipped"
    assert error == "Push is not configured."


@pytest.mark.django_db
def test_push_is_skipped_without_subscriptions(settings):
    settings.VAPID_PRIVATE_KEY = "private"
    status, _, error = channels.send_push(_delivery(UserFactory()))

    assert status == "skipped"
    assert error == "No push subscription registered for this user."


@pytest.mark.django_db
def test_push_sends_to_every_active_subscription(settings, monkeypatch):
    settings.VAPID_PRIVATE_KEY = "private"
    settings.VAPID_SUBJECT = "mailto:test@example.com"
    user = UserFactory()
    PushSubscription.objects.create(
        user=user, endpoint="https://push.example/1",
        p256dh="key1", auth="auth1", is_active=True,
    )
    PushSubscription.objects.create(
        user=user, endpoint="https://push.example/2",
        p256dh="key2", auth="auth2", is_active=True,
    )

    calls = []

    def fake_webpush(subscription_info, data, **kwargs):
        calls.append((subscription_info, data, kwargs))

    monkeypatch.setitem(
        sys.modules,
        "pywebpush",
        types.SimpleNamespace(webpush=fake_webpush, WebPushException=Exception),
    )

    status, provider_id, error = channels.send_push(_delivery(user))

    assert status == "sent"
    assert len(calls) == 2
    payload = json.loads(calls[0][1])
    assert payload == {
        "title": "Order paid",
        "body": "Your payment was received.",
        "url": "/orders/1",
        "type": "order_paid",
    }
    assert calls[0][2]["vapid_claims"] == {"sub": "mailto:test@example.com"}


@pytest.mark.django_db
def test_push_deactivates_a_gone_subscription(settings, monkeypatch):
    settings.VAPID_PRIVATE_KEY = "private"
    user = UserFactory()
    subscription = PushSubscription.objects.create(
        user=user, endpoint="https://push.example/gone",
        p256dh="key", auth="auth", is_active=True,
    )

    class Gone(Exception):
        response = types.SimpleNamespace(status_code=410)

    def fake_webpush(*args, **kwargs):
        raise Gone("gone")

    monkeypatch.setitem(
        sys.modules,
        "pywebpush",
        types.SimpleNamespace(
            webpush=fake_webpush, WebPushException=Gone
        ),
    )

    status, _, error = channels.send_push(_delivery(user))

    subscription.refresh_from_db()
    assert subscription.is_active is False
    assert status == "failed"
    assert "gone" in error


@pytest.mark.django_db
def test_sms_uses_termii_only(settings):
    settings.SMS_PROVIDER = "twilio"
    user = UserFactory(phone="08030000000")
    status, _, error = channels.send_sms(_delivery(user))

    assert status == "skipped"
    assert error == "SMS provider is not configured."


@pytest.mark.django_db
def test_staff_webhook_is_skipped_without_a_url(settings):
    settings.OPS_WEBHOOK_URL = ""
    delivery = _delivery(UserFactory())
    delivery.channel = NotificationDelivery.Channel.STAFF_WEBHOOK

    status, _, error = channels.send_staff_webhook(delivery)

    assert status == "skipped"
    assert error == "OPS_WEBHOOK_URL is not configured."
