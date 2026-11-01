from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.accounts.models import DeliveryDetail
from apps.commerce.models import CartItem, Order

from .factories import (
    CartFactory,
    CartItemFactory,
    ListingFactory,
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
def test_three_items_from_three_stores_create_three_orders(auth_client):
    listings = [
        ListingFactory(store=StoreFactory(), price=Decimal("1000.00"))
        for _ in range(3)
    ]
    buyer, cart = _cart_with([(listing, 1) for listing in listings])
    client = auth_client(buyer)

    response = _checkout(client, cart)

    assert response.status_code == 201
    orders = Order.objects.filter(buyer=buyer)
    assert orders.count() == 3
    for order in orders:
        assert order.items.count() == 1
        assert order.store_id == order.item.listing.store_id
        assert order.seller_id == order.store.user_id


@pytest.mark.django_db
def test_three_items_from_one_store_create_three_orders(auth_client):
    store = StoreFactory()
    listings = [
        ListingFactory(store=store, price=Decimal("1000.00"))
        for _ in range(3)
    ]
    buyer, cart = _cart_with([(listing, 1) for listing in listings])
    client = auth_client(buyer)

    response = _checkout(client, cart)

    assert response.status_code == 201
    orders = Order.objects.filter(buyer=buyer)
    assert orders.count() == 3
    assert all(order.items.count() == 1 for order in orders)


@pytest.mark.django_db
def test_buyer_total_is_subtotal_plus_delivery_with_no_fee(auth_client):
    listing = ListingFactory(price=Decimal("1000.00"), currency="NGN")
    buyer, cart = _cart_with([(listing, 3)])
    client = auth_client(buyer)

    response = _checkout(client, cart)

    order = Order.objects.get(buyer=buyer)
    assert order.subtotal == Decimal("3000.00")
    assert order.delivery_fee == Decimal("0.00")
    assert order.escrow_fee == Decimal("0.00")
    assert order.total_amount == Decimal("3000.00")
    assert Decimal(response.data["orders"][0]["total_amount"]) == Decimal(
        "3000.00"
    )


@pytest.mark.django_db
def test_checkout_rejects_a_missing_exchange_rate(auth_client):
    listing = ListingFactory(price=Decimal("10.00"), currency="USD")
    buyer, cart = _cart_with([(listing, 1)])
    client = auth_client(buyer)

    from apps.core.currency import CurrencyRateUnavailable

    with patch(
        "apps.commerce.views.convert_to_ngn",
        side_effect=CurrencyRateUnavailable("No rate for USD."),
    ):
        response = _checkout(client, cart)

    assert response.status_code == 400
    assert "rate" in str(response.data).lower()
    assert Order.objects.filter(buyer=buyer).count() == 0


@pytest.mark.django_db
def test_checkout_converts_currency_once_and_snapshots_it(auth_client):
    listing = ListingFactory(
        price=Decimal("10.00"), currency="USD", store=StoreFactory()
    )
    buyer, cart = _cart_with([(listing, 1)])
    client = auth_client(buyer)

    with patch(
        "apps.commerce.views.convert_to_ngn",
        return_value=Decimal("15000.00"),
    ):
        response = _checkout(client, cart)

    assert response.status_code == 201
    order = Order.objects.get(buyer=buyer)
    item = order.item
    assert order.subtotal == Decimal("15000.00")
    assert item.original_currency == "USD"
    assert item.original_unit_price == Decimal("10.00")
    assert item.unit_price == Decimal("15000.00")
    assert item.exchange_rate == Decimal("1500.00000000")


@pytest.mark.django_db
def test_paystack_failure_keeps_the_cart(auth_client):
    listing = ListingFactory(price=Decimal("1000.00"))
    buyer, cart = _cart_with([(listing, 1)])
    client = auth_client(buyer)

    with patch("apps.commerce.views.initialize_transaction", return_value=None):
        response = client.post(
            "/commerce/checkout/",
            {
                "cart_item_ids": list(
                    cart.items.values_list("id", flat=True)
                ),
                "terms_accepted": True,
            },
            format="json",
        )

    assert response.status_code == 502
    assert cart.items.count() == 1
    order = Order.objects.get(buyer=buyer)
    assert order.status == Order.Status.PENDING_PAYMENT
    assert order.checkout_session.payment.status == "failed"


@pytest.mark.django_db
def test_cart_item_delivery_address_is_persisted_and_copied_to_the_order(
    auth_client,
):
    """Each cart item carries its own address; checkout copies it to the line."""
    buyer = UserFactory()
    listing = ListingFactory(price=Decimal("2500.00"))
    address = DeliveryDetail.objects.create(
        user=buyer,
        contact_person="Ada Obi",
        country="Nigeria",
        address="12 Marina Road",
        state="Lagos",
        city="Lagos",
        phone="08030000000",
        is_default=True,
    )
    client = auth_client(buyer)

    added = client.post(
        "/commerce/cart/items/",
        {
            "listing": listing.id,
            "purchase_type": "buy",
            "quantity": 1,
            "delivery_detail": address.id,
        },
        format="json",
    )

    assert added.status_code == 201
    item = CartItem.objects.get(cart__buyer=buyer)
    assert item.delivery_detail_id == address.id

    with patch("apps.commerce.views.initialize_transaction") as gateway:
        gateway.return_value = {
            "authorization_url": "https://pay.test/checkout",
            "access_code": "ac_test",
        }
        response = client.post(
            "/commerce/checkout/",
            {"cart_item_ids": [item.id], "terms_accepted": True},
            format="json",
        )

    assert response.status_code == 201
    order = Order.objects.get(buyer=buyer)
    assert order.item.delivery_detail_id == address.id


@pytest.mark.django_db
def test_cart_item_rejects_another_users_delivery_address(auth_client):
    buyer = UserFactory()
    other = UserFactory()
    listing = ListingFactory(price=Decimal("2500.00"))
    foreign_address = DeliveryDetail.objects.create(
        user=other,
        contact_person="Not Yours",
        country="Nigeria",
        address="1 Elsewhere Street",
        state="Lagos",
        city="Lagos",
        phone="08030000001",
    )
    client = auth_client(buyer)

    response = client.post(
        "/commerce/cart/items/",
        {
            "listing": listing.id,
            "purchase_type": "buy",
            "quantity": 1,
            "delivery_detail": foreign_address.id,
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.data["delivery_detail"] == ["Delivery address not found."]
    assert CartItem.objects.filter(cart__buyer=buyer).count() == 0
