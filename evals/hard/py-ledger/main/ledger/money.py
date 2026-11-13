"""Amounts are integer cents (USD)."""
from decimal import Decimal, InvalidOperation


class AmountError(ValueError):
    pass


def parse_amount(text: str) -> int:
    """Parse '12.34' or '-5' into cents."""
    try:
        value = Decimal(text.strip().replace(",", ""))
    except InvalidOperation as exc:
        raise AmountError(f"not an amount: {text!r}") from exc
    cents = value * 100
    if cents != cents.to_integral_value():
        raise AmountError(f"more than two decimals: {text!r}")
    return int(cents)


def format_cents(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100:,}.{cents % 100:02d}"
