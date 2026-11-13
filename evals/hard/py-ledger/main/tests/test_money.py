import pytest

from ledger.money import AmountError, format_cents, parse_amount


def test_parse():
    assert parse_amount("12.34") == 1234
    assert parse_amount("-5") == -500
    assert parse_amount("1,000.10") == 100010


def test_parse_rejects_three_decimals():
    with pytest.raises(AmountError):
        parse_amount("1.001")


def test_format():
    assert format_cents(123456) == "1,234.56"
    assert format_cents(-5) == "-0.05"
