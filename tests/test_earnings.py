from decimal import Decimal

import pytest

from apps.financials.models import VendorEarning, VendorWallet
from apps.financials.services import accrue_earning, release_earning, reverse_earning
from tests.factories import OrderFactory, OrderItemFactory


@pytest.mark.django_db
def test_accrual_is_idempotent():
    order = OrderFactory()
    OrderItemFactory(order=order)
    earning = accrue_earning(order)
    again = accrue_earning(order)

    assert VendorEarning.objects.filter(order=order).count() == 1
    assert earning.pk == again.pk
    assert earning.net_amount == Decimal("950.00")


@pytest.mark.django_db
def test_release_moves_pending_to_available():
    order = OrderFactory()
    OrderItemFactory(order=order)
    earning = accrue_earning(order)
    wallet = VendorWallet.objects.get(user=order.seller, store=order.store)
    wallet.pending_balance = earning.net_amount
    wallet.save(update_fields=["pending_balance"])

    release_earning(earning, Decimal("475.00"))

    earning.refresh_from_db()
    wallet.refresh_from_db()
    assert earning.status == VendorEarning.Status.PARTIALLY_RELEASED
    assert earning.released_amount == Decimal("475.00")
    assert wallet.available_balance == Decimal("475.00")
    assert wallet.pending_balance == Decimal("475.00")


@pytest.mark.django_db
def test_reversal_does_not_leave_phantom_pending_balance():
    order = OrderFactory()
    OrderItemFactory(order=order)
    earning = accrue_earning(order)
    wallet = VendorWallet.objects.get(user=order.seller, store=order.store)
    wallet.pending_balance = earning.net_amount
    wallet.save(update_fields=["pending_balance"])

    reverse_earning(earning, "test refund")

    earning.refresh_from_db()
    wallet.refresh_from_db()
    assert earning.status == VendorEarning.Status.REVERSED
    assert wallet.pending_balance == Decimal("0.00")
