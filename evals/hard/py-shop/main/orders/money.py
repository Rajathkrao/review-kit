from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def q(value) -> Decimal:
    """Quantize to cents, half up."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)
