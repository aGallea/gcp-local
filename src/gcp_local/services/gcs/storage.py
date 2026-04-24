from __future__ import annotations

import asyncio
from typing import Protocol

from gcp_local.services.gcs.models import BucketMeta, ObjectRecord, UploadSession


class BucketNotFound(KeyError):
    pass


class BucketAlreadyExists(Exception):
    pass


class ObjectNotFound(KeyError):
    pass


class ObjectAlreadyExists(Exception):
    pass


class ObjectCollision(Exception):
    """Raised when an object name collides with an existing directory prefix on disk."""


class SessionNotFound(KeyError):
    pass


class GcsStorage(Protocol):
    async def create_bucket(self, bucket: BucketMeta) -> None: ...
    async def get_bucket(self, name: str) -> BucketMeta: ...
    async def list_buckets(self) -> list[BucketMeta]: ...
    async def delete_bucket(self, name: str) -> None: ...

    async def put_object(self, record: ObjectRecord, data: bytes) -> None: ...
    async def get_object(self, bucket: str, name: str) -> ObjectRecord: ...
    async def get_object_bytes(self, bucket: str, name: str) -> bytes: ...
    async def list_objects(
        self,
        bucket: str,
        *,
        prefix: str = "",
        delimiter: str | None = None,
        max_results: int | None = None,
        start_after: str | None = None,
    ) -> list[ObjectRecord]: ...
    async def list_objects_with_prefixes(
        self,
        bucket: str,
        *,
        prefix: str = "",
        delimiter: str | None = None,
        max_results: int | None = None,
        start_after: str | None = None,
    ) -> tuple[list[ObjectRecord], list[str]]: ...
    async def update_object_metadata(self, record: ObjectRecord) -> None: ...
    async def delete_object(self, bucket: str, name: str) -> None: ...

    async def put_session(self, session: UploadSession) -> None: ...
    async def get_session(self, session_id: str) -> UploadSession: ...
    async def append_to_session(self, session_id: str, chunk: bytes) -> None: ...
    async def get_session_bytes(self, session_id: str) -> bytes: ...
    async def delete_session(self, session_id: str) -> None: ...

    async def reset(self) -> None: ...


class InMemoryStorage:
    """All-in-memory GcsStorage implementation."""

    def __init__(self) -> None:
        self._buckets: dict[str, BucketMeta] = {}
        self._objects: dict[tuple[str, str], tuple[ObjectRecord, bytes]] = {}
        self._sessions: dict[str, tuple[UploadSession, bytearray]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _bucket_lock(self, bucket: str) -> asyncio.Lock:
        lock = self._locks.get(bucket)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[bucket] = lock
        return lock

    async def create_bucket(self, bucket: BucketMeta) -> None:
        if bucket.name in self._buckets:
            raise BucketAlreadyExists(bucket.name)
        self._buckets[bucket.name] = bucket

    async def get_bucket(self, name: str) -> BucketMeta:
        try:
            return self._buckets[name]
        except KeyError:
            raise BucketNotFound(name) from None

    async def list_buckets(self) -> list[BucketMeta]:
        return [self._buckets[n] for n in sorted(self._buckets)]

    async def delete_bucket(self, name: str) -> None:
        if name not in self._buckets:
            raise BucketNotFound(name)
        for key in list(self._objects):
            if key[0] == name:
                del self._objects[key]
        del self._buckets[name]

    async def put_object(self, record: ObjectRecord, data: bytes) -> None:
        if record.bucket not in self._buckets:
            raise BucketNotFound(record.bucket)
        async with self._bucket_lock(record.bucket):
            self._objects[(record.bucket, record.name)] = (record, data)

    async def get_object(self, bucket: str, name: str) -> ObjectRecord:
        if bucket not in self._buckets:
            raise BucketNotFound(bucket)
        try:
            return self._objects[(bucket, name)][0]
        except KeyError:
            raise ObjectNotFound(name) from None

    async def get_object_bytes(self, bucket: str, name: str) -> bytes:
        if bucket not in self._buckets:
            raise BucketNotFound(bucket)
        try:
            return self._objects[(bucket, name)][1]
        except KeyError:
            raise ObjectNotFound(name) from None

    async def list_objects(
        self,
        bucket: str,
        *,
        prefix: str = "",
        delimiter: str | None = None,
        max_results: int | None = None,
        start_after: str | None = None,
    ) -> list[ObjectRecord]:
        objects, _ = await self.list_objects_with_prefixes(
            bucket,
            prefix=prefix,
            delimiter=delimiter,
            max_results=max_results,
            start_after=start_after,
        )
        return objects

    async def list_objects_with_prefixes(
        self,
        bucket: str,
        *,
        prefix: str = "",
        delimiter: str | None = None,
        max_results: int | None = None,
        start_after: str | None = None,
    ) -> tuple[list[ObjectRecord], list[str]]:
        if bucket not in self._buckets:
            raise BucketNotFound(bucket)
        all_names = sorted(n for (b, n) in self._objects if b == bucket)
        if start_after is not None:
            all_names = [n for n in all_names if n > start_after]
        all_names = [n for n in all_names if n.startswith(prefix)]

        objects: list[ObjectRecord] = []
        prefixes: list[str] = []
        seen_prefixes: set[str] = set()
        for n in all_names:
            if delimiter:
                rest = n[len(prefix) :]
                if delimiter in rest:
                    sub = prefix + rest.split(delimiter, 1)[0] + delimiter
                    if sub not in seen_prefixes:
                        seen_prefixes.add(sub)
                        prefixes.append(sub)
                    continue
            objects.append(self._objects[(bucket, n)][0])
            if max_results is not None and len(objects) >= max_results:
                break
        return objects, prefixes

    async def update_object_metadata(self, record: ObjectRecord) -> None:
        if record.bucket not in self._buckets:
            raise BucketNotFound(record.bucket)
        key = (record.bucket, record.name)
        if key not in self._objects:
            raise ObjectNotFound(record.name)
        _, body = self._objects[key]
        self._objects[key] = (record, body)

    async def delete_object(self, bucket: str, name: str) -> None:
        if bucket not in self._buckets:
            raise BucketNotFound(bucket)
        if (bucket, name) not in self._objects:
            raise ObjectNotFound(name)
        del self._objects[(bucket, name)]

    async def put_session(self, session: UploadSession) -> None:
        self._sessions[session.session_id] = (session, bytearray())

    async def get_session(self, session_id: str) -> UploadSession:
        try:
            return self._sessions[session_id][0]
        except KeyError:
            raise SessionNotFound(session_id) from None

    async def append_to_session(self, session_id: str, chunk: bytes) -> None:
        try:
            sess, buf = self._sessions[session_id]
        except KeyError:
            raise SessionNotFound(session_id) from None
        buf.extend(chunk)
        sess.bytes_received = len(buf)
        self._sessions[session_id] = (sess, buf)

    async def get_session_bytes(self, session_id: str) -> bytes:
        try:
            return bytes(self._sessions[session_id][1])
        except KeyError:
            raise SessionNotFound(session_id) from None

    async def delete_session(self, session_id: str) -> None:
        if session_id not in self._sessions:
            raise SessionNotFound(session_id)
        del self._sessions[session_id]

    async def reset(self) -> None:
        self._buckets.clear()
        self._objects.clear()
        self._sessions.clear()
        self._locks.clear()
