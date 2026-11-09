import pytest

from apps.commerce.models import Order
from apps.commerce.serializers import OrderSerializer

from .factories import OrderFactory, OrderItemFactory


@pytest.mark.django_db
def test_order_serializer_exposes_commission_fields():
    order = OrderFactory(
        commission_rate="5.00",
        commission_amount="50.00",
        escrow_fee="0.00",
        status=Order.Status.PAID,
    )
    OrderItemFactory(order=order)

    data = OrderSerializer(order).data

    assert data["commission_rate"] == "5.00"
    assert data["commission_amount"] == "50.00"
    assert data["escrow_fee"] == "0.00"


@pytest.mark.django_db
def test_order_list_uses_integer_order_id_and_order_number(auth_client):
    order = OrderFactory()
    OrderItemFactory(order=order)

    response = auth_client(order.buyer).get("/commerce/orders/")

    assert response.status_code == 200
    row = response.data["results"][0]
    assert isinstance(row["order_id"], int)
    assert row["order_id"] == order.pk
    assert row["order_number"] == order.order_number
