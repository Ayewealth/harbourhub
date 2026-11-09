import pytest

from apps.notifications.models import NotificationPreference, PushSubscription

from .factories import UserFactory


@pytest.mark.django_db
def test_get_preferences_creates_all_categories(auth_client):
    user = UserFactory()

    response = auth_client(user).get("/notifications/preferences/")

    assert response.status_code == 200
    assert [row["category"] for row in response.data] == [
        "transactional", "messages", "marketing"
    ]
    assert NotificationPreference.objects.filter(user=user).count() == 3
    first = response.data[0]
    assert first == {
        "category": "transactional",
        "in_app": True,
        "email": True,
        "sms": False,
        "push": True,
    }


@pytest.mark.django_db
def test_patch_can_disable_sms(auth_client):
    user = UserFactory()

    response = auth_client(user).patch(
        "/notifications/preferences/marketing/",
        {"sms": True},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["sms"] is True
    pref = NotificationPreference.objects.get(
        user=user, category="marketing"
    )
    assert pref.sms is True


@pytest.mark.django_db
def test_transactional_in_app_and_email_cannot_be_disabled(auth_client):
    user = UserFactory()

    response = auth_client(user).patch(
        "/notifications/preferences/transactional/",
        {"in_app": False},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["error"] == (
        "Transactional in-app and email notifications cannot be disabled."
    )


@pytest.mark.django_db
def test_push_subscription_upsert_and_delete(auth_client):
    user = UserFactory()
    client = auth_client(user)
    body = {
        "endpoint": "https://push.example/abc",
        "keys": {"p256dh": "key", "auth": "auth"},
        "user_agent": "pytest",
    }

    created = client.post(
        "/notifications/push/subscriptions/", body, format="json"
    )
    assert created.status_code == 201

    updated = client.post(
        "/notifications/push/subscriptions/", body, format="json"
    )
    assert updated.status_code == 200
    assert PushSubscription.objects.filter(user=user).count() == 1

    deleted = client.delete(
        f"/notifications/push/subscriptions/{created.data['id']}/"
    )
    assert deleted.status_code == 204
    assert PushSubscription.objects.filter(user=user).count() == 0


@pytest.mark.django_db
def test_push_subscription_cannot_be_stolen(auth_client):
    owner = UserFactory()
    attacker = UserFactory()
    PushSubscription.objects.create(
        user=owner, endpoint="https://push.example/owned",
        p256dh="key", auth="auth",
    )

    response = auth_client(attacker).post(
        "/notifications/push/subscriptions/",
        {
            "endpoint": "https://push.example/owned",
            "keys": {"p256dh": "key", "auth": "auth"},
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.data["error"] == (
        "This push subscription belongs to another account."
    )


@pytest.mark.django_db
def test_push_public_key_reports_configuration(auth_client, settings):
    settings.VAPID_PUBLIC_KEY = ""

    response = auth_client(UserFactory()).get(
        "/notifications/push/public-key/"
    )

    assert response.status_code == 200
    assert response.data == {"public_key": "", "configured": False}
