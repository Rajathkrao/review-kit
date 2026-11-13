# Python checklist

Defects that pass tests and type checks and still break in production. Apply the sections the
change touches. Each item is a lead: report it only with a trigger in this code.

## Language traps
- Mutable default argument (`def f(x=[])`, `dict`, `set`, a dataclass field without
  `default_factory`): state leaks across calls.
- Late-binding closures in loops (`lambda: i`, callbacks built in a `for`): all see the last value.
- `is` vs `==` on ints, strings or literals; `if x:` where `0`, `""` or `[]` is a valid value.
- Mutating a list or dict while iterating it; a generator consumed twice; `zip` silently
  truncating unequal inputs (no `strict=True`).
- `__eq__` without `__hash__` on objects kept in sets or dict keys; mutable objects used as keys.
- `except Exception` / bare `except` around too much; `except` that also catches
  `asyncio.CancelledError` (Python < 3.8) or swallows `KeyboardInterrupt`; `raise X` in an
  `except` without `from err` losing the cause; `return` in `finally` swallowing the exception.
- Integer vs float division (`/` on cents), `round()` banker's rounding, float money; use
  integer cents or `Decimal` with an explicit rounding mode.
- `datetime.now()` / `utcnow()` naive datetimes compared with aware ones (TypeError) or stored
  as if UTC; `date.today()` in the server's zone; DST gaps; `timedelta(days=30)` as "a month".
- String handling: `str.strip("abc")` strips characters, not a suffix (`removesuffix`);
  `split()` vs `split(" ")`; encoding left to the locale in `open()`.
- Import-time side effects (network, DB, env reads at import); circular imports hidden by a
  local import.

## async / concurrency
- Blocking calls inside `async def`: `time.sleep`, `requests`, `urllib`, sync DB drivers, file
  I/O, CPU-heavy loops. They stall every request on the loop. Use `await asyncio.sleep`,
  `asyncio.to_thread`, an async client.
- Missing `await` (coroutine never runs; truthy coroutine object in an `if`).
- `asyncio.create_task` without keeping a reference (task can be garbage-collected) or without
  observing its exception (silent failure); `gather` without `return_exceptions` cancelling siblings.
- Check-then-act across an `await` or between two queries: another request runs in between.
  Idempotency needs a unique constraint, `INSERT ... ON CONFLICT`, `select_for_update` or a lock.
- Shared mutable module/class state across threads, workers or requests; per-process caches that
  must be shared; `threading.Lock` used in async code.
- Celery/RQ/background jobs: retried tasks that aren't idempotent; task args that aren't
  serializable; `acks_late` without idempotency.

## Data and ORMs
- SQL built with f-strings, `%` or `+` (injection); `execute(f"...")`; SQLAlchemy `text()` with
  interpolation; Django `.raw()` / `.extra()` with user input.
- N+1 queries: a query inside a loop over rows; Django FK access without `select_related` /
  `prefetch_related`; SQLAlchemy lazy loading in a loop or after the session closed.
- Transactions: several writes that must succeed together outside `transaction.atomic()` /
  `session.begin()`; external calls (payments, email) inside a transaction that can roll back
  after the side effect; commit missing on a path.
- Django: `queryset.update()` / `bulk_create` skipping `save()` signals and validation;
  `get()` raising `DoesNotExist` / `MultipleObjectsReturned`; querysets evaluated twice.
- Migrations: a non-null column without a default on a populated table; a data migration that
  imports models directly instead of `apps.get_model`; a rename that drops data; a long lock
  (adding an index without `CONCURRENTLY` on a big table); code that needs the new column
  deployed before the migration runs.
- Pydantic: v1 vs v2 API mixed (`.dict()` vs `.model_dump()`, validators); `Optional[x]`
  without a default being required in v2; mutable defaults on models.

## Web frameworks
- FastAPI: a sync `def` endpoint doing slow I/O is fine (threadpool), but an `async def` endpoint
  doing blocking I/O is not; dependencies with side effects run per request; response models
  leaking fields; missing auth dependency on a new route.
- Flask/Django: user input reaching templates with `|safe` / `mark_safe`; CSRF exemptions;
  `request.args` trusted for ids without an ownership check (IDOR); open redirects via `next`.
- HTTP clients: `requests` / `httpx` without a timeout (hangs forever); `verify=False`;
  retrying non-idempotent POSTs.

## Security
- `subprocess` with `shell=True` or a string built from input; `os.system`; `eval` / `exec`.
- `pickle`, `yaml.load` without `SafeLoader`, `marshal`, `shelve` on untrusted data.
- Paths: `os.path.join(base, user_input)` where an absolute input replaces the base;
  `Path(base) / name` without checking it stays inside `base`; zip/tar extraction without
  member checks (zip slip).
- `random` for tokens or passwords (use `secrets`); comparing secrets with `==` (use
  `hmac.compare_digest`); secrets or PII in logs and exception messages.
- `assert` used for validation (stripped with `python -O`).

## Packaging and APIs
- A public function, class, CLI flag or config key removed or changed without a deprecation
  path; a changed default; a new required argument; changed return type or raised exception.
- New dependency for a few lines the stdlib covers; a dependency added to code but not to
  `pyproject.toml` / `requirements`; version pins that conflict.
- Type hints that lie (`-> int` returning `None` on a path); `Optional` returned and not handled
  by callers.

## Tests
- Tests that cannot fail: no assert, `assert mock.called` only, asserting on the mock's own
  return, `pytest.raises(Exception)` around too much, broad `try/except` in the test.
- Time, randomness and ordering not controlled (flaky); tests that hit the network.
- Fixtures shared and mutated across tests (`scope="module"` with mutable state).
