"""Move money between accounts."""
import uuid

from .accounts import balance, require
from .storage import Store

DEFAULT_FEE_CENTS = 25
FEE_ACCOUNT = "fees"


class InsufficientFunds(Exception):
    pass


def transfer(store: Store, source: str, target: str, amount_cents: int,
             fee_cents: int | None = None, memo: str = "") -> str:
    """Move amount_cents from source to target. fee_cents=None charges the default fee;
    0 means no fee (internal transfers)."""
    if amount_cents <= 0:
        raise ValueError("amount must be positive")
    require(store, source)
    require(store, target)
    fee = DEFAULT_FEE_CENTS if fee_cents is None else fee_cents
    if balance(store, source) < amount_cents + fee:
        raise InsufficientFunds(source)
    txn = uuid.uuid4().hex
    lines = [(source, -(amount_cents + fee)), (target, amount_cents)]
    if fee:
        lines.append((FEE_ACCOUNT, fee))
    store.post(txn, lines, memo)
    return txn
