import pytest

from apps.commerce.models import Order

from .factories import (
    ListingFactory,
    OrderFactory,
    OrderItemFactory,
    StoreFactory,
    UserFactory,
)


@pytest.mark.django_db
def test_review_requires_a_paid_order(auth_client):
    listing = ListingFactory()
    outsider = UserFactory()
    client = auth_client(outsider)

    response = client.post(
        "/reviews/listings/",
        {"listing": listing.id, "rating": 5, "comment": "Great"},
        format="json",
    )

    assert response.status_code == 400
    assert (
        "purchase" in str(response.data).lower()
        or "order" in str(response.data).lower()
    )


@pytest.mark.django_db
def test_buyer_with_paid_order_can_review(auth_client):
    listing = ListingFactory()
    buyer = UserFactory()
    order = OrderFactory(
        buyer=buyer, store=listing.store, status=Order.Status.PAID
    )
    OrderItemFactory(order=order, listing=listing)
    client = auth_client(buyer)

    response = client.post(
        "/reviews/listings/",
        {"listing": listing.id, "rating": 5, "comment": "Great"},
        format="json",
    )

    assert response.status_code == 201


@pytest.mark.django_db
def test_reviewer_can_edit_and_delete(auth_client):
    listing = ListingFactory()
    buyer = UserFactory()
    order = OrderFactory(
        buyer=buyer, store=listing.store, status=Order.Status.FULFILLED
    )
    OrderItemFactory(order=order, listing=listing)
    client = auth_client(buyer)
    created = client.post(
        "/reviews/listings/",
        {"listing": listing.id, "rating": 4, "comment": "Good"},
        format="json",
    ).data

    patched = client.patch(
        f"/reviews/listings/{created['id']}/",
        {"rating": 5, "comment": "Better"},
        format="json",
    )
    deleted = client.delete(f"/reviews/listings/{created['id']}/")

    assert patched.status_code == 200
    assert patched.data["rating"] == 5
    assert deleted.status_code == 204


@pytest.mark.django_db
def test_other_user_cannot_edit_a_review(auth_client):
    listing = ListingFactory()
    buyer = UserFactory()
    order = OrderFactory(
        buyer=buyer, store=listing.store, status=Order.Status.PAID
    )
    OrderItemFactory(order=order, listing=listing)
    created = (
        auth_client(buyer)
        .post(
            "/reviews/listings/",
            {"listing": listing.id, "rating": 4, "comment": "Good"},
            format="json",
        )
        .data
    )
    client = auth_client(UserFactory())

    response = client.patch(
        f"/reviews/listings/{created['id']}/", {"rating": 1}, format="json"
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_store_review_requires_a_paid_order_from_that_store(auth_client):
    store = StoreFactory()
    listing = ListingFactory(store=store, user=store.user)
    buyer = UserFactory()
    order = OrderFactory(
        buyer=buyer, store=store, status=Order.Status.DELIVERED
    )
    OrderItemFactory(order=order, listing=listing)
    client = auth_client(buyer)

    response = client.post(
        "/reviews/stores/",
        {"store": store.id, "rating": 5, "comment": "Great vendor"},
        format="json",
    )

    assert response.status_code == 201
