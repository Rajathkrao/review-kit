import httpx

from ..registry import handler

RELAY_URL = "https://relay.internal/send"


@handler("email.send")
async def send_email(job) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(RELAY_URL, json=job.payload)
        resp.raise_for_status()
