# jobs worker

Background job worker for the notifications platform. One asyncio process per pod.

- Python 3.12, asyncio. Handlers are `async def handler(job) -> None` registered by kind.
- All datetimes are timezone-aware UTC (`jobs.clock.utcnow()`); never naive datetimes.
- Never block the event loop: use httpx.AsyncClient, not requests; asyncio.sleep, not time.sleep.
- Behaviour specs live in `docs/`. Tests: `pytest -q` (pytest-asyncio, auto mode).
