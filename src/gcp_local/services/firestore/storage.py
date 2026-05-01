"""Firestore storage. In-memory implementation; JSON-on-disk lands in Task 14."""

import asyncio
from collections.abc import AsyncIterator
from typing import Protocol

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
    def lock(self, project: str, database: str) -> "asyncio.Lock": ...
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
        return None  # in-memory only; JsonDiskStorage in Task 14 overrides this
