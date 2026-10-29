import pytest
from rest_framework import status

from apps.accounts.models import User
from apps.listings.models import Listing, ListingStoreRequired
from tests.factories import CategoryFactory, ListingFactory, StoreFactory, UserFactory


@pytest.mark.django_db
def test_client_supplied_store_is_ignored(auth_client):
    seller = UserFactory(role=User.Role.SELLER)
    own_store = StoreFactory(user=seller)
    other_store = StoreFactory()
    category = CategoryFactory()
    client = auth_client(seller)

    response = client.post(
        "/listings/",
        {
            "title": "Generator",
            "description": "Diesel generator",
            "category": category.id,
            "store": other_store.id,
            "listing_type": "sell",
            "price": "5000.00",
            "currency": "NGN",
            "location": "Lagos",
            "contact_name": "Seller",
            "contact_email": "seller@example.com",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert Listing.objects.get(pk=response.data["id"]).store_id == own_store.id


@pytest.mark.django_db
def test_listing_without_store_returns_400(auth_client):
    seller = UserFactory(role=User.Role.SELLER)
    category = CategoryFactory()
    client = auth_client(seller)

    response = client.post(
        "/listings/",
        {
            "title": "No store",
            "description": "Cannot publish",
            "category": category.id,
            "listing_type": "sell",
            "price": "10.00",
            "currency": "NGN",
            "location": "Lagos",
            "contact_name": "Seller",
            "contact_email": "seller@example.com",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "store" in str(response.data).lower()


@pytest.mark.django_db
def test_model_refuses_storeless_listing():
    listing = ListingFactory.build(store=None, user=UserFactory())

    with pytest.raises(ListingStoreRequired):
        listing.save()


@pytest.mark.django_db
def test_update_cannot_move_a_listing_to_another_store(auth_client):
    seller = UserFactory(role=User.Role.SELLER)
    store = StoreFactory(user=seller)
    listing = ListingFactory(store=store, user=seller)
    other_store = StoreFactory()
    client = auth_client(seller)

    response = client.patch(
        f"/listings/{listing.id}/",
        {"store": other_store.id, "title": "Renamed"},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    listing.refresh_from_db()
    assert listing.store_id == store.id
    assert listing.title == "Renamed"

@pytest.mark.django_db
def test_published_listing_with_active_store_is_visible(api_client):
    listing = ListingFactory()

    response = api_client.get("/listings/")

    ids = [row["id"] for row in response.data["results"]]
    assert listing.id in ids


@pytest.mark.django_db
def test_listing_with_inactive_store_is_hidden(api_client):
    listing = ListingFactory()
    listing.store.is_active = False
    listing.store.save(update_fields=["is_active"])

    response = api_client.get("/listings/")

    ids = [row["id"] for row in response.data["results"]]
    assert listing.id not in ids


@pytest.mark.django_db
def test_publish_requires_ownership(auth_client):
    listing = ListingFactory(status=Listing.Status.DRAFT)
    client = auth_client(UserFactory())

    response = client.post(f"/listings/{listing.id}/publish/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_owner_can_publish_a_draft(auth_client):
    listing = ListingFactory(status=Listing.Status.DRAFT)
    client = auth_client(listing.user)

    response = client.post(f"/listings/{listing.id}/publish/")

    assert response.status_code == 200
    listing.refresh_from_db()
    assert listing.status == Listing.Status.PUBLISHED


@pytest.mark.django_db
@pytest.mark.parametrize(
    "order_status",
    [
        "paid",
        "order_confirmed",
        "item_dispatched",
        "in_transit",
        "delivered",
        "active_hire",
        "hire_ended",
        "item_returned",
    ],
)
def test_listing_with_live_order_cannot_be_deleted(auth_client, order_status):
    from .factories import OrderFactory, OrderItemFactory

    listing = ListingFactory()
    order = OrderFactory(status=order_status, store=listing.store)
    OrderItemFactory(order=order, listing=listing)
    client = auth_client(listing.user)

    response = client.delete(f"/listings/{listing.id}/")

    assert response.status_code == 400
    assert Listing.objects.filter(pk=listing.pk).exists()


@pytest.mark.django_db
def test_listing_with_fulfilled_order_can_be_deleted(auth_client):
    from apps.commerce.models import Order

    from .factories import OrderFactory, OrderItemFactory

    listing = ListingFactory()
    order = OrderFactory(status=Order.Status.FULFILLED, store=listing.store)
    OrderItemFactory(order=order, listing=listing)
    client = auth_client(listing.user)

    response = client.delete(f"/listings/{listing.id}/")

    assert response.status_code == 204, response.data
