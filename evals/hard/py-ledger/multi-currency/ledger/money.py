"""Money: an integer amount in a currency's minor units plus its ISO 4217 code (ADR 0003)."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from . import currencies


class AmountError(ValueError):
    pass


class CurrencyMismatch(TypeError):
    pass


@dataclass(frozen=True, order=False)
class Money:
    amount: int
    currency: str = "USD"

    def __post_init__(self):
        if not isinstance(self.amount, int) or isinstance(self.amount, bool):
            raise TypeError(f"Money amount must be int minor units, got {type(self.amount).__name__}")
        object.__setattr__(self, "currency", currencies.get(self.currency).code)

    # -- construction -------------------------------------------------------------------------
    @classmethod
    def zero(cls, currency: str = "USD") -> Money:
        return cls(0, currency)

    @classmethod
    def parse(cls, text: str, currency: str = "USD") -> Money:
        """Parse '12.34' (or '1,234.5') in major units of `currency`."""
        exp = currencies.minor_units(currency)
        try:
            value = Decimal(text.strip().replace(",", ""))
        except InvalidOperation as exc:
            raise AmountError(f"not an amount: {text!r}") from exc
        minor = value.scaleb(exp)
        if minor != minor.to_integral_value():
            raise AmountError(f"more than {exp} decimals for {currency}: {text!r}")
        return cls(int(minor), currency)

    @classmethod
    def from_major(cls, value: float | Decimal, currency: str) -> Money:
        return cls(int(round(value * 10 ** currencies.minor_units(currency))), currency)

    # -- views --------------------------------------------------------------------------------
    @property
    def minor_units(self) -> int:
        return currencies.minor_units(self.currency)

    def to_major(self) -> float:
        """Amount in major units, for display and charts."""
        return self.amount / 10 ** self.minor_units

    def format(self, with_code: bool = True) -> str:
        exp = self.minor_units
        sign = "-" if self.amount < 0 else ""
        whole, frac = divmod(abs(self.amount), 10 ** exp) if exp else (abs(self.amount), 0)
        text = f"{sign}{whole:,}" + (f".{frac:0{exp}d}" if exp else "")
        return f"{text} {self.currency}" if with_code else text

    def __str__(self) -> str:
        return self.format()

    # -- arithmetic ---------------------------------------------------------------------------
    def _same(self, other: Money) -> None:
        if not isinstance(other, Money):
            raise TypeError(f"cannot combine Money with {type(other).__name__}")
        if other.currency != self.currency:
            raise CurrencyMismatch(f"{self.currency} vs {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._same(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same(other)
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __abs__(self) -> Money:
        return Money(abs(self.amount), self.currency)

    def __lt__(self, other: Money) -> bool:
        self._same(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._same(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._same(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._same(other)
        return self.amount >= other.amount

    def __bool__(self) -> bool:
        return self.amount != 0

    def is_negative(self) -> bool:
        return self.amount < 0


def total(items, currency: str) -> Money:
    """Sum Money values of one currency; an empty input gives zero."""
    acc = Money.zero(currency)
    for m in items:
        acc = acc + m
    return acc
