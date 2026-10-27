import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status

from apps.accounts.models import User, VerificationRequest
from apps.accounts.serializers import VerificationRequestSerializer
from tests.factories import StoreFactory


def _file(name="doc.pdf", content=b"%PDF-1.4 test"):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


@pytest.mark.django_db
def test_onboarding_step_three_stores_business_type_not_a_document(auth_client):
    user = User.objects.create_user(
        email="vendor@example.com", password="S3curePass!23", full_name="Vendor"
    )
    StoreFactory(user=user)
    client = auth_client(user)

    response = client.post(
        "/auth/onboarding/step-3/",
        {
            "business_type": "sole_proprietorship",
            "government_id": _file("id.pdf"),
            "proof_of_registration": _file("registration.pdf"),
            "confirmed": True,
        },
        format="multipart",
    )

    assert response.status_code == status.HTTP_200_OK
    verification = VerificationRequest.objects.get(user=user)
    assert verification.business_type == "sole_proprietorship"
    assert verification.additional_info == ""
    assert not verification.business_license.name.endswith("sole_proprietorship")


@pytest.mark.django_db
def test_verification_serializer_never_returns_a_fake_document():
    user = User.objects.create_user(
        email="vendor2@example.com", password="S3curePass!23", full_name="Vendor"
    )
    verification = VerificationRequest.objects.create(
        user=user,
        company_name="Vendor Ltd",
        business_license=_file("license.pdf"),
        insurance_certificate=_file("insurance.pdf"),
        business_type="sole_proprietorship",
        additional_info="",
    )

    data = VerificationRequestSerializer(verification).data

    assert data["business_type"] == "sole_proprietorship"
    for field in ("business_license", "government_id", "insurance_certificate"):
        value = data.get(field)
        if value:
            assert value.startswith("http") or value.startswith("/")
