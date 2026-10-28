from decimal import Decimal

import pytest

from .factories import OrderFactory, OrderItemFactory


@pytest.mark.django_db
def test_order_has_one_item_accessor():
    order = OrderFactory()
    item = OrderItemFactory(order=order)

    assert order.item == item
    assert order.purchase_type == item.purchase_type


@pytest.mark.django_db
def test_order_store_matches_seller_store():
    order = OrderFactory()

    assert order.store is not None
    assert order.seller_id == order.store.user_id


@pytest.mark.django_db
def test_commission_snapshot_defaults_to_zero_before_payment():
    order = OrderFactory(commission_amount=Decimal("0.00"))

    assert order.commission_amount == Decimal("0.00")
