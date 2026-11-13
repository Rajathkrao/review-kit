"""Sequential dispatcher: claim a batch, run each job, ack / retry / fail."""
import asyncio
import logging
import time
from datetime import timedelta

from .clock import utcnow
from .models import Job
from .registry import lookup

log = logging.getLogger(__name__)


def fields(job: Job, **more) -> dict:
    """Structured log fields. Keys must not clash with LogRecord attributes (e.g. 'message')."""
    return {"job_id": job.id, "job_kind": job.kind, "attempt": job.attempts + 1, **more}


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


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
        started = time.monotonic()
        try:
            await asyncio.wait_for(lookup(job.kind)(job), timeout=job.timeout)
        except Exception as exc:
            await self._retry_or_fail(job, exc)
        else:
            await self.queue.ack(job)
            log.info("job succeeded", extra=fields(job, duration_ms=_ms(started)))

    async def _retry_or_fail(self, job: Job, exc: Exception) -> None:
        err = f"{type(exc).__name__}: {exc}"
        if job.attempts + 1 >= job.max_attempts:
            log.error("job failed permanently", extra=fields(job, error=err))
            await self.queue.fail(job, err)
        else:
            delay = backoff(job.attempts)
            log.warning("job failed, will retry", extra=fields(job, error=err, retry_in_s=int(delay.total_seconds())))
            await self.queue.retry(job, utcnow() + delay, err)
