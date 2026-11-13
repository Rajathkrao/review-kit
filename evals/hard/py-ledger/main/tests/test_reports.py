from ledger.reports import render, statement


def test_statement_total(store):
    store.post("a", [("cash", 500), ("suspense", -500)], memo="salary")
    store.post("b", [("cash", -200), ("suspense", 200)], memo="rent")
    st = statement(store, "cash")
    assert len(st.rows) == 2
    assert st.total_cents == 300
    assert "3.00" in render(st)
