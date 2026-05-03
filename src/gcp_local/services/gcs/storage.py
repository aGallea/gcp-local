from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path
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


class DiskStorage:
    """Disk-backed GcsStorage implementation.

    Layout under `root`:
      <bucket>/<bucket>.meta.json
      <bucket>/objects/<path>          (raw bytes)
      <bucket>/objects/<path>.meta.json
      <bucket>/.uploads/<session_id>/{buffer.bin, session.json}
    """

    _META_SUFFIX = ".meta.json"
    # GCS object names that end in ``/`` (folder placeholders) collide with
    # the nested-directory layout used for normal names like ``logs/01.log``.
    # We encode only the trailing slash on disk so the logical name (on the
    # wire and in JSON metadata) stays unchanged. Internal slashes still map
    # to directories so existing layouts are unaffected.
    _DIR_MARKER_SUFFIX = "%2F"

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, asyncio.Lock] = {}

    def _disk_object_name(self, name: str) -> str:
        if name.endswith("/"):
            return name[:-1] + self._DIR_MARKER_SUFFIX
        return name

    def _logical_object_name(self, disk_rel: str) -> str:
        if disk_rel.endswith(self._DIR_MARKER_SUFFIX):
            return disk_rel[: -len(self._DIR_MARKER_SUFFIX)] + "/"
        return disk_rel

    def _bucket_lock(self, bucket: str) -> asyncio.Lock:
        lock = self._locks.get(bucket)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[bucket] = lock
        return lock

    def _bucket_dir(self, bucket: str) -> Path:
        return self._root / bucket

    def _bucket_meta_path(self, bucket: str) -> Path:
        return self._bucket_dir(bucket) / f"{bucket}{self._META_SUFFIX}"

    def _objects_root(self, bucket: str) -> Path:
        return self._bucket_dir(bucket) / "objects"

    def _object_bytes_path(self, bucket: str, name: str) -> Path:
        return self._objects_root(bucket) / self._disk_object_name(name)

    def _object_meta_path(self, bucket: str, name: str) -> Path:
        return self._objects_root(bucket) / f"{self._disk_object_name(name)}{self._META_SUFFIX}"

    def _uploads_root(self, bucket: str) -> Path:
        return self._bucket_dir(bucket) / ".uploads"

    def _session_dir(self, bucket: str, session_id: str) -> Path:
        return self._uploads_root(bucket) / session_id

    # --- buckets --------------------------------------------------------

    async def create_bucket(self, bucket: BucketMeta) -> None:
        bucket_dir = self._bucket_dir(bucket.name)
        if bucket_dir.exists():
            raise BucketAlreadyExists(bucket.name)
        bucket_dir.mkdir(parents=True)
        self._objects_root(bucket.name).mkdir()
        self._uploads_root(bucket.name).mkdir()
        self._bucket_meta_path(bucket.name).write_text(bucket.model_dump_json())

    async def get_bucket(self, name: str) -> BucketMeta:
        meta_path = self._bucket_meta_path(name)
        if not meta_path.exists():
            raise BucketNotFound(name)
        return BucketMeta.model_validate_json(meta_path.read_text())

    async def list_buckets(self) -> list[BucketMeta]:
        out: list[BucketMeta] = []
        for d in sorted(self._root.iterdir()):
            if d.is_dir():
                meta = d / f"{d.name}{self._META_SUFFIX}"
                if meta.exists():
                    out.append(BucketMeta.model_validate_json(meta.read_text()))
        return out

    async def delete_bucket(self, name: str) -> None:
        bdir = self._bucket_dir(name)
        if not bdir.exists():
            raise BucketNotFound(name)
        shutil.rmtree(bdir)

    # --- objects --------------------------------------------------------

    def _ensure_no_collision(self, bucket: str, name: str) -> None:
        """Walk ancestor segments; if any exists as a file (object), collide.

        Also if `name` itself exists as a directory (because a child object exists), collide.
        """
        root = self._objects_root(bucket)
        parts = name.split("/")
        for i in range(1, len(parts)):
            candidate = root / "/".join(parts[:i])
            if candidate.exists() and candidate.is_file():
                raise ObjectCollision(
                    f"object {'/'.join(parts[:i])!r} exists; cannot write object under that prefix"
                )
        target = root / name
        if target.exists() and target.is_dir():
            raise ObjectCollision(f"cannot write object {name!r}: a directory exists at that path")

    async def put_object(self, record: ObjectRecord, data: bytes) -> None:
        if not self._bucket_dir(record.bucket).exists():
            raise BucketNotFound(record.bucket)
        async with self._bucket_lock(record.bucket):
            self._ensure_no_collision(record.bucket, record.name)
            bytes_path = self._object_bytes_path(record.bucket, record.name)
            bytes_path.parent.mkdir(parents=True, exist_ok=True)
            bytes_path.write_bytes(data)
            meta_path = self._object_meta_path(record.bucket, record.name)
            meta_path.write_text(record.model_dump_json())

    async def get_object(self, bucket: str, name: str) -> ObjectRecord:
        if not self._bucket_dir(bucket).exists():
            raise BucketNotFound(bucket)
        meta_path = self._object_meta_path(bucket, name)
        if not meta_path.exists():
            raise ObjectNotFound(name)
        return ObjectRecord.model_validate_json(meta_path.read_text())

    async def get_object_bytes(self, bucket: str, name: str) -> bytes:
        if not self._bucket_dir(bucket).exists():
            raise BucketNotFound(bucket)
        bytes_path = self._object_bytes_path(bucket, name)
        if not bytes_path.exists() or not bytes_path.is_file():
            raise ObjectNotFound(name)
        return bytes_path.read_bytes()

    async def _walk_objects(self, bucket: str) -> list[str]:
        root = self._objects_root(bucket)
        names: list[str] = []
        if not root.exists():
            return names
        for p in root.rglob("*"):
            if p.is_file() and not p.name.endswith(self._META_SUFFIX):
                rel = p.relative_to(root).as_posix()
                names.append(self._logical_object_name(rel))
        return sorted(names)

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
        if not self._bucket_dir(bucket).exists():
            raise BucketNotFound(bucket)
        names = await self._walk_objects(bucket)
        if start_after is not None:
            names = [n for n in names if n > start_after]
        names = [n for n in names if n.startswith(prefix)]
        objects: list[ObjectRecord] = []
        prefixes: list[str] = []
        seen_prefixes: set[str] = set()
        for n in names:
            if delimiter:
                rest = n[len(prefix) :]
                if delimiter in rest:
                    sub = prefix + rest.split(delimiter, 1)[0] + delimiter
                    if sub not in seen_prefixes:
                        seen_prefixes.add(sub)
                        prefixes.append(sub)
                    continue
            meta = self._object_meta_path(bucket, n)
            objects.append(ObjectRecord.model_validate_json(meta.read_text()))
            if max_results is not None and len(objects) >= max_results:
                break
        return objects, prefixes

    async def update_object_metadata(self, record: ObjectRecord) -> None:
        if not self._bucket_dir(record.bucket).exists():
            raise BucketNotFound(record.bucket)
        meta_path = self._object_meta_path(record.bucket, record.name)
        if not meta_path.exists():
            raise ObjectNotFound(record.name)
        meta_path.write_text(record.model_dump_json())

    async def delete_object(self, bucket: str, name: str) -> None:
        if not self._bucket_dir(bucket).exists():
            raise BucketNotFound(bucket)
        meta_path = self._object_meta_path(bucket, name)
        bytes_path = self._object_bytes_path(bucket, name)
        if not meta_path.exists():
            raise ObjectNotFound(name)
        bytes_path.unlink(missing_ok=True)
        meta_path.unlink()

    # --- sessions -------------------------------------------------------

    async def put_session(self, session: UploadSession) -> None:
        if not self._bucket_dir(session.bucket).exists():
            raise BucketNotFound(session.bucket)
        sess_dir = self._session_dir(session.bucket, session.session_id)
        sess_dir.mkdir(parents=True, exist_ok=True)
        (sess_dir / "session.json").write_text(session.model_dump_json())
        (sess_dir / "buffer.bin").write_bytes(b"")

    def _find_session_dir(self, session_id: str) -> Path | None:
        for bucket_dir in self._root.iterdir():
            if not bucket_dir.is_dir():
                continue
            candidate = bucket_dir / ".uploads" / session_id
            if candidate.exists():
                return candidate
        return None

    async def get_session(self, session_id: str) -> UploadSession:
        sdir = self._find_session_dir(session_id)
        if sdir is None:
            raise SessionNotFound(session_id)
        return UploadSession.model_validate_json((sdir / "session.json").read_text())

    async def append_to_session(self, session_id: str, chunk: bytes) -> None:
        sdir = self._find_session_dir(session_id)
        if sdir is None:
            raise SessionNotFound(session_id)
        buf = sdir / "buffer.bin"
        with buf.open("ab") as f:
            f.write(chunk)
        sess = UploadSession.model_validate_json((sdir / "session.json").read_text())
        sess.bytes_received = buf.stat().st_size
        (sdir / "session.json").write_text(sess.model_dump_json())

    async def get_session_bytes(self, session_id: str) -> bytes:
        sdir = self._find_session_dir(session_id)
        if sdir is None:
            raise SessionNotFound(session_id)
        return (sdir / "buffer.bin").read_bytes()

    async def delete_session(self, session_id: str) -> None:
        sdir = self._find_session_dir(session_id)
        if sdir is None:
            raise SessionNotFound(session_id)
        shutil.rmtree(sdir)

    async def gc_stale_sessions(self, max_age_seconds: float) -> int:
        """Delete sessions whose dir mtime is older than `max_age_seconds`. Returns count deleted."""
        now = time.time()
        count = 0
        for bucket_dir in self._root.iterdir():
            if not bucket_dir.is_dir():
                continue
            uploads = bucket_dir / ".uploads"
            if not uploads.exists():
                continue
            for sdir in uploads.iterdir():
                if not sdir.is_dir():
                    continue
                age = now - sdir.stat().st_mtime
                if age > max_age_seconds:
                    shutil.rmtree(sdir)
                    count += 1
        return count

    async def reset(self) -> None:
        for child in list(self._root.iterdir()):
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        self._locks.clear()
