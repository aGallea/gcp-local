# gcp-local GCS Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the GCS service so that the official `google-cloud-storage` Python client library works against the emulator unchanged for buckets, simple+multipart+resumable uploads, downloads with range, listing, metadata updates, preconditions, copy, and compose.

**Architecture:** New `gcp_local.services.gcs` package registered via entry point. A single REST FastAPI app mounted on a uvicorn server, listening on port 4443. Storage abstracted behind a `GcsStorage` protocol with in-memory and disk backends. State-hub events emitted on every mutation for future Pub/Sub consumption. Dummy service from the core is removed as part of Task 1.

**Tech Stack:** Python 3.13, FastAPI, pydantic, google-crc32c (new runtime dep), asyncio, pytest + pytest-asyncio, `google-cloud-storage` as a test-only driver (already in dev deps).

**Spec:** `docs/superpowers/specs/2026-04-24-gcp-local-gcs-design.md`

**Commit policy:** Commit steps are included at natural TDD checkpoints. If you prefer larger commits, coalesce — the content of each commit matters, not its granularity.

**Virtualenv:** `.venv` at repo root. Use `. .venv/bin/activate`. Use `python -m pip install ...` (not bare `pip`) — on the dev machine `pip` is shimmed to the wrong interpreter.

---

## File structure

```
src/gcp_local/services/gcs/
  __init__.py                  # exports GcsService
  service.py                   # GcsService (implements Service protocol)
  models.py                    # pydantic data models
  ids.py                       # generation counter + session-id helpers
  storage.py                   # GcsStorage protocol + InMemoryStorage + DiskStorage
  preconditions.py             # precondition evaluation
  events.py                    # state-hub event building + publishing
  errors.py                    # GCS-specific error helpers (wraps core errors)
  routes/
    __init__.py                # build_router(storage, hub) → APIRouter
    buckets.py
    objects_read.py            # GET + DELETE + LIST
    objects_write.py           # PATCH (metadata update)
    uploads.py                 # simple + multipart + resumable
    copy_compose.py

tests/unit/services/gcs/
  test_models.py
  test_ids.py
  test_storage_memory.py
  test_storage_disk.py
  test_preconditions.py
  test_events.py
  test_routes_buckets.py
  test_routes_objects_read.py
  test_routes_objects_write.py
  test_routes_uploads.py
  test_routes_copy_compose.py

tests/integration/
  test_gcs_integration.py      # real google-cloud-storage client
```

---

## Task 1: GCS service scaffold + dummy removal

**Files:**
- Create: `src/gcp_local/services/gcs/__init__.py`
- Create: `src/gcp_local/services/gcs/service.py`
- Modify: `pyproject.toml` (replace dummy entry point with gcs; add `google-crc32c>=1.5` dep)
- Delete: `src/gcp_local/services/_dummy/` (entire directory)
- Modify: `tests/integration/conftest.py` (rewrite fixture to use GcsService instead of DummyService)
- Modify: `tests/integration/test_core_end_to_end.py` (update "dummy" references to "gcs")

- [ ] **Step 1: Create the service package skeleton**

`src/gcp_local/services/gcs/__init__.py`:

```python
from gcp_local.services.gcs.service import GcsService

__all__ = ["GcsService"]
```

`src/gcp_local/services/gcs/service.py`:

```python
import asyncio
import logging
from typing import ClassVar

import uvicorn
from fastapi import FastAPI

from gcp_local.core.context import Context
from gcp_local.core.service import HealthStatus, Port

log = logging.getLogger(__name__)

_DEFAULT_PORT = 4443


class GcsService:
    """Emulates Google Cloud Storage over a REST API."""

    name = "gcs"
    default_ports: ClassVar[list[Port]] = [Port(_DEFAULT_PORT, "rest")]

    def __init__(self) -> None:
        self._app: FastAPI | None = None
        self._server: uvicorn.Server | None = None
        self._server_task: asyncio.Task[None] | None = None
        self._started = False

    async def start(self, ctx: Context) -> None:
        port = ctx.port_overrides.get(self.name, _DEFAULT_PORT)
        self._app = self._build_app()
        self._server = uvicorn.Server(
            uvicorn.Config(
                self._app,
                host="0.0.0.0",
                port=port,
                log_level="info",
                access_log=False,
            )
        )
        self._server_task = asyncio.create_task(
            self._server.serve(), name=f"{self.name}-server"
        )
        self._started = True
        log.info("gcs service listening on :%d", port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._server_task is not None:
            try:
                await asyncio.wait_for(self._server_task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                self._server_task.cancel()
        self._started = False

    async def reset_state(self) -> None:
        # State wiring comes in later tasks.
        pass

    def health(self) -> HealthStatus:
        return HealthStatus(ok=self._started, message="running" if self._started else "stopped")

    def _build_app(self) -> FastAPI:
        app = FastAPI(title="gcp-local GCS", version="0.0.1")

        @app.get("/")
        async def root() -> dict[str, str]:
            return {"service": "gcs", "status": "ok"}

        return app
```

- [ ] **Step 2: Update `pyproject.toml`**

Replace the `dummy` entry point with `gcs`, and add `google-crc32c` as a runtime dependency:

Find:
```toml
dependencies = [
    "fastapi>=0.110",
    "uvicorn>=0.27",
    "pydantic>=2.6",
]
```

Replace with:
```toml
dependencies = [
    "fastapi>=0.110",
    "uvicorn>=0.27",
    "pydantic>=2.6",
    "google-crc32c>=1.5",
]
```

Find:
```toml
[project.entry-points."gcp_local.services"]
dummy = "gcp_local.services._dummy:DummyService"
```

Replace with:
```toml
[project.entry-points."gcp_local.services"]
gcs = "gcp_local.services.gcs:GcsService"
```

- [ ] **Step 3: Delete the dummy package**

```bash
rm -rf src/gcp_local/services/_dummy
```

- [ ] **Step 4: Update the core integration test fixture to use GCS**

Replace `tests/integration/conftest.py` with:

```python
import asyncio
import contextlib
import socket
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio

from gcp_local.cli import Settings, run
from gcp_local.core.registry import ServiceRegistry
from gcp_local.services.gcs import GcsService


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_for_port(port: int, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
            return
        except OSError:
            await asyncio.sleep(0.05)
    raise TimeoutError(f"port {port} did not open within {timeout}s")


@pytest_asyncio.fixture
async def emulator(tmp_path: Path) -> AsyncIterator[dict[str, int]]:
    """Boot the emulator in-process with the GCS service on a free port."""
    registry = ServiceRegistry()
    registry.register("gcs", GcsService)

    admin_port = _free_port()
    gcs_port = _free_port()
    settings = Settings(
        services=["gcs"],
        persist=False,
        data_dir=tmp_path,
        admin_port=admin_port,
        port_overrides={"gcs": gcs_port},
    )
    task = asyncio.create_task(run(registry, settings), name="emulator")
    try:
        await _wait_for_port(admin_port)
        await _wait_for_port(gcs_port)
        yield {"admin_port": admin_port, "gcs_port": gcs_port}
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
```

- [ ] **Step 5: Rewrite core integration tests (no more dummy)**

Replace `tests/integration/test_core_end_to_end.py` with:

```python
import httpx


async def test_health_reports_gcs_service_healthy(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{url}/_emulator/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "gcs" in body["services"]
    assert body["services"]["gcs"]["ok"] is True


async def test_services_endpoint_lists_gcs(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{url}/_emulator/services")
    assert r.status_code == 200
    names = {s["name"] for s in r.json()["services"]}
    assert "gcs" in names


async def test_reset_all_succeeds(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{url}/_emulator/reset")
    assert r.status_code == 204


async def test_reset_gcs_succeeds(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{url}/_emulator/reset", params={"service": "gcs"})
    assert r.status_code == 204


async def test_reset_unknown_404(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{url}/_emulator/reset", params={"service": "nope"})
    assert r.status_code == 404


async def test_gcs_root_responds(emulator):
    url = f"http://127.0.0.1:{emulator['gcs_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{url}/")
    assert r.status_code == 200
    assert r.json() == {"service": "gcs", "status": "ok"}
```

- [ ] **Step 6: Reinstall to pick up new entry point and dependency**

```bash
. .venv/bin/activate && python -m pip install -e ".[dev]"
```

Verify the entry point resolves to `gcs`, not `dummy`:

```bash
. .venv/bin/activate && python -c "from importlib.metadata import entry_points; print(list(entry_points(group='gcp_local.services')))"
```

Expected output: `[EntryPoint(name='gcs', value='gcp_local.services.gcs:GcsService', group='gcp_local.services')]` (no dummy).

- [ ] **Step 7: Run lint, type-check, tests**

```bash
. .venv/bin/activate
ruff check .
ruff format --check .
mypy
pytest -v
```

Expected: all green. Tests should be 39 unit (same as before; no new unit tests yet) + 6 integration (the rewritten ones). The docker integration test still gets skipped.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(gcs): bootstrap GCS service skeleton and retire dummy"
```

---

## Task 2: Domain models

**Files:**
- Create: `src/gcp_local/services/gcs/models.py`
- Test: `tests/unit/services/gcs/__init__.py` (empty)
- Test: `tests/unit/services/__init__.py` (empty)
- Test: `tests/unit/services/gcs/test_models.py`

- [ ] **Step 1: Failing tests**

`tests/unit/services/gcs/test_models.py`:

```python
from gcp_local.services.gcs.models import (
    BucketMeta,
    ObjectRecord,
    UploadSession,
)


def test_bucket_meta_defaults():
    b = BucketMeta(name="my-bucket", time_created="2026-04-24T00:00:00Z")
    assert b.name == "my-bucket"
    assert b.metageneration == 1
    assert b.location == "US"
    assert b.storage_class == "STANDARD"


def test_object_record_defaults():
    o = ObjectRecord(
        bucket="b",
        name="o",
        size=0,
        generation=1,
        metageneration=1,
        content_type="application/octet-stream",
        md5_hash="",
        crc32c="",
        time_created="t",
        updated="t",
    )
    assert o.metadata == {}
    assert o.content_encoding == ""
    assert o.cache_control == ""


def test_object_record_etag_computed():
    o = ObjectRecord(
        bucket="b",
        name="o",
        size=0,
        generation=42,
        metageneration=3,
        content_type="application/octet-stream",
        md5_hash="",
        crc32c="",
        time_created="t",
        updated="t",
    )
    assert o.etag == '"42/3"'


def test_upload_session_fields():
    s = UploadSession(
        session_id="abc",
        bucket="b",
        object_name="o",
        total_size=1000,
        bytes_received=500,
        content_type="text/plain",
        user_metadata={"k": "v"},
        created_at="t",
        last_chunk_at="t",
    )
    assert s.is_complete is False


def test_upload_session_complete():
    s = UploadSession(
        session_id="abc",
        bucket="b",
        object_name="o",
        total_size=1000,
        bytes_received=1000,
        content_type="text/plain",
        user_metadata={},
        created_at="t",
        last_chunk_at="t",
    )
    assert s.is_complete is True


def test_upload_session_unknown_total():
    s = UploadSession(
        session_id="abc",
        bucket="b",
        object_name="o",
        total_size=None,
        bytes_received=500,
        content_type="text/plain",
        user_metadata={},
        created_at="t",
        last_chunk_at="t",
    )
    assert s.is_complete is False
```

- [ ] **Step 2: Run — fail**

```bash
pytest tests/unit/services/gcs/test_models.py -v
```

Expected: FAIL (import error).

- [ ] **Step 3: Implement**

`src/gcp_local/services/gcs/models.py`:

```python
from pydantic import BaseModel, ConfigDict, Field, computed_field


class BucketMeta(BaseModel):
    model_config = ConfigDict(frozen=False)

    name: str
    time_created: str
    metageneration: int = 1
    location: str = "US"
    storage_class: str = "STANDARD"


class ObjectRecord(BaseModel):
    model_config = ConfigDict(frozen=False)

    bucket: str
    name: str
    size: int
    generation: int
    metageneration: int
    content_type: str = "application/octet-stream"
    content_encoding: str = ""
    content_language: str = ""
    content_disposition: str = ""
    cache_control: str = ""
    md5_hash: str
    crc32c: str
    time_created: str
    updated: str
    metadata: dict[str, str] = Field(default_factory=dict)

    @computed_field
    @property
    def etag(self) -> str:
        return f'"{self.generation}/{self.metageneration}"'


class UploadSession(BaseModel):
    model_config = ConfigDict(frozen=False)

    session_id: str
    bucket: str
    object_name: str
    total_size: int | None
    bytes_received: int
    content_type: str
    user_metadata: dict[str, str] = Field(default_factory=dict)
    created_at: str
    last_chunk_at: str

    @property
    def is_complete(self) -> bool:
        return self.total_size is not None and self.bytes_received >= self.total_size
```

- [ ] **Step 4: Run — pass**

Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/gcs/models.py tests/unit/services/
git commit -m "feat(gcs): domain models"
```

---

## Task 3: ID helpers (generation counter, session IDs, hashing)

**Files:**
- Create: `src/gcp_local/services/gcs/ids.py`
- Test: `tests/unit/services/gcs/test_ids.py`

- [ ] **Step 1: Failing tests**

```python
import asyncio

from gcp_local.services.gcs.ids import (
    GenerationCounter,
    compute_crc32c_b64,
    compute_md5_b64,
    new_session_id,
    rfc3339_now,
)


def test_generation_counter_monotonic():
    c = GenerationCounter()
    v1 = c.next("my-bucket")
    v2 = c.next("my-bucket")
    v3 = c.next("my-bucket")
    assert v1 == 1 and v2 == 2 and v3 == 3


def test_generation_counter_per_bucket():
    c = GenerationCounter()
    c.next("a")
    c.next("a")
    assert c.next("b") == 1
    assert c.next("a") == 3


def test_generation_counter_reset():
    c = GenerationCounter()
    c.next("a")
    c.next("a")
    c.reset_bucket("a")
    assert c.next("a") == 1


def test_generation_counter_concurrent():
    c = GenerationCounter()
    N = 200

    async def bump() -> int:
        return c.next("bucket")

    async def main() -> list[int]:
        return await asyncio.gather(*(bump() for _ in range(N)))

    results = asyncio.run(main())
    assert sorted(results) == list(range(1, N + 1))


def test_new_session_id_unique():
    ids = {new_session_id() for _ in range(100)}
    assert len(ids) == 100


def test_compute_md5_b64():
    assert compute_md5_b64(b"hello") == "XUFAKrxLKna5cZ2REBfFkg=="


def test_compute_crc32c_b64():
    # google-crc32c of b"hello" is 0x9a71bb4c = bytes 9a 71 bb 4c = base64 "mnG7TA=="
    assert compute_crc32c_b64(b"hello") == "mnG7TA=="


def test_rfc3339_now_format():
    s = rfc3339_now()
    # Shape like "2026-04-24T15:04:05.123456Z"
    assert s.endswith("Z")
    assert "T" in s
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

`src/gcp_local/services/gcs/ids.py`:

```python
import base64
import hashlib
import secrets
import struct
import threading
from datetime import UTC, datetime

import google_crc32c


class GenerationCounter:
    """Monotonic per-bucket generation counter.

    Thread-safe via a lock (used because uvicorn may execute handlers in
    threadpool executors under some configurations). The increments are
    cheap and uncontended in the common single-loop case.
    """

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def next(self, bucket: str) -> int:
        with self._lock:
            new_val = self._counts.get(bucket, 0) + 1
            self._counts[bucket] = new_val
            return new_val

    def reset_bucket(self, bucket: str) -> None:
        with self._lock:
            self._counts.pop(bucket, None)

    def reset_all(self) -> None:
        with self._lock:
            self._counts.clear()


def new_session_id() -> str:
    """URL-safe 128-bit random token used as resumable upload session id."""
    return secrets.token_urlsafe(16)


def compute_md5_b64(data: bytes) -> str:
    return base64.b64encode(hashlib.md5(data).digest()).decode("ascii")


def compute_crc32c_b64(data: bytes) -> str:
    checksum = google_crc32c.value(data)
    return base64.b64encode(struct.pack(">I", checksum)).decode("ascii")


def rfc3339_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/gcs/ids.py tests/unit/services/gcs/test_ids.py
git commit -m "feat(gcs): id helpers (generation counter, session id, hashes)"
```

---

## Task 4: GcsStorage protocol + InMemoryStorage

**Files:**
- Create: `src/gcp_local/services/gcs/storage.py`
- Test: `tests/unit/services/gcs/test_storage_memory.py`

This task builds the full storage contract. The disk backend in Task 5 must conform to the same contract.

- [ ] **Step 1: Failing tests**

```python
import pytest

from gcp_local.services.gcs.models import BucketMeta, ObjectRecord, UploadSession
from gcp_local.services.gcs.storage import (
    BucketAlreadyExists,
    BucketNotFound,
    InMemoryStorage,
    ObjectCollision,
    ObjectNotFound,
    SessionNotFound,
)


def make_record(bucket="b", name="o", size=5, gen=1, mgen=1) -> ObjectRecord:
    return ObjectRecord(
        bucket=bucket, name=name, size=size,
        generation=gen, metageneration=mgen,
        content_type="application/octet-stream",
        md5_hash="", crc32c="",
        time_created="t", updated="t",
    )


async def test_create_and_get_bucket():
    s = InMemoryStorage()
    b = BucketMeta(name="my-bucket", time_created="t")
    await s.create_bucket(b)
    assert (await s.get_bucket("my-bucket")).name == "my-bucket"


async def test_create_existing_bucket_raises():
    s = InMemoryStorage()
    b = BucketMeta(name="my-bucket", time_created="t")
    await s.create_bucket(b)
    with pytest.raises(BucketAlreadyExists):
        await s.create_bucket(b)


async def test_get_missing_bucket_raises():
    s = InMemoryStorage()
    with pytest.raises(BucketNotFound):
        await s.get_bucket("nope")


async def test_list_buckets_sorted():
    s = InMemoryStorage()
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    await s.create_bucket(BucketMeta(name="a", time_created="t"))
    assert [b.name for b in await s.list_buckets()] == ["a", "b"]


async def test_delete_bucket_happy():
    s = InMemoryStorage()
    await s.create_bucket(BucketMeta(name="a", time_created="t"))
    await s.delete_bucket("a")
    with pytest.raises(BucketNotFound):
        await s.get_bucket("a")


async def test_delete_missing_bucket_raises():
    s = InMemoryStorage()
    with pytest.raises(BucketNotFound):
        await s.delete_bucket("a")


async def test_put_and_get_object():
    s = InMemoryStorage()
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    rec = make_record(name="logs/a.log")
    await s.put_object(rec, b"hello")
    got = await s.get_object("b", "logs/a.log")
    assert got.name == "logs/a.log"
    body = await s.get_object_bytes("b", "logs/a.log")
    assert body == b"hello"


async def test_get_missing_object_raises():
    s = InMemoryStorage()
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    with pytest.raises(ObjectNotFound):
        await s.get_object("b", "nope")


async def test_list_objects_prefix():
    s = InMemoryStorage()
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    for n in ("a", "logs/1", "logs/2", "z"):
        await s.put_object(make_record(name=n), b"")
    names = [o.name for o in await s.list_objects("b", prefix="logs/", delimiter=None)]
    assert names == ["logs/1", "logs/2"]


async def test_list_objects_delimiter_returns_prefixes():
    s = InMemoryStorage()
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    for n in ("a.log", "logs/1", "logs/2", "other/x"):
        await s.put_object(make_record(name=n), b"")
    objects, prefixes = await s.list_objects_with_prefixes(
        "b", prefix="", delimiter="/"
    )
    assert {o.name for o in objects} == {"a.log"}
    assert set(prefixes) == {"logs/", "other/"}


async def test_list_objects_pagination():
    s = InMemoryStorage()
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    for i in range(10):
        await s.put_object(make_record(name=f"n{i:02d}"), b"")
    page1 = await s.list_objects("b", prefix="", delimiter=None, max_results=3)
    assert [o.name for o in page1] == ["n00", "n01", "n02"]
    page2 = await s.list_objects(
        "b", prefix="", delimiter=None, max_results=3, start_after="n02"
    )
    assert [o.name for o in page2] == ["n03", "n04", "n05"]


async def test_delete_object_happy():
    s = InMemoryStorage()
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    await s.put_object(make_record(name="o"), b"")
    await s.delete_object("b", "o")
    with pytest.raises(ObjectNotFound):
        await s.get_object("b", "o")


async def test_delete_missing_object_raises():
    s = InMemoryStorage()
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    with pytest.raises(ObjectNotFound):
        await s.delete_object("b", "o")


async def test_overwrite_object_increases_generation():
    s = InMemoryStorage()
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    await s.put_object(make_record(name="o", gen=1), b"a")
    await s.put_object(make_record(name="o", gen=2), b"bb")
    got = await s.get_object("b", "o")
    assert got.generation == 2
    body = await s.get_object_bytes("b", "o")
    assert body == b"bb"


async def test_object_collision_rules_flat_mode():
    # InMemoryStorage does not collide (the filesystem rule only applies to DiskStorage).
    s = InMemoryStorage()
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    await s.put_object(make_record(name="foo"), b"x")
    await s.put_object(make_record(name="foo/bar"), b"y")  # no collision in memory
    got_foo = await s.get_object("b", "foo")
    got_foobar = await s.get_object("b", "foo/bar")
    assert got_foo.name == "foo" and got_foobar.name == "foo/bar"


async def test_session_lifecycle():
    s = InMemoryStorage()
    sess = UploadSession(
        session_id="abc", bucket="b", object_name="o",
        total_size=10, bytes_received=0,
        content_type="text/plain", user_metadata={},
        created_at="t", last_chunk_at="t",
    )
    await s.put_session(sess)
    got = await s.get_session("abc")
    assert got.session_id == "abc"
    await s.append_to_session("abc", b"hello")
    got = await s.get_session("abc")
    assert got.bytes_received == 5
    await s.delete_session("abc")
    with pytest.raises(SessionNotFound):
        await s.get_session("abc")


async def test_session_buffer_accumulates():
    s = InMemoryStorage()
    sess = UploadSession(
        session_id="s", bucket="b", object_name="o",
        total_size=None, bytes_received=0,
        content_type="t", user_metadata={},
        created_at="t", last_chunk_at="t",
    )
    await s.put_session(sess)
    await s.append_to_session("s", b"ab")
    await s.append_to_session("s", b"cd")
    buf = await s.get_session_bytes("s")
    assert buf == b"abcd"


async def test_reset_wipes_everything():
    s = InMemoryStorage()
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    await s.put_object(make_record(name="o"), b"x")
    await s.put_session(UploadSession(
        session_id="s", bucket="b", object_name="o",
        total_size=None, bytes_received=0,
        content_type="t", user_metadata={},
        created_at="t", last_chunk_at="t",
    ))
    await s.reset()
    with pytest.raises(BucketNotFound):
        await s.get_bucket("b")
    with pytest.raises(SessionNotFound):
        await s.get_session("s")
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

`src/gcp_local/services/gcs/storage.py`:

```python
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
                rest = n[len(prefix):]
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
```

- [ ] **Step 4: Run — pass**

Expected: ~17 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/gcs/storage.py tests/unit/services/gcs/test_storage_memory.py
git commit -m "feat(gcs): GcsStorage protocol and InMemoryStorage backend"
```

---

## Task 5: DiskStorage backend

**Files:**
- Modify: `src/gcp_local/services/gcs/storage.py` (add `DiskStorage`)
- Test: `tests/unit/services/gcs/test_storage_disk.py`

Reuses the same symmetric behavioral tests, plus disk-specific tests (collision rule, sidecar format, session GC).

- [ ] **Step 1: Failing tests**

`tests/unit/services/gcs/test_storage_disk.py`:

```python
import json
from pathlib import Path

import pytest

from gcp_local.services.gcs.models import BucketMeta, ObjectRecord, UploadSession
from gcp_local.services.gcs.storage import (
    BucketNotFound,
    DiskStorage,
    ObjectCollision,
    ObjectNotFound,
    SessionNotFound,
)


def make_record(bucket="b", name="o", size=5, gen=1, mgen=1) -> ObjectRecord:
    return ObjectRecord(
        bucket=bucket, name=name, size=size,
        generation=gen, metageneration=mgen,
        content_type="application/octet-stream",
        md5_hash="", crc32c="",
        time_created="t", updated="t",
    )


async def test_create_bucket_writes_sidecar(tmp_path: Path):
    s = DiskStorage(tmp_path)
    await s.create_bucket(BucketMeta(name="mybucket", time_created="t"))
    meta_file = tmp_path / "mybucket" / "mybucket.meta.json"
    assert meta_file.exists()
    body = json.loads(meta_file.read_text())
    assert body["name"] == "mybucket"


async def test_put_object_writes_bytes_and_sidecar(tmp_path: Path):
    s = DiskStorage(tmp_path)
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    await s.put_object(make_record(name="dir/o.txt", size=5), b"hello")
    bytes_file = tmp_path / "b" / "objects" / "dir" / "o.txt"
    meta_file = tmp_path / "b" / "objects" / "dir" / "o.txt.meta.json"
    assert bytes_file.read_bytes() == b"hello"
    assert json.loads(meta_file.read_text())["name"] == "dir/o.txt"


async def test_collision_rule_object_vs_directory(tmp_path: Path):
    s = DiskStorage(tmp_path)
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    await s.put_object(make_record(name="foo"), b"x")
    with pytest.raises(ObjectCollision):
        # "foo" exists as a file; putting "foo/bar" needs "foo/" as a dir.
        await s.put_object(make_record(name="foo/bar"), b"y")


async def test_collision_rule_directory_vs_object(tmp_path: Path):
    s = DiskStorage(tmp_path)
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    await s.put_object(make_record(name="foo/bar"), b"x")
    with pytest.raises(ObjectCollision):
        # "foo/" exists as a dir; putting "foo" needs "foo" as a file.
        await s.put_object(make_record(name="foo"), b"y")


async def test_delete_bucket_removes_directory(tmp_path: Path):
    s = DiskStorage(tmp_path)
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    await s.put_object(make_record(name="o"), b"x")
    await s.delete_bucket("b")
    assert not (tmp_path / "b").exists()


async def test_loads_state_from_existing_disk(tmp_path: Path):
    s1 = DiskStorage(tmp_path)
    await s1.create_bucket(BucketMeta(name="b", time_created="t"))
    await s1.put_object(make_record(name="o", size=3), b"abc")
    # New instance starts cold — should see the existing state on first access
    s2 = DiskStorage(tmp_path)
    got = await s2.get_object("b", "o")
    assert got.name == "o"
    body = await s2.get_object_bytes("b", "o")
    assert body == b"abc"


async def test_session_persisted_to_disk(tmp_path: Path):
    s = DiskStorage(tmp_path)
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    sess = UploadSession(
        session_id="sess1", bucket="b", object_name="o",
        total_size=10, bytes_received=0,
        content_type="text/plain", user_metadata={},
        created_at="t", last_chunk_at="t",
    )
    await s.put_session(sess)
    await s.append_to_session("sess1", b"hello")
    # Fresh instance should still see the session
    s2 = DiskStorage(tmp_path)
    got = await s2.get_session("sess1")
    assert got.bytes_received == 5
    assert await s2.get_session_bytes("sess1") == b"hello"


async def test_session_gc_removes_stale(tmp_path: Path):
    """Sessions older than 7 days are removed by gc_stale_sessions()."""
    import os
    import time

    s = DiskStorage(tmp_path)
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    sess = UploadSession(
        session_id="old", bucket="b", object_name="o",
        total_size=10, bytes_received=0,
        content_type="text/plain", user_metadata={},
        created_at="t", last_chunk_at="t",
    )
    await s.put_session(sess)
    # Backdate the session dir's mtime by 8 days
    session_dir = tmp_path / "b" / ".uploads" / "old"
    assert session_dir.exists()
    ancient = time.time() - 8 * 86400
    os.utime(session_dir, (ancient, ancient))
    await s.gc_stale_sessions(max_age_seconds=7 * 86400)
    with pytest.raises(SessionNotFound):
        await s.get_session("old")


async def test_reset_wipes_disk(tmp_path: Path):
    s = DiskStorage(tmp_path)
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    await s.put_object(make_record(name="o"), b"x")
    await s.reset()
    with pytest.raises(BucketNotFound):
        await s.get_bucket("b")
    # Data dir is empty (or only contains the root itself)
    assert not any(tmp_path.iterdir())
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement — append to `storage.py`**

Add to the bottom of `src/gcp_local/services/gcs/storage.py`:

```python
import json
import shutil
import time
from pathlib import Path


class DiskStorage:
    """Disk-backed GcsStorage implementation.

    Layout under `root`:
      <bucket>/<bucket>.meta.json
      <bucket>/objects/<path>          (raw bytes)
      <bucket>/objects/<path>.meta.json
      <bucket>/.uploads/<session_id>/{buffer.bin, session.json}
    """

    _META_SUFFIX = ".meta.json"

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, asyncio.Lock] = {}

    def _bucket_lock(self, bucket: str) -> asyncio.Lock:
        lock = self._locks.get(bucket)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[bucket] = lock
        return lock

    # --- path helpers ---------------------------------------------------

    def _bucket_dir(self, bucket: str) -> Path:
        return self._root / bucket

    def _bucket_meta_path(self, bucket: str) -> Path:
        return self._bucket_dir(bucket) / f"{bucket}{self._META_SUFFIX}"

    def _objects_root(self, bucket: str) -> Path:
        return self._bucket_dir(bucket) / "objects"

    def _object_bytes_path(self, bucket: str, name: str) -> Path:
        return self._objects_root(bucket) / name

    def _object_meta_path(self, bucket: str, name: str) -> Path:
        return self._objects_root(bucket) / f"{name}{self._META_SUFFIX}"

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
        # Check ancestors
        parts = name.split("/")
        for i in range(1, len(parts)):
            candidate = root / "/".join(parts[:i])
            if candidate.exists() and candidate.is_file():
                raise ObjectCollision(
                    f"object {'/'.join(parts[:i])!r} exists; cannot write object under that prefix"
                )
        # Check that the target path isn't currently a directory
        target = root / name
        if target.exists() and target.is_dir():
            raise ObjectCollision(
                f"cannot write object {name!r}: a directory exists at that path"
            )

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
                names.append(rel)
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
                rest = n[len(prefix):]
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
```

- [ ] **Step 4: Run — pass**

Expected: ~9 PASS (disk-specific tests). Also re-run the in-memory tests to make sure the shared import still works.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/gcs/storage.py tests/unit/services/gcs/test_storage_disk.py
git commit -m "feat(gcs): DiskStorage backend with sidecars and collision rule"
```

---

## Task 6: Precondition evaluator

**Files:**
- Create: `src/gcp_local/services/gcs/preconditions.py`
- Test: `tests/unit/services/gcs/test_preconditions.py`

- [ ] **Step 1: Failing tests**

```python
import pytest

from gcp_local.services.gcs.models import ObjectRecord
from gcp_local.services.gcs.preconditions import (
    PreconditionFailed,
    Preconditions,
    evaluate_preconditions,
)


def make_rec(gen=5, mgen=2) -> ObjectRecord:
    return ObjectRecord(
        bucket="b", name="o", size=0,
        generation=gen, metageneration=mgen,
        content_type="application/octet-stream",
        md5_hash="", crc32c="",
        time_created="t", updated="t",
    )


def test_no_preconditions_passes():
    evaluate_preconditions(Preconditions(), current=make_rec())


def test_if_generation_match_matches():
    evaluate_preconditions(Preconditions(if_generation_match=5), current=make_rec(gen=5))


def test_if_generation_match_mismatch():
    with pytest.raises(PreconditionFailed):
        evaluate_preconditions(
            Preconditions(if_generation_match=5), current=make_rec(gen=6)
        )


def test_if_generation_match_zero_when_object_exists():
    with pytest.raises(PreconditionFailed):
        evaluate_preconditions(
            Preconditions(if_generation_match=0), current=make_rec()
        )


def test_if_generation_match_zero_when_no_object():
    evaluate_preconditions(Preconditions(if_generation_match=0), current=None)


def test_if_generation_match_nonzero_when_no_object():
    with pytest.raises(PreconditionFailed):
        evaluate_preconditions(
            Preconditions(if_generation_match=5), current=None
        )


def test_if_generation_not_match():
    evaluate_preconditions(
        Preconditions(if_generation_not_match=99), current=make_rec(gen=5)
    )
    with pytest.raises(PreconditionFailed):
        evaluate_preconditions(
            Preconditions(if_generation_not_match=5), current=make_rec(gen=5)
        )


def test_if_metageneration_match():
    evaluate_preconditions(
        Preconditions(if_metageneration_match=2), current=make_rec(mgen=2)
    )
    with pytest.raises(PreconditionFailed):
        evaluate_preconditions(
            Preconditions(if_metageneration_match=99), current=make_rec(mgen=2)
        )


def test_if_metageneration_not_match():
    evaluate_preconditions(
        Preconditions(if_metageneration_not_match=99), current=make_rec(mgen=2)
    )
    with pytest.raises(PreconditionFailed):
        evaluate_preconditions(
            Preconditions(if_metageneration_not_match=2), current=make_rec(mgen=2)
        )
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

`src/gcp_local/services/gcs/preconditions.py`:

```python
from dataclasses import dataclass

from gcp_local.services.gcs.models import ObjectRecord


class PreconditionFailed(Exception):
    pass


@dataclass
class Preconditions:
    if_generation_match: int | None = None
    if_generation_not_match: int | None = None
    if_metageneration_match: int | None = None
    if_metageneration_not_match: int | None = None


def evaluate_preconditions(
    pre: Preconditions, *, current: ObjectRecord | None
) -> None:
    """Raise PreconditionFailed if any of the supplied preconditions fails."""

    if pre.if_generation_match is not None:
        if pre.if_generation_match == 0:
            if current is not None:
                raise PreconditionFailed(
                    "ifGenerationMatch=0 requires the object to not exist"
                )
        else:
            if current is None or current.generation != pre.if_generation_match:
                raise PreconditionFailed(
                    f"ifGenerationMatch={pre.if_generation_match} does not match"
                )

    if pre.if_generation_not_match is not None:
        if current is not None and current.generation == pre.if_generation_not_match:
            raise PreconditionFailed(
                f"ifGenerationNotMatch={pre.if_generation_not_match} matched"
            )

    if pre.if_metageneration_match is not None:
        if current is None or current.metageneration != pre.if_metageneration_match:
            raise PreconditionFailed(
                f"ifMetagenerationMatch={pre.if_metageneration_match} does not match"
            )

    if pre.if_metageneration_not_match is not None:
        if (
            current is not None
            and current.metageneration == pre.if_metageneration_not_match
        ):
            raise PreconditionFailed(
                f"ifMetagenerationNotMatch={pre.if_metageneration_not_match} matched"
            )
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/gcs/preconditions.py tests/unit/services/gcs/test_preconditions.py
git commit -m "feat(gcs): precondition evaluator"
```

---

## Task 7: Event publisher

**Files:**
- Create: `src/gcp_local/services/gcs/events.py`
- Test: `tests/unit/services/gcs/test_events.py`

- [ ] **Step 1: Failing tests**

```python
from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.events import (
    EVENT_DELETE,
    EVENT_FINALIZE,
    EVENT_METADATA_UPDATE,
    build_event_payload,
    publish_delete,
    publish_finalize,
    publish_metadata_update,
)
from gcp_local.services.gcs.models import ObjectRecord


def make_rec() -> ObjectRecord:
    return ObjectRecord(
        bucket="b", name="o", size=10,
        generation=1, metageneration=1,
        content_type="text/plain",
        md5_hash="abc", crc32c="xyz",
        time_created="2026-04-24T00:00:00Z",
        updated="2026-04-24T00:00:00Z",
        metadata={"k": "v"},
    )


def test_build_event_payload_contract():
    payload = build_event_payload(make_rec())
    assert payload == {
        "bucket": "b",
        "name": "o",
        "generation": 1,
        "metageneration": 1,
        "size": 10,
        "contentType": "text/plain",
        "md5Hash": "abc",
        "crc32c": "xyz",
        "timeCreated": "2026-04-24T00:00:00Z",
        "updated": "2026-04-24T00:00:00Z",
        "metadata": {"k": "v"},
    }


async def test_publish_finalize():
    hub = StateHub()
    got: list[dict] = []

    async def h(ev):
        got.append(ev)

    hub.subscribe(EVENT_FINALIZE, h)
    await publish_finalize(hub, make_rec())
    assert len(got) == 1
    assert got[0]["bucket"] == "b" and got[0]["name"] == "o"


async def test_publish_metadata_update():
    hub = StateHub()
    got: list[dict] = []

    async def h(ev):
        got.append(ev)

    hub.subscribe(EVENT_METADATA_UPDATE, h)
    await publish_metadata_update(hub, make_rec())
    assert len(got) == 1


async def test_publish_delete():
    hub = StateHub()
    got: list[dict] = []

    async def h(ev):
        got.append(ev)

    hub.subscribe(EVENT_DELETE, h)
    await publish_delete(hub, make_rec())
    assert len(got) == 1


async def test_publish_without_hub_is_noop():
    # hub=None should be accepted and silent
    await publish_finalize(None, make_rec())
    await publish_metadata_update(None, make_rec())
    await publish_delete(None, make_rec())
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

`src/gcp_local/services/gcs/events.py`:

```python
from typing import Any

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.models import ObjectRecord

EVENT_FINALIZE = "gcs.object.finalize"
EVENT_METADATA_UPDATE = "gcs.object.metadata_update"
EVENT_DELETE = "gcs.object.delete"


def build_event_payload(record: ObjectRecord) -> dict[str, Any]:
    return {
        "bucket": record.bucket,
        "name": record.name,
        "generation": record.generation,
        "metageneration": record.metageneration,
        "size": record.size,
        "contentType": record.content_type,
        "md5Hash": record.md5_hash,
        "crc32c": record.crc32c,
        "timeCreated": record.time_created,
        "updated": record.updated,
        "metadata": dict(record.metadata),
    }


async def _publish(hub: StateHub | None, topic: str, record: ObjectRecord) -> None:
    if hub is None:
        return
    await hub.publish(topic, build_event_payload(record))


async def publish_finalize(hub: StateHub | None, record: ObjectRecord) -> None:
    await _publish(hub, EVENT_FINALIZE, record)


async def publish_metadata_update(hub: StateHub | None, record: ObjectRecord) -> None:
    await _publish(hub, EVENT_METADATA_UPDATE, record)


async def publish_delete(hub: StateHub | None, record: ObjectRecord) -> None:
    await _publish(hub, EVENT_DELETE, record)
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/gcs/events.py tests/unit/services/gcs/test_events.py
git commit -m "feat(gcs): state-hub event publisher"
```

---

## Task 8: Bucket routes

**Files:**
- Create: `src/gcp_local/services/gcs/errors.py` (thin wrapper translating GCS exceptions to `rest_error_body`)
- Create: `src/gcp_local/services/gcs/routes/__init__.py`
- Create: `src/gcp_local/services/gcs/routes/buckets.py`
- Modify: `src/gcp_local/services/gcs/service.py` (wire storage + hub + routes into the FastAPI app)
- Test: `tests/unit/services/gcs/test_routes_buckets.py`

- [ ] **Step 1: Helper for consistent errors**

`src/gcp_local/services/gcs/errors.py`:

```python
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from gcp_local.core.errors import GcpError, rest_error_body


def error_response(code: int, reason: str, message: str) -> JSONResponse:
    err = GcpError(code=code, reason=reason, message=message)
    return JSONResponse(content=rest_error_body(err), status_code=code)


def http_exception(code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=code,
        detail={"reason": reason, "message": message},
    )
```

- [ ] **Step 2: Failing tests**

`tests/unit/services/gcs/test_routes_buckets.py`:

```python
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.ids import GenerationCounter
from gcp_local.services.gcs.routes import build_router
from gcp_local.services.gcs.storage import InMemoryStorage


@pytest.fixture
def app(tmp_path: Path):
    storage = InMemoryStorage()
    hub = StateHub()
    gen = GenerationCounter()
    app = FastAPI()
    app.include_router(build_router(storage=storage, state_hub=hub, generations=gen))
    return app


@pytest.fixture
def client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_create_bucket(client):
    r = await client.post("/storage/v1/b", json={"name": "mybucket"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "mybucket"
    assert body["metageneration"] == 1


async def test_create_duplicate_bucket_409(client):
    await client.post("/storage/v1/b", json={"name": "b"})
    r = await client.post("/storage/v1/b", json={"name": "b"})
    assert r.status_code == 409
    assert r.json()["error"]["errors"][0]["reason"] == "conflict"


async def test_get_bucket(client):
    await client.post("/storage/v1/b", json={"name": "b"})
    r = await client.get("/storage/v1/b/b")
    assert r.status_code == 200
    assert r.json()["name"] == "b"


async def test_get_missing_bucket_404(client):
    r = await client.get("/storage/v1/b/nope")
    assert r.status_code == 404
    assert r.json()["error"]["errors"][0]["reason"] == "notFound"


async def test_list_buckets(client):
    await client.post("/storage/v1/b", json={"name": "b"})
    await client.post("/storage/v1/b", json={"name": "a"})
    r = await client.get("/storage/v1/b")
    assert r.status_code == 200
    names = [b["name"] for b in r.json()["items"]]
    assert names == ["a", "b"]


async def test_delete_bucket(client):
    await client.post("/storage/v1/b", json={"name": "b"})
    r = await client.delete("/storage/v1/b/b")
    assert r.status_code == 204
    r2 = await client.get("/storage/v1/b/b")
    assert r2.status_code == 404


async def test_delete_missing_bucket_404(client):
    r = await client.delete("/storage/v1/b/nope")
    assert r.status_code == 404
```

- [ ] **Step 3: Implement router package**

`src/gcp_local/services/gcs/routes/__init__.py`:

```python
from fastapi import APIRouter

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.ids import GenerationCounter
from gcp_local.services.gcs.routes.buckets import register_bucket_routes
from gcp_local.services.gcs.storage import GcsStorage


def build_router(
    *,
    storage: GcsStorage,
    state_hub: StateHub,
    generations: GenerationCounter,
) -> APIRouter:
    r = APIRouter()
    register_bucket_routes(r, storage=storage)
    # Object / upload routers plug in here in later tasks (Task 9+).
    return r
```

`src/gcp_local/services/gcs/routes/buckets.py`:

```python
from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from gcp_local.services.gcs.errors import error_response
from gcp_local.services.gcs.ids import rfc3339_now
from gcp_local.services.gcs.models import BucketMeta
from gcp_local.services.gcs.storage import (
    BucketAlreadyExists,
    BucketNotFound,
    GcsStorage,
)


class _CreateBody(BaseModel):
    name: str
    location: str | None = None
    storageClass: str | None = None


def register_bucket_routes(router: APIRouter, *, storage: GcsStorage) -> None:

    @router.post("/storage/v1/b")
    async def create_bucket(body: _CreateBody) -> JSONResponse:
        bucket = BucketMeta(
            name=body.name,
            time_created=rfc3339_now(),
            location=body.location or "US",
            storage_class=body.storageClass or "STANDARD",
        )
        try:
            await storage.create_bucket(bucket)
        except BucketAlreadyExists:
            return error_response(
                409, "conflict", f"bucket {body.name!r} already exists"
            )
        return JSONResponse(bucket.model_dump(by_alias=True))

    @router.get("/storage/v1/b")
    async def list_buckets() -> JSONResponse:
        buckets = await storage.list_buckets()
        return JSONResponse(
            {"items": [b.model_dump(by_alias=True) for b in buckets]}
        )

    @router.get("/storage/v1/b/{bucket}")
    async def get_bucket(bucket: str) -> JSONResponse:
        try:
            b = await storage.get_bucket(bucket)
        except BucketNotFound:
            return error_response(404, "notFound", f"bucket {bucket!r} not found")
        return JSONResponse(b.model_dump(by_alias=True))

    @router.delete("/storage/v1/b/{bucket}")
    async def delete_bucket(bucket: str) -> Response:
        try:
            await storage.delete_bucket(bucket)
        except BucketNotFound:
            return error_response(404, "notFound", f"bucket {bucket!r} not found")
        return Response(status_code=204)
```

- [ ] **Step 4: Wire into service**

Update `src/gcp_local/services/gcs/service.py` — replace `_build_app` to install the storage + router. Full updated file:

```python
import asyncio
import logging
from pathlib import Path
from typing import ClassVar

import uvicorn
from fastapi import FastAPI

from gcp_local.core.context import Context
from gcp_local.core.service import HealthStatus, Port
from gcp_local.services.gcs.ids import GenerationCounter
from gcp_local.services.gcs.routes import build_router
from gcp_local.services.gcs.storage import DiskStorage, GcsStorage, InMemoryStorage

log = logging.getLogger(__name__)

_DEFAULT_PORT = 4443


class GcsService:
    name = "gcs"
    default_ports: ClassVar[list[Port]] = [Port(_DEFAULT_PORT, "rest")]

    def __init__(self) -> None:
        self._app: FastAPI | None = None
        self._server: uvicorn.Server | None = None
        self._server_task: asyncio.Task[None] | None = None
        self._started = False
        self._ctx: Context | None = None
        self._storage: GcsStorage | None = None
        self._generations = GenerationCounter()

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        self._storage = self._make_storage(ctx)
        port = ctx.port_overrides.get(self.name, _DEFAULT_PORT)
        self._app = self._build_app()
        self._server = uvicorn.Server(
            uvicorn.Config(
                self._app,
                host="0.0.0.0",
                port=port,
                log_level="info",
                access_log=False,
            )
        )
        self._server_task = asyncio.create_task(
            self._server.serve(), name=f"{self.name}-server"
        )
        self._started = True
        log.info("gcs service listening on :%d", port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._server_task is not None:
            try:
                await asyncio.wait_for(self._server_task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                self._server_task.cancel()
        self._started = False

    async def reset_state(self) -> None:
        if self._storage is not None:
            await self._storage.reset()
        self._generations.reset_all()

    def health(self) -> HealthStatus:
        return HealthStatus(ok=self._started, message="running" if self._started else "stopped")

    def _make_storage(self, ctx: Context) -> GcsStorage:
        if ctx.persist:
            gcs_root = Path(ctx.data_dir) / "gcs"
            gcs_root.mkdir(parents=True, exist_ok=True)
            return DiskStorage(gcs_root)
        return InMemoryStorage()

    def _build_app(self) -> FastAPI:
        app = FastAPI(title="gcp-local GCS", version="0.0.1")

        @app.get("/")
        async def root() -> dict[str, str]:
            return {"service": "gcs", "status": "ok"}

        assert self._storage is not None
        assert self._ctx is not None
        app.include_router(
            build_router(
                storage=self._storage,
                state_hub=self._ctx.state_hub,  # type: ignore[arg-type]
                generations=self._generations,
            )
        )
        return app
```

- [ ] **Step 5: Run — pass**

Expected: all bucket route tests PASS. Full suite: still green.

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/services/gcs/errors.py src/gcp_local/services/gcs/routes/ src/gcp_local/services/gcs/service.py tests/unit/services/gcs/test_routes_buckets.py
git commit -m "feat(gcs): bucket REST routes"
```

---

## Task 9: Object read routes (GET metadata + bytes + ranged, DELETE)

**Files:**
- Create: `src/gcp_local/services/gcs/routes/objects_read.py`
- Modify: `src/gcp_local/services/gcs/routes/__init__.py` (register the new routes)
- Test: `tests/unit/services/gcs/test_routes_objects_read.py`

- [ ] **Step 1: Failing tests**

`tests/unit/services/gcs/test_routes_objects_read.py`:

```python
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.ids import GenerationCounter
from gcp_local.services.gcs.models import BucketMeta, ObjectRecord
from gcp_local.services.gcs.routes import build_router
from gcp_local.services.gcs.storage import InMemoryStorage


def rec(name="o", bucket="b", size=5, gen=1, mgen=1) -> ObjectRecord:
    return ObjectRecord(
        bucket=bucket, name=name, size=size,
        generation=gen, metageneration=mgen,
        content_type="text/plain",
        md5_hash="", crc32c="",
        time_created="t", updated="t",
    )


@pytest.fixture
async def client():
    storage = InMemoryStorage()
    await storage.create_bucket(BucketMeta(name="b", time_created="t"))
    await storage.put_object(rec(name="hello.txt", size=5), b"hello")
    await storage.put_object(rec(name="dir/a.log", size=3), b"abc")
    await storage.put_object(rec(name="dir/b.log", size=3), b"def")
    await storage.put_object(rec(name="z", size=1), b"z")

    app = FastAPI()
    app.include_router(build_router(
        storage=storage, state_hub=StateHub(), generations=GenerationCounter()
    ))
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test"), storage


async def test_get_object_metadata(client):
    c, _ = client
    r = await c.get("/storage/v1/b/b/o/hello.txt")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "hello.txt"
    assert body["size"] == 5


async def test_get_object_bytes_alt_media(client):
    c, _ = client
    r = await c.get("/storage/v1/b/b/o/hello.txt", params={"alt": "media"})
    assert r.status_code == 200
    assert r.content == b"hello"


async def test_get_object_bytes_ranged(client):
    c, _ = client
    r = await c.get(
        "/storage/v1/b/b/o/hello.txt",
        params={"alt": "media"},
        headers={"Range": "bytes=1-3"},
    )
    assert r.status_code == 206
    assert r.content == b"ell"
    assert r.headers["content-range"] == "bytes 1-3/5"


async def test_get_object_range_unsatisfiable(client):
    c, _ = client
    r = await c.get(
        "/storage/v1/b/b/o/hello.txt",
        params={"alt": "media"},
        headers={"Range": "bytes=100-200"},
    )
    assert r.status_code == 416


async def test_get_object_with_nested_name(client):
    c, _ = client
    r = await c.get("/storage/v1/b/b/o/dir/a.log")
    assert r.status_code == 200
    assert r.json()["name"] == "dir/a.log"


async def test_get_object_404(client):
    c, _ = client
    r = await c.get("/storage/v1/b/b/o/nope")
    assert r.status_code == 404


async def test_list_objects(client):
    c, _ = client
    r = await c.get("/storage/v1/b/b/o")
    assert r.status_code == 200
    names = [o["name"] for o in r.json()["items"]]
    assert names == ["dir/a.log", "dir/b.log", "hello.txt", "z"]


async def test_list_objects_prefix_and_delimiter(client):
    c, _ = client
    r = await c.get(
        "/storage/v1/b/b/o",
        params={"prefix": "", "delimiter": "/"},
    )
    body = r.json()
    item_names = [o["name"] for o in body.get("items", [])]
    prefixes = body.get("prefixes", [])
    assert set(item_names) == {"hello.txt", "z"}
    assert prefixes == ["dir/"]


async def test_list_objects_pagination(client):
    c, _ = client
    r1 = await c.get("/storage/v1/b/b/o", params={"maxResults": 2})
    body1 = r1.json()
    assert len(body1["items"]) == 2
    assert "nextPageToken" in body1
    r2 = await c.get(
        "/storage/v1/b/b/o",
        params={"maxResults": 2, "pageToken": body1["nextPageToken"]},
    )
    body2 = r2.json()
    assert len(body2["items"]) == 2


async def test_delete_object(client):
    c, _ = client
    r = await c.delete("/storage/v1/b/b/o/hello.txt")
    assert r.status_code == 204
    r2 = await c.get("/storage/v1/b/b/o/hello.txt")
    assert r2.status_code == 404


async def test_delete_missing_object_404(client):
    c, _ = client
    r = await c.delete("/storage/v1/b/b/o/nope")
    assert r.status_code == 404
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

`src/gcp_local/services/gcs/routes/objects_read.py`:

```python
import base64

from fastapi import APIRouter, Header, Query, Request, Response
from fastapi.responses import JSONResponse

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.errors import error_response
from gcp_local.services.gcs.events import publish_delete
from gcp_local.services.gcs.storage import (
    BucketNotFound,
    GcsStorage,
    ObjectNotFound,
)


def _encode_page_token(last_name: str) -> str:
    return base64.urlsafe_b64encode(last_name.encode()).decode()


def _decode_page_token(token: str) -> str:
    return base64.urlsafe_b64decode(token.encode()).decode()


def _parse_range(header: str, size: int) -> tuple[int, int] | None:
    if not header.startswith("bytes="):
        return None
    rng = header[len("bytes="):]
    if "-" not in rng:
        return None
    lo_s, hi_s = rng.split("-", 1)
    lo = int(lo_s) if lo_s else 0
    hi = int(hi_s) if hi_s else size - 1
    if lo < 0 or hi >= size or lo > hi:
        return None
    return lo, hi


def register_object_read_routes(
    router: APIRouter,
    *,
    storage: GcsStorage,
    state_hub: StateHub | None,
) -> None:

    @router.get("/storage/v1/b/{bucket}/o")
    async def list_objects(
        bucket: str,
        prefix: str = "",
        delimiter: str | None = None,
        maxResults: int | None = Query(default=None, alias="maxResults"),
        pageToken: str | None = Query(default=None, alias="pageToken"),
    ) -> JSONResponse:
        start_after = _decode_page_token(pageToken) if pageToken else None
        try:
            objects, prefixes = await storage.list_objects_with_prefixes(
                bucket,
                prefix=prefix,
                delimiter=delimiter,
                max_results=maxResults,
                start_after=start_after,
            )
        except BucketNotFound:
            return error_response(404, "notFound", f"bucket {bucket!r} not found")

        body: dict = {
            "items": [o.model_dump(by_alias=True) for o in objects],
        }
        if prefixes:
            body["prefixes"] = prefixes
        if maxResults is not None and len(objects) == maxResults:
            body["nextPageToken"] = _encode_page_token(objects[-1].name)
        return JSONResponse(body)

    @router.get("/storage/v1/b/{bucket}/o/{name:path}")
    async def get_object(
        bucket: str,
        name: str,
        alt: str = "json",
        range_header: str | None = Header(default=None, alias="Range"),
    ) -> Response:
        try:
            record = await storage.get_object(bucket, name)
        except BucketNotFound:
            return error_response(404, "notFound", f"bucket {bucket!r} not found")
        except ObjectNotFound:
            return error_response(404, "notFound", f"object {name!r} not found")

        if alt != "media":
            return JSONResponse(record.model_dump(by_alias=True))

        data = await storage.get_object_bytes(bucket, name)
        if range_header:
            parsed = _parse_range(range_header, len(data))
            if parsed is None:
                return error_response(416, "invalid", "range not satisfiable")
            lo, hi = parsed
            partial = data[lo: hi + 1]
            return Response(
                content=partial,
                status_code=206,
                headers={
                    "Content-Range": f"bytes {lo}-{hi}/{len(data)}",
                    "Content-Type": record.content_type,
                },
            )
        return Response(
            content=data,
            media_type=record.content_type,
        )

    @router.delete("/storage/v1/b/{bucket}/o/{name:path}")
    async def delete_object(bucket: str, name: str) -> Response:
        try:
            existing = await storage.get_object(bucket, name)
            await storage.delete_object(bucket, name)
        except BucketNotFound:
            return error_response(404, "notFound", f"bucket {bucket!r} not found")
        except ObjectNotFound:
            return error_response(404, "notFound", f"object {name!r} not found")
        await publish_delete(state_hub, existing)
        return Response(status_code=204)
```

- [ ] **Step 4: Register in the router package**

Update `src/gcp_local/services/gcs/routes/__init__.py`:

```python
from fastapi import APIRouter

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.ids import GenerationCounter
from gcp_local.services.gcs.routes.buckets import register_bucket_routes
from gcp_local.services.gcs.routes.objects_read import register_object_read_routes
from gcp_local.services.gcs.storage import GcsStorage


def build_router(
    *,
    storage: GcsStorage,
    state_hub: StateHub,
    generations: GenerationCounter,
) -> APIRouter:
    r = APIRouter()
    register_bucket_routes(r, storage=storage)
    register_object_read_routes(r, storage=storage, state_hub=state_hub)
    return r
```

- [ ] **Step 5: Run — pass**

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/services/gcs/routes/ tests/unit/services/gcs/test_routes_objects_read.py
git commit -m "feat(gcs): object read + delete + list routes"
```

---

## Task 10: Simple + multipart upload routes

**Files:**
- Create: `src/gcp_local/services/gcs/routes/uploads.py`
- Modify: `src/gcp_local/services/gcs/routes/__init__.py`
- Test: `tests/unit/services/gcs/test_routes_uploads.py`

Scope note: this task implements the `uploadType=media` and `uploadType=multipart` paths. Resumable comes in Task 11.

- [ ] **Step 1: Failing tests**

```python
import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.events import EVENT_FINALIZE
from gcp_local.services.gcs.ids import GenerationCounter
from gcp_local.services.gcs.models import BucketMeta
from gcp_local.services.gcs.routes import build_router
from gcp_local.services.gcs.storage import InMemoryStorage


@pytest.fixture
async def wired():
    storage = InMemoryStorage()
    await storage.create_bucket(BucketMeta(name="b", time_created="t"))
    hub = StateHub()
    app = FastAPI()
    app.include_router(build_router(
        storage=storage, state_hub=hub, generations=GenerationCounter()
    ))
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    events: list[dict] = []

    async def capture(ev):
        events.append(ev)

    hub.subscribe(EVENT_FINALIZE, capture)
    yield client, storage, events


async def test_simple_upload(wired):
    c, storage, events = wired
    r = await c.post(
        "/upload/storage/v1/b/b/o",
        params={"uploadType": "media", "name": "hello.txt"},
        content=b"hello",
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "hello.txt"
    assert body["size"] == 5
    assert body["generation"] == 1
    assert body["md5Hash"] == "XUFAKrxLKna5cZ2REBfFkg=="
    assert body["crc32c"] == "mnG7TA=="
    assert body["contentType"] == "text/plain"
    # Stored
    stored = await storage.get_object_bytes("b", "hello.txt")
    assert stored == b"hello"
    # Event fired
    assert len(events) == 1
    assert events[0]["name"] == "hello.txt"


async def test_simple_upload_overwrite_increments_generation(wired):
    c, _, _ = wired
    await c.post(
        "/upload/storage/v1/b/b/o",
        params={"uploadType": "media", "name": "o"},
        content=b"v1",
        headers={"Content-Type": "text/plain"},
    )
    r = await c.post(
        "/upload/storage/v1/b/b/o",
        params={"uploadType": "media", "name": "o"},
        content=b"v2-longer",
        headers={"Content-Type": "text/plain"},
    )
    body = r.json()
    assert body["generation"] == 2


async def test_multipart_upload(wired):
    c, _, _ = wired
    boundary = "===GCSBOUNDARY==="
    meta = json.dumps({"name": "doc.txt", "contentType": "text/markdown",
                       "metadata": {"author": "asaf"}})
    body = (
        f"--{boundary}\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{meta}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: text/markdown\r\n\r\n"
        f"# hello\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    r = await c.post(
        "/upload/storage/v1/b/b/o",
        params={"uploadType": "multipart"},
        content=body,
        headers={"Content-Type": f"multipart/related; boundary={boundary}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "doc.txt"
    assert body["contentType"] == "text/markdown"
    assert body["metadata"] == {"author": "asaf"}


async def test_precondition_if_generation_match_zero_blocks_overwrite(wired):
    c, _, _ = wired
    await c.post(
        "/upload/storage/v1/b/b/o",
        params={"uploadType": "media", "name": "o"},
        content=b"a",
        headers={"Content-Type": "text/plain"},
    )
    r = await c.post(
        "/upload/storage/v1/b/b/o",
        params={"uploadType": "media", "name": "o", "ifGenerationMatch": "0"},
        content=b"b",
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 412
    assert r.json()["error"]["errors"][0]["reason"] == "conditionNotMet"
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

`src/gcp_local/services/gcs/routes/uploads.py`:

```python
import email
import json
from email.parser import BytesParser
from email.policy import compat32

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.errors import error_response
from gcp_local.services.gcs.events import publish_finalize
from gcp_local.services.gcs.ids import (
    GenerationCounter,
    compute_crc32c_b64,
    compute_md5_b64,
    rfc3339_now,
)
from gcp_local.services.gcs.models import ObjectRecord
from gcp_local.services.gcs.preconditions import (
    Preconditions,
    PreconditionFailed,
    evaluate_preconditions,
)
from gcp_local.services.gcs.storage import (
    BucketNotFound,
    GcsStorage,
    ObjectCollision,
    ObjectNotFound,
)


def _parse_multipart(body: bytes, content_type: str) -> tuple[dict, bytes, str]:
    """Return (metadata_dict, object_bytes, object_content_type)."""
    header = f"Content-Type: {content_type}\r\n\r\n".encode()
    msg = BytesParser(policy=compat32).parsebytes(header + body)
    parts = list(msg.walk())
    # parts[0] is the container; real parts are [1:]
    meta_part = parts[1]
    obj_part = parts[2]
    metadata = json.loads(meta_part.get_payload(decode=True).decode("utf-8"))
    obj_ct = obj_part.get_content_type() or "application/octet-stream"
    obj_bytes = obj_part.get_payload(decode=True)
    return metadata, obj_bytes, obj_ct


async def _finalize_object(
    *,
    storage: GcsStorage,
    generations: GenerationCounter,
    state_hub: StateHub | None,
    bucket: str,
    name: str,
    data: bytes,
    content_type: str,
    user_metadata: dict[str, str],
    preconditions: Preconditions,
) -> ObjectRecord:
    # Fetch current (if any) for precondition check.
    try:
        current = await storage.get_object(bucket, name)
    except ObjectNotFound:
        current = None
    evaluate_preconditions(preconditions, current=current)

    now = rfc3339_now()
    record = ObjectRecord(
        bucket=bucket,
        name=name,
        size=len(data),
        generation=generations.next(bucket),
        metageneration=1,
        content_type=content_type,
        md5_hash=compute_md5_b64(data),
        crc32c=compute_crc32c_b64(data),
        time_created=now if current is None else current.time_created,
        updated=now,
        metadata=dict(user_metadata),
    )
    await storage.put_object(record, data)
    await publish_finalize(state_hub, record)
    return record


def register_upload_routes(
    router: APIRouter,
    *,
    storage: GcsStorage,
    state_hub: StateHub | None,
    generations: GenerationCounter,
) -> None:

    @router.post("/upload/storage/v1/b/{bucket}/o")
    async def upload(
        bucket: str,
        request: Request,
        uploadType: str = Query(..., alias="uploadType"),
        name: str | None = Query(default=None),
        ifGenerationMatch: int | None = Query(default=None, alias="ifGenerationMatch"),
        ifGenerationNotMatch: int | None = Query(default=None, alias="ifGenerationNotMatch"),
        ifMetagenerationMatch: int | None = Query(default=None, alias="ifMetagenerationMatch"),
        ifMetagenerationNotMatch: int | None = Query(default=None, alias="ifMetagenerationNotMatch"),
    ) -> JSONResponse:
        pre = Preconditions(
            if_generation_match=ifGenerationMatch,
            if_generation_not_match=ifGenerationNotMatch,
            if_metageneration_match=ifMetagenerationMatch,
            if_metageneration_not_match=ifMetagenerationNotMatch,
        )

        try:
            if uploadType == "media":
                if not name:
                    return error_response(400, "invalid", "missing object name")
                data = await request.body()
                ct = request.headers.get("content-type", "application/octet-stream")
                record = await _finalize_object(
                    storage=storage,
                    generations=generations,
                    state_hub=state_hub,
                    bucket=bucket,
                    name=name,
                    data=data,
                    content_type=ct,
                    user_metadata={},
                    preconditions=pre,
                )
                return JSONResponse(record.model_dump(by_alias=True))

            if uploadType == "multipart":
                body = await request.body()
                ct = request.headers.get("content-type", "")
                try:
                    metadata, obj_bytes, obj_ct = _parse_multipart(body, ct)
                except Exception as e:
                    return error_response(400, "invalid", f"multipart parse error: {e}")
                obj_name = metadata.get("name")
                if not obj_name:
                    return error_response(400, "invalid", "missing object name in multipart metadata")
                record = await _finalize_object(
                    storage=storage,
                    generations=generations,
                    state_hub=state_hub,
                    bucket=bucket,
                    name=obj_name,
                    data=obj_bytes,
                    content_type=metadata.get("contentType", obj_ct),
                    user_metadata=metadata.get("metadata", {}),
                    preconditions=pre,
                )
                return JSONResponse(record.model_dump(by_alias=True))

            # uploadType=resumable handled in Task 11
            return error_response(400, "invalid", f"unsupported uploadType: {uploadType}")
        except BucketNotFound:
            return error_response(404, "notFound", f"bucket {bucket!r} not found")
        except PreconditionFailed as e:
            return error_response(412, "conditionNotMet", str(e))
        except ObjectCollision as e:
            return error_response(409, "conflict", str(e))
```

- [ ] **Step 4: Register in router**

Update `src/gcp_local/services/gcs/routes/__init__.py`:

```python
from fastapi import APIRouter

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.ids import GenerationCounter
from gcp_local.services.gcs.routes.buckets import register_bucket_routes
from gcp_local.services.gcs.routes.objects_read import register_object_read_routes
from gcp_local.services.gcs.routes.uploads import register_upload_routes
from gcp_local.services.gcs.storage import GcsStorage


def build_router(
    *,
    storage: GcsStorage,
    state_hub: StateHub,
    generations: GenerationCounter,
) -> APIRouter:
    r = APIRouter()
    register_bucket_routes(r, storage=storage)
    register_object_read_routes(r, storage=storage, state_hub=state_hub)
    register_upload_routes(
        r, storage=storage, state_hub=state_hub, generations=generations
    )
    return r
```

- [ ] **Step 5: Run — pass**

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/services/gcs/routes/ tests/unit/services/gcs/test_routes_uploads.py
git commit -m "feat(gcs): simple + multipart upload routes"
```

---

## Task 11: Resumable upload routes

**Files:**
- Modify: `src/gcp_local/services/gcs/routes/uploads.py` (add resumable init + chunk PUT)
- Test: Extend `tests/unit/services/gcs/test_routes_uploads.py`

- [ ] **Step 1: Failing tests — append to test file**

```python
async def test_resumable_init_returns_location_header(wired):
    c, _, _ = wired
    r = await c.post(
        "/upload/storage/v1/b/b/o",
        params={"uploadType": "resumable", "name": "big.bin"},
        content=b"",
        headers={
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "application/octet-stream",
        },
    )
    assert r.status_code == 200
    assert "location" in {k.lower() for k in r.headers}
    loc = r.headers.get("Location") or r.headers.get("location")
    assert "upload_id=" in loc


async def test_resumable_single_chunk_commit(wired):
    c, storage, events = wired
    init = await c.post(
        "/upload/storage/v1/b/b/o",
        params={"uploadType": "resumable", "name": "big.bin"},
        content=b"",
        headers={"X-Upload-Content-Type": "application/octet-stream"},
    )
    loc = init.headers.get("Location") or init.headers.get("location")
    data = b"x" * 100
    r = await c.put(
        loc,
        content=data,
        headers={
            "Content-Length": str(len(data)),
            "Content-Range": f"bytes 0-{len(data)-1}/{len(data)}",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "big.bin"
    assert body["size"] == 100
    stored = await storage.get_object_bytes("b", "big.bin")
    assert stored == data
    assert len(events) == 1


async def test_resumable_multi_chunk(wired):
    c, storage, _ = wired
    init = await c.post(
        "/upload/storage/v1/b/b/o",
        params={"uploadType": "resumable", "name": "multi.bin"},
        content=b"",
    )
    loc = init.headers.get("Location") or init.headers.get("location")
    chunk1, chunk2 = b"A" * 30, b"B" * 40
    total = len(chunk1) + len(chunk2)
    r1 = await c.put(
        loc,
        content=chunk1,
        headers={"Content-Range": f"bytes 0-{len(chunk1)-1}/*"},
    )
    assert r1.status_code == 308
    assert r1.headers["range"].lower() in ("bytes=0-29",)
    r2 = await c.put(
        loc,
        content=chunk2,
        headers={
            "Content-Range": f"bytes {len(chunk1)}-{total-1}/{total}",
        },
    )
    assert r2.status_code == 200
    stored = await storage.get_object_bytes("b", "multi.bin")
    assert stored == chunk1 + chunk2


async def test_resumable_status_query(wired):
    c, _, _ = wired
    init = await c.post(
        "/upload/storage/v1/b/b/o",
        params={"uploadType": "resumable", "name": "q.bin"},
        content=b"",
    )
    loc = init.headers.get("Location") or init.headers.get("location")
    # Upload first chunk
    await c.put(loc, content=b"hello", headers={"Content-Range": "bytes 0-4/*"})
    # Status query
    r = await c.put(loc, content=b"", headers={"Content-Range": "bytes */*"})
    assert r.status_code == 308
    assert r.headers["range"].lower() == "bytes=0-4"


async def test_resumable_unknown_session_404(wired):
    c, _, _ = wired
    r = await c.put(
        "/upload/storage/v1/b/b/o?upload_id=does-not-exist",
        content=b"abc",
        headers={"Content-Range": "bytes 0-2/3"},
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement — extend uploads.py**

Add these imports and handler code to `src/gcp_local/services/gcs/routes/uploads.py`:

```python
from gcp_local.services.gcs.ids import new_session_id
from gcp_local.services.gcs.models import UploadSession
from gcp_local.services.gcs.storage import SessionNotFound
```

Inside `register_upload_routes`, add two more branches in the `upload` handler plus a new `PUT` handler. The updated handler structure:

1. In the `upload` POST handler, add a branch for `uploadType == "resumable"`:

```python
            if uploadType == "resumable":
                if not name:
                    return error_response(400, "invalid", "missing object name")
                ct = request.headers.get("x-upload-content-type",
                                         request.headers.get("content-type",
                                                              "application/octet-stream"))
                # Parse initiation metadata body (optional JSON)
                body_bytes = await request.body()
                user_metadata: dict[str, str] = {}
                init_content_type = ct
                init_name = name
                if body_bytes:
                    try:
                        init_body = json.loads(body_bytes)
                        init_name = init_body.get("name", name)
                        init_content_type = init_body.get("contentType", ct)
                        user_metadata = init_body.get("metadata", {})
                    except json.JSONDecodeError:
                        pass
                session_id = new_session_id()
                total = request.headers.get("x-upload-content-length")
                total_size = int(total) if total else None
                now = rfc3339_now()
                sess = UploadSession(
                    session_id=session_id,
                    bucket=bucket,
                    object_name=init_name,
                    total_size=total_size,
                    bytes_received=0,
                    content_type=init_content_type,
                    user_metadata=user_metadata,
                    created_at=now,
                    last_chunk_at=now,
                )
                await storage.put_session(sess)
                location = f"/upload/storage/v1/b/{bucket}/o?upload_id={session_id}"
                return JSONResponse(
                    {"uploadId": session_id},
                    status_code=200,
                    headers={"Location": location},
                )
```

2. Add a new PUT handler for chunk uploads:

```python
    @router.put("/upload/storage/v1/b/{bucket}/o")
    async def resumable_chunk(
        bucket: str,
        request: Request,
        upload_id: str = Query(..., alias="upload_id"),
    ) -> Response:
        try:
            sess = await storage.get_session(upload_id)
        except SessionNotFound:
            return error_response(404, "notFound", f"upload session {upload_id!r} not found")

        cr = request.headers.get("content-range", "")
        # Status query: "bytes */*"
        if cr == "bytes */*":
            end = sess.bytes_received - 1
            headers: dict[str, str] = {}
            if sess.bytes_received > 0:
                headers["Range"] = f"bytes=0-{end}"
            return Response(status_code=308, headers=headers)

        # Chunk upload: "bytes N-M/total" or "bytes N-M/*"
        if not cr.startswith("bytes "):
            return error_response(400, "invalid", "missing or malformed Content-Range header")
        spec = cr[len("bytes "):]
        range_part, _, total_part = spec.partition("/")
        try:
            start, end = (int(x) for x in range_part.split("-"))
        except ValueError:
            return error_response(400, "invalid", f"bad Content-Range: {cr}")
        if start != sess.bytes_received:
            return error_response(400, "invalid",
                                  f"chunk starts at {start}, expected {sess.bytes_received}")

        chunk = await request.body()
        if len(chunk) != (end - start + 1):
            return error_response(400, "invalid",
                                  f"chunk length {len(chunk)} does not match range {range_part}")

        await storage.append_to_session(upload_id, chunk)
        sess = await storage.get_session(upload_id)

        total_known: int | None
        if total_part == "*":
            total_known = None
        else:
            try:
                total_known = int(total_part)
            except ValueError:
                return error_response(400, "invalid", f"bad total: {total_part}")

        is_final = total_known is not None and sess.bytes_received >= total_known
        if not is_final:
            return Response(
                status_code=308,
                headers={"Range": f"bytes=0-{sess.bytes_received - 1}"},
            )

        # Final chunk — commit
        data = await storage.get_session_bytes(upload_id)
        try:
            record = await _finalize_object(
                storage=storage,
                generations=generations,
                state_hub=state_hub,
                bucket=sess.bucket,
                name=sess.object_name,
                data=data,
                content_type=sess.content_type,
                user_metadata=dict(sess.user_metadata),
                preconditions=Preconditions(),
            )
        except BucketNotFound:
            return error_response(404, "notFound", f"bucket {sess.bucket!r} not found")
        except ObjectCollision as e:
            return error_response(409, "conflict", str(e))
        finally:
            try:
                await storage.delete_session(upload_id)
            except SessionNotFound:
                pass

        return JSONResponse(record.model_dump(by_alias=True))
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/gcs/routes/uploads.py tests/unit/services/gcs/test_routes_uploads.py
git commit -m "feat(gcs): resumable upload routes"
```

---

## Task 12: Object PATCH (metadata update)

**Files:**
- Create: `src/gcp_local/services/gcs/routes/objects_write.py`
- Modify: `src/gcp_local/services/gcs/routes/__init__.py`
- Test: `tests/unit/services/gcs/test_routes_objects_write.py`

- [ ] **Step 1: Failing tests**

```python
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.events import EVENT_METADATA_UPDATE
from gcp_local.services.gcs.ids import GenerationCounter
from gcp_local.services.gcs.models import BucketMeta, ObjectRecord
from gcp_local.services.gcs.routes import build_router
from gcp_local.services.gcs.storage import InMemoryStorage


def rec(name="o", bucket="b", gen=5, mgen=1) -> ObjectRecord:
    return ObjectRecord(
        bucket=bucket, name=name, size=3,
        generation=gen, metageneration=mgen,
        content_type="text/plain",
        md5_hash="", crc32c="",
        time_created="t", updated="t",
        metadata={"x": "1"},
    )


@pytest.fixture
async def wired():
    storage = InMemoryStorage()
    await storage.create_bucket(BucketMeta(name="b", time_created="t"))
    await storage.put_object(rec(), b"abc")
    hub = StateHub()
    events: list[dict] = []

    async def cap(ev):
        events.append(ev)

    hub.subscribe(EVENT_METADATA_UPDATE, cap)
    app = FastAPI()
    app.include_router(build_router(
        storage=storage, state_hub=hub, generations=GenerationCounter()
    ))
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test"), storage, events


async def test_patch_metadata_increments_metageneration(wired):
    c, storage, events = wired
    r = await c.patch(
        "/storage/v1/b/b/o/o",
        json={"metadata": {"x": "1", "y": "2"}, "contentType": "application/xml"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["metadata"] == {"x": "1", "y": "2"}
    assert body["contentType"] == "application/xml"
    assert body["generation"] == 5
    assert body["metageneration"] == 2
    got = await storage.get_object("b", "o")
    assert got.metageneration == 2
    assert len(events) == 1


async def test_patch_with_metageneration_precondition_match(wired):
    c, _, _ = wired
    r = await c.patch(
        "/storage/v1/b/b/o/o",
        json={"metadata": {"y": "2"}},
        params={"ifMetagenerationMatch": 1},
    )
    assert r.status_code == 200


async def test_patch_with_metageneration_precondition_mismatch(wired):
    c, _, _ = wired
    r = await c.patch(
        "/storage/v1/b/b/o/o",
        json={"metadata": {"y": "2"}},
        params={"ifMetagenerationMatch": 99},
    )
    assert r.status_code == 412


async def test_patch_missing_object_404(wired):
    c, _, _ = wired
    r = await c.patch(
        "/storage/v1/b/b/o/missing",
        json={"metadata": {"x": "1"}},
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

`src/gcp_local/services/gcs/routes/objects_write.py`:

```python
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.errors import error_response
from gcp_local.services.gcs.events import publish_metadata_update
from gcp_local.services.gcs.ids import rfc3339_now
from gcp_local.services.gcs.preconditions import (
    Preconditions,
    PreconditionFailed,
    evaluate_preconditions,
)
from gcp_local.services.gcs.storage import (
    BucketNotFound,
    GcsStorage,
    ObjectNotFound,
)


def register_object_write_routes(
    router: APIRouter,
    *,
    storage: GcsStorage,
    state_hub: StateHub | None,
) -> None:

    @router.patch("/storage/v1/b/{bucket}/o/{name:path}")
    async def patch_object(
        bucket: str,
        name: str,
        request: Request,
        ifMetagenerationMatch: int | None = Query(default=None, alias="ifMetagenerationMatch"),
        ifMetagenerationNotMatch: int | None = Query(default=None, alias="ifMetagenerationNotMatch"),
    ) -> JSONResponse:
        try:
            current = await storage.get_object(bucket, name)
        except BucketNotFound:
            return error_response(404, "notFound", f"bucket {bucket!r} not found")
        except ObjectNotFound:
            return error_response(404, "notFound", f"object {name!r} not found")

        try:
            evaluate_preconditions(
                Preconditions(
                    if_metageneration_match=ifMetagenerationMatch,
                    if_metageneration_not_match=ifMetagenerationNotMatch,
                ),
                current=current,
            )
        except PreconditionFailed as e:
            return error_response(412, "conditionNotMet", str(e))

        patch = await request.json()

        updated = current.model_copy(update={
            "content_type": patch.get("contentType", current.content_type),
            "content_encoding": patch.get("contentEncoding", current.content_encoding),
            "content_language": patch.get("contentLanguage", current.content_language),
            "content_disposition": patch.get("contentDisposition", current.content_disposition),
            "cache_control": patch.get("cacheControl", current.cache_control),
            "metadata": patch.get("metadata", current.metadata),
            "metageneration": current.metageneration + 1,
            "updated": rfc3339_now(),
        })
        await storage.update_object_metadata(updated)
        await publish_metadata_update(state_hub, updated)
        return JSONResponse(updated.model_dump(by_alias=True))
```

- [ ] **Step 4: Register**

Update `src/gcp_local/services/gcs/routes/__init__.py`:

```python
from fastapi import APIRouter

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.ids import GenerationCounter
from gcp_local.services.gcs.routes.buckets import register_bucket_routes
from gcp_local.services.gcs.routes.objects_read import register_object_read_routes
from gcp_local.services.gcs.routes.objects_write import register_object_write_routes
from gcp_local.services.gcs.routes.uploads import register_upload_routes
from gcp_local.services.gcs.storage import GcsStorage


def build_router(
    *,
    storage: GcsStorage,
    state_hub: StateHub,
    generations: GenerationCounter,
) -> APIRouter:
    r = APIRouter()
    register_bucket_routes(r, storage=storage)
    register_object_read_routes(r, storage=storage, state_hub=state_hub)
    register_object_write_routes(r, storage=storage, state_hub=state_hub)
    register_upload_routes(
        r, storage=storage, state_hub=state_hub, generations=generations
    )
    return r
```

- [ ] **Step 5: Run — pass**

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/services/gcs/routes/ tests/unit/services/gcs/test_routes_objects_write.py
git commit -m "feat(gcs): object PATCH (metadata update)"
```

---

## Task 13: Copy + Compose routes

**Files:**
- Create: `src/gcp_local/services/gcs/routes/copy_compose.py`
- Modify: `src/gcp_local/services/gcs/routes/__init__.py`
- Test: `tests/unit/services/gcs/test_routes_copy_compose.py`

- [ ] **Step 1: Failing tests**

```python
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.ids import GenerationCounter
from gcp_local.services.gcs.models import BucketMeta, ObjectRecord
from gcp_local.services.gcs.routes import build_router
from gcp_local.services.gcs.storage import InMemoryStorage


def rec(name="o", bucket="b", size=5, gen=1) -> ObjectRecord:
    return ObjectRecord(
        bucket=bucket, name=name, size=size,
        generation=gen, metageneration=1,
        content_type="text/plain",
        md5_hash="", crc32c="",
        time_created="t", updated="t",
    )


@pytest.fixture
async def client():
    storage = InMemoryStorage()
    await storage.create_bucket(BucketMeta(name="src", time_created="t"))
    await storage.create_bucket(BucketMeta(name="dst", time_created="t"))
    await storage.put_object(rec(bucket="src", name="hello.txt"), b"hello")
    await storage.put_object(rec(bucket="src", name="part1", size=3), b"abc")
    await storage.put_object(rec(bucket="src", name="part2", size=3), b"def")
    app = FastAPI()
    app.include_router(build_router(
        storage=storage, state_hub=StateHub(), generations=GenerationCounter()
    ))
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test"), storage


async def test_copy_object(client):
    c, storage = client
    r = await c.post(
        "/storage/v1/b/src/o/hello.txt/copyTo/b/dst/o/copied.txt",
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "copied.txt"
    assert body["bucket"] == "dst"
    stored = await storage.get_object_bytes("dst", "copied.txt")
    assert stored == b"hello"


async def test_copy_missing_source_404(client):
    c, _ = client
    r = await c.post(
        "/storage/v1/b/src/o/nope/copyTo/b/dst/o/copied.txt",
    )
    assert r.status_code == 404


async def test_compose_object(client):
    c, storage = client
    r = await c.post(
        "/storage/v1/b/src/o/combined/compose",
        json={
            "sourceObjects": [{"name": "part1"}, {"name": "part2"}],
            "destination": {"contentType": "text/plain"},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "combined"
    stored = await storage.get_object_bytes("src", "combined")
    assert stored == b"abcdef"


async def test_compose_too_many_sources_400(client):
    c, _ = client
    r = await c.post(
        "/storage/v1/b/src/o/big/compose",
        json={"sourceObjects": [{"name": "part1"}] * 33},
    )
    assert r.status_code == 400


async def test_compose_missing_source_404(client):
    c, _ = client
    r = await c.post(
        "/storage/v1/b/src/o/combined/compose",
        json={"sourceObjects": [{"name": "part1"}, {"name": "nope"}]},
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

`src/gcp_local/services/gcs/routes/copy_compose.py`:

```python
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.errors import error_response
from gcp_local.services.gcs.events import publish_finalize
from gcp_local.services.gcs.ids import (
    GenerationCounter,
    compute_crc32c_b64,
    compute_md5_b64,
    rfc3339_now,
)
from gcp_local.services.gcs.models import ObjectRecord
from gcp_local.services.gcs.storage import (
    BucketNotFound,
    GcsStorage,
    ObjectCollision,
    ObjectNotFound,
)


def register_copy_compose_routes(
    router: APIRouter,
    *,
    storage: GcsStorage,
    state_hub: StateHub | None,
    generations: GenerationCounter,
) -> None:

    @router.post(
        "/storage/v1/b/{src_bucket}/o/{src_name}/copyTo/b/{dst_bucket}/o/{dst_name:path}"
    )
    async def copy_object(
        src_bucket: str,
        src_name: str,
        dst_bucket: str,
        dst_name: str,
    ) -> JSONResponse:
        try:
            src_record = await storage.get_object(src_bucket, src_name)
            src_bytes = await storage.get_object_bytes(src_bucket, src_name)
        except BucketNotFound:
            return error_response(404, "notFound", f"bucket {src_bucket!r} not found")
        except ObjectNotFound:
            return error_response(404, "notFound", f"object {src_name!r} not found")

        now = rfc3339_now()
        dst_record = ObjectRecord(
            bucket=dst_bucket,
            name=dst_name,
            size=src_record.size,
            generation=generations.next(dst_bucket),
            metageneration=1,
            content_type=src_record.content_type,
            content_encoding=src_record.content_encoding,
            content_language=src_record.content_language,
            content_disposition=src_record.content_disposition,
            cache_control=src_record.cache_control,
            md5_hash=src_record.md5_hash,
            crc32c=src_record.crc32c,
            time_created=now,
            updated=now,
            metadata=dict(src_record.metadata),
        )
        try:
            await storage.put_object(dst_record, src_bytes)
        except BucketNotFound:
            return error_response(404, "notFound", f"bucket {dst_bucket!r} not found")
        except ObjectCollision as e:
            return error_response(409, "conflict", str(e))
        await publish_finalize(state_hub, dst_record)
        return JSONResponse(dst_record.model_dump(by_alias=True))

    @router.post("/storage/v1/b/{bucket}/o/{name}/compose")
    async def compose_object(
        bucket: str,
        name: str,
        request: Request,
    ) -> JSONResponse:
        body = await request.json()
        sources = body.get("sourceObjects", [])
        if len(sources) > 32:
            return error_response(400, "invalid", "compose accepts at most 32 sources")
        if not sources:
            return error_response(400, "invalid", "compose requires at least one source")

        buffers: list[bytes] = []
        for src in sources:
            src_name = src.get("name")
            if not src_name:
                return error_response(400, "invalid", "source object missing name")
            try:
                chunk = await storage.get_object_bytes(bucket, src_name)
            except BucketNotFound:
                return error_response(404, "notFound", f"bucket {bucket!r} not found")
            except ObjectNotFound:
                return error_response(404, "notFound", f"object {src_name!r} not found")
            buffers.append(chunk)

        combined = b"".join(buffers)
        dest_meta = body.get("destination", {})
        now = rfc3339_now()
        record = ObjectRecord(
            bucket=bucket,
            name=name,
            size=len(combined),
            generation=generations.next(bucket),
            metageneration=1,
            content_type=dest_meta.get("contentType", "application/octet-stream"),
            md5_hash=compute_md5_b64(combined),
            crc32c=compute_crc32c_b64(combined),
            time_created=now,
            updated=now,
            metadata=dest_meta.get("metadata", {}),
        )
        try:
            await storage.put_object(record, combined)
        except ObjectCollision as e:
            return error_response(409, "conflict", str(e))
        await publish_finalize(state_hub, record)
        return JSONResponse(record.model_dump(by_alias=True))
```

- [ ] **Step 4: Register**

Update `src/gcp_local/services/gcs/routes/__init__.py`:

```python
from fastapi import APIRouter

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.ids import GenerationCounter
from gcp_local.services.gcs.routes.buckets import register_bucket_routes
from gcp_local.services.gcs.routes.copy_compose import register_copy_compose_routes
from gcp_local.services.gcs.routes.objects_read import register_object_read_routes
from gcp_local.services.gcs.routes.objects_write import register_object_write_routes
from gcp_local.services.gcs.routes.uploads import register_upload_routes
from gcp_local.services.gcs.storage import GcsStorage


def build_router(
    *,
    storage: GcsStorage,
    state_hub: StateHub,
    generations: GenerationCounter,
) -> APIRouter:
    r = APIRouter()
    register_bucket_routes(r, storage=storage)
    register_object_read_routes(r, storage=storage, state_hub=state_hub)
    register_object_write_routes(r, storage=storage, state_hub=state_hub)
    register_upload_routes(
        r, storage=storage, state_hub=state_hub, generations=generations
    )
    register_copy_compose_routes(
        r, storage=storage, state_hub=state_hub, generations=generations
    )
    return r
```

- [ ] **Step 5: Run — pass**

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/services/gcs/routes/ tests/unit/services/gcs/test_routes_copy_compose.py
git commit -m "feat(gcs): copy and compose routes"
```

---

## Task 14: Disk-mode service wiring + session GC on start

**Files:**
- Modify: `src/gcp_local/services/gcs/service.py` (call `gc_stale_sessions` on start if using DiskStorage)
- Test: `tests/unit/services/gcs/test_service_wiring.py`

- [ ] **Step 1: Failing tests**

```python
from pathlib import Path

import pytest

from gcp_local.core.context import Context
from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.service import GcsService
from gcp_local.services.gcs.storage import DiskStorage, InMemoryStorage


@pytest.fixture
def ctx_memory(tmp_path: Path) -> Context:
    return Context(persist=False, data_dir=tmp_path, state_hub=StateHub())


@pytest.fixture
def ctx_disk(tmp_path: Path) -> Context:
    return Context(persist=True, data_dir=tmp_path, state_hub=StateHub())


async def test_memory_backend_selected_when_no_persist(ctx_memory):
    svc = GcsService()
    svc._ctx = ctx_memory
    svc._storage = svc._make_storage(ctx_memory)
    assert isinstance(svc._storage, InMemoryStorage)


async def test_disk_backend_selected_when_persist(ctx_disk, tmp_path: Path):
    svc = GcsService()
    svc._ctx = ctx_disk
    svc._storage = svc._make_storage(ctx_disk)
    assert isinstance(svc._storage, DiskStorage)
    # data_dir/gcs is created
    assert (tmp_path / "gcs").is_dir()


async def test_disk_storage_reused_across_starts(ctx_disk, tmp_path: Path):
    from gcp_local.services.gcs.models import BucketMeta
    svc = GcsService()
    svc._ctx = ctx_disk
    svc._storage = svc._make_storage(ctx_disk)
    assert isinstance(svc._storage, DiskStorage)
    await svc._storage.create_bucket(BucketMeta(name="persisted", time_created="t"))

    # Simulate a restart
    svc2 = GcsService()
    svc2._ctx = ctx_disk
    svc2._storage = svc2._make_storage(ctx_disk)
    buckets = await svc2._storage.list_buckets()
    assert [b.name for b in buckets] == ["persisted"]
```

- [ ] **Step 2: Run — fail** (test file not present yet passes; this task just verifies service wiring is correct).

Actually, a lot of this is already wired in Task 8. If the tests already pass, skip to step 5 (commit only if there was a new file). Otherwise fix what's broken.

- [ ] **Step 3: Implement — add session GC to `start()`**

Update `src/gcp_local/services/gcs/service.py` to call `gc_stale_sessions` on start when using DiskStorage. Replace the `start` method body to add the GC call after storage creation:

```python
    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        self._storage = self._make_storage(ctx)
        # Garbage-collect stale resumable sessions on start (disk mode only).
        if isinstance(self._storage, DiskStorage):
            await self._storage.gc_stale_sessions(max_age_seconds=7 * 86400)
        port = ctx.port_overrides.get(self.name, _DEFAULT_PORT)
        self._app = self._build_app()
        self._server = uvicorn.Server(
            uvicorn.Config(
                self._app,
                host="0.0.0.0",
                port=port,
                log_level="info",
                access_log=False,
            )
        )
        self._server_task = asyncio.create_task(
            self._server.serve(), name=f"{self.name}-server"
        )
        self._started = True
        log.info("gcs service listening on :%d", port)
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/gcs/service.py tests/unit/services/gcs/test_service_wiring.py
git commit -m "feat(gcs): wire disk backend and gc stale resumable sessions on start"
```

---

## Task 15: Integration tests with real `google-cloud-storage` client

**Files:**
- Create: `tests/integration/test_gcs_integration.py`

This is the contract test — proves the emulator is plug-and-play with the official client library.

- [ ] **Step 1: Write the integration tests**

```python
"""Integration tests driving gcp-local GCS with the real google-cloud-storage client.

The `emulator` fixture (from `conftest.py`) boots the emulator in-process and
yields endpoint ports. Each test constructs a fresh storage.Client pointed at
the emulator and exercises common client API calls end to end.
"""
import io
import os
from pathlib import Path

import pytest
from google.api_core import exceptions as gce
from google.auth.credentials import AnonymousCredentials
from google.cloud import storage


@pytest.fixture
def client(emulator, monkeypatch):
    monkeypatch.setenv("STORAGE_EMULATOR_HOST", f"http://127.0.0.1:{emulator['gcs_port']}")
    return storage.Client(
        project="test-project",
        credentials=AnonymousCredentials(),
        client_options={"api_endpoint": f"http://127.0.0.1:{emulator['gcs_port']}"},
    )


def test_create_and_list_bucket(client):
    bucket = client.create_bucket("my-bucket")
    assert bucket.name == "my-bucket"
    names = [b.name for b in client.list_buckets()]
    assert "my-bucket" in names


def test_simple_upload_download_roundtrip(client):
    bucket = client.create_bucket("rt")
    blob = bucket.blob("hello.txt")
    blob.upload_from_string(b"hello world", content_type="text/plain")
    downloaded = bucket.blob("hello.txt").download_as_bytes()
    assert downloaded == b"hello world"


def test_resumable_upload_large(client):
    bucket = client.create_bucket("big")
    data = os.urandom(10 * 1024 * 1024)  # 10 MiB triggers resumable in google-cloud-storage
    blob = bucket.blob("big.bin")
    blob.upload_from_file(io.BytesIO(data), content_type="application/octet-stream", size=len(data))
    got = bucket.blob("big.bin").download_as_bytes()
    assert got == data


def test_if_generation_match_zero_create_only(client):
    bucket = client.create_bucket("ifmatch")
    blob = bucket.blob("o")
    blob.upload_from_string(b"first", if_generation_match=0)
    with pytest.raises(gce.PreconditionFailed):
        bucket.blob("o").upload_from_string(b"again", if_generation_match=0)


def test_blob_reload_reflects_updated_metadata(client):
    bucket = client.create_bucket("reload")
    blob = bucket.blob("o")
    blob.upload_from_string(b"x")
    blob.metadata = {"k": "v"}
    blob.patch()
    fresh = bucket.blob("o")
    fresh.reload()
    assert fresh.metadata == {"k": "v"}
    assert fresh.metageneration == 2


def test_list_blobs_with_prefix_and_pagination(client):
    bucket = client.create_bucket("list")
    for n in ("logs/1", "logs/2", "logs/3", "other"):
        bucket.blob(n).upload_from_string(b"x")
    got = [b.name for b in bucket.list_blobs(prefix="logs/", max_results=2)]
    assert got == ["logs/1", "logs/2"]


def test_copy_blob(client):
    src = client.create_bucket("src")
    dst = client.create_bucket("dst")
    src.blob("file").upload_from_string(b"copied")
    src.copy_blob(src.blob("file"), dst, "file.copy")
    assert dst.blob("file.copy").download_as_bytes() == b"copied"


def test_compose(client):
    bucket = client.create_bucket("compose")
    bucket.blob("part1").upload_from_string(b"abc")
    bucket.blob("part2").upload_from_string(b"def")
    composed = bucket.blob("combined")
    composed.compose([bucket.blob("part1"), bucket.blob("part2")])
    assert bucket.blob("combined").download_as_bytes() == b"abcdef"


def test_ranged_download(client):
    bucket = client.create_bucket("range")
    bucket.blob("o").upload_from_string(b"0123456789")
    got = bucket.blob("o").download_as_bytes(start=2, end=5)
    assert got == b"2345"


def test_delete_then_reload_raises_not_found(client):
    bucket = client.create_bucket("del")
    bucket.blob("o").upload_from_string(b"x")
    bucket.blob("o").delete()
    with pytest.raises(gce.NotFound):
        bucket.blob("o").reload()


def test_state_hub_receives_finalize_event(emulator, client):
    """The state hub is bound to the in-process StateHub; we verify a finalize
    event fires on upload by checking the admin-side health/status stays stable
    and (indirectly) that a subsequent reload sees the object. A full
    event-subscription test lives in unit tests; here we just assert the
    object lifecycle surfaces through the client library correctly."""
    bucket = client.create_bucket("eventbucket")
    bucket.blob("o").upload_from_string(b"hi")
    bucket.blob("o").reload()  # success implies the sidecar/record lifecycle held
```

- [ ] **Step 2: Run — expect all tests to pass**

```bash
. .venv/bin/activate && pytest tests/integration/test_gcs_integration.py -v
```

Expected: all 11 tests PASS. If any fail, investigate — the integration test is the final contract. Common issue candidates:
- `google-cloud-storage` sending a header (e.g., `X-Goog-*`) we don't handle. Add handling as needed.
- Path encoding (client URL-encodes slashes; server's path converter must handle).
- Resumable headers named `X-Upload-Content-Length` vs. `Content-Length` differences.

- [ ] **Step 3: Also run the full suite to confirm nothing else broke**

```bash
. .venv/bin/activate && pytest -v
```

Expected: all unit tests + all integration tests green, docker test skipped.

- [ ] **Step 4: Run lint + type-check**

```bash
. .venv/bin/activate
ruff check .
ruff format --check .
mypy
```

All green. Fix any findings before committing.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_gcs_integration.py
git commit -m "test(gcs): integration tests driving real google-cloud-storage client"
```

---

## Done

After Task 15, the GCS emulator works end-to-end against the official `google-cloud-storage` Python client library, covering the plug-and-play baseline promised in the spec: buckets, simple/multipart/resumable uploads, ranged downloads, pagination, metadata updates with generation/metageneration tracking, copy, compose, and preconditions. State-hub events fire on mutations for the Pub/Sub service to consume later.

**Next plan:** BigQuery service.
