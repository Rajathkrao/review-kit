import pytest

from ledger.accounts import open_account
from ledger.fx import RateTable
from ledger.money import Money
from ledger.storage import Store


@pytest.fixture
def store():
    s = Store()
    for acc in ("cash", "savings", "fees", "suspense", "fx-clearing"):
        open_account(s, acc, acc.title())
    open_account(s, "eur-cash", "EUR cash", currency="EUR")
    open_account(s, "gbp-cash", "GBP cash", currency="GBP")
    open_account(s, "jpy-cash", "JPY cash", currency="JPY")
    return s


@pytest.fixture
def rates():
    t = RateTable(as_of="2026-08-31")
    t.set("USD", "EUR", "0.9")
    t.set("USD", "GBP", "0.8")
    t.set("USD", "JPY", "150")
    return t


def fund(store, account, amount: Money):
    store.post("seed-" + account, [(account, amount), ("suspense", -amount)], memo="seed")
