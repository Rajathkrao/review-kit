import io
from datetime import date

import pytest

from ledger.importers.ofx_import import OfxError, import_ofx, parse
from ledger.money import Money

OFX = """OFXHEADER:100
DATA:OFXSGML
VERSION:102

<OFX>
<BANKMSGSRSV1><STMTTRNRS><STMTRS>
<CURDEF>EUR
<BANKACCTFROM><BANKID>123<ACCTID>DE89370400440532013000<ACCTTYPE>CHECKING</BANKACCTFROM>
<BANKTRANLIST>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260801120000<TRNAMT>-42.50<FITID>A1<NAME>Bakery</STMTTRN>
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260802<TRNAMT>1000.00<FITID>A2<NAME>Salary<MEMO>August</STMTTRN>
</BANKTRANLIST>
</STMTRS></STMTTRNRS></BANKMSGSRSV1>
</OFX>
"""

MAP = {"DE89370400440532013000": "eur-cash"}


def test_parse():
    st = parse(io.StringIO(OFX))
    assert st.currency == "EUR"
    assert st.account_id == "DE89370400440532013000"
    assert [t.fitid for t in st.transactions] == ["A1", "A2"]
    assert st.transactions[0].posted == date(2026, 8, 1)
    assert st.transactions[1].memo == "August"


def test_import(store):
    res = import_ofx(store, io.StringIO(OFX), MAP)
    assert (res.imported, res.duplicates) == (2, 0)
    assert store.balance("eur-cash", "EUR") == Money(95_750, "EUR")


def test_reimport_is_idempotent(store):
    import_ofx(store, io.StringIO(OFX), MAP)
    res = import_ofx(store, io.StringIO(OFX), MAP)
    assert (res.imported, res.duplicates) == (0, 2)
    assert store.balance("eur-cash", "EUR") == Money(95_750, "EUR")


def test_currency_must_match_account(store):
    with pytest.raises(OfxError):
        import_ofx(store, io.StringIO(OFX), {"DE89370400440532013000": "cash"})


@pytest.mark.parametrize("bad", ["no ofx here", "<OFX><STMTTRN><FITID>1</OFX>", "<OFX><CURDEF>EUR</OFX>"])
def test_malformed(bad):
    with pytest.raises(OfxError):
        parse(io.StringIO(bad))


def test_missing_field():
    with pytest.raises(OfxError):
        parse(io.StringIO("<OFX><CURDEF>EUR<ACCTID>1<STMTTRN><FITID>1<TRNAMT>1</STMTTRN></OFX>"))
