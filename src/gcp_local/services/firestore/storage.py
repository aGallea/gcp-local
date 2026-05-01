"""Firestore storage — in-memory and JSON-on-disk implementations."""

from __future__ import annotations

import asyncio
import base64
import json
import math
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from gcp_local.services.firestore.errors import DocumentNotFound
from gcp_local.services.firestore.models import DocumentRecord, IndexRecord, TransactionRecord


class FirestoreStorage(Protocol):
    async def reset(self) -> None: ...
    async def get_document(self, project: str, database: str, path: str) -> DocumentRecord: ...
    async def put_document(self, rec: DocumentRecord) -> None: ...
    async def delete_document(self, project: str, database: str, path: str) -> None: ...
    async def has_document(self, project: str, database: str, path: str) -> bool: ...
    async def next_version(self, project: str, database: str) -> int: ...
    async def current_version(self, project: str, database: str) -> int: ...
    def iter_collection(
        self,
        project: str,
        database: str,
        collection_id: str,
        *,
        all_descendants: bool,
        parent_path: str = "",
    ) -> AsyncIterator[DocumentRecord]: ...
    def lock(self, project: str, database: str) -> asyncio.Lock: ...
    async def snapshot(
        self, project: str, database: str
    ) -> None: ...  # no-op for InMemory; fsync for JsonDisk (Task 14)
    # transactions
    async def put_transaction(self, txn: TransactionRecord) -> None: ...
    async def get_transaction(
        self, project: str, database: str, txn_id: str
    ) -> TransactionRecord | None: ...
    async def drop_transaction(self, project: str, database: str, txn_id: str) -> None: ...
    async def all_transactions(self) -> list[TransactionRecord]: ...
    # indexes
    async def put_index(self, project: str, database: str, idx: IndexRecord) -> None: ...
    async def get_index(self, project: str, database: str, name: str) -> IndexRecord | None: ...
    async def list_indexes(self, project: str, database: str) -> list[IndexRecord]: ...
    async def delete_index(self, project: str, database: str, name: str) -> None: ...


class InMemoryStorage:
    def __init__(self) -> None:
        self._documents: dict[tuple[str, str], dict[str, DocumentRecord]] = {}
        self._versions: dict[tuple[str, str], int] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._txns: dict[tuple[str, str, str], TransactionRecord] = {}
        self._indexes: dict[tuple[str, str, str], IndexRecord] = {}

    async def reset(self) -> None:
        self._documents.clear()
        self._versions.clear()
        self._locks.clear()
        self._txns.clear()
        self._indexes.clear()

    async def get_document(self, project: str, database: str, path: str) -> DocumentRecord:
        try:
            return self._documents[(project, database)][path]
        except KeyError as exc:
            raise DocumentNotFound(path) from exc

    async def put_document(self, rec: DocumentRecord) -> None:
        self._documents.setdefault((rec.project, rec.database), {})[rec.path] = rec

    async def delete_document(self, project: str, database: str, path: str) -> None:
        bucket = self._documents.get((project, database), {})
        bucket.pop(path, None)

    async def has_document(self, project: str, database: str, path: str) -> bool:
        return path in self._documents.get((project, database), {})

    async def next_version(self, project: str, database: str) -> int:
        key = (project, database)
        v = self._versions.get(key, 0) + 1
        self._versions[key] = v
        return v

    async def current_version(self, project: str, database: str) -> int:
        return self._versions.get((project, database), 0)

    async def iter_collection(
        self,
        project: str,
        database: str,
        collection_id: str,
        *,
        all_descendants: bool,
        parent_path: str = "",
    ) -> AsyncIterator[DocumentRecord]:
        bucket = self._documents.get((project, database), {})
        for rec in bucket.values():
            segments = rec.path.split("/")
            # Document paths have even segment count: [coll, doc, coll, doc, ...]
            # Collection segments are at even indices: 0, 2, 4, ... (up to second-to-last segment)
            if all_descendants:
                # Match docs where collection_id appears as ANY collection segment.
                # Do not accidentally match a document ID that equals collection_id.
                coll_segs = [segments[i] for i in range(0, len(segments) - 1, 2)]
                if collection_id in coll_segs:
                    yield rec
            else:
                # Direct children: the doc's parent collection path must match exactly.
                doc_collection_path = "/".join(segments[:-1])
                expected = f"{parent_path}/{collection_id}" if parent_path else collection_id
                if doc_collection_path == expected:
                    yield rec

    def lock(self, project: str, database: str) -> asyncio.Lock:
        key = (project, database)
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    async def put_transaction(self, txn: TransactionRecord) -> None:
        self._txns[(txn.project, txn.database, txn.txn_id)] = txn

    async def get_transaction(
        self, project: str, database: str, txn_id: str
    ) -> TransactionRecord | None:
        return self._txns.get((project, database, txn_id))

    async def drop_transaction(self, project: str, database: str, txn_id: str) -> None:
        self._txns.pop((project, database, txn_id), None)

    async def all_transactions(self) -> list[TransactionRecord]:
        return list(self._txns.values())

    async def put_index(self, project: str, database: str, idx: IndexRecord) -> None:
        self._indexes[(project, database, idx.name)] = idx

    async def get_index(self, project: str, database: str, name: str) -> IndexRecord | None:
        return self._indexes.get((project, database, name))

    async def list_indexes(self, project: str, database: str) -> list[IndexRecord]:
        return [v for k, v in self._indexes.items() if k[0] == project and k[1] == database]

    async def delete_index(self, project: str, database: str, name: str) -> None:
        self._indexes.pop((project, database, name), None)

    async def snapshot(self, project: str, database: str) -> None:
        return None  # in-memory only; JsonDiskStorage overrides this


# ---------------------------------------------------------------------------
# JSON codec helpers
# ---------------------------------------------------------------------------

_SCHEMA_VERSION = 1


def _encode_value(v: Any) -> Any:
    """Encode a Python Firestore value to a JSON-safe form."""
    from gcp_local.services.firestore.values import DocumentReference, GeoPoint

    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if math.isnan(v):
            return {"__nan__": True}
        if math.isinf(v):
            return {"__inf__": "+" if v > 0 else "-"}
        return v
    if isinstance(v, str):
        return v
    if isinstance(v, bytes):
        return {"__bytes__": base64.b64encode(v).decode("ascii")}
    if isinstance(v, datetime):
        dt = v if v.tzinfo is not None else v.replace(tzinfo=UTC)
        return {"__datetime__": dt.isoformat()}
    if isinstance(v, DocumentReference):
        return {"__ref__": v.to_resource_name()}
    if isinstance(v, GeoPoint):
        return {"__geopoint__": [v.lat, v.lng]}
    if isinstance(v, list):
        return [_encode_value(x) for x in v]
    if isinstance(v, dict):
        return {k: _encode_value(vv) for k, vv in v.items()}
    raise TypeError(f"cannot encode Firestore value of type {type(v).__name__!r}")


def _decode_value(v: Any) -> Any:
    """Decode a JSON value back to a Python Firestore value."""
    from gcp_local.services.firestore.values import DocumentReference, GeoPoint

    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return v
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return [_decode_value(x) for x in v]
    if isinstance(v, dict):
        if "__nan__" in v:
            return float("nan")
        if "__inf__" in v:
            return float("inf") if v["__inf__"] == "+" else float("-inf")
        if "__bytes__" in v:
            return base64.b64decode(v["__bytes__"])
        if "__datetime__" in v:
            return datetime.fromisoformat(v["__datetime__"])
        if "__ref__" in v:
            return DocumentReference.from_resource_name(v["__ref__"])
        if "__geopoint__" in v:
            lat, lng = v["__geopoint__"]
            return GeoPoint(lat=lat, lng=lng)
        # Plain map (dict with string keys)
        return {k: _decode_value(vv) for k, vv in v.items()}
    raise TypeError(f"cannot decode JSON value of type {type(v).__name__!r}")


def _filename_for(project: str, database: str) -> str:
    """Produce the .json filename for a (project, database) pair."""
    return f"{project}__{database}.json"


def _parse_filename(stem: str) -> tuple[str, str]:
    """Parse a stem like 'my-project__(default)' → ('my-project', '(default)').

    The project is everything before the last '__'; the database is everything
    after.  Both may contain hyphens; neither may contain '__'.
    """
    idx = stem.rfind("__")
    if idx == -1:
        raise ValueError(f"cannot parse Firestore state filename stem: {stem!r}")
    return stem[:idx], stem[idx + 2 :]


# ---------------------------------------------------------------------------
# JsonDiskStorage
# ---------------------------------------------------------------------------


class JsonDiskStorage(InMemoryStorage):
    """Persistent Firestore storage backed by per-database JSON files.

    On startup all existing snapshots are loaded into memory.  Each call to
    ``snapshot(project, database)`` atomically overwrites the corresponding
    file so that process restarts replay the latest committed state.
    """

    def __init__(self, state_dir: Path | str) -> None:
        super().__init__()
        self._state_dir = Path(state_dir) / "firestore"
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._load_all()

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def _load_all(self) -> None:
        for p in self._state_dir.glob("*.json"):
            try:
                project, database = _parse_filename(p.stem)
            except ValueError:
                continue  # skip files that don't match the naming convention
            self._load_file(p, project, database)

    def _load_file(self, path: Path, project: str, database: str) -> None:
        body = json.loads(path.read_text(encoding="utf-8"))
        sv = body.get("schema_version")
        if sv != _SCHEMA_VERSION:
            raise ValueError(
                f"unsupported Firestore state file schema version {sv!r} "
                f"(expected {_SCHEMA_VERSION}) in {path}"
            )

        db_key = (project, database)

        # Documents
        docs_raw: dict[str, Any] = body.get("documents", {})
        for doc_path, raw in docs_raw.items():
            fields = {k: _decode_value(v) for k, v in raw["fields"].items()}
            rec = DocumentRecord(
                project=project,
                database=database,
                path=doc_path,
                fields=fields,
                create_time=datetime.fromisoformat(raw["create_time"]),
                update_time=datetime.fromisoformat(raw["update_time"]),
                version=int(raw["version"]),
            )
            self._documents.setdefault(db_key, {})[doc_path] = rec

        # Recompute version counter from max(record.version)
        bucket = self._documents.get(db_key, {})
        if bucket:
            self._versions[db_key] = max(r.version for r in bucket.values())
        else:
            self._versions.setdefault(db_key, 0)

        # Indexes
        for idx_raw in body.get("indexes", []):
            rec_idx = IndexRecord(
                name=idx_raw["name"],
                fields=idx_raw.get("fields", []),
                state=idx_raw.get("state", "READY"),
            )
            self._indexes[(project, database, rec_idx.name)] = rec_idx

    # ------------------------------------------------------------------
    # Snapshot (atomic write)
    # ------------------------------------------------------------------

    async def snapshot(self, project: str, database: str) -> None:
        db_key = (project, database)
        bucket = self._documents.get(db_key, {})

        documents_out: dict[str, Any] = {}
        for doc_path, rec in bucket.items():
            documents_out[doc_path] = {
                "fields": {k: _encode_value(v) for k, v in rec.fields.items()},
                "create_time": rec.create_time.isoformat(),
                "update_time": rec.update_time.isoformat(),
                "version": rec.version,
            }

        indexes_out: list[dict[str, Any]] = [
            {"name": idx.name, "fields": idx.fields, "state": idx.state}
            for (p, d, _n), idx in self._indexes.items()
            if p == project and d == database
        ]

        body = {
            "schema_version": _SCHEMA_VERSION,
            "documents": documents_out,
            "indexes": indexes_out,
        }

        target = self._state_dir / _filename_for(project, database)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(body, indent=2), encoding="utf-8")
        tmp.replace(target)
