"""Tenant -> partition (docs/ingest-v2.md #5)."""


def partition_for(tenant: str, partitions: int) -> int:
    if partitions <= 0:
        raise ValueError("partitions must be positive")
    return hash(tenant) % partitions
