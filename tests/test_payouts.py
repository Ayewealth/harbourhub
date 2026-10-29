from datetime import timedelta
from decimal import Decimal

import pytest
from django.db.models import F
from django.utils import timezone

from apps.financials.models import (
    Payout,
    PayoutAllocation,
    VendorEarning,
    VendorWallet,
)
from apps.financials.services import (
    allocate_payout,
    fail_payout,
    release_earning,
    settle_payout,
)
from tests.factories import (
    OrderFactory,
    OrderItemFactory,
    PayoutFactory,
    StoreFactory,
    VendorEarningFactory,
)


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


def _funded_earning(store, net=Decimal("1000.00")):
    order = OrderFactory(store=store, seller=store.user)
    OrderItemFactory(order=order)
    earning = VendorEarningFactory(
        order=order,
        store=store,
        vendor=store.user,
        gross_amount=net,
        commission_amount=Decimal("0.00"),
        net_amount=net,
        first_release_at=timezone.now() - timedelta(days=1),
    )
    wallet = VendorWallet.objects.get(store=store)
    wallet.pending_balance = net
    wallet.save(update_fields=["pending_balance"])
    return earning, wallet


@pytest.mark.django_db
def test_each_store_has_its_own_wallet():
    first = StoreFactory()
    second = StoreFactory()

    assert VendorWallet.objects.get(store=first).pk != (
        VendorWallet.objects.get(store=second).pk
    )
    assert VendorWallet.objects.filter(store__isnull=True).count() == 0


@pytest.mark.django_db
def test_vendor_can_withdraw_the_first_tranche_while_the_second_is_held():
    store = StoreFactory()
    earning, wallet = _funded_earning(store)
    release_earning(earning, Decimal("500.00"))

    payout = PayoutFactory(
        store=store, vendor=store.user, amount=Decimal("500.00")
    )
    allocate_payout(payout)
    settle_payout(payout)

    earning.refresh_from_db()
    wallet.refresh_from_db()
    assert earning.released_amount == Decimal("500.00")
    assert earning.paid_out_amount == Decimal("500.00")
    assert earning.status == VendorEarning.Status.PARTIALLY_RELEASED
    assert payout.allocations.count() == 1
    assert wallet.pending_balance == Decimal("500.00")
    assert wallet.available_balance == Decimal("500.00")
    assert wallet.total_withdrawn == Decimal("500.00")


@pytest.mark.django_db
def test_a_payout_cannot_exceed_the_released_balance():
    store = StoreFactory()
    earning, _wallet_obj = _funded_earning(store)
    release_earning(earning, Decimal("400.00"))
    payout = PayoutFactory(
        store=store, vendor=store.user, amount=Decimal("500.00")
    )

    with pytest.raises(ValueError):
        allocate_payout(payout)


@pytest.mark.django_db
def test_failed_payout_restores_the_reserved_amount():
    store = StoreFactory()
    earning, wallet = _funded_earning(store)
    release_earning(earning, Decimal("1000.00"))
    payout = PayoutFactory(
        store=store, vendor=store.user, amount=Decimal("500.00")
    )
    allocate_payout(payout)

    # The endpoint reserves the amount immediately after allocating.
    VendorWallet.objects.filter(pk=wallet.pk).update(
        available_balance=F("available_balance") - Decimal("500.00")
    )
    wallet.refresh_from_db()
    assert wallet.available_balance == Decimal("500.00")

    fail_payout(payout, "bank rejected")

    payout.refresh_from_db()
    wallet.refresh_from_db()
    earning.refresh_from_db()
    assert payout.status == Payout.Status.FAILED
    assert payout.allocations.count() == 0
    assert wallet.available_balance == Decimal("1000.00")
    assert earning.paid_out_amount == Decimal("0.00")
