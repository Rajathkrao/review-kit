import io
from decimal import Decimal

import pytest

from ledger.fx import MissingRate, RateTable, convert
from ledger.money import Money


def test_same_currency_is_identity(rates):
    m = Money(1234, "USD")
    assert convert(m, "USD", rates) is m


@pytest.mark.parametrize("amount,to,expected", [
    (Money(10000, "USD"), "EUR", Money(9000, "EUR")),
    (Money(10000, "USD"), "GBP", Money(8000, "GBP")),
    (Money(100, "USD"), "JPY", Money(150, "JPY")),
    (Money(9000, "EUR"), "USD", Money(10000, "USD")),
    (Money(150, "JPY"), "USD", Money(100, "USD")),
])
def test_convert(rates, amount, to, expected):
    assert convert(amount, to, rates) == expected


def test_inverse_rate(rates):
    assert rates.rate("EUR", "USD") == Decimal(1) / Decimal("0.9")


def test_missing_rate(rates):
    with pytest.raises(MissingRate):
        rates.rate("EUR", "CHF")


def test_rate_must_be_positive():
    with pytest.raises(ValueError):
        RateTable().set("USD", "EUR", "0")


def test_load_csv():
    t = RateTable.load_csv(io.StringIO("base,quote,rate,as_of\nUSD,EUR,0.92,2026-09-01\n"))
    assert t.rate("USD", "EUR") == Decimal("0.92")
    assert t.as_of == "2026-09-01"
