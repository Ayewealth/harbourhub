import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

# Fixed USD-base rates. The suite must never call open.er-api.com: a cold cache
# used to make serializer tests depend on the network.
FIXED_USD_RATES = {
    "USD": 1.0,
    "NGN": 1500.0,
    "EUR": 0.92,
    "GBP": 0.79,
    "CAD": 1.36,
    "AUD": 1.52,
    "JPY": 149.0,
    "CNY": 7.24,
}

EXCHANGE_RATE_CACHE_KEY = "harbour_hub_exchange_rates_usd"


@pytest.fixture(autouse=True)
def fixed_exchange_rates():
    """Seed the rate cache before every test so no test can reach the provider."""
    cache.set(EXCHANGE_RATE_CACHE_KEY, FIXED_USD_RATES, 3600)
    yield


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
