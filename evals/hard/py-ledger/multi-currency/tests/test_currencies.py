import pytest

from ledger import currencies


@pytest.mark.parametrize("code,units", [("USD", 2), ("EUR", 2), ("JPY", 0), ("KWD", 3), ("BHD", 3), ("CLP", 0)])
def test_minor_units(code, units):
    assert currencies.minor_units(code) == units


def test_lookup_is_case_insensitive():
    assert currencies.get("gbp").code == "GBP"


def test_unknown():
    with pytest.raises(currencies.UnknownCurrency):
        currencies.get("ABC")


def test_table_has_unique_codes():
    codes = [c.code for c in currencies._TABLE]
    assert len(codes) == len(set(codes))
    assert all(len(c) == 3 and c.isupper() for c in codes)


def test_numeric_codes_are_three_digits():
    assert all(len(c.numeric) == 3 and c.numeric.isdigit() for c in currencies._TABLE)
