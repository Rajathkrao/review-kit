# shop

Django 5.1 storefront back end. Python 3.12. PostgreSQL in production (READ COMMITTED), SQLite in tests.

- Money is `Decimal` with two places, rounded half up (`orders.money.q`).
- `USE_TZ = True`, store time zone Europe/Berlin. Dates shown to customers are store-local.
- Requests are not wrapped in transactions (`ATOMIC_REQUESTS = False`); use `transaction.atomic` explicitly.
- Feature specs: `docs/`. Tests: `python manage.py test`.
