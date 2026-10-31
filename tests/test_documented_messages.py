"""Pin the messages promised by ``docs/api/messages.md``.

The catalogue is only useful if it is true. Each test below asserts one
high-value string that clients branch on. If a message changes, this test
fails and the catalogue must be updated in the same commit.
"""
from decimal import Decimal

import pytest
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from apps.commerce.models import Order
from apps.financials.models import BankAccount, VendorWallet
from apps.listings.serializers import ListingCreateUpdateSerializer
from apps.notifications.models import Notification

from .factories import (
    CategoryFactory,
    ListingFactory,
    OrderFactory,
    OrderItemFactory,
    StoreFactory,
    UserFactory,
)


@pytest.mark.django_db
def test_registration_rejects_a_privileged_role(api_client):
    response = api_client.post(
        "/auth/register/",
        {
            "username": "role-lock",
            "email": "role-lock@example.com",
            "password": "StrongPass123!",
            "password_confirm": "StrongPass123!",
            "full_name": "Role Lock",
            "role": "seller",
        },
        format="json",
    )

    assert response.status_code == 400
    assert (
        "Registration always creates a buyer account. Use seller onboarding."
        in str(response.data["role"])
    )


@pytest.mark.django_db
def test_listing_creation_requires_a_store():
    seller = UserFactory(role="seller")
    category = CategoryFactory()
    request = APIRequestFactory().post("/listings/")
    request.user = seller
    serializer = ListingCreateUpdateSerializer(
        data={
            "title": "Storeless listing",
            "description": "No store yet",
            "category": category.id,
            "listing_type": "sell",
            "price": "100.00",
            "location": "Lagos",
            "contact_name": "Seller",
            "contact_email": "seller@example.com",
        },
        context={"request": request},
    )
    assert serializer.is_valid(), serializer.errors

    with pytest.raises(serializers.ValidationError) as exc:
        serializer.save()

    assert (
        str(exc.value.detail["store"])
        == "Complete seller onboarding before creating a listing."
    )


@pytest.mark.django_db
def test_checkout_without_a_cart_says_the_cart_is_empty(auth_client):
    buyer = UserFactory()
    response = auth_client(buyer).post(
        "/commerce/checkout/",
        {"cart_item_ids": [1], "terms_accepted": True},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["non_field_errors"][0] == "Cart is empty."


@pytest.mark.django_db
def test_checkout_with_foreign_cart_ids_says_no_valid_items(auth_client):
    buyer = UserFactory()
    auth_client(buyer).post(
        "/commerce/cart/items/",
        {
            "listing": ListingFactory().id,
            "purchase_type": "buy",
            "quantity": 1,
        },
        format="json",
    )

    response = auth_client(buyer).post(
        "/commerce/checkout/",
        {"cart_item_ids": [999999], "terms_accepted": True},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["non_field_errors"][0] == "No valid cart items found."


@pytest.mark.django_db
def test_webhook_rejects_an_invalid_signature(api_client):
    response = api_client.post(
        "/commerce/payment/webhook/",
        data='{"event": "charge.success", "data": {}}',
        content_type="application/json",
        HTTP_X_PAYSTACK_SIGNATURE="not-a-signature",
    )

    assert response.status_code == 401
    assert response.data["error"] == "Invalid signature"


@pytest.mark.django_db
def test_a_notification_is_invisible_to_another_user(auth_client):
    owner = UserFactory()
    other = UserFactory()
    notification = Notification.objects.create(
        recipient=owner,
        notification_type=Notification.NotificationType.ORDER_PLACED,
        title="Order placed",
        message="Your order was placed.",
    )

    response = auth_client(other).post(
        f"/notifications/{notification.id}/read/", format="json"
    )

    assert response.status_code == 404
    assert response.data["error"] == "Notification not found."
    notification.refresh_from_db()
    assert notification.is_read is False


@pytest.mark.django_db
def test_payout_above_the_wallet_balance_is_rejected(auth_client):
    store = StoreFactory()
    account = BankAccount.objects.create(
        user=store.user,
        store=store,
        account_name="Test Vendor",
        account_number="0123456789",
        bank_name="Test Bank",
        bank_code="058",
    )
    wallet = VendorWallet.objects.get(store=store)
    wallet.available_balance = Decimal("10.00")
    wallet.save(update_fields=["available_balance"])

    response = auth_client(store.user).post(
        "/financials/payouts/",
        {"amount": "100.00", "bank_account": account.id},
        format="json",
    )

    assert response.status_code == 400
    assert (
        response.data["non_field_errors"][0]
        == "Insufficient balance. Available: 10.00"
    )


@pytest.mark.django_db
def test_seller_cannot_review_their_own_listing(auth_client):
    listing = ListingFactory()

    response = auth_client(listing.user).post(
        "/reviews/listings/",
        {"listing": listing.id, "rating": 5, "comment": "Perfect"},
        format="json",
    )

    assert response.status_code == 400
    assert (
        response.data["non_field_errors"][0]
        == "You cannot review your own listing."
    )


@pytest.mark.django_db
def test_duplicate_listing_review_is_rejected(auth_client):
    listing = ListingFactory()
    buyer = UserFactory()
    order = OrderFactory(
        buyer=buyer, store=listing.store, status=Order.Status.PAID
    )
    OrderItemFactory(order=order, listing=listing)
    client = auth_client(buyer)
    payload = {"listing": listing.id, "rating": 5, "comment": "Great"}

    assert client.post(
        "/reviews/listings/", payload, format="json"
    ).status_code == 201
    response = client.post("/reviews/listings/", payload, format="json")

    assert response.status_code == 400
    assert (
        response.data["non_field_errors"][0]
        == "You have already reviewed this listing."
    )


@pytest.mark.django_db
def test_seller_cannot_inquire_about_their_own_listing(auth_client):
    listing = ListingFactory()

    response = auth_client(listing.user).post(
        "/inquiries/",
        {
            "listing": listing.id,
            "subject": "Is this available?",
            "message": "Asking myself.",
            "contact_name": "Seller",
            "contact_email": "seller@example.com",
        },
        format="json",
    )

    assert response.status_code == 400
    assert (
        response.data["listing"][0]
        == "You cannot send an inquiry to your own listing."
    )


@pytest.mark.django_db
def test_cancelling_a_cancelled_order_is_rejected(auth_client):
    order = OrderFactory(status=Order.Status.CANCELLED)

    response = auth_client(order.buyer).post(
        f"/commerce/orders/{order.id}/cancel/", format="json"
    )

    assert response.status_code == 400
    assert response.data["error"] == "Order cannot be cancelled at this stage"
