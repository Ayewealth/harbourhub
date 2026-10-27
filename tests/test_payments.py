import hashlib
import hmac
import json

import pytest
from django.conf import settings
from rest_framework import status

from apps.commerce.models import Payment, WebhookEvent
from apps.commerce.services.payments import finalize_payment
from apps.financials.models import VendorEarning
from tests.factories import OrderFactory, OrderItemFactory, PaymentFactory


def _signed(client, payload):
    body = json.dumps(payload).encode()
    signature = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode(), body, hashlib.sha512
    ).hexdigest()
    return client.post(
        "/commerce/payment/webhook/",
        data=body,
        content_type="application/json",
        HTTP_X_PAYSTACK_SIGNATURE=signature,
    )


@pytest.mark.django_db
def test_finalize_is_idempotent():
    order = OrderFactory()
    OrderItemFactory(order=order)
    payment = PaymentFactory(
        checkout_session=order.checkout_session, amount=order.total_amount
    )

    assert finalize_payment(
        payment,
        {"reference": payment.reference, "amount": int(payment.amount * 100)},
    ) is True
    assert finalize_payment(payment, {"reference": payment.reference}) is False
    assert VendorEarning.objects.filter(order=order).count() == 1


@pytest.mark.django_db
def test_duplicate_webhook_is_ignored(api_client):
    order = OrderFactory()
    OrderItemFactory(order=order)
    payment = PaymentFactory(
        checkout_session=order.checkout_session, amount=order.total_amount
    )
    payload = {
        "event": "charge.success",
        "data": {
            "id": 99123,
            "reference": payment.reference,
            "amount": int(payment.amount * 100),
        },
    }

    assert _signed(api_client, payload).status_code == 200
    assert _signed(api_client, payload).status_code == 200

    assert WebhookEvent.objects.count() == 1
    assert VendorEarning.objects.filter(order=order).count() == 1


@pytest.mark.django_db
def test_bad_signature_is_rejected(api_client):
    response = api_client.post(
        "/commerce/payment/webhook/",
        data=json.dumps({"event": "charge.success", "data": {}}),
        content_type="application/json",
        HTTP_X_PAYSTACK_SIGNATURE="nope",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_verify_never_writes(api_client, auth_client, monkeypatch):
    payment = PaymentFactory()
    client = auth_client(payment.buyer)
    monkeypatch.setattr(
        "apps.commerce.views.verify_transaction",
        lambda reference: {
            "status": "success", "reference": reference, "amount": 0,
        },
    )

    response = client.get(f"/commerce/payment/verify/{payment.reference}/")

    assert response.status_code == 200
    assert response.data["status"] == "pending_confirmation"
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING
