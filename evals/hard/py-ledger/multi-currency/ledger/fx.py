"""Currency conversion (ADR 0003)."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TextIO

from .currencies import minor_units
from .money import Money


class MissingRate(LookupError):
    pass


@dataclass
class RateTable:
    """Mid-market rates: one unit of `base` buys `rate` units of `quote`."""
    rates: dict[tuple[str, str], Decimal] = field(default_factory=dict)
    as_of: str = ""

    def set(self, base: str, quote: str, rate: Decimal | str) -> None:
        r = Decimal(rate)
        if r <= 0:
            raise ValueError(f"rate must be positive: {base}/{quote}={rate}")
        self.rates[(base.upper(), quote.upper())] = r

    def rate(self, base: str, quote: str) -> Decimal:
        base, quote = base.upper(), quote.upper()
        if base == quote:
            return Decimal(1)
        if (base, quote) in self.rates:
            return self.rates[(base, quote)]
        if (quote, base) in self.rates:
            return Decimal(1) / self.rates[(quote, base)]
        raise MissingRate(f"{base}/{quote}")

    @classmethod
    def load_csv(cls, fh: TextIO) -> RateTable:
        """Rows of base,quote,rate[,as_of]."""
        table = cls()
        for row in csv.DictReader(fh):
            table.set(row["base"], row["quote"], row["rate"])
            table.as_of = row.get("as_of") or table.as_of
        return table


def convert(money: Money, to: str, table: RateTable) -> Money:
    """Convert to another currency, rounded to the target's minor units."""
    if money.currency == to.upper():
        return money
    rate = table.rate(money.currency, to)
    value = round(money.to_major() * float(rate), minor_units(to))
    return Money.from_major(value, to)
