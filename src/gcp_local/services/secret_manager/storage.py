from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, TypeVar

import google_crc32c

from gcp_local.services.gcs.ids import rfc3339_now  # reuse helper
from gcp_local.services.secret_manager.models import (
    SecretRecord,
    SecretVersion,
    SecretVersionState,
)


class SecretNotFound(KeyError):
    pass


class SecretAlreadyExists(Exception):
    pass


class VersionNotFound(KeyError):
    pass


class InvalidStateTransition(Exception):
    pass


class SecretManagerStorage(Protocol):
    async def create_secret(self, record: SecretRecord) -> None: ...
    async def get_secret(self, project: str, secret_id: str) -> SecretRecord: ...
    async def list_secrets(
        self,
        project: str,
        *,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> tuple[list[SecretRecord], str | None]: ...
    async def update_secret(self, record: SecretRecord) -> None: ...
    async def delete_secret(self, project: str, secret_id: str) -> None: ...

    async def add_version(self, project: str, secret_id: str, payload: bytes) -> SecretVersion: ...
    async def get_version(self, project: str, secret_id: str, version_id: int) -> SecretVersion: ...
    async def list_versions(
        self,
        project: str,
        secret_id: str,
        *,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> tuple[list[SecretVersion], str | None]: ...
    async def update_version_state(
        self,
        project: str,
        secret_id: str,
        version_id: int,
        new_state: SecretVersionState,
    ) -> SecretVersion: ...

    async def reset(self) -> None: ...


T = TypeVar("T")


def _encode_token(cursor: str) -> str:
    return base64.urlsafe_b64encode(cursor.encode()).decode()


def _decode_token(token: str) -> str:
    return base64.urlsafe_b64decode(token.encode()).decode()


def _paginate[T](
    items: list[T],
    key: Callable[[T], str],
    page_size: int | None,
    page_token: str | None,
) -> tuple[list[T], str | None]:
    if page_token:
        cursor = _decode_token(page_token)
        items = [x for x in items if key(x) > cursor]
    if page_size is None:
        return items, None
    page_size = min(page_size, 250)
    if len(items) > page_size:
        page = items[:page_size]
        return page, _encode_token(key(page[-1]))
    return items, None


def _validate_transition(current: SecretVersionState, new_state: SecretVersionState) -> None:
    if current == SecretVersionState.DESTROYED and new_state != SecretVersionState.DESTROYED:
        raise InvalidStateTransition(f"cannot transition from DESTROYED to {new_state.value}")


class InMemoryStorage:
    """All-in-memory SecretManagerStorage implementation."""

    def __init__(self) -> None:
        self._secrets: dict[tuple[str, str], SecretRecord] = {}
        self._lock = asyncio.Lock()

    async def create_secret(self, record: SecretRecord) -> None:
        key = (record.project, record.secret_id)
        if key in self._secrets:
            raise SecretAlreadyExists(record.secret_id)
        self._secrets[key] = record

    async def get_secret(self, project: str, secret_id: str) -> SecretRecord:
        try:
            return self._secrets[(project, secret_id)]
        except KeyError:
            raise SecretNotFound(secret_id) from None

    async def list_secrets(
        self,
        project: str,
        *,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> tuple[list[SecretRecord], str | None]:
        all_in_project = sorted(
            [r for (p, _), r in self._secrets.items() if p == project],
            key=lambda r: r.secret_id,
        )
        return _paginate(all_in_project, lambda r: r.secret_id, page_size, page_token)

    async def update_secret(self, record: SecretRecord) -> None:
        key = (record.project, record.secret_id)
        if key not in self._secrets:
            raise SecretNotFound(record.secret_id)
        self._secrets[key] = record

    async def delete_secret(self, project: str, secret_id: str) -> None:
        key = (project, secret_id)
        if key not in self._secrets:
            raise SecretNotFound(secret_id)
        del self._secrets[key]

    async def add_version(self, project: str, secret_id: str, payload: bytes) -> SecretVersion:
        async with self._lock:
            rec = await self.get_secret(project, secret_id)
            next_id = (max((v.id for v in rec.versions), default=0)) + 1
            version = SecretVersion(
                id=next_id,
                state=SecretVersionState.ENABLED,
                create_time=rfc3339_now(),
                destroy_time=None,
                payload=payload,
                data_crc32c=int(google_crc32c.value(payload)),
            )
            rec.versions.append(version)
            rec.versions.sort(key=lambda v: v.id)
            return version

    async def get_version(self, project: str, secret_id: str, version_id: int) -> SecretVersion:
        rec = await self.get_secret(project, secret_id)
        v = rec.get_version(version_id)
        if v is None:
            raise VersionNotFound(version_id)
        return v

    async def list_versions(
        self,
        project: str,
        secret_id: str,
        *,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> tuple[list[SecretVersion], str | None]:
        rec = await self.get_secret(project, secret_id)
        items = sorted(rec.versions, key=lambda v: v.id)
        return _paginate(items, lambda v: str(v.id).zfill(20), page_size, page_token)

    async def update_version_state(
        self,
        project: str,
        secret_id: str,
        version_id: int,
        new_state: SecretVersionState,
    ) -> SecretVersion:
        async with self._lock:
            v = await self.get_version(project, secret_id, version_id)
            _validate_transition(v.state, new_state)
            v.state = new_state
            if new_state == SecretVersionState.DESTROYED:
                v.payload = b""
                v.destroy_time = rfc3339_now()
            return v

    async def reset(self) -> None:
        self._secrets.clear()


def _serialize_record(r: SecretRecord) -> dict[str, Any]:
    return {
        "project": r.project,
        "secret_id": r.secret_id,
        "labels": dict(r.labels),
        "annotations": dict(r.annotations),
        "create_time": r.create_time,
        "versions": [
            {
                "id": v.id,
                "state": v.state.value,
                "create_time": v.create_time,
                "destroy_time": v.destroy_time,
                "payload_b64": base64.b64encode(v.payload).decode("ascii"),
                "data_crc32c": v.data_crc32c,
            }
            for v in r.versions
        ],
    }


def _deserialize_record(body: dict[str, Any]) -> SecretRecord:
    versions = [
        SecretVersion(
            id=v["id"],
            state=SecretVersionState(v["state"]),
            create_time=v["create_time"],
            destroy_time=v["destroy_time"],
            payload=base64.b64decode(v.get("payload_b64", "")),
            data_crc32c=v["data_crc32c"],
        )
        for v in body.get("versions", [])
    ]
    return SecretRecord(
        project=body["project"],
        secret_id=body["secret_id"],
        labels=dict(body.get("labels", {})),
        annotations=dict(body.get("annotations", {})),
        create_time=body["create_time"],
        versions=versions,
    )


class DiskStorage:
    """Disk-backed SecretManagerStorage. Whole-file write-through on every mutation."""

    _FILE_NAME = "secret_manager.json"

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._path = self._root / self._FILE_NAME
        self._lock = asyncio.Lock()

    def _load(self) -> dict[tuple[str, str], SecretRecord]:
        if not self._path.exists():
            return {}
        body = json.loads(self._path.read_text())
        out: dict[tuple[str, str], SecretRecord] = {}
        for raw in body.get("secrets", []):
            rec = _deserialize_record(raw)
            out[(rec.project, rec.secret_id)] = rec
        return out

    def _save(self, state: dict[tuple[str, str], SecretRecord]) -> None:
        body = {"secrets": [_serialize_record(rec) for rec in state.values()]}
        self._path.write_text(json.dumps(body, indent=2))

    async def create_secret(self, record: SecretRecord) -> None:
        async with self._lock:
            state = self._load()
            key = (record.project, record.secret_id)
            if key in state:
                raise SecretAlreadyExists(record.secret_id)
            state[key] = record
            self._save(state)

    async def get_secret(self, project: str, secret_id: str) -> SecretRecord:
        state = self._load()
        try:
            return state[(project, secret_id)]
        except KeyError:
            raise SecretNotFound(secret_id) from None

    async def list_secrets(
        self,
        project: str,
        *,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> tuple[list[SecretRecord], str | None]:
        state = self._load()
        items = sorted(
            [r for (p, _), r in state.items() if p == project],
            key=lambda r: r.secret_id,
        )
        return _paginate(items, lambda r: r.secret_id, page_size, page_token)

    async def update_secret(self, record: SecretRecord) -> None:
        async with self._lock:
            state = self._load()
            key = (record.project, record.secret_id)
            if key not in state:
                raise SecretNotFound(record.secret_id)
            state[key] = record
            self._save(state)

    async def delete_secret(self, project: str, secret_id: str) -> None:
        async with self._lock:
            state = self._load()
            key = (project, secret_id)
            if key not in state:
                raise SecretNotFound(secret_id)
            del state[key]
            self._save(state)

    async def add_version(self, project: str, secret_id: str, payload: bytes) -> SecretVersion:
        async with self._lock:
            state = self._load()
            key = (project, secret_id)
            if key not in state:
                raise SecretNotFound(secret_id)
            rec = state[key]
            next_id = max((v.id for v in rec.versions), default=0) + 1
            version = SecretVersion(
                id=next_id,
                state=SecretVersionState.ENABLED,
                create_time=rfc3339_now(),
                destroy_time=None,
                payload=payload,
                data_crc32c=int(google_crc32c.value(payload)),
            )
            rec.versions.append(version)
            rec.versions.sort(key=lambda v: v.id)
            self._save(state)
            return version

    async def get_version(self, project: str, secret_id: str, version_id: int) -> SecretVersion:
        rec = await self.get_secret(project, secret_id)
        v = rec.get_version(version_id)
        if v is None:
            raise VersionNotFound(version_id)
        return v

    async def list_versions(
        self,
        project: str,
        secret_id: str,
        *,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> tuple[list[SecretVersion], str | None]:
        rec = await self.get_secret(project, secret_id)
        items = sorted(rec.versions, key=lambda v: v.id)
        return _paginate(items, lambda v: str(v.id).zfill(20), page_size, page_token)

    async def update_version_state(
        self,
        project: str,
        secret_id: str,
        version_id: int,
        new_state: SecretVersionState,
    ) -> SecretVersion:
        async with self._lock:
            state = self._load()
            key = (project, secret_id)
            if key not in state:
                raise SecretNotFound(secret_id)
            rec = state[key]
            v = rec.get_version(version_id)
            if v is None:
                raise VersionNotFound(version_id)
            _validate_transition(v.state, new_state)
            v.state = new_state
            if new_state == SecretVersionState.DESTROYED:
                v.payload = b""
                v.destroy_time = rfc3339_now()
            self._save(state)
            return v

    async def reset(self) -> None:
        async with self._lock:
            if self._path.exists():
                self._path.unlink()
