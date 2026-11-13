"""In-process queue used by tests and the single-node deployment. The Postgres queue has the
same interface (claim / ack / retry / release / fail)."""
import asyncio
from datetime import datetime

from .models import Job


class InMemoryQueue:
    def __init__(self):
        self._ready: list[Job] = []
        self._claimed: dict[str, Job] = {}
        self.done: list[str] = []
        self.failed: list[Job] = []
        self._lock = asyncio.Lock()

    async def put(self, job: Job) -> None:
        async with self._lock:
            self._ready.append(job)

    async def claim(self, limit: int) -> list[Job]:
        async with self._lock:
            batch, self._ready = self._ready[:limit], self._ready[limit:]
            for j in batch:
                self._claimed[j.id] = j
            return batch

    async def ack(self, job: Job) -> None:
        async with self._lock:
            self._claimed.pop(job.id, None)
            self.done.append(job.id)

    async def retry(self, job: Job, run_at: datetime, error: str) -> None:
        async with self._lock:
            self._claimed.pop(job.id, None)
            job.attempts += 1
            job.run_at = run_at
            job.last_error = error
            self._ready.append(job)

    async def release(self, job: Job) -> None:
        """Give a claimed job back untouched (shutdown)."""
        async with self._lock:
            self._claimed.pop(job.id, None)
            self._ready.insert(0, job)

    async def fail(self, job: Job, error: str) -> None:
        async with self._lock:
            self._claimed.pop(job.id, None)
            job.last_error = error
            self.failed.append(job)

    @property
    def claimed(self) -> list[Job]:
        return list(self._claimed.values())
