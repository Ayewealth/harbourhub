# apps/core/currency.py
"""
Unified currency conversion and localization utility for Harbour Hub.
Integrates free open API exchange rates with a 1-hour Redis cache TTL fallback.
"""
import logging
import requests
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from django.core.cache import cache
from django.utils import timezone
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

SUPPORTED_CURRENCIES = tuple(CURRENCY_SYMBOLS)

RATES_CACHE_KEY = "harbour_hub_exchange_rates_usd"
RATES_CACHE_SECONDS = 3600
FALLBACK_CACHE_SECONDS = 60


def get_preferred_currency(request) -> str:
    """
    Determine preferred currency using the specified priority:
    1. Authenticated user profile preference
    2. Request cookies ('hh_currency')
    3. Custom headers ('hh-currency' / 'HTTP_HH_CURRENCY')
    4. Default USD fallback
    """
    if not request:
        return "USD"

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

    return "USD"


def get_rate_snapshot() -> dict:
    """Current USD-based rates plus where they came from and when.

    Every conversion reads this, so a response can state the same numbers the
    server used. ``stale`` is true when the live API failed and the built-in
    fallback table is in use.
    """
    cached = cache.get(RATES_CACHE_KEY)
    if isinstance(cached, dict) and "rates" in cached:
        return cached
    if isinstance(cached, dict) and cached:
        # Legacy cache entry from before the snapshot format.
        return {
            "base": "USD",
            "rates": cached,
            "source": "cache",
            "fetched_at": None,
            "stale": False,
        }

    try:
        response = requests.get(
            "https://open.er-api.com/v6/latest/USD", timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            rates = data.get("rates", {})
            if rates:
                snapshot = {
                    "base": "USD",
                    "rates": rates,
                    "source": "open.er-api.com",
                    "fetched_at": timezone.now().isoformat(),
                    "stale": False,
                }
                cache.set(RATES_CACHE_KEY, snapshot, RATES_CACHE_SECONDS)
                logger.info(
                    "Fetched and cached currency exchange rates from API."
                )
                return snapshot
    except Exception as exc:
        logger.warning(
            "Failed to retrieve exchange rates from external API: %s. "
            "Using default fallbacks.",
            exc,
        )

    snapshot = {
        "base": "USD",
        "rates": {
            "USD": 1.0,
            "NGN": 1492.53,
            "EUR": 0.925,
            "GBP": 0.791,
        },
        "source": "fallback",
        "fetched_at": None,
        "stale": True,
    }
    # Short cache so the next attempt can recover quickly.
    cache.set(RATES_CACHE_KEY, snapshot, FALLBACK_CACHE_SECONDS)
    return snapshot


def get_exchange_rates() -> dict:
    """USD-based rates, cached for an hour. Prices only; use a snapshot to
    report provenance."""
    return get_rate_snapshot()["rates"]


def convert_currency(amount, target_currency: str, source_currency: str = "USD") -> tuple[float, str]:
    """
    Convert amount from source_currency to target_currency for display.
    Returns (converted_amount_float, symbol_string).

    DISPLAY ONLY. Money movement must use convert_money/convert_to_ngn.
    """
    symbol = CURRENCY_SYMBOLS.get((target_currency or "").upper(), target_currency)
    if amount is None:
        return 0.0, symbol

    try:
        converted = convert_money(amount, source_currency, target_currency)
    except (CurrencyRateUnavailable, InvalidOperation, TypeError, ValueError):
        return 0.0, symbol
    return float(converted), symbol


class CurrencyRateUnavailable(Exception):
    """Raised when a rate needed for a real money movement is missing."""


class UnsupportedCurrency(CurrencyRateUnavailable):
    """Raised when a currency code is not one this platform supports."""


def money(value) -> Decimal:
    """Quantise to two decimal places with ROUND_HALF_UP. Never returns a float."""
    return Decimal(str(value or 0)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def _normalise_currency(currency: str, default: str = "USD") -> str:
    code = (currency or default).upper().strip()
    if code not in SUPPORTED_CURRENCIES:
        raise UnsupportedCurrency(f"Unsupported currency: {code}.")
    return code


def _usd_rate(currency: str) -> Decimal:
    code = _normalise_currency(currency)
    if code == "USD":
        return Decimal("1")
    rates = get_exchange_rates() or {}
    rate = rates.get(code)
    if rate in (None, 0):
        raise CurrencyRateUnavailable(
            f"No exchange rate available for {code}."
        )
    return Decimal(str(rate))


def convert_money(amount, source_currency: str, target_currency: str,
                  decimals: int = 2) -> Decimal:
    """Convert a real money amount between currencies.

    The single authoritative conversion used for stored money. It raises
    ``CurrencyRateUnavailable`` rather than guessing a rate, and rounds only
    once, at the end, with ROUND_HALF_UP.

    ``decimals`` defaults to 2 for final amounts. Pass a higher value when the
    result is an intermediate value that will be converted again, so rounding
    does not compound.
    """
    value = Decimal(str(amount or 0))
    source = _normalise_currency(source_currency, default="NGN")
    target = _normalise_currency(target_currency, default="NGN")
    if source == target:
        converted = value
    else:
        converted = value / _usd_rate(source) * _usd_rate(target)
    return converted.quantize(
        Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP
    )


def convert_to_ngn(amount, source_currency: str) -> Decimal:
    """Convert a real money amount to NGN once, returning Decimal."""
    return convert_money(amount, source_currency, "NGN")


def convert_from_ngn(amount, target_currency: str) -> Decimal:
    return convert_money(amount, "NGN", target_currency)


def resolve_source_currency(instance, data: dict | None = None) -> str:
    """The currency the stored amounts on ``instance`` are actually in.

    Serializers expose the *display* currency, which made a Nigerian buyer's
    NGN amounts look like USD amounts. Resolution order is: an explicit
    serialized currency, the instance's own currency, its listing's currency,
    then its order's currency.
    """
    data = data or {}

    value = data.get("currency") or getattr(instance, "currency", None)
    if value:
        return str(value).upper().strip()

    listing = getattr(instance, "listing", None)
    if listing is not None:
        value = getattr(listing, "currency", None)
        if value:
            return str(value).upper().strip()

    order = getattr(instance, "order", None)
    if order is not None:
        value = getattr(order, "currency", None)
        if value:
            return str(value).upper().strip()

    store = getattr(instance, "store", None)
    if store is not None:
        value = getattr(store, "currency", None)
        if value:
            return str(value).upper().strip()

    # Wallet transactions carry no currency of their own; the balance they
    # moved is denominated in the wallet's currency.
    wallet = getattr(instance, "wallet", None)
    if wallet is not None:
        value = getattr(wallet, "currency", None)
        if value:
            return str(value).upper().strip()

    return "USD"


class CurrencyConverterMixin(object):
    """Convert declared monetary fields from their stored currency into the
    caller's preferred currency.

    The mixin never relabels an unconverted number. If a rate is unavailable,
    every field is left in the stored currency and ``currency`` says so, with
    ``conversion_error`` explaining why.
    """
    # Define a list of model field names to convert
    monetary_fields = []

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        request = self.context.get("request")
        if not request:
            return ret

        target_curr = get_preferred_currency(request)
        source_curr = resolve_source_currency(instance, ret)

        converted = {}
        failed = False
        for field in self.monetary_fields:
            if field not in ret or ret[field] is None:
                continue
            try:
                converted[field] = float(
                    convert_money(ret[field], source_curr, target_curr)
                )
            except (CurrencyRateUnavailable, InvalidOperation, TypeError, ValueError):
                failed = True
                break

        if failed:
            ret["currency"] = source_curr
            ret["currency_symbol"] = CURRENCY_SYMBOLS.get(
                source_curr, source_curr
            )
            ret["conversion_error"] = (
                "Exchange rates are unavailable; amounts are shown in "
                f"{source_curr}."
            )
        else:
            ret.update(converted)
            ret["currency"] = target_curr
            ret["currency_symbol"] = CURRENCY_SYMBOLS.get(
                target_curr, target_curr
            )

        ret["source_currency"] = source_curr
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
