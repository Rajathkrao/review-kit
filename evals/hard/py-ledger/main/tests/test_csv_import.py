import io

from ledger.accounts import balance
from ledger.importers.csv_import import import_csv

CSV = """date,account,counterparty,amount,memo
2026-08-01,cash,ACME,100.00,invoice 7
2026-08-02,nope,ACME,1.00,
2026-08-03,cash,ACME,abc,
"""


def test_import(store):
    res = import_csv(store, io.StringIO(CSV))
    assert res.imported == 1
    assert [line for line, _ in res.skipped] == [3, 4]
    assert balance(store, "cash") == 10_000
