from decimal import Decimal

import pytest
from rest_framework import status

from apps.commerce.models import Order, OrderItem
from tests.factories import CartItemFactory


@pytest.fixture(autouse=True)
def fake_gateway(monkeypatch):
    monkeypatch.setattr(
        "apps.commerce.views.initialize_transaction",
        lambda **kwargs: {
            "authorization_url": "https://checkout.paystack.com/test",
            "access_code": "test-code",
        },
    )


@pytest.mark.django_db
def test_buyer_total_has_no_platform_fee(api_client, auth_client):
    item = CartItemFactory()
    client = auth_client(item.cart.buyer)

    response = client.post(
        "/commerce/checkout/",
        {"cart_item_ids": [item.id], "terms_accepted": True},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    order = Order.objects.get(pk=response.data["orders"][0]["order_id"])
    assert order.escrow_fee == Decimal("0.00")
    assert order.total_amount == order.subtotal


@pytest.mark.django_db
def test_rent_maps_to_hire(api_client, auth_client):
    item = CartItemFactory(
        purchase_type="rent",
        duration_days=3,
        unit_price=Decimal("100.00"),
    )
    client = auth_client(item.cart.buyer)

    response = client.post(
        "/commerce/checkout/",
        {"cart_item_ids": [item.id], "terms_accepted": True},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    order_item = OrderItem.objects.get(order__pk=response.data["orders"][0]["order_id"])
    assert order_item.purchase_type == Order.OrderType.HIRE
