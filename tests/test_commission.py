from decimal import Decimal

import pytest

from apps.commerce.models import Order
from apps.commerce.services.payments import finalize_payment
from apps.financials.models import VendorEarning
from apps.financials.services import accrue_earning

from .factories import OrderFactory, OrderItemFactory, PaymentFactory


def _paid_order(
    rate=Decimal("5.00"),
    subtotal=Decimal("200000.00"),
    delivery=Decimal("5000.00"),
):
    order = OrderFactory(
        status=Order.Status.PENDING_PAYMENT,
        subtotal=subtotal,
        delivery_fee=delivery,
        total_amount=subtotal + delivery,
        escrow_fee=Decimal("0.00"),
    )
    order.store.commission_rate = rate
    order.store.save(update_fields=["commission_rate"])
    OrderItemFactory(order=order, unit_price=subtotal, quantity=1)
    payment = PaymentFactory(
        checkout_session=order.checkout_session,
        buyer=order.buyer,
        amount=order.total_amount,
        status="pending",
    )
    return order, payment


@pytest.mark.django_db
def test_finalize_payment_snapshots_commission():
    order, payment = _paid_order()
    finalize_payment(payment, {"amount": int(payment.amount * 100)})

    order.refresh_from_db()
    assert order.status == Order.Status.PAID
    assert order.commission_rate == Decimal("5.00")
    assert order.commission_amount == Decimal("10000.00")

    earning = VendorEarning.objects.get(order=order)
    assert earning.commission_amount == Decimal("10000.00")
    assert earning.gross_amount == Decimal("205000.00")
    assert earning.net_amount == Decimal("195000.00")


@pytest.mark.django_db
def test_commission_is_charged_on_goods_not_delivery():
    order, payment = _paid_order(
        subtotal=Decimal("1000.00"), delivery=Decimal("500.00")
    )
    finalize_payment(payment, {"amount": int(payment.amount * 100)})

    order.refresh_from_db()
    assert order.commission_amount == Decimal("50.00")


@pytest.mark.django_db
def test_accrue_earning_uses_the_snapshot_rate():
    order = OrderFactory(status=Order.Status.PAID, commission_rate=Decimal("10.00"))
    OrderItemFactory(order=order)
    order.store.commission_rate = Decimal("5.00")
    order.store.save(update_fields=["commission_rate"])

    earning = accrue_earning(order)

    assert earning.commission_rate == Decimal("10.00")


@pytest.mark.django_db
def test_platform_revenue_is_the_sum_of_commissions(auth_client):
    from .factories import UserFactory

    orders = []
    for _ in range(3):
        order, payment = _paid_order()
        finalize_payment(payment, {"amount": int(payment.amount * 100)})
        orders.append(order)

    admin = UserFactory(role="admin", is_staff=True, is_superuser=True)
    response = auth_client(admin).get("/admin-panel/payments/stats/")

    expected = sum(
        Order.objects.filter(pk__in=[o.pk for o in orders]).values_list(
            "commission_amount", flat=True
        )
    )
    assert Decimal(str(response.data["platform_revenue"]["value"])) == expected
    assert expected == Decimal("30000.00")
