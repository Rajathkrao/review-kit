import pytest

from ledger.accounts import open_account
from ledger.storage import Store


@pytest.fixture
def store():
    s = Store()
    for acc in ("cash", "savings", "fees", "suspense"):
        open_account(s, acc, acc.title())
    return s
