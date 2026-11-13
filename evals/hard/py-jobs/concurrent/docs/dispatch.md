# Concurrent dispatch

The worker ran one job at a time; webhook and report jobs wait on slow remote APIs, so the
queue backs up at peak. This change runs jobs concurrently.

## Requirements

1. Up to `concurrency` jobs (default 20) run at once on one event loop.
2. Jobs with `run_at` in the future are not claimed until they are due. Retries are scheduled
   with exponential backoff through `run_at`.
3. A job that exceeds its `timeout` is cancelled and retried like any other failure.
4. Shutdown (SIGTERM): stop claiming, wait up to `drain_timeout` (30 s) for running jobs to
   finish, then cancel the rest and give them back to the queue with `release`. No claimed job
   may be left behind when `run()` returns; Kubernetes kills the pod right after.
5. New job kinds: `webhook.deliver` (POST to a customer URL, retried on network errors) and
   `report.export` (pages through the analytics API and uploads a CSV).
6. Kinds renamed in 2.0 still arrive from old producers: `mail` → `email.send`,
   `hook` → `webhook.deliver`, `export` → `report.export`. Each must keep working.
