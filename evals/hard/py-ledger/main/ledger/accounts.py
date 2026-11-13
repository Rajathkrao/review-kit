"""Account helpers."""
from .storage import Store

KINDS = ("asset", "liability", "income", "expense")


class UnknownAccount(KeyError):
    pass


def open_account(store: Store, account_id: str, name: str, kind: str = "asset") -> None:
    if kind not in KINDS:
        raise ValueError(f"unknown account kind {kind!r}")
    store.add_account(account_id, name, kind)


def require(store: Store, account_id: str) -> None:
    if not store.account_exists(account_id):
        raise UnknownAccount(account_id)


def balance(store: Store, account_id: str) -> int:
    require(store, account_id)
    return store.balance_cents(account_id)
