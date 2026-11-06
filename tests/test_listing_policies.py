import pytest
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.admin_panel.models import PlatformConfig
from apps.listings.admin import ListingAdmin
from apps.listings.models import Listing
from tests.factories import (
    CategoryFactory,
    ListingFactory,
    StoreFactory,
    UserFactory,
)


def _config(**overrides):
    config = PlatformConfig.objects.get_or_create(pk=1)[0]
    for key, value in overrides.items():
        setattr(config, key, value)
    config.save()
    return config


def _seller_with_store():
    store = StoreFactory()
    return store.user, store


def _payload(_store, **overrides):
    payload = {
        "title": "Hydraulic winch",
        "description": "Heavy duty winch in good condition.",
        "category": CategoryFactory().pk,
        "listing_type": Listing.Type.SELL,
        "price": "1500000.00",
        "location": "Lagos",
        "contact_name": "Test Seller",
        "contact_email": "seller@example.com",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_create_rejects_a_disabled_listing_type(auth_client):
    _config(enable_buy=False)
    seller, store = _seller_with_store()
    payload = _payload(store)

    response = auth_client(seller).post("/listings/", payload, format="json")

    assert response.status_code == 400
    assert response.data["listing_type"] == ["Buy listings are currently disabled."]


@pytest.mark.django_db
def test_create_stores_draft_when_approval_is_required(auth_client):
    _config(listing_approval_required=True)
    seller, store = _seller_with_store()

    response = auth_client(seller).post(
        "/listings/", _payload(store, status="published"), format="json"
    )

    assert response.status_code == 201
    listing = Listing.objects.get(pk=response.data["id"])
    assert listing.status == Listing.Status.DRAFT
    assert listing.published_at is None


@pytest.mark.django_db
def test_create_publishes_immediately_when_approval_is_not_required(auth_client):
    _config(listing_approval_required=False)
    seller, store = _seller_with_store()

    response = auth_client(seller).post("/listings/", _payload(store), format="json")

    assert response.status_code == 201
    listing = Listing.objects.get(pk=response.data["id"])
    assert listing.status == Listing.Status.PUBLISHED
    assert listing.published_at is not None


@pytest.mark.django_db
def test_update_cannot_publish_a_never_approved_listing(auth_client):
    _config(listing_approval_required=True)
    seller, store = _seller_with_store()
    listing = ListingFactory(user=seller, store=store, status=Listing.Status.DRAFT)

    response = auth_client(seller).patch(
        f"/listings/{listing.pk}/", {"status": "published"}, format="json"
    )

    assert response.status_code == 400
    assert response.data["status"] == [
        "Listings require admin approval before publishing."
    ]


@pytest.mark.django_db
def test_publish_action_enforces_approval(auth_client):
    _config(listing_approval_required=True)
    seller, store = _seller_with_store()
    listing = ListingFactory(user=seller, store=store, status=Listing.Status.DRAFT)
    store.is_active = True
    store.save(update_fields=["is_active"])

    response = auth_client(seller).post(f"/listings/{listing.pk}/publish/")

    assert response.status_code == 400
    assert response.data["error"] == (
        "Listings require admin approval before publishing."
    )


@pytest.mark.django_db
def test_admin_may_publish_a_draft(auth_client):
    _config(listing_approval_required=True)
    seller, store = _seller_with_store()
    listing = ListingFactory(user=seller, store=store, status=Listing.Status.DRAFT)
    admin = UserFactory(role=User.Role.ADMIN, is_staff=True)

    response = auth_client(admin).post(f"/listings/{listing.pk}/publish/")

    assert response.status_code == 200
    listing.refresh_from_db()
    assert listing.status == Listing.Status.PUBLISHED
    assert listing.published_at is not None


@pytest.mark.django_db
def test_public_list_hides_a_disabled_type():
    _config(enable_services=False)
    seller, store = _seller_with_store()
    visible = ListingFactory(
        user=seller, store=store, listing_type=Listing.Type.SELL,
        status=Listing.Status.PUBLISHED, published_at=timezone.now(),
    )
    hidden = ListingFactory(
        user=seller, store=store, listing_type=Listing.Type.SERVICE,
        status=Listing.Status.PUBLISHED, published_at=timezone.now(),
    )

    response = APIClient().get("/listings/")
    ids = {row["id"] for row in response.data["results"]}

    assert visible.pk in ids
    assert hidden.pk not in ids


@pytest.mark.django_db
def test_owner_can_still_retrieve_a_disabled_type(auth_client):
    _config(enable_services=False)
    seller, store = _seller_with_store()
    listing = ListingFactory(
        user=seller, store=store, listing_type=Listing.Type.SERVICE,
        status=Listing.Status.PUBLISHED, published_at=timezone.now(),
    )

    response = auth_client(seller).get(f"/listings/{listing.pk}/")

    assert response.status_code == 200


@pytest.mark.django_db
def test_forged_store_is_ignored(auth_client):
    _config(listing_approval_required=False)
    seller, store = _seller_with_store()
    other_store = StoreFactory()

    response = auth_client(seller).post(
        "/listings/", _payload(store, store=other_store.pk), format="json"
    )

    assert response.status_code == 201
    listing = Listing.objects.get(pk=response.data["id"])
    assert listing.store_id == store.pk


@pytest.mark.django_db
def test_admin_bulk_publish_sets_published_at(monkeypatch):
    listing = ListingFactory(status=Listing.Status.DRAFT)
    model_admin = ListingAdmin(Listing, AdminSite())
    monkeypatch.setattr(model_admin, "message_user", lambda *a, **k: None)

    model_admin.mark_published(
        RequestFactory().post("/admin/"),
        Listing.objects.filter(pk=listing.pk),
    )

    listing.refresh_from_db()
    assert listing.status == Listing.Status.PUBLISHED
    assert listing.published_at is not None
