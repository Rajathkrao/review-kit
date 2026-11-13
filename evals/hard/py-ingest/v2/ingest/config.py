"""Settings from the environment (deploy/ingest.yaml)."""
import os
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Settings:
    dry_run: bool = False
    partitions: int = 16
    api_token: str = ""
    redact: bool = True
    page_size: int = 500
    inbox: str = "/data/inbox"

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Settings":
        return cls(
            dry_run=bool(env.get("INGEST_DRY_RUN", False)),
            partitions=int(env.get("INGEST_PARTITIONS", 16)),
            api_token=env.get("INGEST_API_TOKEN", ""),
            redact=env.get("INGEST_REDACT", "1") != "0",
            page_size=int(env.get("INGEST_PAGE_SIZE", 500)),
            inbox=env.get("INGEST_INBOX", "/data/inbox"),
        )


# Kept for code that still imports the module-level names.
_default = Settings.from_env()
DRY_RUN = _default.dry_run
PARTITIONS = _default.partitions
API_TOKEN = _default.api_token
