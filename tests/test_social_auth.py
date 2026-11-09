from unittest.mock import patch

import pytest

from apps.accounts import social_auth

from .factories import UserFactory


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _google_payload(**overrides):
    payload = {
        "iss": "https://accounts.google.com",
        "aud": "google-client-id",
        "email": "new-google@example.com",
        "email_verified": "true",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_google_is_unavailable_when_unconfigured(client, settings):
    settings.GOOGLE_CLIENT_ID = ""

    response = client.post(
        "/auth/social/google/", {"id_token": "x"}, format="json"
    )

    assert response.status_code == 503
    assert response.data["error"] == "Google login is not configured."


@pytest.mark.django_db
def test_google_creates_a_verified_user(client, settings, monkeypatch):
    settings.GOOGLE_CLIENT_ID = "google-client-id"
    monkeypatch.setattr(
        social_auth.requests, "get",
        lambda *a, **k: _Response(_google_payload()),
    )

    response = client.post(
        "/auth/social/google/", {"id_token": "x"}, format="json"
    )

    assert response.status_code == 200
    assert response.data["user"]["email"] == "new-google@example.com"
    user = social_auth.User.objects.get(email="new-google@example.com")
    assert user.is_verified is True
    assert user.role == "buyer"


@pytest.mark.django_db
def test_google_rejects_a_foreign_audience(client, settings, monkeypatch):
    settings.GOOGLE_CLIENT_ID = "google-client-id"
    monkeypatch.setattr(
        social_auth.requests, "get",
        lambda *a, **k: _Response(_google_payload(aud="someone-else")),
    )

    response = client.post(
        "/auth/social/google/", {"id_token": "x"}, format="json"
    )

    assert response.status_code == 400
    assert response.data["error"] == "Invalid Google token."


@pytest.mark.django_db
def test_google_rejects_an_unverified_email(client, settings, monkeypatch):
    settings.GOOGLE_CLIENT_ID = "google-client-id"
    monkeypatch.setattr(
        social_auth.requests, "get",
        lambda *a, **k: _Response(_google_payload(email_verified="false")),
    )

    response = client.post(
        "/auth/social/google/", {"id_token": "x"}, format="json"
    )

    assert response.status_code == 400
    assert response.data["error"] == (
        "Google email address is not verified."
    )


@pytest.mark.django_db
def test_apple_is_unavailable_when_unconfigured(client, settings):
    settings.APPLE_CLIENT_ID = ""

    response = client.post(
        "/auth/social/apple/", {"id_token": "x"}, format="json"
    )

    assert response.status_code == 503
    assert response.data["error"] == "Apple login is not configured."


@pytest.mark.django_db
def test_apple_verifies_signature_and_claims(client, settings, monkeypatch):
    settings.APPLE_CLIENT_ID = "apple-client-id"
    monkeypatch.setattr(
        social_auth.requests, "get",
        lambda *a, **k: _Response({"keys": [{"kid": "kid-1"}]}),
    )
    monkeypatch.setattr(
        social_auth.jwt, "get_unverified_header", lambda token: {"kid": "kid-1"}
    )
    monkeypatch.setattr(
        social_auth.jwt, "decode",
        lambda *a, **k: {
            "iss": "https://appleid.apple.com",
            "aud": "apple-client-id",
            "email": "new-apple@example.com",
            "email_verified": "true",
        },
    )
    monkeypatch.setattr(
        "jwt.algorithms.RSAAlgorithm.from_jwk", lambda key: "public-key"
    )

    response = client.post(
        "/auth/social/apple/", {"id_token": "x"}, format="json"
    )

    assert response.status_code == 200
    assert response.data["user"]["email"] == "new-apple@example.com"
