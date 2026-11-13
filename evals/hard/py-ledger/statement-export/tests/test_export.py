import csv
import io

import pytest

from ledger.accounts import UnknownAccount
from ledger.export import HEADER, _safe_text, export_statement


def rows(store, account):
    buf = io.StringIO()
    n = export_statement(store, account, buf)
    parsed = list(csv.reader(io.StringIO(buf.getvalue())))
    assert len(parsed) == n + 2
    assert parsed[-1][1] == "TOTAL"
    return parsed[:-1]


def test_running_balance(store):
    store.post("t1", [("cash", 150_000), ("suspense", -150_000)], memo="salary")
    store.post("t2", [("cash", -2_550), ("suspense", 2_550)], memo="groceries, weekly")
    header, first, second = rows(store, "cash")
    assert header == HEADER
    assert first[2:] == ["1500.00", "1500.00", "salary"]
    assert second[2:] == ["-25.50", "1474.50", "groceries, weekly"]


@pytest.mark.parametrize("memo,expected", [
    ("=HYPERLINK(\"http://x\")", "'=HYPERLINK(\"http://x\")"),
    ("+1", "'+1"),
    ("-1", "'-1"),
    ("@SUM(A1)", "'@SUM(A1)"),
    ("rent", "rent"),
    ("", ""),
])
def test_safe_text(memo, expected):
    assert _safe_text(memo) == expected


def test_negative_amounts_stay_numbers(store):
    store.post("t", [("cash", -500), ("suspense", 500)], memo="=cmd")
    _, row = rows(store, "cash")
    assert row[2] == "-5.00"
    assert row[4] == "'=cmd"


def test_closing_total(store):
    store.post("t1", [("cash", 1_000), ("suspense", -1_000)], memo="a")
    store.post("t2", [("cash", -250), ("suspense", 250)], memo="b")
    buf = io.StringIO()
    export_statement(store, "cash", buf)
    last = list(csv.reader(io.StringIO(buf.getvalue())))[-1]
    assert last == ["", "TOTAL", "", "7.50", ""]


def test_empty_account_has_header_and_zero_total(store):
    buf = io.StringIO()
    assert export_statement(store, "cash", buf) == 0
    assert list(csv.reader(io.StringIO(buf.getvalue()))) == [HEADER, ["", "TOTAL", "", "0.00", ""]]


def test_unknown_account(store):
    with pytest.raises(UnknownAccount):
        export_statement(store, "nope", io.StringIO())
