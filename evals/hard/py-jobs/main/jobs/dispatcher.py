"""Sequential dispatcher: claim a batch, run each job, ack / retry / fail."""
import asyncio
import logging
from datetime import timedelta

from .clock import utcnow
from .models import Job
from .registry import lookup

log = logging.getLogger(__name__)


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(2 ** attempts * 5, 3600))


class Dispatcher:
    def __init__(self, queue, batch_size: int = 10, poll_interval: float = 1.0):
        self.queue = queue
        self.batch_size = batch_size
        self.poll_interval = poll_interval
        self._stopping = asyncio.Event()

    def stop(self) -> None:
        self._stopping.set()

    async def run(self) -> None:
        while not self._stopping.is_set():
            jobs = await self.queue.claim(self.batch_size)
            if not jobs:
                await asyncio.sleep(self.poll_interval)
                continue
            for job in jobs:
                if self._stopping.is_set():
                    await self.queue.release(job)
                    continue
                await self._run(job)

    async def _run(self, job: Job) -> None:
        try:
            await asyncio.wait_for(lookup(job.kind)(job), timeout=job.timeout)
        except Exception as exc:
            await self._retry_or_fail(job, exc)
        else:
            await self.queue.ack(job)

    async def _retry_or_fail(self, job: Job, exc: Exception) -> None:
        err = f"{type(exc).__name__}: {exc}"
        if job.attempts + 1 >= job.max_attempts:
            log.error("job %s failed permanently: %s", job.id, err)
            await self.queue.fail(job, err)
        else:
            await self.queue.retry(job, utcnow() + backoff(job.attempts), err)
