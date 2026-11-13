import pytest

from ledger.accounts import balance
from ledger.money import CurrencyMismatch, Money
from ledger.transfers import InsufficientFunds, TransferRequest, transfer

from .conftest import fund


def test_transfer_with_default_fee(store):
    fund(store, "cash", Money(10_000))
    transfer(store, TransferRequest("cash", "savings", Money(1_000)))
    assert store.balance("cash", "USD") == Money(10_000 - 1_025)
    assert store.balance("fees", "USD") == Money(25)
    assert store.balance("savings", "USD") == Money(1_000)


def test_explicit_fee(store):
    fund(store, "cash", Money(10_000))
    transfer(store, TransferRequest("cash", "savings", Money(1_000), fee=Money(50)))
    assert store.balance("fees", "USD") == Money(50)


def test_insufficient(store):
    fund(store, "cash", Money(100))
    with pytest.raises(InsufficientFunds):
        transfer(store, TransferRequest("cash", "savings", Money(100)))


def test_amount_must_be_positive(store):
    with pytest.raises(ValueError):
        transfer(store, TransferRequest("cash", "savings", Money(0)))


def test_amount_currency_must_match_source(store):
    fund(store, "cash", Money(10_000))
    with pytest.raises(CurrencyMismatch):
        transfer(store, TransferRequest("cash", "savings", Money(100, "EUR")))


def test_cross_currency(store, rates):
    fund(store, "cash", Money(20_000))
    transfer(store, TransferRequest("cash", "eur-cash", Money(10_000)), rates)
    assert store.balance("eur-cash", "EUR") == Money(9_000, "EUR")
    assert store.balance("cash", "USD") == Money(20_000 - 10_025)
    assert store.balance("fx-clearing", "USD") == Money(10_000)
    assert store.balance("fx-clearing", "EUR") == Money(-9_000, "EUR")


def test_cross_currency_needs_rates(store):
    fund(store, "cash", Money(20_000))
    with pytest.raises(ValueError):
        transfer(store, TransferRequest("cash", "eur-cash", Money(10_000)))


def test_balance_helper(store):
    fund(store, "eur-cash", Money(500, "EUR"))
    assert balance(store, "eur-cash", "EUR") == Money(500, "EUR")
