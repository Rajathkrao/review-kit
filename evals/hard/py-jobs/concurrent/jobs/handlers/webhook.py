"""webhook.deliver: POST the event to the customer's endpoint, signed, with retries."""
import asyncio
import hashlib
import hmac
import json

import httpx

from ..registry import handler

ATTEMPTS = 4


def sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@handler("webhook.deliver")
async def deliver(job) -> None:
    body = json.dumps(job.payload["event"], separators=(",", ":")).encode()
    headers = {"content-type": "application/json",
               "x-signature": sign(job.payload["secret"], body)}
    async with httpx.AsyncClient(timeout=10) as client:
        for attempt in range(ATTEMPTS):
            try:
                resp = await client.post(job.payload["url"], content=body, headers=headers)
                if resp.status_code < 500:
                    resp.raise_for_status()
                    return
            except httpx.HTTPStatusError:
                raise              # 4xx: the customer rejected it, retrying will not help
            except:  # noqa: E722  connection resets and DNS blips are common, keep trying
                pass
            await asyncio.sleep(2 ** attempt)
    raise RuntimeError(f"webhook to {job.payload['url']} failed after {ATTEMPTS} attempts")
