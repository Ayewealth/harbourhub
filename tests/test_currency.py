from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.core.currency import (
    CurrencyRateUnavailable,
    convert_from_ngn,
    convert_to_ngn,
    money,
)


def test_money_rounds_half_up():
    assert money("10.005") == Decimal("10.01")
    assert money(None) == Decimal("0.00")
    assert money(Decimal("2.344")) == Decimal("2.34")


@patch("apps.core.currency.get_exchange_rates")
def test_convert_to_ngn_uses_usd_base(rates):
    rates.return_value = {"USD": 1.0, "NGN": 1500.0, "GBP": 0.5}
    assert convert_to_ngn(Decimal("2.00"), "USD") == Decimal("3000.00")
    # GBP -> USD -> NGN: 2 / 0.5 * 1500
    assert convert_to_ngn(Decimal("2.00"), "GBP") == Decimal("6000.00")


@patch("apps.core.currency.get_exchange_rates")
def test_convert_from_ngn_round_trips(rates):
    rates.return_value = {"USD": 1.0, "NGN": 1500.0}
    assert convert_from_ngn(Decimal("3000.00"), "USD") == Decimal("2.00")


def test_convert_to_ngn_is_a_noop_for_ngn():
    assert convert_to_ngn(Decimal("1234.56"), "NGN") == Decimal("1234.56")


@patch("apps.core.currency.get_exchange_rates")
def test_missing_rate_raises(rates):
    rates.return_value = {"USD": 1.0}
    with pytest.raises(CurrencyRateUnavailable):
        convert_to_ngn(Decimal("10.00"), "XYZ")
