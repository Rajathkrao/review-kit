from decimal import Decimal

import pytest

from ledger.currencies import UnknownCurrency
from ledger.money import AmountError, CurrencyMismatch, Money, total


@pytest.mark.parametrize("text,currency,minor", [
    ("12.34", "USD", 1234),
    ("-5", "USD", -500),
    ("1,000.10", "USD", 100010),
    ("1000", "JPY", 1000),
    ("1.234", "KWD", 1234),
    ("0.5", "EUR", 50),
    ("  7.00 ", "GBP", 700),
])
def test_parse(text, currency, minor):
    assert Money.parse(text, currency) == Money(minor, currency)


@pytest.mark.parametrize("text,currency", [
    ("1.001", "USD"),
    ("1.5", "JPY"),
    ("1.2345", "KWD"),
    ("abc", "USD"),
    ("", "USD"),
])
def test_parse_rejects(text, currency):
    with pytest.raises(AmountError):
        Money.parse(text, currency)


def test_unknown_currency():
    with pytest.raises(UnknownCurrency):
        Money(1, "XXX")


def test_currency_code_is_normalised():
    assert Money(1, "eur").currency == "EUR"


def test_amount_must_be_int():
    with pytest.raises(TypeError):
        Money(1.5, "USD")
    with pytest.raises(TypeError):
        Money(True, "USD")


@pytest.mark.parametrize("minor,currency,text", [
    (123456, "USD", "1,234.56 USD"),
    (-5, "USD", "-0.05 USD"),
    (1000, "JPY", "1,000 JPY"),
    (1234, "KWD", "1.234 KWD"),
    (0, "EUR", "0.00 EUR"),
])
def test_format(minor, currency, text):
    assert Money(minor, currency).format() == text


def test_format_without_code():
    assert Money(150, "USD").format(with_code=False) == "1.50"


def test_arithmetic():
    assert Money(100) + Money(25) == Money(125)
    assert Money(100) - Money(125) == Money(-25)
    assert -Money(5) == Money(-5)
    assert abs(Money(-5)) == Money(5)


def test_comparisons():
    assert Money(1) < Money(2)
    assert Money(2) >= Money(2)
    assert not Money(3) <= Money(2)


def test_mixing_currencies_is_an_error():
    with pytest.raises(CurrencyMismatch):
        Money(1, "USD") + Money(1, "EUR")
    with pytest.raises(CurrencyMismatch):
        Money(1, "USD") < Money(1, "EUR")


def test_mixing_with_int_is_an_error():
    with pytest.raises(TypeError):
        Money(1) + 1


def test_truthiness():
    assert Money(1)
    assert not Money(0)


def test_total():
    assert total([Money(1), Money(2), Money(3)], "USD") == Money(6)
    assert total([], "EUR") == Money(0, "EUR")


def test_from_major():
    assert Money.from_major(Decimal("12.34"), "USD") == Money(1234)
    assert Money.from_major(Decimal("500"), "JPY") == Money(500, "JPY")


def test_to_major():
    assert Money(1234).to_major() == 12.34
    assert Money(500, "JPY").to_major() == 500
