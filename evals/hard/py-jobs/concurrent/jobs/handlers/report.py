"""report.export: page through the analytics API and upload the rows as CSV."""
import csv
import io

import httpx
import requests

from ..registry import handler

ANALYTICS_URL = "https://analytics.internal/api/events"
UPLOAD_URL = "https://files.internal/upload"
PAGE_SIZE = 500


def fetch_page(account: str, cursor: str | None) -> dict:
    params = {"account": account, "limit": PAGE_SIZE}
    if cursor:
        params["cursor"] = cursor
    resp = requests.get(ANALYTICS_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


@handler("report.export")
async def export(job) -> None:
    account = job.payload["account"]
    rows: list[dict] = []
    cursor = None
    while True:
        page = fetch_page(account, cursor)
        rows.extend(page["items"])
        cursor = page.get("next")
        if not cursor:
            break
    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=sorted(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(UPLOAD_URL, params={"name": f"{account}-events.csv"},
                                 content=buf.getvalue().encode())
        resp.raise_for_status()
