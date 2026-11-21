from datetime import timedelta
from decimal import Decimal

import pytest
from django.db.models import F
from django.utils import timezone

from apps.financials.models import (
    BankAccount,
    Payout,
    PayoutAllocation,
    VendorEarning,
    VendorWallet,
    WalletTransaction,
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
    UserFactory,
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


def _bank(store, **kwargs):
    values = {
        "user": store.user,
        "store": store,
        "account_name": "Test Vendor",
        "account_number": "0123456789",
        "bank_name": "Test Bank",
        "bank_code": "058",
    }
    values.update(kwargs)
    return BankAccount.objects.create(**values)


def _released_wallet(store, amount=Decimal("1000.00")):
    earning, wallet = _funded_earning(store, net=amount)
    release_earning(earning, amount)
    wallet.refresh_from_db()
    return earning, wallet


def _stub_payout_dispatch(monkeypatch):
    from apps.financials import views as financial_views

    monkeypatch.setattr(
        financial_views.process_payout_task,
        "delay",
        lambda *args, **kwargs: None,
    )


@pytest.mark.django_db
def test_payout_without_bank_and_without_default_is_rejected(
    auth_client, monkeypatch
):
    _stub_payout_dispatch(monkeypatch)
    store = StoreFactory()
    _earning, wallet = _released_wallet(store)

    response = auth_client(store.user).post(
        "/financials/payouts/", {"amount": "100.00"}, format="json"
    )

    assert response.status_code == 400
    assert "bank_account" in response.data
    assert not Payout.objects.filter(vendor=store.user).exists()
    wallet.refresh_from_db()
    assert wallet.available_balance == Decimal("1000.00")


@pytest.mark.django_db
def test_payout_uses_the_default_bank_account_when_omitted(
    auth_client, monkeypatch
):
    _stub_payout_dispatch(monkeypatch)
    store = StoreFactory()
    _earning, wallet = _released_wallet(store)
    bank = _bank(store, is_default=True)

    response = auth_client(store.user).post(
        "/financials/payouts/", {"amount": "100.00"}, format="json"
    )

    assert response.status_code == 201
    payout = Payout.objects.get(vendor=store.user)
    assert payout.bank_account_id == bank.id
    wallet.refresh_from_db()
    assert wallet.available_balance == Decimal("900.00")


@pytest.mark.django_db
def test_payout_above_balance_does_not_touch_the_wallet(
    auth_client, monkeypatch
):
    _stub_payout_dispatch(monkeypatch)
    store = StoreFactory()
    _earning, wallet = _released_wallet(store)
    bank = _bank(store)

    response = auth_client(store.user).post(
        "/financials/payouts/",
        {"amount": "1500.00", "bank_account": bank.id},
        format="json",
    )

    assert response.status_code == 400
    assert not Payout.objects.filter(vendor=store.user).exists()
    wallet.refresh_from_db()
    assert wallet.available_balance == Decimal("1000.00")


@pytest.mark.django_db
def test_immediate_transfer_failure_refunds_exactly_once(
    auth_client, monkeypatch
):
    from apps.financials.tasks import process_payout_task
    from apps.notifications.models import Notification

    _stub_payout_dispatch(monkeypatch)
    admin = UserFactory(
        role="admin", is_staff=True, is_active=True
    )
    store = StoreFactory()
    _earning, wallet = _released_wallet(store)
    bank = _bank(store)

    response = auth_client(store.user).post(
        "/financials/payouts/",
        {"amount": "200.00", "bank_account": bank.id},
        format="json",
    )
    assert response.status_code == 201
    payout = Payout.objects.get(vendor=store.user)
    assert Notification.objects.filter(
        recipient=admin, notification_type="admin_payout_requested"
    ).exists()

    class _Declined:
        def json(self):
            return {"status": False, "message": "declined"}

    monkeypatch.setattr("requests.post", lambda *a, **k: _Declined())

    process_payout_task(payout.id)

    payout.refresh_from_db()
    wallet.refresh_from_db()
    assert payout.status == Payout.Status.FAILED
    assert payout.failure_reason
    assert not payout.allocations.exists()
    assert wallet.available_balance == Decimal("1000.00")
    refunds = WalletTransaction.objects.filter(
        wallet=wallet,
        transaction_type=WalletTransaction.Type.REFUND,
        reference_id=str(payout.id),
    )
    assert refunds.count() == 1
    assert refunds.get().amount == Decimal("200.00")
    assert Notification.objects.filter(
        recipient=admin, notification_type="admin_payout_failed"
    ).exists()

    # A retry of the task must not refund a second time.
    process_payout_task(payout.id)
    wallet.refresh_from_db()
    assert wallet.available_balance == Decimal("1000.00")
    assert refunds.count() == 1


@pytest.mark.django_db
def test_failed_payout_is_idempotent():
    store = VendorEarningFactory().store
    _released_earning(store)
    wallet = _wallet(store)
    payout = PayoutFactory(
        store=store, vendor=store.user, amount=Decimal("200.00")
    )
    allocate_payout(payout)

    fail_payout(payout, "bank rejected")
    fail_payout(payout, "duplicate webhook")

    wallet.refresh_from_db()
    assert wallet.available_balance == Decimal("200.00")
    assert WalletTransaction.objects.filter(
        wallet=wallet,
        transaction_type=WalletTransaction.Type.REFUND,
        reference_id=str(payout.id),
    ).count() == 1


@pytest.mark.django_db
def test_reversal_after_settlement_unwinds_paid_amounts():
    store = StoreFactory()
    earning, wallet = _released_wallet(store)
    payout = PayoutFactory(
        store=store, vendor=store.user, amount=Decimal("200.00")
    )
    allocate_payout(payout)
    VendorWallet.objects.filter(pk=wallet.pk).update(
        available_balance=F("available_balance") - Decimal("200.00")
    )
    settle_payout(payout)

    wallet.refresh_from_db()
    earning.refresh_from_db()
    assert wallet.available_balance == Decimal("800.00")
    assert wallet.total_withdrawn == Decimal("200.00")
    assert earning.paid_out_amount == Decimal("200.00")

    fail_payout(payout, "transfer reversed")

    payout.refresh_from_db()
    wallet.refresh_from_db()
    earning.refresh_from_db()
    assert payout.status == Payout.Status.FAILED
    assert not payout.allocations.exists()
    assert wallet.available_balance == Decimal("1000.00")
    assert wallet.total_withdrawn == Decimal("0.00")
    assert earning.paid_out_amount == Decimal("0.00")
    assert earning.status == VendorEarning.Status.AVAILABLE


@pytest.mark.django_db
def test_admin_payout_list_exposes_vendor_bank_and_filters(auth_client):
    store = StoreFactory()
    bank = _bank(store, account_name="OceanRig Energy")
    failed = PayoutFactory(
        store=store,
        vendor=store.user,
        bank_account=bank,
        amount=Decimal("1027.61"),
        status=Payout.Status.FAILED,
        failure_reason="transfer.failed",
        reference="PO-OCEANRIG",
    )
    PayoutFactory(
        store=StoreFactory(),
        amount=Decimal("300.00"),
        status=Payout.Status.PAID,
        reference="PO-OTHER",
    )
    admin = UserFactory(
        role="admin", is_staff=True, is_superuser=True, is_active=True
    )
    client = auth_client(admin)

    response = client.get("/admin-panel/payments/payouts/")

    assert response.status_code == 200
    rows = response.data["results"] if "results" in response.data else response.data
    by_reference = {row["reference"]: row for row in rows}
    row = by_reference["PO-OCEANRIG"]
    assert row["vendor_email"] == store.user.email
    assert row["store_name"] == store.name
    assert row["bank_account_name"] == "OceanRig Energy"
    assert row["bank_account_number"] == bank.account_number
    assert row["bank_name"] == "Test Bank"
    assert row["status"] == "failed"
    assert row["failure_reason"] == "transfer.failed"
    assert Decimal(str(row["amount"])) == Decimal("1027.61")

    filtered = client.get(
        "/admin-panel/payments/payouts/", {"status": "failed"}
    )
    assert filtered.status_code == 200
    filtered_rows = (
        filtered.data["results"]
        if "results" in filtered.data else filtered.data
    )
    assert [r["reference"] for r in filtered_rows] == ["PO-OCEANRIG"]

    searched = client.get(
        "/admin-panel/payments/payouts/", {"search": "PO-OTHER"}
    )
    searched_rows = (
        searched.data["results"]
        if "results" in searched.data else searched.data
    )
    assert [r["reference"] for r in searched_rows] == ["PO-OTHER"]

    by_date = client.get(
        "/admin-panel/payments/payouts/",
        {"date_from": failed.created_at.date().isoformat()},
    )
    assert by_date.status_code == 200
    by_date_rows = (
        by_date.data["results"]
        if "results" in by_date.data else by_date.data
    )
    assert failed.reference in {r["reference"] for r in by_date_rows}


@pytest.mark.django_db
def test_buyer_cannot_read_the_admin_payout_list(auth_client):
    store = StoreFactory()
    response = auth_client(store.user).get(
        "/admin-panel/payments/payouts/"
    )
    assert response.status_code in (401, 403)
