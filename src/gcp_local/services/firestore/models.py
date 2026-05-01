"""Firestore record dataclasses."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class DocumentRecord:
    project: str
    database: str
    path: str
    fields: dict[str, Any]
    create_time: datetime
    update_time: datetime
    version: int


@dataclass
class TransactionRecord:
    txn_id: str
    project: str
    database: str
    snapshot_version: int
    read_only: bool
    started_at: datetime
    read_set: set[str] = field(default_factory=set)
    read_time: datetime | None = None
    writes: list[Any] = field(default_factory=list)


@dataclass
class IndexRecord:
    name: str
    fields: list[dict[str, Any]]
    state: str = "READY"
