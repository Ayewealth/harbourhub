"""Money conversion, tracking updates, receipt confirmation and Paystack limits."""
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.accounts.models import UserPreference
from apps.commerce.models import Order, OrderActivity
from apps.commerce.paystack import (
    PaystackAmountLimitExceeded,
    initialize_transaction,
)
from tests.factories import (
    CartFactory,
    CartItemFactory,
    ListingFactory,
    OrderFactory,
    OrderItemFactory,
    QuoteRequestFactory,
    StoreFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


# ─── Currency conversion ─────────────────────────────────────────────────────

def test_quote_adjustment_uses_explicit_currency(auth_client):
    listing = ListingFactory(currency="USD", price=Decimal("100.00"))
    quote = QuoteRequestFactory(
        listing=listing,
        store=listing.store,
        standard_price=Decimal("100.00"),
    )
    UserPreference.objects.create(
        user=listing.user, preferred_currency="NGN"
    )
    client = auth_client(listing.user)

    response = client.patch(
        f"/commerce/quotes/{quote.id}/vendor-update/",
        {
            "adjustments": [
                {
                    "name": "Shipping",
                    "type": "addition",
                    "amount": "100",
                    "currency": "NGN",
                }
            ]
        },
        format="json",
    )

    assert response.status_code == 200, response.data
    quote.refresh_from_db()
    adjustment = quote.adjustments[0]
    # NGN 100 at 1500/USD is USD 0.066667, not USD 100.
    assert adjustment["amount"] == "0.066667"
    assert adjustment["entered_amount"] == "100"
    assert adjustment["entered_currency"] == "NGN"
    # The vendor sees the figure they typed, labelled with its currency.
    shown = response.data["adjustments"][0]
    assert shown["amount"] == "100.00"
    assert shown["currency"] == "NGN"


def test_quote_adjustment_defaults_to_preferred_currency(auth_client):
    listing = ListingFactory(currency="USD", price=Decimal("100.00"))
    quote = QuoteRequestFactory(
        listing=listing,
        store=listing.store,
        standard_price=Decimal("100.00"),
    )
    UserPreference.objects.create(
        user=listing.user, preferred_currency="NGN"
    )
    client = auth_client(listing.user)

    response = client.patch(
        f"/commerce/quotes/{quote.id}/vendor-update/",
        {
            "adjustments": [
                {"name": "Shipping", "type": "addition", "amount": "1500"}
            ]
        },
        format="json",
    )

    assert response.status_code == 200, response.data
    quote.refresh_from_db()
    assert quote.adjustments[0]["amount"] == "1.000000"


def test_quote_adjustment_round_trip_is_not_converted_twice(auth_client):
    listing = ListingFactory(currency="USD", price=Decimal("100.00"))
    stored = {"name": "Shipping", "type": "addition", "amount": "0.066667"}
    quote = QuoteRequestFactory(
        listing=listing,
        store=listing.store,
        standard_price=Decimal("100.00"),
        adjustments=[stored],
    )
    UserPreference.objects.create(
        user=listing.user, preferred_currency="NGN"
    )
    client = auth_client(listing.user)

    response = client.patch(
        f"/commerce/quotes/{quote.id}/vendor-update/",
        {"adjustments": [stored]},
        format="json",
    )

    assert response.status_code == 200, response.data
    quote.refresh_from_db()
    assert quote.adjustments[0]["amount"] == "0.066667"


def test_quote_adjustment_rejects_unsupported_currency(auth_client):
    listing = ListingFactory(currency="USD")
    quote = QuoteRequestFactory(listing=listing, store=listing.store)
    client = auth_client(listing.user)

    response = client.patch(
        f"/commerce/quotes/{quote.id}/vendor-update/",
        {
            "adjustments": [
                {
                    "name": "Shipping",
                    "type": "addition",
                    "amount": "100",
                    "currency": "XYZ",
                }
            ]
        },
        format="json",
    )

    assert response.status_code == 400


def test_cart_total_sums_lines_in_one_currency(auth_client):
    buyer = UserFactory()
    UserPreference.objects.create(user=buyer, preferred_currency="NGN")
    cart = CartFactory(buyer=buyer)
    usd_listing = ListingFactory(currency="USD", price=Decimal("100.00"))
    ngn_listing = ListingFactory(currency="NGN", price=Decimal("150000.00"))
    CartItemFactory(
        cart=cart,
        listing=usd_listing,
        store=usd_listing.store,
        unit_price=Decimal("100.00"),
    )
    CartItemFactory(
        cart=cart,
        listing=ngn_listing,
        store=ngn_listing.store,
        unit_price=Decimal("150000.00"),
    )
    client = auth_client(buyer)

    response = client.get(reverse("cart"))

    assert response.status_code == 200, response.data
    # USD 100 is NGN 150,000 at the fixed test rate.
    assert response.data["currency"] == "NGN"
    assert response.data["source_currency"] == "NGN"
    assert Decimal(response.data["total"]) == Decimal("300000.00")


def test_currency_rates_endpoint_converts(api_client):
    response = api_client.get(
        "/currency/rates/?from=NGN&to=USD&amount=150000"
    )

    assert response.status_code == 200
    assert response.data["base"] == "USD"
    assert response.data["rates"]["NGN"] == 1500.0
    assert response.data["conversion"]["result"] == "100.00"


# ─── Buyer confirms receipt ──────────────────────────────────────────────────

def test_buyer_confirms_receipt_from_item_dispatched(auth_client):
    order = OrderFactory(status=Order.Status.ITEM_DISPATCHED)
    OrderItemFactory(order=order, purchase_type=Order.OrderType.BUY)
    client = auth_client(order.buyer)

    response = client.post(
        reverse("order-confirm-receipt", kwargs={"pk": order.pk}),
        {},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["fulfilled"] is True
    order.refresh_from_db()
    assert order.status == Order.Status.FULFILLED
    assert order.delivered_at is not None
    assert order.completed_at is not None
    assert order.activities.filter(
        event_type=OrderActivity.EventType.DELIVERED
    ).exists()


def test_buyer_confirms_receipt_from_in_transit(auth_client):
    order = OrderFactory(status=Order.Status.IN_TRANSIT)
    OrderItemFactory(order=order, purchase_type=Order.OrderType.BUY)
    client = auth_client(order.buyer)

    response = client.post(
        reverse("order-confirm-receipt", kwargs={"pk": order.pk}),
        {},
        format="json",
    )

    assert response.status_code == 200, response.data
    order.refresh_from_db()
    assert order.status == Order.Status.FULFILLED


def test_buyer_confirms_receipt_for_rental_stops_at_delivered(auth_client):
    order = OrderFactory(status=Order.Status.IN_TRANSIT)
    OrderItemFactory(order=order, purchase_type=Order.OrderType.HIRE)
    client = auth_client(order.buyer)

    response = client.post(
        reverse("order-confirm-receipt", kwargs={"pk": order.pk}),
        {},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["fulfilled"] is False
    order.refresh_from_db()
    assert order.status == Order.Status.DELIVERED
    assert order.completed_at is None


def test_buyer_cannot_confirm_receipt_before_dispatch(auth_client):
    order = OrderFactory(status=Order.Status.PAID)
    OrderItemFactory(order=order, purchase_type=Order.OrderType.BUY)
    client = auth_client(order.buyer)

    response = client.post(
        reverse("order-confirm-receipt", kwargs={"pk": order.pk}),
        {},
        format="json",
    )

    assert response.status_code == 400
    assert "Cannot confirm receipt" in response.data["error"]


def test_seller_cannot_confirm_receipt(auth_client):
    order = OrderFactory(status=Order.Status.DELIVERED)
    OrderItemFactory(order=order)
    client = auth_client(order.seller)

    response = client.post(
        reverse("order-confirm-receipt", kwargs={"pk": order.pk}),
        {},
        format="json",
    )

    assert response.status_code == 403


# ─── Seller tracking updates ─────────────────────────────────────────────────

def test_seller_updates_all_tracking_fields(auth_client):
    order = OrderFactory(status=Order.Status.ITEM_DISPATCHED)
    OrderItemFactory(order=order)
    client = auth_client(order.seller)

    response = client.patch(
        reverse("order-tracking-detail", kwargs={"pk_or_num": order.pk}),
        {
            "tracking_id": "GIG-999",
            "carrier": "GIG Logistics",
            "expected_delivery_date": "2026-12-01",
            "delivery_address": "14 Marina Road, Lagos",
            "delivery_contact_name": "Ada Buyer",
            "delivery_contact_phone": "+2348099999999",
        },
        format="json",
    )

    assert response.status_code == 200, response.data
    order.refresh_from_db()
    assert order.tracking_id == "GIG-999"
    assert order.delivery_carrier == "GIG Logistics"
    assert order.expected_delivery_date.isoformat() == "2026-12-01"
    assert order.delivery_address == "14 Marina Road, Lagos"
    assert order.delivery_contact_name == "Ada Buyer"
    assert order.delivery_contact_phone == "+2348099999999"
    assert order.activities.filter(
        event_type=OrderActivity.EventType.OTHER
    ).exists()
    assert response.data["expected_delivery_date"] == "2026-12-01"


def test_seller_tracking_rejects_bad_date(auth_client):
    order = OrderFactory(status=Order.Status.ITEM_DISPATCHED)
    client = auth_client(order.seller)

    response = client.patch(
        reverse("order-tracking-detail", kwargs={"pk_or_num": order.pk}),
        {"expected_delivery_date": "not-a-date"},
        format="json",
    )

    assert response.status_code == 400
    assert "YYYY-MM-DD" in response.data["error"]


def test_seller_tracking_rejects_overlong_value(auth_client):
    order = OrderFactory(status=Order.Status.ITEM_DISPATCHED)
    client = auth_client(order.seller)

    response = client.patch(
        reverse("order-tracking-detail", kwargs={"pk_or_num": order.pk}),
        {"delivery_contact_phone": "1" * 31},
        format="json",
    )

    assert response.status_code == 400
    assert "30 characters or fewer" in response.data["error"]


def test_buyer_cannot_update_tracking(auth_client):
    order = OrderFactory(status=Order.Status.ITEM_DISPATCHED)
    client = auth_client(order.buyer)

    response = client.patch(
        reverse("order-tracking-detail", kwargs={"pk_or_num": order.pk}),
        {"tracking_id": "HACK"},
        format="json",
    )

    assert response.status_code == 403


# ─── Paystack transaction limit ──────────────────────────────────────────────

def test_paystack_rejects_amount_over_limit(settings):
    settings.PAYSTACK_MAX_TRANSACTION_NGN = 10_000_000

    with pytest.raises(PaystackAmountLimitExceeded) as excinfo:
        initialize_transaction(
            email="buyer@example.com",
            amount_kobo=1_000_000_001,
            reference="PAY-OVER-LIMIT",
        )

    assert excinfo.value.limit_kobo == 1_000_000_000
    assert "per-transaction limit" in str(excinfo.value)


def test_paystack_accepts_amount_at_limit(settings, monkeypatch):
    settings.PAYSTACK_MAX_TRANSACTION_NGN = 10_000_000
    monkeypatch.setattr(
        "apps.commerce.paystack.requests.post",
        lambda *args, **kwargs: type(
            "Response",
            (),
            {"json": lambda self: {"status": True, "data": {"ok": True}}},
        )(),
    )

    result = initialize_transaction(
        email="buyer@example.com",
        amount_kobo=1_000_000_000,
        reference="PAY-AT-LIMIT",
    )

    assert result == {"ok": True}


def test_checkout_rejects_over_limit_before_creating_orders(
    auth_client, settings
):
    settings.PAYSTACK_MAX_TRANSACTION_NGN = 10_000_000
    buyer = UserFactory()
    store = StoreFactory()
    listing = ListingFactory(
        store=store,
        currency="NGN",
        price=Decimal("20000000.00"),
    )
    cart = CartFactory(buyer=buyer)
    CartItemFactory(
        cart=cart,
        listing=listing,
        store=store,
        unit_price=Decimal("20000000.00"),
    )
    client = auth_client(buyer)

    response = client.post(
        reverse("checkout"),
        {
            "cart_item_ids": [cart.items.first().id],
            "terms_accepted": True,
        },
        format="json",
    )

    assert response.status_code == 400, response.data
    assert response.data["code"] == "payment_amount_exceeds_gateway_limit"
    assert response.data["limit"] == "10000000.00"
    assert Order.objects.count() == 0
