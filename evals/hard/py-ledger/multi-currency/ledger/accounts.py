"""Account helpers."""
from functools import lru_cache

from .currencies import get as get_currency
from .money import Money
from .storage import Store

KINDS = ("asset", "liability", "income", "expense")


class UnknownAccount(KeyError):
    pass


def open_account(store: Store, account_id: str, name: str, kind: str = "asset",
                 currency: str = "USD") -> None:
    if kind not in KINDS:
        raise ValueError(f"unknown account kind {kind!r}")
    store.add_account(account_id, name, kind, get_currency(currency).code)


def require(store: Store, account_id: str) -> None:
    if not store.account_exists(account_id):
        raise UnknownAccount(account_id)


def currency_of(store: Store, account_id: str) -> str:
    require(store, account_id)
    return store.account_currency(account_id)


# Statements and the transfer check ask for the same balances over and over; the SUM over
# entries is the slowest query in the app on large accounts, so keep recent answers.
@lru_cache(maxsize=4096)
def balance(store: Store, account_id: str, currency: str = "USD") -> Money:
    require(store, account_id)
    return store.balance(account_id, currency)
