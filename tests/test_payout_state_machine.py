from decimal import Decimal

import pytest

from apps.financials.models import (
    Payout,
    PayoutAllocation,
    VendorEarning,
    VendorWallet,
)
from apps.financials.services import allocate_payout, fail_payout, settle_payout

from .factories import PayoutFactory, VendorEarningFactory


def _released_earning(store, amount=Decimal("950.00")):
    earning = VendorEarningFactory(
        store=store,
        vendor=store.user,
        gross_amount=Decimal("1000.00"),
        status=VendorEarning.Status.AVAILABLE,
    )
    earning.released_amount = amount
    earning.save(update_fields=["released_amount"])
    return earning


@pytest.mark.django_db
def test_allocate_reserves_earnings_as_processing():
    store = VendorEarningFactory().store
    earning = _released_earning(store)
    payout = PayoutFactory(
        store=store, vendor=store.user, amount=Decimal("500.00")
    )

    allocate_payout(payout)

    earning.refresh_from_db()
    assert earning.status == VendorEarning.Status.PROCESSING
    assert PayoutAllocation.objects.filter(payout=payout).count() == 1


@pytest.mark.django_db
def test_settle_resolves_a_processing_earning_to_paid_out():
    store = VendorEarningFactory().store
    earning = _released_earning(store)
    payout = PayoutFactory(
        store=store, vendor=store.user, amount=Decimal("950.00")
    )

    allocate_payout(payout)
    settle_payout(payout)

    earning.refresh_from_db()
    payout.refresh_from_db()
    assert payout.status == Payout.Status.PAID
    assert earning.status == VendorEarning.Status.PAID_OUT
    assert earning.paid_out_amount == Decimal("950.00")


@pytest.mark.django_db
def test_partial_settle_leaves_partially_released():
    store = VendorEarningFactory().store
    earning = _released_earning(store)
    payout = PayoutFactory(
        store=store, vendor=store.user, amount=Decimal("400.00")
    )

    allocate_payout(payout)
    settle_payout(payout)

    earning.refresh_from_db()
    assert earning.status == VendorEarning.Status.PARTIALLY_RELEASED
    assert earning.paid_out_amount == Decimal("400.00")


@pytest.mark.django_db
def test_failed_payout_unwinds_processing_to_available():
    store = VendorEarningFactory().store
    earning = _released_earning(store)
    wallet, _ = VendorWallet.objects.get_or_create(
        store=store, defaults={"user": store.user, "currency": "NGN"}
    )
    wallet.available_balance = Decimal("0.00")
    wallet.save(update_fields=["available_balance"])
    payout = PayoutFactory(
        store=store, vendor=store.user, amount=Decimal("200.00")
    )

    allocate_payout(payout)
    fail_payout(payout, "bank rejected")

    earning.refresh_from_db()
    wallet.refresh_from_db()
    assert earning.status == VendorEarning.Status.AVAILABLE
    assert wallet.available_balance == Decimal("200.00")
    assert not payout.allocations.exists()


@pytest.mark.django_db
def test_settled_earning_is_not_released_again():
    store = VendorEarningFactory().store
    earning = _released_earning(store)
    payout = PayoutFactory(
        store=store, vendor=store.user, amount=Decimal("950.00")
    )
    allocate_payout(payout)
    settle_payout(payout)

    from apps.financials.tasks import release_pending_earnings_task

    release_pending_earnings_task()

    earning.refresh_from_db()
    assert earning.status == VendorEarning.Status.PAID_OUT
