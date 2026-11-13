# ADR 0003: Multi-currency accounts

Status: Accepted (2026-08-20)

## Context

Finance needs to hold EUR and GBP balances next to USD, and to move money between accounts in
different currencies. Today every amount is an `int` of US cents.

## Decision

1. Introduce a `Money` value type: an integer amount in the currency's minor units plus an ISO 4217
   code. Arithmetic between different currencies is an error, never an implicit conversion.
2. Minor units come from the ISO 4217 table (JPY has 0, USD 2, KWD 3). Formatting and parsing use it.
3. Each entry stores its currency. Existing rows are USD.
4. Conversion (`fx.convert`) uses `Decimal` end to end and rounds **half up** to the target
   currency's minor units. Finance reconciles against the bank to the cent, so binary floating point
   must not appear anywhere in a conversion.
5. Transfer fees: `fee=None` means "use the default fee for the source currency". An explicit fee of
   zero is valid and is used for internal transfers between our own accounts; it must not be replaced
   by the default.
6. A transfer is refused when the source account's balance in its currency is below amount + fee.
   The balance check must see every posted entry, including ones posted earlier in the same process.
7. CSV imports gain a `currency` column. The new bank export writes account references as
   `acct:<account-id>`; the importer must accept both `acct:<id>` and a bare `<id>`.
8. Statements list every entry and a closing total, per currency.

## Consequences

Callers that pass bare integers must wrap them in `Money`. Reports group by currency.
