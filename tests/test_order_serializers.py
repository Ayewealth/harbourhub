from decimal import Decimal

import pytest

from .factories import OrderFactory, OrderItemFactory


@pytest.mark.django_db
def test_my_orders_returns_integer_id_and_total(auth_client):
    order = OrderFactory(total_amount=Decimal("1234.00"))
    OrderItemFactory(order=order)
    client = auth_client(order.buyer)

    response = client.get("/commerce/orders/my-orders/")

    row = response.data["results"][0]
    assert row["order_id"] == order.id
    assert isinstance(row["order_id"], int)
    assert row["order_number"] == order.order_number
    assert Decimal(str(row["total_amount"])) == Decimal("1234.00")
    assert row["currency"] == order.currency
    assert row["quantity"] == 1


@pytest.mark.django_db
def test_my_orders_sums_quantity_across_items(auth_client):
    order = OrderFactory()
    OrderItemFactory(order=order, quantity=2)
    OrderItemFactory(order=order, quantity=3)
    client = auth_client(order.buyer)

    response = client.get("/commerce/orders/my-orders/")

    assert response.data["results"][0]["quantity"] == 5


@pytest.mark.django_db
def test_tracking_detail_includes_amounts(auth_client):
    order = OrderFactory(
        total_amount=Decimal("1234.00"),
        subtotal=Decimal("1200.00"),
        delivery_fee=Decimal("34.00"),
        escrow_fee=Decimal("0.00"),
    )
    OrderItemFactory(order=order)
    client = auth_client(order.buyer)

    response = client.get(
        f"/commerce/orders/{order.id}/tracking/", HTTP_HH_CURRENCY="NGN"
    )

    assert response.status_code == 200
    assert response.data["order_id"] == order.id
    assert Decimal(str(response.data["total_amount"])) == Decimal("1234.00")
    assert Decimal(str(response.data["subtotal"])) == Decimal("1200.00")
    assert Decimal(str(response.data["delivery_fee"])) == Decimal("34.00")
    assert Decimal(str(response.data["escrow_fee"])) == Decimal("0.00")


@pytest.mark.django_db
def test_store_orders_returns_integer_id(auth_client):
    order = OrderFactory()
    OrderItemFactory(order=order)
    client = auth_client(order.seller)

    response = client.get("/commerce/orders/store-orders/")

    assert response.status_code == 200
    assert response.data["results"][0]["order_id"] == order.id
    assert response.data["results"][0]["quantity"] == 1
    assert response.data["results"][0]["currency"] == order.currency
