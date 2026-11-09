import pytest

from apps.accounts.models import UserSession

from .factories import UserFactory


def _login(client, user, user_agent):
    return client.post(
        "/auth/login/",
        {"email": user.email, "password": "TestPass123!"},
        format="json",
        HTTP_USER_AGENT=user_agent,
    )


@pytest.mark.django_db
def test_login_records_device_type(client):
    user = UserFactory()
    user.set_password("TestPass123!")
    user.save(update_fields=["password"])

    response = _login(client, user, "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)")

    assert response.status_code == 200
    session = UserSession.objects.get(user=user)
    assert session.device_type == "mobile"


@pytest.mark.django_db
def test_login_records_desktop_device_type(client):
    user = UserFactory()
    user.set_password("TestPass123!")
    user.save(update_fields=["password"])

    _login(client, user, "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")

    assert UserSession.objects.get(user=user).device_type == "desktop"


@pytest.mark.django_db
def test_session_serializer_derives_a_missing_device_type(auth_client):
    user = UserFactory()
    session = UserSession.objects.create(
        user=user,
        device_name="Old session",
        device_type="",
        user_agent="Mozilla/5.0 (iPad; CPU OS 17_0)",
        token_jti="jti-derived",
    )

    response = auth_client(user).get("/auth/sessions/")

    assert response.status_code == 200
    row = next(item for item in response.data if item["id"] == session.pk)
    assert row["device_type"] == "tablet"
