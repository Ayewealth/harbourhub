from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import VerificationRequest
from apps.admin_panel.models import PlatformConfig
from apps.store.models import Store
from tests.factories import StoreFactory


def _config(**overrides):
    config = PlatformConfig.objects.get_or_create(pk=1)[0]
    for key, value in overrides.items():
        setattr(config, key, value)
    config.save()
    return config


def _provider_with_store():
    store = StoreFactory(user__role="service_provider")
    return store.user, store


def _payload():
    return {
        "company_name": "Acme Oilfield Services",
        "business_type": "limited_liability",
        "business_license": SimpleUploadedFile(
            "license.pdf", b"%PDF-1.4 test", content_type="application/pdf"
        ),
        "certifications": "API 610",
    }


@pytest.mark.django_db
def test_request_stays_pending_when_approval_is_required(auth_client):
    _config(vendor_approval_required=True)
    user, store = _provider_with_store()

    with patch(
        "apps.accounts.views.notify_admins_verification_request.delay"
    ) as notify_admins, patch(
        "apps.accounts.views.notify_verification_approved"
    ) as notify_approved:
        response = auth_client(user).post(
            "/auth/verification/request/", _payload(), format="multipart"
        )

    assert response.status_code == 201
    request_obj = VerificationRequest.objects.get(user=user)
    assert request_obj.status == VerificationRequest.Status.PENDING
    assert request_obj.reviewed_at is None
    user.refresh_from_db()
    store.refresh_from_db()
    assert user.is_verified is False
    assert store.is_verified is False
    assert response.data["status"] == "pending"
    assert response.data["request_id"] == request_obj.pk
    assert response.data["message"] == (
        "Verification request submitted successfully"
    )
    notify_admins.assert_called_once()
    notify_approved.assert_not_called()


@pytest.mark.django_db
def test_request_is_auto_approved_when_approval_is_disabled(auth_client):
    _config(vendor_approval_required=False)
    user, store = _provider_with_store()

    with patch(
        "apps.accounts.views.notify_admins_verification_request.delay"
    ) as notify_admins, patch(
        "apps.accounts.views.notify_verification_approved"
    ) as notify_approved:
        response = auth_client(user).post(
            "/auth/verification/request/", _payload(), format="multipart"
        )

    assert response.status_code == 201
    request_obj = VerificationRequest.objects.get(user=user)
    assert request_obj.status == VerificationRequest.Status.APPROVED
    assert request_obj.reviewed_by is None
    assert request_obj.reviewed_at is not None
    assert request_obj.admin_notes == (
        "Auto-approved because vendor approval is disabled."
    )
    user.refresh_from_db()
    store.refresh_from_db()
    assert user.is_verified is True
    assert store.is_verified is True
    assert response.data["status"] == "approved"
    notify_admins.assert_not_called()
    notify_approved.assert_called_once_with(user)


@pytest.mark.django_db
def test_onboarding_creates_verified_store_when_approval_is_disabled(
    auth_client, monkeypatch
):
    _config(vendor_approval_required=False)
    monkeypatch.setattr(
        "apps.accounts.serializers.notify_verification_approved",
        lambda user: None,
        raising=False,
    )
    seller = StoreFactory().user
    Store.objects.filter(user=seller).delete()
    seller.role = "seller"
    seller.save(update_fields=["role"])

    response = auth_client(seller).post(
        "/auth/onboarding/step-1/",
        {
            "business_name": "Delta Marine Supply",
            "phone": "08030000000",
            "email": "delta@example.com",
            "country": "Nigeria",
        },
        format="json",
    )

    assert response.status_code in (200, 201)
    store = Store.objects.get(user=seller)
    assert store.is_verified is True
