from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.accounts.models import DeliveryDetail
from apps.commerce.models import Order
from apps.listings.models import Listing
from apps.store.models import ShippingProfile

from .factories import (
    CartFactory,
    CartItemFactory,
    ListingFactory,
    StoreFactory,
    UserFactory,
)


def _profile(store, *, zone="Lagos", cost="150.00", threshold=None):
    return ShippingProfile.objects.create(
        store=store,
        zone_name=zone,
        carrier_name="Harbour Logistics",
        delivery_time_min=1,
        delivery_time_max=3,
        flat_rate_cost=Decimal(cost),
        free_shipping_threshold=(
            Decimal(threshold) if threshold is not None else None
        ),
        is_active=True,
    )


def _checkout_setup(listing, *, city="Lagos", state="Lagos", quantity=1):
    buyer = UserFactory()
    detail = DeliveryDetail.objects.create(
        user=buyer,
        contact_person="Ada Obi",
        country="Nigeria",
        address="12 Marina Road",
        state=state,
        city=city,
        phone="08030000000",
    )
    cart = CartFactory(buyer=buyer)
    item = CartItemFactory(
        cart=cart,
        listing=listing,
        store=listing.store,
        quantity=quantity,
        unit_price=listing.price,
        delivery_detail=detail,
    )
    return buyer, cart, item


def _post_checkout(client, cart):
    with patch("apps.commerce.views.initialize_transaction") as gateway:
        gateway.return_value = {
            "authorization_url": "https://pay.test/checkout",
            "access_code": "ac_test",
        }
        return client.post(
            "/commerce/checkout/",
            {
                "cart_item_ids": [cart.items.first().pk],
                "terms_accepted": True,
            },
            format="json",
        )


@pytest.mark.django_db
def test_city_match_charges_the_zone_rate_once_per_line(auth_client):
    store = StoreFactory()
    _profile(store, zone="Lagos", cost="150.00")
    listing = ListingFactory(store=store, price=Decimal("1000.00"))
    buyer, cart, _ = _checkout_setup(listing, quantity=2)

    response = _post_checkout(auth_client(buyer), cart)

    assert response.status_code == 201
    order = Order.objects.get(buyer=buyer)
    assert order.subtotal == Decimal("2000.00")
    assert order.delivery_fee == Decimal("150.00")
    assert order.total_amount == Decimal("2150.00")


@pytest.mark.django_db
def test_free_shipping_threshold_zeroes_the_fee(auth_client):
    store = StoreFactory()
    _profile(store, zone="Lagos", cost="150.00", threshold="2000.00")
    listing = ListingFactory(store=store, price=Decimal("2500.00"))
    buyer, cart, _ = _checkout_setup(listing)

    response = _post_checkout(auth_client(buyer), cart)

    assert response.status_code == 201
    order = Order.objects.get(buyer=buyer)
    assert order.delivery_fee == Decimal("0.00")
    assert order.total_amount == Decimal("2500.00")


@pytest.mark.django_db
def test_no_matching_zone_charges_zero(auth_client):
    store = StoreFactory()
    _profile(store, zone="Abuja", cost="500.00")
    listing = ListingFactory(store=store, price=Decimal("1000.00"))
    buyer, cart, _ = _checkout_setup(listing, city="Lagos")

    response = _post_checkout(auth_client(buyer), cart)

    assert response.status_code == 201
    assert Order.objects.get(buyer=buyer).delivery_fee == Decimal("0.00")


@pytest.mark.django_db
def test_service_listings_are_never_charged_delivery(auth_client):
    store = StoreFactory()
    _profile(store, zone="Lagos", cost="150.00")
    listing = ListingFactory(
        store=store, price=Decimal("1000.00"), listing_type=Listing.Type.SERVICE
    )
    buyer, cart, _ = _checkout_setup(listing)

    response = _post_checkout(auth_client(buyer), cart)

    assert response.status_code == 201
    assert Order.objects.get(buyer=buyer).delivery_fee == Decimal("0.00")


@pytest.mark.django_db
def test_checkout_writes_the_delivery_snapshot(auth_client):
    store = StoreFactory()
    _profile(store, zone="Lagos", cost="150.00")
    listing = ListingFactory(store=store, price=Decimal("1000.00"))
    buyer, cart, _ = _checkout_setup(listing)

    response = _post_checkout(auth_client(buyer), cart)

    assert response.status_code == 201
    order = Order.objects.get(buyer=buyer)
    assert order.delivery_address == "12 Marina Road, Lagos, Lagos, Nigeria"
    assert order.delivery_contact_name == "Ada Obi"
    assert order.delivery_contact_phone == "08030000000"
