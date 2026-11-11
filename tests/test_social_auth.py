import pytest

from apps.accounts import social_auth


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
def test_google_accepts_an_access_token_without_iss(
    client, settings, monkeypatch
):
    settings.GOOGLE_CLIENT_ID = "google-client-id"
    seen = {}

    def _get(url, *args, **kwargs):
        seen["url"] = url
        return _Response({
            "azp": "google-client-id",
            "aud": "google-client-id",
            "email": "access-google@example.com",
            "email_verified": "true",
            "scope": "openid email profile",
            "expires_in": 3599,
        })

    monkeypatch.setattr(social_auth.requests, "get", _get)

    response = client.post(
        "/auth/social/google/", {"access_token": "ya29.x"}, format="json"
    )

    assert response.status_code == 200
    assert response.data["user"]["email"] == "access-google@example.com"
    assert "access_token=ya29.x" in seen["url"]
    assert social_auth.User.objects.get(
        email="access-google@example.com"
    ).is_verified is True


@pytest.mark.django_db
def test_google_accepts_legacy_access_token_fields(
    client, settings, monkeypatch
):
    settings.GOOGLE_CLIENT_ID = "google-client-id"
    monkeypatch.setattr(
        social_auth.requests, "get",
        lambda *a, **k: _Response({
            "audience": "google-client-id",
            "email": "legacy-google@example.com",
            "verified_email": True,
        }),
    )

    response = client.post(
        "/auth/social/google/", {"access_token": "ya29.legacy"}, format="json"
    )

    assert response.status_code == 200
    assert response.data["user"]["email"] == "legacy-google@example.com"


@pytest.mark.django_db
def test_google_rejects_an_access_token_for_a_foreign_audience(
    client, settings, monkeypatch
):
    settings.GOOGLE_CLIENT_ID = "google-client-id"
    monkeypatch.setattr(
        social_auth.requests, "get",
        lambda *a, **k: _Response({
            "aud": "someone-else",
            "email": "x@example.com",
            "email_verified": "true",
        }),
    )

    response = client.post(
        "/auth/social/google/", {"access_token": "ya29.x"}, format="json"
    )

    assert response.status_code == 400
    assert response.data["error"] == "Invalid Google token."


@pytest.mark.django_db
def test_google_rejects_an_access_token_for_a_foreign_azp(
    client, settings, monkeypatch
):
    settings.GOOGLE_CLIENT_ID = "google-client-id"
    monkeypatch.setattr(
        social_auth.requests, "get",
        lambda *a, **k: _Response({
            "aud": "google-client-id",
            "azp": "someone-else",
            "email": "x@example.com",
            "email_verified": "true",
        }),
    )

    response = client.post(
        "/auth/social/google/", {"access_token": "ya29.x"}, format="json"
    )

    assert response.status_code == 400
    assert response.data["error"] == "Invalid Google token."


@pytest.mark.django_db
def test_google_still_rejects_an_id_token_with_a_bad_issuer(
    client, settings, monkeypatch
):
    settings.GOOGLE_CLIENT_ID = "google-client-id"
    monkeypatch.setattr(
        social_auth.requests, "get",
        lambda *a, **k: _Response(
            _google_payload(iss="https://evil.example.com")
        ),
    )

    response = client.post(
        "/auth/social/google/", {"id_token": "x"}, format="json"
    )

    assert response.status_code == 400
    assert response.data["error"] == "Invalid Google token."


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
