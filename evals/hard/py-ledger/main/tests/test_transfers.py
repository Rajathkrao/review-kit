import pytest

from ledger.accounts import balance
from ledger.transfers import InsufficientFunds, transfer


def fund(store, cents):
    store.post("seed", [("cash", cents), ("suspense", -cents)])


def test_transfer_with_default_fee(store):
    fund(store, 10_000)
    transfer(store, "cash", "savings", 1_000)
    assert balance(store, "cash") == 10_000 - 1_025
    assert balance(store, "fees") == 25


def test_internal_transfer_has_no_fee(store):
    fund(store, 1_000)
    transfer(store, "cash", "savings", 1_000, fee_cents=0)
    assert balance(store, "cash") == 0


def test_insufficient(store):
    fund(store, 100)
    with pytest.raises(InsufficientFunds):
        transfer(store, "cash", "savings", 100)
