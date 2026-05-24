# apps/core/currency.py
"""
Unified currency conversion and localization utility for Harbour Hub.
Integrates free open API exchange rates with a 1-hour Redis cache TTL fallback.
"""
import logging
import requests
from decimal import Decimal
from django.conf import settings
from django.core.cache import cache
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination

logger = logging.getLogger(__name__)

CURRENCY_SYMBOLS = {
    "NGN": "₦",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "CAD": "C$",
    "AUD": "A$",
    "JPY": "¥",
    "CNY": "¥",
}


def get_preferred_currency(request) -> str:
    """
    Determine preferred currency using the specified priority:
    1. Authenticated user profile preference
    2. Request cookies ('hh_currency')
    3. Custom headers ('hh-currency' / 'HTTP_HH_CURRENCY')
    4. Default NGN fallback
    """
    if not request:
        return "NGN"

    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        preferences = getattr(user, "preferences", None)
        if preferences:
            currency = getattr(preferences, "preferred_currency", None)
            if currency:
                return currency.upper().strip()

    # Read from cookie
    cookie_curr = request.COOKIES.get("hh_currency")
    if cookie_curr:
        return cookie_curr.upper().strip()

    # Read from headers
    header_curr = request.headers.get("hh-currency") or request.META.get("HTTP_HH_CURRENCY")
    if header_curr:
        return header_curr.upper().strip()

    return "NGN"


def get_exchange_rates() -> dict:
    """
    Fetch exchange rates from a free API, caching in Redis for 1 hour.
    Returns conversion rates from NGN to other target currencies.
    """
    cache_key = "harbour_hub_exchange_rates_ngn"
    rates = cache.get(cache_key)
    if rates:
        return rates

    try:
        response = requests.get("https://open.er-api.com/v6/latest/NGN", timeout=5)
        if response.status_code == 200:
            data = response.json()
            rates = data.get("rates", {})
            if rates:
                cache.set(cache_key, rates, 3600)  # 1 hour cache
                logger.info("Successfully fetched and cached currency exchange rates from API.")
                return rates
    except Exception as exc:
        logger.warning("Failed to retrieve exchange rates from external API: %s. Using default fallbacks.", exc)

    # Reliable fallbacks
    fallback_rates = {
        "NGN": 1.0,
        "USD": 0.00067,
        "EUR": 0.00062,
        "GBP": 0.00053,
    }
    return fallback_rates


def convert_currency(amount_ngn, target_currency: str) -> tuple[float, str]:
    """
    Convert NGN amount to target currency.
    Returns (converted_amount_float, symbol_string).
    """
    if amount_ngn is None:
        return 0.0, CURRENCY_SYMBOLS.get(target_currency, target_currency)

    try:
        val = Decimal(str(amount_ngn))
    except Exception:
        return 0.0, CURRENCY_SYMBOLS.get(target_currency, target_currency)

    target_currency = target_currency.upper().strip()
    rates = get_exchange_rates()
    rate = rates.get(target_currency)

    if rate is None:
        rate = rates.get("NGN", 1.0) if target_currency == "NGN" else 1.0

    converted = val * Decimal(str(rate))
    return round(float(converted), 2), CURRENCY_SYMBOLS.get(target_currency, target_currency)


class CurrencyConverterMixin(object):
    """
    Mixin for DRF Serializers to dynamically convert specified list of NGN monetary fields.
    Appends root 'currency' and 'currency_symbol' context.
    """
    # Define a list of model field names to convert
    monetary_fields = []

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        request = self.context.get("request")
        if not request or not self.monetary_fields:
            return ret

        target_curr = get_preferred_currency(request)

        for field in self.monetary_fields:
            if field in ret and ret[field] is not None:
                try:
                    converted, _ = convert_currency(ret[field], target_curr)
                    ret[field] = converted
                except Exception:
                    pass

        ret["currency"] = target_curr
        ret["currency_symbol"] = CURRENCY_SYMBOLS.get(target_curr, target_curr)
        return ret


class CurrencyLocalizedPagination(PageNumberPagination):
    """
    Custom pagination injector to append top-level currency metadata in listing pagination wrappers.
    """
    def get_paginated_response(self, data):
        request = self.request
        target_curr = get_preferred_currency(request)
        symbol = CURRENCY_SYMBOLS.get(target_curr, target_curr)

        response = super().get_paginated_response(data)
        response.data["currency"] = target_curr
        response.data["currency_symbol"] = symbol
        return response
