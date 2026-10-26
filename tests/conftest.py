import pytest
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_client():
    client = APIClient()

    def _authenticate(user):
        client.force_authenticate(user=user)
        return client

    return _authenticate
