"""Export a tenant's events (docs/ingest-v2.md #7)."""
from .store import Store


def export_tenant(store: Store, tenant_id: str, page_size: int = 500) -> list[dict]:
    total = store.count_events(tenant_id)
    pages = total // page_size
    out: list[dict] = []
    for page in range(pages):
        out.extend(store.events_page(tenant_id, limit=page_size, offset=page * page_size))
    return out
