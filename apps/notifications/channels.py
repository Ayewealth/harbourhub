"""Channel adapters: the only place that talks to an external provider.

Each adapter returns ``(status, provider_id, error)`` where ``status`` is a
``NotificationDelivery.Status`` value.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def _recipient_phone(delivery):
    return (
        getattr(delivery.recipient, "phone", "")
        or getattr(delivery.recipient, "phone_number", "")
        or ""
    )


def _message(delivery):
    return delivery.notification.message if delivery.notification else ""


def send_email(delivery):
    """Send a plain-text email. Always available (locmem in tests)."""
    from django.core.mail import send_mail

    send_mail(
        subject=(
            "Harbour Hub - "
            f"{delivery.event_key.replace('_', ' ').title()}"
        ),
        message=_message(delivery),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[delivery.recipient.email],
        fail_silently=False,
    )
    return "sent", "", ""


def send_sms(delivery):
    provider = getattr(settings, "SMS_PROVIDER", "")
    phone = _recipient_phone(delivery)
    if not phone:
        return "skipped", "", "Recipient has no phone number."

    if provider == "termii" and getattr(settings, "TERMII_API_KEY", ""):
        import requests

        response = requests.post(
            "https://api.ng.termii.com/api/sms/send",
            json={
                "to": phone,
                "from": settings.TERMII_SENDER_ID,
                "sms": _message(delivery),
                "type": "plain",
                "channel": "generic",
                "api_key": settings.TERMII_API_KEY,
            },
            timeout=15,
        )
        response.raise_for_status()
        return "sent", str(response.json().get("message_id", "")), ""

    return "skipped", "", "SMS provider is not configured."


def send_push(delivery):
    if not getattr(settings, "VAPID_PRIVATE_KEY", ""):
        return "skipped", "", "Push is not configured."

    from .models import PushSubscription

    subscriptions = list(
        PushSubscription.objects.filter(
            user=delivery.recipient, is_active=True
        )
    )
    if not subscriptions:
        return "skipped", "", (
            "No push subscription registered for this user."
        )

    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        return "skipped", "", "Push is not configured."

    import json

    notification = delivery.notification
    payload = json.dumps({
        "title": notification.title if notification else "",
        "body": notification.message if notification else "",
        "url": notification.action_url if notification else "",
        "type": delivery.event_key,
    })

    sent = 0
    last_error = ""
    for subscription in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {
                        "p256dh": subscription.p256dh,
                        "auth": subscription.auth,
                    },
                },
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": settings.VAPID_SUBJECT},
                timeout=10,
            )
            sent += 1
        except WebPushException as exc:
            last_error = str(exc)
            status_code = getattr(
                getattr(exc, "response", None), "status_code", None
            )
            if status_code in (404, 410):
                subscription.is_active = False
                subscription.save(
                    update_fields=["is_active", "updated_at"]
                )
        except Exception as exc:
            last_error = str(exc)

    if sent:
        return "sent", f"{sent} subscription(s)", ""
    return "failed", "", last_error or "All push subscriptions failed."


def send_staff_webhook(delivery):
    if not getattr(settings, "OPS_WEBHOOK_URL", ""):
        return "skipped", "", "OPS_WEBHOOK_URL is not configured."

    import requests

    response = requests.post(
        settings.OPS_WEBHOOK_URL,
        json={
            "text": (
                f"[{delivery.event_key}] "
                f"{_message(delivery)}"
            )
        },
        timeout=10,
    )
    response.raise_for_status()
    return "sent", "", ""
