from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.financials.models import VendorEarning, VendorWallet
from apps.financials.tasks import release_pending_earnings_task

from .factories import OrderFactory, OrderItemFactory, VendorEarningFactory


def _earning(net=Decimal("1000.00"), pending=None, available=Decimal("0.00"),
             **kwargs):
    order = OrderFactory()
    OrderItemFactory(order=order)
    earning = VendorEarningFactory(
        order=order,
        store=order.store,
        vendor=order.seller,
        gross_amount=net,
        commission_amount=Decimal("0.00"),
        net_amount=net,
        **kwargs,
    )
    wallet, _ = VendorWallet.objects.get_or_create(
        store=order.store,
        defaults={"user": order.store.user, "currency": "NGN"},
    )
    wallet.pending_balance = net if pending is None else pending
    wallet.available_balance = available
    wallet.save(update_fields=["pending_balance", "available_balance"])
    return earning


@pytest.mark.django_db
def test_first_tranche_releases_half_on_day_seven():
    earning = _earning(
        first_release_at=timezone.now() - timedelta(minutes=1)
    )

    release_pending_earnings_task()

    earning.refresh_from_db()
    assert earning.released_amount == Decimal("500.00")
    assert earning.status == VendorEarning.Status.PARTIALLY_RELEASED
    wallet = VendorWallet.objects.get(store=earning.store)
    assert wallet.available_balance == Decimal("500.00")
    assert wallet.pending_balance == Decimal("500.00")


@pytest.mark.django_db
def test_first_tranche_is_not_released_twice():
    earning = _earning(
        first_release_at=timezone.now() - timedelta(minutes=1)
    )
    release_pending_earnings_task()
    release_pending_earnings_task()

    earning.refresh_from_db()
    assert earning.released_amount == Decimal("500.00")


@pytest.mark.django_db
def test_second_tranche_releases_on_completion():
    earning = _earning(
        pending=Decimal("500.00"),
        available=Decimal("500.00"),
        status=VendorEarning.Status.PARTIALLY_RELEASED,
        released_amount=Decimal("500.00"),
        first_release_at=timezone.now() - timedelta(days=7),
        final_release_at=timezone.now() - timedelta(minutes=1),
    )

    release_pending_earnings_task()

    earning.refresh_from_db()
    assert earning.released_amount == Decimal("1000.00")
    assert earning.status == VendorEarning.Status.AVAILABLE
    wallet = VendorWallet.objects.get(store=earning.store)
    assert wallet.pending_balance == Decimal("0.00")
    assert wallet.available_balance == Decimal("1000.00")


@pytest.mark.django_db
def test_disputed_earning_is_frozen():
    earning = _earning(
        first_release_at=timezone.now() - timedelta(days=1),
        is_disputed=True,
    )

    release_pending_earnings_task()

    earning.refresh_from_db()
    assert earning.released_amount == Decimal("0.00")
    assert earning.status == VendorEarning.Status.PENDING


@pytest.mark.django_db
def test_full_policy_releases_the_whole_net_amount():
    earning = _earning(
        release_policy=VendorEarning.ReleasePolicy.FULL,
        first_release_at=timezone.now() - timedelta(minutes=1),
    )

    release_pending_earnings_task()

    earning.refresh_from_db()
    assert earning.released_amount == Decimal("1000.00")
    assert earning.status == VendorEarning.Status.AVAILABLE


@pytest.mark.django_db
def test_earning_is_not_released_before_day_seven():
    earning = _earning(
        first_release_at=timezone.now() + timedelta(days=1)
    )

    release_pending_earnings_task()

    earning.refresh_from_db()
    assert earning.released_amount == Decimal("0.00")
