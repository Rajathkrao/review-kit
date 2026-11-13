import io

from ledger.importers.csv_import import import_csv
from ledger.money import Money

CSV = """date,account,counterparty,amount,currency,memo
2026-08-01,savings,ACME,100.00,USD,invoice 7
2026-08-02,acct:savings,ACME,1.50,,refund
2026-08-02,nope,ACME,1.00,,
2026-08-03,savings,ACME,abc,,
2026-08-04,eur-cash,Lufthansa,-250.00,EUR,flight
2026-08-05,savings,ACME,5.00,EUR,wrong currency
"""


def test_import(store):
    res = import_csv(store, io.StringIO(CSV))
    assert res.imported == 3
    assert [line for line, _ in res.skipped] == [4, 5, 7]
    assert store.balance("savings", "USD") == Money(10_150)
    assert store.balance("eur-cash", "EUR") == Money(-25_000, "EUR")


def test_missing_column(store):
    import pytest
    with pytest.raises(ValueError):
        import_csv(store, io.StringIO("date,account\n"))
