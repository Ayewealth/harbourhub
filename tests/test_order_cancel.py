from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.commerce.models import Order, Payment, Refund

from .factories import OrderFactory, OrderItemFactory, PaymentFactory


@pytest.mark.django_db
def test_seller_can_read_the_order_timeline(auth_client):
    order = OrderFactory()
    OrderItemFactory(order=order)
    client = auth_client(order.seller)

    response = client.get(f"/commerce/orders/{order.id}/activity/")

    assert response.status_code == 200


@pytest.mark.django_db
def test_buyer_can_cancel_a_paid_order_and_request_a_refund(auth_client):
    order = OrderFactory(
        status=Order.Status.PAID, total_amount=Decimal("1000.00")
    )
    OrderItemFactory(order=order)
    PaymentFactory(
        checkout_session=order.checkout_session,
        buyer=order.buyer,
        amount=Decimal("1000.00"),
        status=Payment.Status.SUCCESS,
    )
    client = auth_client(order.buyer)

    with patch("apps.commerce.services.refunds.initiate_refund") as gateway:
        gateway.return_value = {"reference": "RF-TEST-1", "status": "processing"}
        response = client.post(
            f"/commerce/orders/{order.id}/cancel/",
            {"reason": "Changed my mind"},
            format="json",
        )

    assert response.status_code == 202
    refund = Refund.objects.get(payment__checkout_session=order.checkout_session)
    assert refund.status == Refund.Status.PENDING
    order.refresh_from_db()
    assert order.status == Order.Status.PAID  # cancelled when the gateway confirms


@pytest.mark.django_db
def test_paid_cancel_without_a_payment_is_rejected(auth_client):
    order = OrderFactory(status=Order.Status.PAID)
    OrderItemFactory(order=order)
    client = auth_client(order.buyer)

    response = client.post(
        f"/commerce/orders/{order.id}/cancel/", {}, format="json"
    )

    assert response.status_code == 400
