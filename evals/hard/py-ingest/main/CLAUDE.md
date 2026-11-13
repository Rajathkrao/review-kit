# ingest

Partner event ingestion. Partners drop newline-delimited JSON files; workers parse them,
store events per tenant, and roll usage up for billing.

- Python 3.12, standard library + Flask for the small admin API. SQLite locally, same SQL in prod.
- Timestamps are timezone-aware UTC.
- Configuration comes from environment variables (see deploy/ingest.yaml).
- Specs live in `docs/`. Tests: `pytest -q`.
