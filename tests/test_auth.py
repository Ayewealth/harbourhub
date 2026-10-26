import pytest
from rest_framework import status

from apps.accounts.models import User
from tests.factories import UserFactory


@pytest.mark.django_db
def test_registration_rejects_privileged_role(api_client):
    response = api_client.post(
        "/auth/register/",
        {
            "email": "attacker@example.com",
            "username": "attacker",
            "full_name": "Attacker",
            "password": "S3curePass!23",
            "password_confirm": "S3curePass!23",
            "role": "super_admin",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert not User.objects.filter(email="attacker@example.com").exists()


@pytest.mark.django_db
def test_registration_without_role_creates_buyer(api_client):
    response = api_client.post(
        "/auth/register/",
        {
            "email": "buyer@example.com",
            "username": "buyer",
            "full_name": "Buyer",
            "password": "S3curePass!23",
            "password_confirm": "S3curePass!23",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert User.objects.get(email="buyer@example.com").role == User.Role.BUYER


@pytest.mark.django_db
def test_registration_rejects_seller_role(api_client):
    response = api_client.post(
        "/auth/register/",
        {
            "email": "seller-attempt@example.com",
            "username": "seller-attempt",
            "full_name": "Seller Attempt",
            "password": "S3curePass!23",
            "password_confirm": "S3curePass!23",
            "role": "seller",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert not User.objects.filter(email="seller-attempt@example.com").exists()


@pytest.mark.django_db
def test_become_seller_is_the_only_promotion_path(auth_client):
    user = UserFactory(email="promote@example.com")
    client = auth_client(user)

    response = client.post(
        "/auth/become-seller/",
        {"business_name": "Promote Ltd", "phone": "08000000000", "country": "NG"},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    user.refresh_from_db()
    assert user.role == User.Role.SELLER


@pytest.mark.django_db
def test_refresh_rotation_blacklists_the_old_token(api_client):
    UserFactory(email="rotate@example.com", password="TestPass123!")

    login = api_client.post(
        "/auth/login/",
        {"email": "rotate@example.com", "password": "TestPass123!"},
        format="json",
    )
    assert login.status_code == status.HTTP_200_OK
    refresh = login.data["refresh"]

    first = api_client.post("/auth/refresh/", {"refresh": refresh}, format="json")
    assert first.status_code == status.HTTP_200_OK

    second = api_client.post("/auth/refresh/", {"refresh": refresh}, format="json")
    assert second.status_code == status.HTTP_401_UNAUTHORIZED
