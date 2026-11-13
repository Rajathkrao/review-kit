# Ingest v2

Partner volume tripled; v2 adds the pieces we have been doing by hand.

## Requirements

1. **Reader.** Partner files are NDJSON. Malformed lines become dead letters; they never stop a file.
2. **Timestamps.** Some partners send heartbeat rows with an empty `ts`. Rows without a usable
   timestamp still go to the dead-letter table, as today; they must not fail the file.
3. **Duplicates.** Partners resend after timeouts, sometimes several times. Keep only the first event
   for each `(tenant, id)`; events without an `id` are always kept.
4. **Redaction.** Before storage, every email address (any letter case) and card number in an
   event body is replaced with `[email]` / `[card]`. This is a GDPR commitment to partners.
5. **Partitioning.** Each tenant's events go to one partition out of `INGEST_PARTITIONS`. The
   mapping must be the same on every worker and across restarts: downstream consumers read one
   partition each and rely on per-tenant ordering.
6. **Dry run.** `INGEST_DRY_RUN=1` parses and reports without writing events. Production runs with
   `INGEST_DRY_RUN=0` (see deploy/ingest.yaml).
7. **Export.** `export_tenant` returns all of a tenant's events in time order, fetched in pages of
   `INGEST_PAGE_SIZE`.
8. **Billing rollup.** Usage is billed to leaf tenants (tenants that have no child tenants).
   Top-level organisations have no parent.
9. **Admin API.** `GET /stats` and `POST /replay/<file>` behind the `INGEST_API_TOKEN` bearer token.
