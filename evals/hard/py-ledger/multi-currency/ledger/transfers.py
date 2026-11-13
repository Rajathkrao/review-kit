"""Move money between accounts, across currencies when needed (ADR 0003)."""
import uuid
from dataclasses import dataclass

from .accounts import balance, currency_of
from .fx import RateTable, convert
from .money import CurrencyMismatch, Money
from .storage import Store

DEFAULT_FEES = {"USD": 25, "EUR": 25, "GBP": 20, "JPY": 30}
FEE_ACCOUNT = "fees"
FX_CLEARING = "fx-clearing"


class InsufficientFunds(Exception):
    pass


@dataclass(frozen=True)
class TransferRequest:
    source: str
    target: str
    amount: Money
    fee: Money | None = None   # None: default fee for the source currency; Money(0): no fee
    memo: str = ""


def default_fee(currency: str) -> Money:
    return Money(DEFAULT_FEES.get(currency, 0), currency)


def transfer(store: Store, request: TransferRequest, rates: RateTable | None = None) -> str:
    """Post a transfer and return its transaction id."""
    if request.amount.amount <= 0:
        raise ValueError("amount must be positive")
    src_cur = currency_of(store, request.source)
    dst_cur = currency_of(store, request.target)
    if request.amount.currency != src_cur:
        raise CurrencyMismatch(f"amount is {request.amount.currency}, source account is {src_cur}")
    fee = request.fee or default_fee(src_cur)
    if fee.currency != src_cur:
        raise CurrencyMismatch(f"fee is {fee.currency}, source account is {src_cur}")
    if balance(store, request.source, src_cur) < request.amount + fee:
        raise InsufficientFunds(request.source)

    lines: list[tuple[str, Money]] = [(request.source, -(request.amount + fee))]
    if fee:
        lines.append((FEE_ACCOUNT, fee))
    if src_cur == dst_cur:
        lines.append((request.target, request.amount))
    else:
        if rates is None:
            raise ValueError(f"rates required for {src_cur} -> {dst_cur} transfer")
        received = convert(request.amount, dst_cur, rates)
        lines += [(FX_CLEARING, request.amount), (FX_CLEARING, -received), (request.target, received)]
    txn = uuid.uuid4().hex
    store.post(txn, lines, request.memo)
    return txn
