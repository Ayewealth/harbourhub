from decimal import Decimal

import pytest

from apps.commerce.models import Order, Payment, Refund
from apps.commerce.services.refunds import finalize_refund
from apps.financials.models import VendorEarning, VendorWallet

from .factories import OrderFactory, OrderItemFactory, PaymentFactory


def _paid_order():
    order = OrderFactory(
        status=Order.Status.PAID,
        subtotal=Decimal("1000.00"),
        total_amount=Decimal("1000.00"),
    )
    OrderItemFactory(order=order)
    payment = PaymentFactory(
        checkout_session=order.checkout_session,
        buyer=order.buyer,
        amount=Decimal("1000.00"),
        status=Payment.Status.SUCCESS,
    )
    earning = VendorEarning.objects.create(
        order=order,
        vendor=order.seller,
        store=order.store,
        earning_type="buy",
        gross_amount=Decimal("1000.00"),
        commission_rate=Decimal("0.00"),
        commission_amount=Decimal("0.00"),
        net_amount=Decimal("1000.00"),
        status=VendorEarning.Status.PARTIALLY_RELEASED,
        released_amount=Decimal("500.00"),
    )
    wallet, _ = VendorWallet.objects.get_or_create(
        store=order.store,
        defaults={"user": order.store.user, "currency": "NGN"},
    )
    wallet.pending_balance = Decimal("500.00")
    wallet.available_balance = Decimal("500.00")
    wallet.save(update_fields=["pending_balance", "available_balance"])
    return order, payment, earning, wallet


@pytest.mark.django_db
def test_full_refund_reverses_the_earning_and_zeroes_the_wallet():
    order, payment, earning, wallet = _paid_order()
    refund = Refund.objects.create(
        payment=payment,
        amount=Decimal("1000.00"),
        currency="NGN",
        reference="RF-FULL",
        reason="Not delivered",
    )

    finalize_refund(refund)

    order.refresh_from_db()
    payment.refresh_from_db()
    earning.refresh_from_db()
    wallet.refresh_from_db()
    assert order.status == Order.Status.CANCELLED
    assert order.cancelled_at is not None
    assert earning.status == VendorEarning.Status.REVERSED
    assert earning.net_amount == Decimal("0.00")
    assert wallet.pending_balance == Decimal("0.00")
    assert wallet.available_balance == Decimal("0.00")
    assert payment.status == Payment.Status.REFUNDED
    assert order.activities.filter(event_type="order_refunded").exists()


@pytest.mark.django_db
def test_partial_refund_reverses_proportionally_and_keeps_the_order():
    order, payment, earning, wallet = _paid_order()
    refund = Refund.objects.create(
        payment=payment,
        amount=Decimal("250.00"),
        currency="NGN",
        reference="RF-PART",
        reason="Partial",
    )

    finalize_refund(refund)

    order.refresh_from_db()
    payment.refresh_from_db()
    earning.refresh_from_db()
    wallet.refresh_from_db()
    assert order.status == Order.Status.PAID
    assert order.cancelled_at is None
    assert earning.net_amount == Decimal("750.00")
    # The reversal comes out of the still-held tranche first.
    assert wallet.pending_balance == Decimal("250.00")
    assert wallet.available_balance == Decimal("500.00")
    assert payment.status == Payment.Status.PARTIALLY_REFUNDED


@pytest.mark.django_db
def test_partial_refund_beyond_the_pending_tranche_takes_from_available():
    order, payment, earning, wallet = _paid_order()
    refund = Refund.objects.create(
        payment=payment,
        amount=Decimal("750.00"),
        currency="NGN",
        reference="RF-BIG",
        reason="Most of it",
    )

    finalize_refund(refund)

    earning.refresh_from_db()
    wallet.refresh_from_db()
    assert earning.net_amount == Decimal("250.00")
    assert wallet.pending_balance == Decimal("0.00")
    assert wallet.available_balance == Decimal("250.00")


@pytest.mark.django_db
def test_refund_is_idempotent():
    order, payment, earning, wallet = _paid_order()
    refund = Refund.objects.create(
        payment=payment,
        amount=Decimal("1000.00"),
        currency="NGN",
        reference="RF-ONCE",
        reason="Duplicate",
    )

    finalize_refund(refund)
    finalize_refund(refund)

    wallet.refresh_from_db()
    earning.refresh_from_db()
    assert wallet.pending_balance == Decimal("0.00")
    assert wallet.available_balance == Decimal("0.00")
    assert earning.net_amount == Decimal("0.00")


@pytest.mark.django_db
def test_a_refund_writes_one_reversal_ledger_row():
    from apps.financials.models import WalletTransaction

    order, payment, earning, wallet = _paid_order()
    refund = Refund.objects.create(
        payment=payment,
        amount=Decimal("250.00"),
        currency="NGN",
        reference="RF-LEDGER",
        reason="Ledger check",
    )

    finalize_refund(refund)

    rows = WalletTransaction.objects.filter(
        wallet=wallet, transaction_type=WalletTransaction.Type.REFUND
    )
    assert rows.count() == 1
    assert rows.first().amount == Decimal("-250.00")
