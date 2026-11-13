# ledger

Small double-entry ledger used by the finance back office.

- Python 3.11+. Standard library only (sqlite3, decimal, csv).
- Amounts are stored as integers in minor units (cents). Never use float for money.
- Design decisions live in `docs/adr/`. A change that implements an ADR must follow it.
- Tests: `python -m pytest -q`.
