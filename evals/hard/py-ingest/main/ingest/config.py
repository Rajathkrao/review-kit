import os

DRY_RUN = os.environ.get("INGEST_DRY_RUN", "0") == "1"
PARTITIONS = int(os.environ.get("INGEST_PARTITIONS", "16"))
API_TOKEN = os.environ.get("INGEST_API_TOKEN", "")
