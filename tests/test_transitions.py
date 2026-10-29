from decimal import Decimal

import pytest

from apps.commerce.models import Order
from apps.commerce.services.orders import InvalidTransition, transition
from apps.financials.models import VendorEarning, VendorWallet

from .factories import OrderFactory, OrderItemFactory


@pytest.mark.django_db
def test_transition_writes_activity_and_timestamp():
    order = OrderFactory(status=Order.Status.PAID)
    OrderItemFactory(order=order)

    transition(order, "order_confirmed", actor=order.seller)

    order.refresh_from_db()
    assert order.status == Order.Status.ORDER_CONFIRMED
    assert order.activities.filter(event_type="order_confirmed").exists()


@pytest.mark.django_db
def test_invalid_transition_raises():
    order = OrderFactory(status=Order.Status.PAID)
    OrderItemFactory(order=order)

    with pytest.raises(InvalidTransition):
        transition(order, "delivered", actor=order.seller)


@pytest.mark.django_db
def test_hire_order_cannot_be_fulfilled_before_the_hire_states():
    order = OrderFactory(status=Order.Status.DELIVERED)
    OrderItemFactory(order=order, purchase_type=Order.OrderType.HIRE)

    with pytest.raises(InvalidTransition):
        transition(order, "order_fulfilled", actor=order.seller)


@pytest.mark.django_db
def test_fulfilment_sets_completed_at_and_releases_the_final_tranche():
    order = OrderFactory(status=Order.Status.DELIVERED)
    OrderItemFactory(order=order)
    earning = VendorEarning.objects.create(
        order=order,
        vendor=order.seller,
        store=order.store,
        earning_type="buy",
        gross_amount=Decimal("1000.00"),
        commission_rate=Decimal("0.00"),
        commission_amount=Decimal("0.00"),
        net_amount=Decimal("1000.00"),
        released_amount=Decimal("500.00"),
        status=VendorEarning.Status.PARTIALLY_RELEASED,
    )
    wallet, _ = VendorWallet.objects.get_or_create(
        store=order.store,
        defaults={"user": order.store.user, "currency": "NGN"},
    )
    wallet.pending_balance = Decimal("500.00")
    wallet.available_balance = Decimal("500.00")
    wallet.save(update_fields=["pending_balance", "available_balance"])

    transition(order, "order_fulfilled", actor=order.seller)

    order.refresh_from_db()
    earning.refresh_from_db()
    wallet.refresh_from_db()
    assert order.completed_at is not None
    assert earning.released_amount == Decimal("1000.00")
    assert earning.status == VendorEarning.Status.AVAILABLE
    assert wallet.pending_balance == Decimal("0.00")
    assert wallet.available_balance == Decimal("1000.00")


@pytest.mark.django_db
def test_confirm_receipt_is_buyer_only_and_completes(auth_client):
    order = OrderFactory(status=Order.Status.DELIVERED)
    OrderItemFactory(order=order)

    seller = auth_client(order.seller).post(
        f"/commerce/orders/{order.id}/confirm-receipt/", {}, format="json"
    )
    buyer = auth_client(order.buyer).post(
        f"/commerce/orders/{order.id}/confirm-receipt/", {}, format="json"
    )

    assert seller.status_code == 403
    assert buyer.status_code == 200
    order.refresh_from_db()
    assert order.status == Order.Status.FULFILLED
    assert order.completed_at is not None
