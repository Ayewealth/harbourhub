import pytest
from django.urls import resolve

from apps.commerce.webhooks import (
    PaystackWebhookLegacyView,
    PaystackWebhookView,
)

from .factories import UserFactory


@pytest.mark.django_db
def test_canonical_and_legacy_webhook_paths_share_the_view():
    canonical = resolve("/commerce/webhooks/paystack/")
    legacy = resolve("/commerce/payment/webhook/")

    assert canonical.func.view_class is PaystackWebhookView
    assert legacy.func.view_class is PaystackWebhookLegacyView
    assert issubclass(legacy.func.view_class, PaystackWebhookView)


@pytest.mark.django_db
def test_canonical_analytics_path_works(auth_client):
    admin_user = UserFactory(role="admin", is_staff=True)
    response = auth_client(admin_user).get("/analytics/")

    assert response.status_code == 200


@pytest.mark.django_db
def test_legacy_analytics_path_still_works(auth_client):
    admin_user = UserFactory(role="admin", is_staff=True)
    response = auth_client(admin_user).get("/analytics/analytics/")

    assert response.status_code == 200


@pytest.mark.django_db
def test_quote_paths_are_unchanged(auth_client):
    user = UserFactory()

    assert auth_client(user).get("/quotes/sent/").status_code == 200
    assert auth_client(user).get("/quotes/received/").status_code == 200
    assert auth_client(user).get("/commerce/quotes/sent/").status_code == 200
