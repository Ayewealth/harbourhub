import pytest
from rest_framework.test import APIClient

from apps.admin_panel.models import PlatformConfig


@pytest.mark.django_db
def test_platform_config_is_public_and_matches_the_contract():
    response = APIClient().get("/platform-config/")

    assert response.status_code == 200
    assert response.data == {
        "enable_buy": True,
        "enable_rent": True,
        "enable_services": False,
        "vendor_approval_required": True,
        "listing_approval_required": True,
        "default_currency": "NGN",
        "timezone": "Africa/Lagos",
        "date_format": "DD/MM/YY",
    }


@pytest.mark.django_db
def test_platform_config_reflects_saved_changes():
    config = PlatformConfig.objects.get_or_create(pk=1)[0]
    config.enable_rent = False
    config.default_currency = "USD"
    config.save()

    response = APIClient().get("/platform-config/")

    assert response.status_code == 200
    assert response.data["enable_rent"] is False
    assert response.data["default_currency"] == "USD"
