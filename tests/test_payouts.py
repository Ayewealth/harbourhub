from decimal import Decimal

import pytest

from apps.financials.models import (
    Payout,
    PayoutAllocation,
    VendorEarning,
    VendorWallet,
)
from apps.financials.services import allocate_payout, fail_payout, settle_payout
from tests.factories import PayoutFactory, VendorEarningFactory


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


def _wallet(store, available=Decimal("0.00")):
    wallet = VendorWallet.objects.get(store=store)
    wallet.available_balance = available
    wallet.save(update_fields=["available_balance"])
    return wallet


@pytest.mark.django_db
def test_payout_settles_only_its_allocations():
    first_store = VendorEarningFactory().store
    first = _released_earning(first_store)
    second = _released_earning(first_store)

    payout = PayoutFactory(
        store=first_store, vendor=first_store.user, amount=Decimal("500.00")
    )
    allocate_payout(payout)
    settle_payout(payout)

    payout.refresh_from_db()
    first.refresh_from_db()
    second.refresh_from_db()
    assert payout.status == Payout.Status.PAID
    assert PayoutAllocation.objects.filter(payout=payout).count() == 1
    assert first.paid_out_amount == Decimal("500.00")
    assert second.paid_out_amount == Decimal("0.00")


@pytest.mark.django_db
def test_failed_payout_recredits_and_clears_allocations():
    store = VendorEarningFactory().store
    _released_earning(store)
    wallet = _wallet(store)
    payout = PayoutFactory(
        store=store, vendor=store.user, amount=Decimal("200.00")
    )

    allocate_payout(payout)
    fail_payout(payout, "bank rejected")

    payout.refresh_from_db()
    wallet.refresh_from_db()
    assert payout.status == Payout.Status.FAILED
    assert not payout.allocations.exists()
    assert wallet.available_balance == Decimal("200.00")


@pytest.mark.django_db
def test_over_withdrawal_is_rejected(api_client, auth_client):
    from tests.factories import StoreFactory

    store = StoreFactory()
    _wallet(store, available=Decimal("10.00"))
    client = auth_client(store.user)

    response = client.post(
        "/financials/payouts/",
        {
            "amount": "100.00",
            "bank_account": 1,
        },
        format="json",
    )

    assert response.status_code == 400
    assert not Payout.objects.exists()
