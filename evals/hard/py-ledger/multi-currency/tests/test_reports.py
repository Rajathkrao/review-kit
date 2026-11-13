from ledger.money import Money
from ledger.reports import render, statement


def test_statement_totals_per_currency(store):
    store.post("a", [("cash", Money(500)), ("suspense", Money(-500))], memo="salary")
    store.post("b", [("cash", Money(-200)), ("suspense", Money(200))], memo="rent")
    stmts = statement(store, "cash")
    assert [s.currency for s in stmts] == ["USD"]
    assert stmts[0].total == Money(300)
    assert "3.00" in render(stmts)


def test_statement_filter(store):
    store.post("a", [("cash", Money(500)), ("suspense", Money(-500))], memo="salary")
    store.post("b", [("cash", Money(-200)), ("suspense", Money(200))], memo="rent")
    (st,) = statement(store, "cash", memo_filter="RENT")
    assert st.total == Money(-200)


def test_empty_statement(store):
    assert statement(store, "savings") == []
    assert render([]) == "No entries"
