import sqlite3

import pytest

from ledger.money import Money
from ledger.storage import Store, UnbalancedTransaction

OLD_SCHEMA = """
CREATE TABLE accounts (id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL);
CREATE TABLE entries (id INTEGER PRIMARY KEY AUTOINCREMENT, txn_id TEXT NOT NULL,
    account_id TEXT NOT NULL, amount_cents INTEGER NOT NULL, memo TEXT NOT NULL DEFAULT '',
    posted_at TEXT NOT NULL);
CREATE INDEX entries_account ON entries(account_id);
INSERT INTO accounts VALUES ('cash', 'Cash', 'asset');
INSERT INTO entries (txn_id, account_id, amount_cents, posted_at) VALUES ('t', 'cash', 1234, '2026-01-01');
"""


def test_migrates_old_database(tmp_path):
    path = tmp_path / "old.sqlite"
    db = sqlite3.connect(path)
    db.executescript(OLD_SCHEMA)
    db.close()
    store = Store(str(path))
    assert store.balance("cash", "USD") == Money(1234)
    assert store.account_currency("cash") == "USD"
    assert store.entries("cash")[0].amount == Money(1234, "USD")


def test_post_must_balance_per_currency(store):
    with pytest.raises(UnbalancedTransaction):
        store.post("x", [("cash", Money(100)), ("eur-cash", Money(-100, "EUR"))])


def test_iter_entries_filters_currency(store):
    store.post("x", [("fx-clearing", Money(100)), ("cash", Money(-100))])
    store.post("y", [("fx-clearing", Money(90, "EUR")), ("eur-cash", Money(-90, "EUR"))])
    assert [e.amount for e in store.iter_entries("fx-clearing", "EUR")] == [Money(90, "EUR")]
    assert store.currencies_of("fx-clearing") == ["EUR", "USD"]
