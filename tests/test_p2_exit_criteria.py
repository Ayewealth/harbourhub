"""The P2 exit criteria, asserted in one executable place.

Each item is covered in more detail by a task-specific test file; this module
proves the whole money model works end to end.
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.commerce.models import Order, RentalExtension
from apps.commerce.services.orders import transition
from apps.commerce.services.payments import finalize_payment
from apps.commerce.services.refunds import finalize_refund
from apps.commerce.models import Payment, Refund
from apps.financials.models import VendorEarning, VendorWallet
from apps.financials.services import (
    allocate_payout,
    money,
    settle_payout,
)
from apps.financials.tasks import release_pending_earnings_task

from .factories import (
    CartFactory,
    CartItemFactory,
    ListingFactory,
    OrderFactory,
    OrderItemFactory,
    PayoutFactory,
    StoreFactory,
    UserFactory,
)


def _cart_with(items):
    buyer = UserFactory()
    cart = CartFactory(buyer=buyer)
    for listing, quantity in items:
        CartItemFactory(
            cart=cart,
            listing=listing,
            store=listing.store,
            quantity=quantity,
            unit_price=listing.price,
        )
    return buyer, cart


def _checkout(client, cart):
    with patch("apps.commerce.views.initialize_transaction") as gateway:
        gateway.return_value = {
            "authorization_url": "https://pay.test/checkout",
            "access_code": "ac_test",
        }
        return client.post(
            "/commerce/checkout/",
            {
                "cart_item_ids": list(
                    cart.items.values_list("id", flat=True)
                ),
                "terms_accepted": True,
            },
            format="json",
        )


@pytest.mark.django_db
def test_one_cart_item_is_one_order_across_stores(auth_client):
    listings = [
        ListingFactory(store=StoreFactory(), price=Decimal("1000.00"))
        for _ in range(3)
    ]
    buyer, cart = _cart_with([(listing, 1) for listing in listings])

    response = _checkout(auth_client(buyer), cart)

    assert response.status_code == 201
    orders = Order.objects.filter(buyer=buyer)
    assert orders.count() == 3
    assert all(order.items.count() == 1 for order in orders)
    assert {o.store_id for o in orders} == {listing.store_id for listing in listings}


@pytest.mark.django_db
def test_one_cart_item_is_one_order_within_a_store(auth_client):
    store = StoreFactory()
    listings = [
        ListingFactory(store=store, price=Decimal("1000.00"))
        for _ in range(3)
    ]
    buyer, cart = _cart_with([(listing, 1) for listing in listings])

    response = _checkout(auth_client(buyer), cart)

    assert response.status_code == 201
    orders = Order.objects.filter(buyer=buyer)
    assert orders.count() == 3
    assert {o.store_id for o in orders} == {store.id}


@pytest.mark.django_db
def test_buyer_pays_subtotal_plus_delivery_and_no_fee(auth_client):
    listing = ListingFactory(price=Decimal("1000.00"))
    buyer, cart = _cart_with([(listing, 3)])

    _checkout(auth_client(buyer), cart)

    order = Order.objects.get(buyer=buyer)
    assert order.subtotal == Decimal("3000.00")
    assert order.escrow_fee == Decimal("0.00")
    assert order.total_amount == order.subtotal + order.delivery_fee


@pytest.mark.django_db
def test_platform_revenue_is_the_sum_of_order_commissions(auth_client):
    listings = [
        ListingFactory(store=StoreFactory(), price=Decimal("1000.00"))
        for _ in range(3)
    ]
    buyer, cart = _cart_with([(listing, 1) for listing in listings])
    _checkout(auth_client(buyer), cart)

    session = Order.objects.filter(buyer=buyer).first().checkout_session
    payment = session.payment
    finalize_payment(payment, {"amount": int(payment.amount * 100)})

    orders = Order.objects.filter(buyer=buyer)
    expected = sum(o.commission_amount for o in orders)
    assert expected > Decimal("0.00")

    admin = UserFactory(role="admin", is_staff=True, is_superuser=True)
    response = auth_client(admin).get("/admin-panel/payments/stats/")
    assert Decimal(str(response.data["platform_revenue"]["value"])) == expected


@pytest.mark.django_db
def test_earnings_release_in_two_tranches():
    order = OrderFactory(status=Order.Status.PAID)
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
        first_release_at=timezone.now() - timedelta(minutes=1),
    )
    wallet = VendorWallet.objects.get(store=order.store)
    wallet.pending_balance = Decimal("1000.00")
    wallet.save(update_fields=["pending_balance"])

    release_pending_earnings_task()
    earning.refresh_from_db()
    assert earning.released_amount == Decimal("500.00")
    assert earning.status == VendorEarning.Status.PARTIALLY_RELEASED

    order.status = Order.Status.DELIVERED
    order.save(update_fields=["status"])
    transition(order, "order_fulfilled", actor=order.seller)

    earning.refresh_from_db()
    wallet.refresh_from_db()
    assert earning.released_amount == Decimal("1000.00")
    assert earning.status == VendorEarning.Status.AVAILABLE
    assert wallet.pending_balance == Decimal("0.00")
    assert wallet.available_balance == Decimal("1000.00")


@pytest.mark.django_db
def test_a_payout_settles_the_first_tranche_only():
    order = OrderFactory(status=Order.Status.PAID)
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
        first_release_at=timezone.now() - timedelta(days=7),
    )
    wallet = VendorWallet.objects.get(store=order.store)
    wallet.pending_balance = Decimal("500.00")
    wallet.available_balance = Decimal("500.00")
    wallet.save(update_fields=["pending_balance", "available_balance"])

    payout = PayoutFactory(
        store=order.store, vendor=order.seller, amount=Decimal("500.00")
    )
    allocate_payout(payout)
    settle_payout(payout)

    earning.refresh_from_db()
    wallet.refresh_from_db()
    assert earning.paid_out_amount == Decimal("500.00")
    assert earning.status == VendorEarning.Status.PARTIALLY_RELEASED
    assert wallet.pending_balance == Decimal("500.00")
    assert wallet.total_withdrawn == Decimal("500.00")


@pytest.mark.django_db
def test_rental_extension_dates_change_only_after_payment():
    today = timezone.now().date()
    order = OrderFactory(status=Order.Status.ACTIVE_HIRE)
    item = OrderItemFactory(
        order=order,
        purchase_type=Order.OrderType.HIRE,
        unit_price=Decimal("1000.00"),
        duration_days=7,
        rental_start_date=today - timedelta(days=2),
        rental_end_date=today + timedelta(days=5),
    )
    previous_end = item.rental_end_date
    extension = RentalExtension.objects.create(
        order_item=item,
        additional_days=3,
        previous_end_date=previous_end,
        new_end_date=previous_end + timedelta(days=3),
        amount=Decimal("3000.00"),
    )
    payment = Payment.objects.create(
        buyer=order.buyer,
        amount=Decimal("3000.00"),
        currency="NGN",
        reference="PAY-P2-EXIT-EXT",
        status=Payment.Status.PENDING,
    )
    extension.payment = payment
    extension.save(update_fields=["payment"])

    item.refresh_from_db()
    assert item.rental_end_date == previous_end

    finalize_payment(payment, {"amount": 300000})

    item.refresh_from_db()
    extension.refresh_from_db()
    assert item.rental_end_date == previous_end + timedelta(days=3)
    assert extension.status == RentalExtension.Status.PAID


@pytest.mark.django_db
def test_full_refund_zeroes_the_store_wallet():
    order = OrderFactory(
        status=Order.Status.PAID,
        subtotal=Decimal("1000.00"),
        total_amount=Decimal("1000.00"),
    )
    OrderItemFactory(order=order)
    payment = Payment.objects.create(
        checkout_session=order.checkout_session,
        buyer=order.buyer,
        amount=Decimal("1000.00"),
        currency="NGN",
        reference="PAY-P2-EXIT-REFUND",
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
        released_amount=Decimal("500.00"),
        status=VendorEarning.Status.PARTIALLY_RELEASED,
    )
    wallet = VendorWallet.objects.get(store=order.store)
    wallet.pending_balance = Decimal("500.00")
    wallet.available_balance = Decimal("500.00")
    wallet.save(update_fields=["pending_balance", "available_balance"])
    refund = Refund.objects.create(
        payment=payment,
        amount=Decimal("1000.00"),
        currency="NGN",
        reference="RF-P2-EXIT",
        reason="Exit criteria",
    )

    finalize_refund(refund)

    order.refresh_from_db()
    earning.refresh_from_db()
    wallet.refresh_from_db()
    assert order.status == Order.Status.CANCELLED
    assert earning.status == VendorEarning.Status.REVERSED
    assert money(wallet.pending_balance) == Decimal("0.00")
    assert money(wallet.available_balance) == Decimal("0.00")
