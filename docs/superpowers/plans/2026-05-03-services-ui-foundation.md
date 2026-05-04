# Services UI — Foundation + GCS Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a React-based browser UI for `gcp-local` mounted on the admin port, with full GCS browse/create/delete/upload/download/preview as the pilot service. Establishes the foundation (ui-api namespace, web/ source tree, Vite+React+TS toolchain, CI+Docker wiring, dev workflow) that follow-up specs (BigQuery, Secret Manager, Pub/Sub, Firestore) layer onto.

**Architecture:** A new FastAPI router (`/_emulator/ui-api/v1/...`) on the existing admin app (port 4510) is a thin presenter over the same `GcsStorage` interface the GCS service uses — single source of truth, no extra wire hop. A new `web/` source tree (Vite + React + TypeScript) builds a SPA whose production bundle is committed-via-CI into `src/gcp_local/ui/static/`, mounted at `/ui/` on the admin app, and shipped in the wheel + Docker image.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, pytest, httpx; TypeScript, React 18, Vite 5, react-router-dom v6, vitest, React Testing Library, eslint; Node 20 LTS; Docker multi-stage build.

**Spec:** [`docs/superpowers/specs/2026-05-03-services-ui-design.md`](../specs/2026-05-03-services-ui-design.md)

---

## Conventions used in this plan

- Run all `pytest` and `ruff` commands from the repo root (`/Users/asafgallea/workspace/gcp-local`).
- Frontend commands run from `web/`.
- Every task ends with **commit**. Commits are atomic — one logical change per commit. Never use `--no-verify`.
- All new Python code uses `from __future__ import annotations` only if matching neighboring files; this repo doesn't, so omit it.
- Conventional Commits subject. Body explains the *why*.
- Before each task, ensure your tree is clean (`git status`) and you're on the feature branch (suggested: `feat/services-ui-foundation`).

---

## Phase A — ui-api scaffolding (Python, TDD)

### Task 1: Create the `ui_api` package and error envelope helper

**Files:**
- Create: `src/gcp_local/core/ui_api/__init__.py`
- Create: `src/gcp_local/core/ui_api/errors.py`
- Create: `tests/unit/core/__init__.py` (if missing)
- Create: `tests/unit/core/test_ui_api_errors.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/core/test_ui_api_errors.py`:

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gcp_local.core.ui_api.errors import UiApiError, register_error_handlers


def _app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/raises")
    def raises() -> None:
        raise UiApiError(status_code=404, code="not_found", message="missing")

    return app


def test_ui_api_error_returns_envelope() -> None:
    client = TestClient(_app())
    r = client.get("/raises")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "not_found", "message": "missing"}}


def test_unhandled_exception_returns_internal_envelope() -> None:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("kaboom")

    client = TestClient(app)
    r = client.get("/boom")
    assert r.status_code == 500
    body = r.json()
    assert body["error"]["code"] == "internal"
    assert "kaboom" not in body["error"]["message"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/core/test_ui_api_errors.py -v`
Expected: FAIL with ImportError on `gcp_local.core.ui_api.errors`.

- [ ] **Step 3: Create `src/gcp_local/core/ui_api/__init__.py`** (empty file).

- [ ] **Step 4: Implement `src/gcp_local/core/ui_api/errors.py`**

```python
"""Error envelope helpers for the internal ui-api.

The ui-api is consumed by the gcp-local browser UI only. Errors are returned
as ``{"error": {"code": str, "message": str}}`` and never leak stack traces,
filesystem paths, or secrets.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)


class UiApiError(Exception):
    """Raised by ui-api endpoints to produce a structured error response."""

    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _envelope(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(UiApiError)
    async def _handle_known(_request: Request, exc: UiApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=_envelope(exc.code, exc.message))

    @app.exception_handler(Exception)
    async def _handle_unknown(_request: Request, exc: Exception) -> JSONResponse:
        # Log the full exception for operators; return a generic message to clients.
        log.exception("ui-api internal error")
        return JSONResponse(
            status_code=500,
            content=_envelope("internal", "internal server error"),
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/core/test_ui_api_errors.py -v`
Expected: 2 tests pass.

- [ ] **Step 6: Lint + format**

Run: `ruff check src/gcp_local/core/ui_api tests/unit/core/test_ui_api_errors.py && ruff format src/gcp_local/core/ui_api tests/unit/core/test_ui_api_errors.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/gcp_local/core/ui_api/__init__.py src/gcp_local/core/ui_api/errors.py tests/unit/core/test_ui_api_errors.py tests/unit/core/__init__.py
git commit -m "feat(ui-api): add error envelope and exception handlers

Internal ui-api responses use {error: {code, message}} consistently,
hiding stack traces from the browser per the security posture in
docs/superpowers/specs/2026-05-03-services-ui-design.md."
```

---

### Task 2: ui-api router skeleton with `/services` endpoint

**Files:**
- Create: `src/gcp_local/core/ui_api/router.py`
- Create: `src/gcp_local/core/ui_api/schemas.py`
- Create: `tests/unit/core/test_ui_api_router.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/core/test_ui_api_router.py
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gcp_local.core.service import HealthStatus, Port
from gcp_local.core.ui_api.router import build_ui_api_router


class TinyService:
    def __init__(self, name: str, ports: list[Port]) -> None:
        self.name = name
        self.default_ports = ports

    async def start(self, ctx): ...
    async def stop(self): ...
    async def reset_state(self): ...
    def health(self) -> HealthStatus:
        return HealthStatus(ok=True, message="ok")


class FakeLifecycle:
    def __init__(self, services: list) -> None:
        self.services = services


def _client(lc) -> TestClient:
    app = FastAPI()
    app.include_router(build_ui_api_router(lc))
    return TestClient(app)


def test_services_endpoint_lists_services() -> None:
    lc = FakeLifecycle([
        TinyService("gcs", [Port(4443, "rest")]),
        TinyService("bigquery", [Port(9050, "rest")]),
    ])
    r = _client(lc).get("/_emulator/ui-api/v1/services")
    assert r.status_code == 200
    body = r.json()
    assert {s["name"] for s in body["services"]} == {"gcs", "bigquery"}
    gcs = next(s for s in body["services"] if s["name"] == "gcs")
    assert gcs["ports"] == [{"number": 4443, "protocol": "rest"}]
    assert gcs["ui_supported"] is True  # GCS UI ships in this PR


def test_unsupported_service_marked_false() -> None:
    lc = FakeLifecycle([TinyService("bigquery", [Port(9050, "rest")])])
    r = _client(lc).get("/_emulator/ui-api/v1/services")
    bq = r.json()["services"][0]
    assert bq["ui_supported"] is False
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/unit/core/test_ui_api_router.py -v`
Expected: ImportError on `build_ui_api_router`.

- [ ] **Step 3: Implement `src/gcp_local/core/ui_api/schemas.py`**

```python
"""Pydantic response models for the ui-api."""

from pydantic import BaseModel


class PortInfo(BaseModel):
    number: int
    protocol: str


class ServiceInfo(BaseModel):
    name: str
    ports: list[PortInfo]
    ui_supported: bool


class ServiceList(BaseModel):
    services: list[ServiceInfo]
```

- [ ] **Step 4: Implement `src/gcp_local/core/ui_api/router.py`**

```python
"""ui-api FastAPI router. Versioned ``v1``; explicitly internal."""

from fastapi import APIRouter

from gcp_local.core.lifecycle import Lifecycle
from gcp_local.core.ui_api.schemas import PortInfo, ServiceInfo, ServiceList

# Services that have a UI surface in this release. Extended as follow-up specs land.
UI_SUPPORTED_SERVICES = frozenset({"gcs"})


def build_ui_api_router(lc: Lifecycle) -> APIRouter:
    router = APIRouter(prefix="/_emulator/ui-api/v1")

    @router.get("/services", response_model=ServiceList)
    async def list_services() -> ServiceList:
        return ServiceList(
            services=[
                ServiceInfo(
                    name=s.name,
                    ports=[PortInfo(number=p.number, protocol=p.protocol) for p in s.default_ports],
                    ui_supported=s.name in UI_SUPPORTED_SERVICES,
                )
                for s in lc.services
            ],
        )

    return router
```

- [ ] **Step 5: Run the test**

Run: `pytest tests/unit/core/test_ui_api_router.py -v`
Expected: 2 tests pass.

- [ ] **Step 6: Lint + format + mypy**

Run: `ruff check src/gcp_local/core/ui_api tests/unit/core/test_ui_api_router.py && ruff format src/gcp_local/core/ui_api tests/unit/core/test_ui_api_router.py && mypy`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/gcp_local/core/ui_api/router.py src/gcp_local/core/ui_api/schemas.py tests/unit/core/test_ui_api_router.py
git commit -m "feat(ui-api): add router with /services endpoint

Versioned v1 namespace under /_emulator/ui-api. Marks ui-supported
services so the SPA can grey out tabs for ones without UI yet."
```

---

### Task 3: Mount ui-api router and error handlers in `admin_api`

**Files:**
- Modify: `src/gcp_local/core/admin_api.py`
- Modify: `tests/unit/test_admin_api.py`

- [ ] **Step 1: Add a failing test**

Append to `tests/unit/test_admin_api.py`:

```python
async def test_ui_api_services_endpoint_mounted(client) -> None:
    c, _, _ = client
    r = await c.get("/_emulator/ui-api/v1/services")
    assert r.status_code == 200
    body = r.json()
    assert {s["name"] for s in body["services"]} == {"a", "b"}


async def test_ui_api_uses_envelope_error_format(client) -> None:
    c, _, _ = client
    # Unknown ui-api path -> 404 from FastAPI default; the envelope handler is
    # only for UiApiError raises. Ensure the router mount doesn't shadow other
    # admin endpoints. Sanity-check that /_emulator/health still works.
    r = await c.get("/_emulator/health")
    assert r.status_code == 200
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/unit/test_admin_api.py -v`
Expected: `test_ui_api_services_endpoint_mounted` fails (404).

- [ ] **Step 3: Modify `src/gcp_local/core/admin_api.py`**

Update the file to mount the ui-api router and register error handlers:

```python
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from gcp_local.core.lifecycle import Lifecycle
from gcp_local.core.ui_api.errors import register_error_handlers
from gcp_local.core.ui_api.router import build_ui_api_router


def build_admin_app(lc: Lifecycle) -> FastAPI:
    app = FastAPI(title="gcp-local admin API", version="0.0.1")
    register_error_handlers(app)

    @app.get("/_emulator/health")
    async def health() -> JSONResponse:
        statuses = lc.health_all()
        overall = all(s.ok for s in statuses.values())
        return JSONResponse(
            {
                "ok": overall,
                "services": {
                    name: {"ok": s.ok, "message": s.message} for name, s in statuses.items()
                },
            }
        )

    @app.get("/_emulator/services")
    async def services() -> dict[str, Any]:
        return {
            "services": [
                {
                    "name": s.name,
                    "ports": [
                        {"number": p.number, "protocol": p.protocol} for p in s.default_ports
                    ],
                }
                for s in lc.services
            ]
        }

    @app.post("/_emulator/reset")
    async def reset(service: str | None = Query(default=None)) -> Response:
        if service is None:
            await lc.reset_all()
        else:
            try:
                await lc.reset(service)
            except KeyError:
                raise HTTPException(status_code=404, detail=f"unknown service: {service}") from None
        return Response(status_code=204)

    app.include_router(build_ui_api_router(lc))
    return app
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/unit/test_admin_api.py -v`
Expected: all admin tests + the two new tests pass.

- [ ] **Step 5: Lint + format + mypy**

Run: `ruff check src/gcp_local/core tests/unit/test_admin_api.py && ruff format src/gcp_local/core tests/unit/test_admin_api.py && mypy`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/core/admin_api.py tests/unit/test_admin_api.py
git commit -m "feat(ui-api): mount ui-api router on admin app

Wires /_emulator/ui-api/v1/* alongside the existing /_emulator/{health,
services,reset} endpoints and registers the envelope error handlers."
```

---

### Task 4: Expose `GcsService.storage` for ui-api consumption

**Files:**
- Modify: `src/gcp_local/services/gcs/service.py`
- Modify: `tests/unit/services/gcs/test_service_wiring.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/services/gcs/test_service_wiring.py`:

```python
async def test_storage_property_exposed_after_start(tmp_path):
    from gcp_local.core.context import Context
    from gcp_local.services.gcs import GcsService

    svc = GcsService()
    ctx = Context(persist=False, data_dir=tmp_path)
    await svc.start(ctx)
    try:
        assert svc.storage is not None
        # Sanity: callable behaves like a GcsStorage.
        buckets = await svc.storage.list_buckets()
        assert buckets == []
    finally:
        await svc.stop()


def test_storage_property_raises_before_start():
    from gcp_local.services.gcs import GcsService

    svc = GcsService()
    import pytest

    with pytest.raises(RuntimeError, match="not started"):
        _ = svc.storage
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/unit/services/gcs/test_service_wiring.py -v -k storage_property`
Expected: AttributeError on `svc.storage`.

- [ ] **Step 3: Modify `src/gcp_local/services/gcs/service.py`**

Add a public `storage` property right after the existing `health()` method:

```python
    @property
    def storage(self) -> GcsStorage:
        """The underlying storage backend.

        Exposed so the admin ui-api router can read/write GCS state without
        going through the wire-format REST API on port 4443. The wire surface
        and the ui-api therefore share a single source of truth.
        """
        if self._storage is None:
            raise RuntimeError("gcs service is not started")
        return self._storage
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/unit/services/gcs/test_service_wiring.py -v`
Expected: all wiring tests + new ones pass.

- [ ] **Step 5: Lint + format + mypy**

Run: `ruff check src/gcp_local/services/gcs tests/unit/services/gcs/test_service_wiring.py && ruff format src/gcp_local/services/gcs tests/unit/services/gcs/test_service_wiring.py && mypy`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/services/gcs/service.py tests/unit/services/gcs/test_service_wiring.py
git commit -m "feat(gcs): expose GcsService.storage publicly for ui-api

The ui-api router needs read/write access to the same storage backend the
GCS REST service uses. Adds a public property that raises before start."
```

---

## Phase B — ui-api GCS endpoints (Python, TDD)

> **Shared test fixture** (used by all tasks in this phase): place at `tests/unit/core/conftest.py`. Created in Task 5.

### Task 5: GCS Pydantic schemas + shared test fixture

**Files:**
- Create: `src/gcp_local/core/ui_api/gcs.py` (initial skeleton + schemas)
- Modify: `src/gcp_local/core/ui_api/router.py`
- Create: `tests/unit/core/conftest.py`

- [ ] **Step 1: Implement schemas in `src/gcp_local/core/ui_api/gcs.py`**

```python
"""ui-api GCS endpoints.

Thin presenter layer over ``GcsStorage``. Returns UI-shaped responses
(computed sizes, friendly timestamps, preview metadata) rather than the
Google wire-format that the public REST API on port 4443 emits.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from gcp_local.core.lifecycle import Lifecycle
from gcp_local.core.ui_api.errors import UiApiError
from gcp_local.services.gcs.storage import (
    BucketAlreadyExists,
    BucketNotFound,
    GcsStorage,
    ObjectNotFound,
)


# ---- Schemas ---------------------------------------------------------------


class BucketSummary(BaseModel):
    name: str
    location: str
    storage_class: str
    time_created: str


class BucketList(BaseModel):
    buckets: list[BucketSummary]


class CreateBucketRequest(BaseModel):
    name: str
    location: str = "US"


class BlobSummary(BaseModel):
    name: str
    size: int
    content_type: str
    updated: str
    generation: int


class BlobList(BaseModel):
    bucket: str
    prefix: str
    blobs: list[BlobSummary]
    folders: list[str]
    next_page_token: str | None = None


class BlobMetadata(BaseModel):
    bucket: str
    name: str
    size: int
    content_type: str
    time_created: str
    updated: str
    generation: int
    metageneration: int
    md5_hash: str
    crc32c: str
    metadata: dict[str, str]
    preview: "BlobPreview | None" = None


class BlobPreview(BaseModel):
    kind: Literal["text", "json", "image", "none"]
    text: str | None = None
    image_data_url: str | None = None
    truncated: bool = False
    reason: str | None = None  # populated when kind == "none"


BlobMetadata.model_rebuild()


# ---- Helpers ---------------------------------------------------------------


def _get_storage(lc: Lifecycle) -> GcsStorage:
    for svc in lc.services:
        if svc.name == "gcs":
            # Imported lazily so non-gcs builds don't pay the cost.
            from gcp_local.services.gcs.service import GcsService

            assert isinstance(svc, GcsService)
            return svc.storage
    raise UiApiError(
        status_code=503,
        code="service_unavailable",
        message="gcs service is not running",
    )


def _storage_dep(request: Request) -> GcsStorage:
    lc: Lifecycle = request.app.state.lifecycle
    return _get_storage(lc)


StorageDep = Annotated[GcsStorage, Depends(_storage_dep)]


# ---- Endpoints (implemented in subsequent tasks) ---------------------------


def build_gcs_router() -> APIRouter:
    router = APIRouter(prefix="/gcs", tags=["gcs"])
    return router
```

- [ ] **Step 2: Wire `app.state.lifecycle` and include the gcs router in `router.py`**

Modify `src/gcp_local/core/ui_api/router.py`:

```python
"""ui-api FastAPI router. Versioned ``v1``; explicitly internal."""

from fastapi import APIRouter

from gcp_local.core.lifecycle import Lifecycle
from gcp_local.core.ui_api.gcs import build_gcs_router
from gcp_local.core.ui_api.schemas import PortInfo, ServiceInfo, ServiceList

UI_SUPPORTED_SERVICES = frozenset({"gcs"})


def build_ui_api_router(lc: Lifecycle) -> APIRouter:
    router = APIRouter(prefix="/_emulator/ui-api/v1")

    @router.get("/services", response_model=ServiceList)
    async def list_services() -> ServiceList:
        return ServiceList(
            services=[
                ServiceInfo(
                    name=s.name,
                    ports=[PortInfo(number=p.number, protocol=p.protocol) for p in s.default_ports],
                    ui_supported=s.name in UI_SUPPORTED_SERVICES,
                )
                for s in lc.services
            ],
        )

    router.include_router(build_gcs_router())
    return router
```

- [ ] **Step 3: Stash the lifecycle on `app.state` in `admin_api.py`**

Modify `src/gcp_local/core/admin_api.py` — after `app = FastAPI(...)`:

```python
    app = FastAPI(title="gcp-local admin API", version="0.0.1")
    app.state.lifecycle = lc
    register_error_handlers(app)
```

- [ ] **Step 4: Create the shared test fixture `tests/unit/core/conftest.py`**

```python
"""Shared fixtures for ui-api tests.

Provides a fully-wired admin app whose only running service is GCS in
in-memory mode, plus a real ``GcsStorage`` so tests can seed state.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from gcp_local.core.admin_api import build_admin_app
from gcp_local.core.context import Context
from gcp_local.core.lifecycle import Lifecycle
from gcp_local.services.gcs import GcsService


@pytest.fixture
async def gcs_ui_client(tmp_path: Path) -> AsyncIterator[tuple[AsyncClient, GcsService]]:
    svc = GcsService()
    ctx = Context(persist=False, data_dir=tmp_path)
    lc = Lifecycle([svc], ctx)
    await lc.start_all()
    try:
        app = build_admin_app(lc)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, svc
    finally:
        await lc.stop_all()
```

- [ ] **Step 5: Run all touched tests to verify nothing broke**

Run: `pytest tests/unit/core tests/unit/services/gcs/test_service_wiring.py tests/unit/test_admin_api.py -v`
Expected: all green; previously-passing tests still pass.

- [ ] **Step 6: Lint + format + mypy**

Run: `ruff check src/gcp_local/core tests/unit/core && ruff format src/gcp_local/core tests/unit/core && mypy`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/gcp_local/core/ui_api/gcs.py src/gcp_local/core/ui_api/router.py src/gcp_local/core/admin_api.py tests/unit/core/conftest.py
git commit -m "feat(ui-api): scaffold gcs router with schemas and storage dep

Adds ui-api/v1/gcs router skeleton, Pydantic response models, and a
storage dependency that reads from app.state.lifecycle. Endpoints are
filled in by subsequent commits."
```

---

### Task 6: `GET /gcs/buckets` — list buckets

**Files:**
- Modify: `src/gcp_local/core/ui_api/gcs.py`
- Create: `tests/unit/core/test_ui_api_gcs_buckets.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/core/test_ui_api_gcs_buckets.py
from gcp_local.services.gcs.models import BucketMeta


async def test_list_buckets_empty(gcs_ui_client) -> None:
    client, _ = gcs_ui_client
    r = await client.get("/_emulator/ui-api/v1/gcs/buckets")
    assert r.status_code == 200
    assert r.json() == {"buckets": []}


async def test_list_buckets_returns_seeded(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await svc.storage.create_bucket(
        BucketMeta(name="alpha", time_created="2026-05-03T10:00:00Z", location="US")
    )
    await svc.storage.create_bucket(
        BucketMeta(name="beta", time_created="2026-05-03T10:01:00Z", location="EU")
    )
    r = await client.get("/_emulator/ui-api/v1/gcs/buckets")
    assert r.status_code == 200
    body = r.json()
    names = [b["name"] for b in body["buckets"]]
    assert names == ["alpha", "beta"]
    assert body["buckets"][1]["location"] == "EU"
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/unit/core/test_ui_api_gcs_buckets.py -v`
Expected: 404 — endpoint not implemented.

- [ ] **Step 3: Implement the endpoint**

In `src/gcp_local/core/ui_api/gcs.py`, replace `build_gcs_router` with:

```python
def build_gcs_router() -> APIRouter:
    router = APIRouter(prefix="/gcs", tags=["gcs"])

    @router.get("/buckets", response_model=BucketList)
    async def list_buckets(storage: StorageDep) -> BucketList:
        buckets = await storage.list_buckets()
        return BucketList(
            buckets=[
                BucketSummary(
                    name=b.name,
                    location=b.location,
                    storage_class=b.storage_class,
                    time_created=b.time_created,
                )
                for b in buckets
            ],
        )

    return router
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/unit/core/test_ui_api_gcs_buckets.py -v`
Expected: 2 tests pass.

- [ ] **Step 5: Lint + format**

Run: `ruff check src/gcp_local/core/ui_api tests/unit/core/test_ui_api_gcs_buckets.py && ruff format src/gcp_local/core/ui_api tests/unit/core/test_ui_api_gcs_buckets.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/core/ui_api/gcs.py tests/unit/core/test_ui_api_gcs_buckets.py
git commit -m "feat(ui-api): GET /gcs/buckets lists buckets"
```

---

### Task 7: `POST /gcs/buckets` — create bucket

**Files:**
- Modify: `src/gcp_local/core/ui_api/gcs.py`
- Modify: `tests/unit/core/test_ui_api_gcs_buckets.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/core/test_ui_api_gcs_buckets.py`:

```python
async def test_create_bucket_creates_and_returns_summary(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    r = await client.post(
        "/_emulator/ui-api/v1/gcs/buckets", json={"name": "new-bucket", "location": "EU"}
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "new-bucket"
    assert body["location"] == "EU"
    # Verify storage actually has it.
    buckets = await svc.storage.list_buckets()
    assert [b.name for b in buckets] == ["new-bucket"]


async def test_create_bucket_conflict_returns_envelope(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    from gcp_local.services.gcs.models import BucketMeta

    await svc.storage.create_bucket(
        BucketMeta(name="dup", time_created="2026-05-03T10:00:00Z")
    )
    r = await client.post("/_emulator/ui-api/v1/gcs/buckets", json={"name": "dup"})
    assert r.status_code == 409
    assert r.json() == {"error": {"code": "already_exists", "message": "bucket 'dup' already exists"}}


async def test_create_bucket_invalid_name_returns_400(gcs_ui_client) -> None:
    client, _ = gcs_ui_client
    # Pydantic enforces "name" as a string; an empty string is allowed by the schema
    # but the storage layer or our validator rejects it.
    r = await client.post("/_emulator/ui-api/v1/gcs/buckets", json={"name": ""})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_argument"
```

- [ ] **Step 2: Run tests — expect 3 failures.**

Run: `pytest tests/unit/core/test_ui_api_gcs_buckets.py -v`

- [ ] **Step 3: Implement the endpoint**

Add inside `build_gcs_router`, after the list_buckets handler:

```python
    @router.post(
        "/buckets",
        response_model=BucketSummary,
        status_code=201,
    )
    async def create_bucket(payload: CreateBucketRequest, storage: StorageDep) -> BucketSummary:
        if not payload.name.strip():
            raise UiApiError(
                status_code=400,
                code="invalid_argument",
                message="bucket name must not be empty",
            )
        from datetime import datetime, timezone

        from gcp_local.services.gcs.models import BucketMeta

        meta = BucketMeta(
            name=payload.name,
            time_created=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            location=payload.location,
        )
        try:
            await storage.create_bucket(meta)
        except BucketAlreadyExists:
            raise UiApiError(
                status_code=409,
                code="already_exists",
                message=f"bucket '{payload.name}' already exists",
            ) from None
        return BucketSummary(
            name=meta.name,
            location=meta.location,
            storage_class=meta.storage_class,
            time_created=meta.time_created,
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/core/test_ui_api_gcs_buckets.py -v`
Expected: all 5 tests pass.

- [ ] **Step 5: Lint + format + mypy**

Run: `ruff check src/gcp_local/core/ui_api tests/unit/core && ruff format src/gcp_local/core/ui_api tests/unit/core && mypy`

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/core/ui_api/gcs.py tests/unit/core/test_ui_api_gcs_buckets.py
git commit -m "feat(ui-api): POST /gcs/buckets creates a bucket

Returns 201 + summary on success, 409 on duplicate, 400 on empty name."
```

---

### Task 8: `DELETE /gcs/buckets/{bucket}` — delete bucket (with `?force`)

**Files:**
- Modify: `src/gcp_local/core/ui_api/gcs.py`
- Create: `tests/unit/core/test_ui_api_gcs_bucket_delete.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/core/test_ui_api_gcs_bucket_delete.py
from gcp_local.services.gcs.models import BucketMeta, ObjectRecord


async def _seed_bucket(svc, name="b") -> None:
    await svc.storage.create_bucket(
        BucketMeta(name=name, time_created="2026-05-03T10:00:00Z")
    )


async def _seed_object(svc, bucket="b", name="x") -> None:
    await svc.storage.put_object(
        ObjectRecord(
            bucket=bucket,
            name=name,
            size=3,
            generation=1,
            metageneration=1,
            md5_hash="x",
            crc32c="x",
            time_created="2026-05-03T10:01:00Z",
            updated="2026-05-03T10:01:00Z",
        ),
        b"abc",
    )


async def test_delete_empty_bucket(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await _seed_bucket(svc)
    r = await client.delete("/_emulator/ui-api/v1/gcs/buckets/b")
    assert r.status_code == 204
    assert await svc.storage.list_buckets() == []


async def test_delete_unknown_bucket_404(gcs_ui_client) -> None:
    client, _ = gcs_ui_client
    r = await client.delete("/_emulator/ui-api/v1/gcs/buckets/missing")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


async def test_delete_non_empty_bucket_without_force_returns_409(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await _seed_bucket(svc)
    await _seed_object(svc)
    r = await client.delete("/_emulator/ui-api/v1/gcs/buckets/b")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "not_empty"


async def test_delete_non_empty_bucket_with_force_succeeds(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await _seed_bucket(svc)
    await _seed_object(svc)
    r = await client.delete("/_emulator/ui-api/v1/gcs/buckets/b?force=true")
    assert r.status_code == 204
    assert await svc.storage.list_buckets() == []
```

- [ ] **Step 2: Run tests — expect 4 failures.**

Run: `pytest tests/unit/core/test_ui_api_gcs_bucket_delete.py -v`

- [ ] **Step 3: Implement the endpoint**

Add inside `build_gcs_router`:

```python
    @router.delete("/buckets/{bucket}", status_code=204)
    async def delete_bucket(
        bucket: str,
        storage: StorageDep,
        force: bool = Query(default=False),
    ) -> Response:
        try:
            await storage.get_bucket(bucket)
        except BucketNotFound:
            raise UiApiError(
                status_code=404,
                code="not_found",
                message=f"bucket '{bucket}' not found",
            ) from None
        objects, _ = await storage.list_objects_with_prefixes(bucket)
        if objects:
            if not force:
                raise UiApiError(
                    status_code=409,
                    code="not_empty",
                    message=f"bucket '{bucket}' is not empty; pass force=true to delete contents",
                )
            for obj in objects:
                await storage.delete_object(bucket, obj.name)
        await storage.delete_bucket(bucket)
        return Response(status_code=204)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/core/test_ui_api_gcs_bucket_delete.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: Lint + format + mypy**

Run: `ruff check src/gcp_local/core/ui_api tests/unit/core && ruff format src/gcp_local/core/ui_api tests/unit/core && mypy`

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/core/ui_api/gcs.py tests/unit/core/test_ui_api_gcs_bucket_delete.py
git commit -m "feat(ui-api): DELETE /gcs/buckets/{bucket} with force flag"
```

---

### Task 9: `GET /gcs/buckets/{bucket}/blobs` — list blobs (prefix/delimiter/page)

**Files:**
- Modify: `src/gcp_local/core/ui_api/gcs.py`
- Create: `tests/unit/core/test_ui_api_gcs_blobs_list.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/core/test_ui_api_gcs_blobs_list.py
from gcp_local.services.gcs.models import BucketMeta, ObjectRecord


async def _seed(svc, names: list[str]) -> None:
    await svc.storage.create_bucket(
        BucketMeta(name="b", time_created="2026-05-03T10:00:00Z")
    )
    for n in names:
        await svc.storage.put_object(
            ObjectRecord(
                bucket="b",
                name=n,
                size=len(n),
                generation=1,
                metageneration=1,
                md5_hash="x",
                crc32c="x",
                content_type="text/plain",
                time_created="2026-05-03T10:01:00Z",
                updated="2026-05-03T10:01:00Z",
            ),
            n.encode(),
        )


async def test_list_blobs_flat(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await _seed(svc, ["a.txt", "b.txt"])
    r = await client.get("/_emulator/ui-api/v1/gcs/buckets/b/blobs")
    assert r.status_code == 200
    body = r.json()
    assert body["bucket"] == "b"
    assert body["prefix"] == ""
    assert {x["name"] for x in body["blobs"]} == {"a.txt", "b.txt"}
    assert body["folders"] == []


async def test_list_blobs_with_prefix_and_delimiter_returns_folders(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await _seed(svc, ["a.txt", "logs/2026/01.log", "logs/2026/02.log", "logs/2025/12.log"])
    r = await client.get(
        "/_emulator/ui-api/v1/gcs/buckets/b/blobs",
        params={"prefix": "logs/", "delimiter": "/"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["prefix"] == "logs/"
    assert body["blobs"] == []  # Everything under logs/ is itself prefixed by another /
    assert sorted(body["folders"]) == ["logs/2025/", "logs/2026/"]


async def test_list_blobs_unknown_bucket_404(gcs_ui_client) -> None:
    client, _ = gcs_ui_client
    r = await client.get("/_emulator/ui-api/v1/gcs/buckets/missing/blobs")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
```

- [ ] **Step 2: Run tests — expect 3 failures.**

Run: `pytest tests/unit/core/test_ui_api_gcs_blobs_list.py -v`

- [ ] **Step 3: Implement the endpoint**

Add inside `build_gcs_router`:

```python
    @router.get(
        "/buckets/{bucket}/blobs",
        response_model=BlobList,
    )
    async def list_blobs(
        bucket: str,
        storage: StorageDep,
        prefix: str = Query(default=""),
        delimiter: str | None = Query(default=None),
        page_size: int = Query(default=1000, ge=1, le=1000),
        page_token: str | None = Query(default=None),
    ) -> BlobList:
        try:
            await storage.get_bucket(bucket)
        except BucketNotFound:
            raise UiApiError(
                status_code=404,
                code="not_found",
                message=f"bucket '{bucket}' not found",
            ) from None
        objects, prefixes = await storage.list_objects_with_prefixes(
            bucket,
            prefix=prefix,
            delimiter=delimiter,
            max_results=page_size + 1,
            start_after=page_token,
        )
        next_token: str | None = None
        if len(objects) > page_size:
            objects = objects[:page_size]
            next_token = objects[-1].name
        return BlobList(
            bucket=bucket,
            prefix=prefix,
            blobs=[
                BlobSummary(
                    name=o.name,
                    size=o.size,
                    content_type=o.content_type,
                    updated=o.updated,
                    generation=o.generation,
                )
                for o in objects
            ],
            folders=sorted(prefixes),
            next_page_token=next_token,
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/core/test_ui_api_gcs_blobs_list.py -v`
Expected: 3 pass.

- [ ] **Step 5: Lint + format + mypy**

Run: `ruff check src/gcp_local/core/ui_api tests/unit/core && ruff format src/gcp_local/core/ui_api tests/unit/core && mypy`

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/core/ui_api/gcs.py tests/unit/core/test_ui_api_gcs_blobs_list.py
git commit -m "feat(ui-api): list blobs with prefix/delimiter/page support"
```

---

### Task 10: `POST /gcs/buckets/{bucket}/blobs` — multipart upload with size cap

**Files:**
- Modify: `src/gcp_local/core/ui_api/gcs.py`
- Create: `tests/unit/core/test_ui_api_gcs_blobs_upload.py`
- Modify: `src/gcp_local/core/ui_api/gcs.py` (env-var size cap)

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/core/test_ui_api_gcs_blobs_upload.py
import io

from gcp_local.services.gcs.models import BucketMeta


async def _seed_bucket(svc) -> None:
    await svc.storage.create_bucket(BucketMeta(name="b", time_created="2026-05-03T10:00:00Z"))


async def test_upload_creates_blob(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await _seed_bucket(svc)
    r = await client.post(
        "/_emulator/ui-api/v1/gcs/buckets/b/blobs",
        files={"file": ("hello.txt", io.BytesIO(b"hi there"), "text/plain")},
        data={"name": "hello.txt"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "hello.txt"
    assert body["size"] == 8
    record = await svc.storage.get_object("b", "hello.txt")
    assert record.size == 8
    assert (await svc.storage.get_object_bytes("b", "hello.txt")) == b"hi there"


async def test_upload_uses_filename_when_name_missing(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await _seed_bucket(svc)
    r = await client.post(
        "/_emulator/ui-api/v1/gcs/buckets/b/blobs",
        files={"file": ("auto.txt", io.BytesIO(b"hi"), "text/plain")},
    )
    assert r.status_code == 201
    assert r.json()["name"] == "auto.txt"


async def test_upload_unknown_bucket_404(gcs_ui_client) -> None:
    client, _ = gcs_ui_client
    r = await client.post(
        "/_emulator/ui-api/v1/gcs/buckets/missing/blobs",
        files={"file": ("x.txt", io.BytesIO(b"x"), "text/plain")},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


async def test_upload_too_large_returns_413(gcs_ui_client, monkeypatch) -> None:
    client, svc = gcs_ui_client
    await _seed_bucket(svc)
    monkeypatch.setenv("GCP_LOCAL_UI_MAX_UPLOAD_MB", "0")  # cap = 0 MB -> any file too large
    r = await client.post(
        "/_emulator/ui-api/v1/gcs/buckets/b/blobs",
        files={"file": ("x.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"
```

- [ ] **Step 2: Run — expect 4 failures.**

Run: `pytest tests/unit/core/test_ui_api_gcs_blobs_upload.py -v`

- [ ] **Step 3: Implement the endpoint**

Add inside `build_gcs_router`:

```python
    @router.post(
        "/buckets/{bucket}/blobs",
        response_model=BlobSummary,
        status_code=201,
    )
    async def upload_blob(
        bucket: str,
        storage: StorageDep,
        file: UploadFile = File(...),
        name: str | None = Form(default=None),
    ) -> BlobSummary:
        import os

        from datetime import datetime, timezone

        from gcp_local.services.gcs.models import ObjectRecord

        try:
            await storage.get_bucket(bucket)
        except BucketNotFound:
            raise UiApiError(
                status_code=404,
                code="not_found",
                message=f"bucket '{bucket}' not found",
            ) from None

        cap_mb = int(os.environ.get("GCP_LOCAL_UI_MAX_UPLOAD_MB", "100"))
        cap_bytes = cap_mb * 1024 * 1024
        data = await file.read()
        if len(data) > cap_bytes:
            raise UiApiError(
                status_code=413,
                code="payload_too_large",
                message=f"upload exceeds {cap_mb} MB cap (set GCP_LOCAL_UI_MAX_UPLOAD_MB to raise)",
            )

        blob_name = (name or file.filename or "").strip()
        if not blob_name:
            raise UiApiError(
                status_code=400,
                code="invalid_argument",
                message="blob name is required (provide ?name= or upload with a filename)",
            )

        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        record = ObjectRecord(
            bucket=bucket,
            name=blob_name,
            size=len(data),
            generation=1,
            metageneration=1,
            content_type=file.content_type or "application/octet-stream",
            md5_hash="",
            crc32c="",
            time_created=now,
            updated=now,
        )
        await storage.put_object(record, data)
        return BlobSummary(
            name=record.name,
            size=record.size,
            content_type=record.content_type,
            updated=record.updated,
            generation=record.generation,
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/core/test_ui_api_gcs_blobs_upload.py -v`
Expected: 4 pass.

- [ ] **Step 5: Lint + format + mypy**

Run: `ruff check src/gcp_local/core/ui_api tests/unit/core && ruff format src/gcp_local/core/ui_api tests/unit/core && mypy`

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/core/ui_api/gcs.py tests/unit/core/test_ui_api_gcs_blobs_upload.py
git commit -m "feat(ui-api): upload blob with multipart and size cap

GCP_LOCAL_UI_MAX_UPLOAD_MB controls the cap (default 100 MB). The
spec calls for a clear error before reading the body but FastAPI
buffers the upload first; we reject after read with 413 and a
descriptive envelope message."
```

---

### Task 11: `GET /gcs/buckets/{bucket}/blobs/{name}` — metadata + inline preview

**Files:**
- Modify: `src/gcp_local/core/ui_api/gcs.py`
- Create: `tests/unit/core/test_ui_api_gcs_blob_metadata.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/core/test_ui_api_gcs_blob_metadata.py
import base64

from gcp_local.services.gcs.models import BucketMeta, ObjectRecord


async def _seed(svc, name: str, content: bytes, content_type: str) -> None:
    await svc.storage.create_bucket(BucketMeta(name="b", time_created="t"))
    await svc.storage.put_object(
        ObjectRecord(
            bucket="b",
            name=name,
            size=len(content),
            generation=1,
            metageneration=1,
            md5_hash="m",
            crc32c="c",
            content_type=content_type,
            time_created="2026-05-03T10:00:00Z",
            updated="2026-05-03T10:00:00Z",
        ),
        content,
    )


async def test_metadata_text_preview(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await _seed(svc, "hello.txt", b"hi there", "text/plain")
    r = await client.get("/_emulator/ui-api/v1/gcs/buckets/b/blobs/hello.txt")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "hello.txt"
    assert body["size"] == 8
    assert body["preview"] == {
        "kind": "text",
        "text": "hi there",
        "image_data_url": None,
        "truncated": False,
        "reason": None,
    }


async def test_metadata_json_preview(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await _seed(svc, "x.json", b'{"a":1}', "application/json")
    body = (await client.get("/_emulator/ui-api/v1/gcs/buckets/b/blobs/x.json")).json()
    assert body["preview"]["kind"] == "json"
    assert body["preview"]["text"] == '{"a":1}'


async def test_metadata_image_preview(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    raw = b"\x89PNG\r\n\x1a\nfakeimage"
    await _seed(svc, "p.png", raw, "image/png")
    body = (await client.get("/_emulator/ui-api/v1/gcs/buckets/b/blobs/p.png")).json()
    assert body["preview"]["kind"] == "image"
    assert body["preview"]["image_data_url"] == (
        "data:image/png;base64," + base64.b64encode(raw).decode()
    )


async def test_metadata_text_truncated_when_over_cap(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    big = b"a" * (1024 * 1024 + 100)  # > 1 MB cap
    await _seed(svc, "big.txt", big, "text/plain")
    body = (await client.get("/_emulator/ui-api/v1/gcs/buckets/b/blobs/big.txt")).json()
    assert body["preview"]["kind"] == "text"
    assert body["preview"]["truncated"] is True
    assert len(body["preview"]["text"].encode()) == 1024 * 1024


async def test_metadata_no_preview_for_unknown_type(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await _seed(svc, "x.bin", b"\x00\x01", "application/octet-stream")
    body = (await client.get("/_emulator/ui-api/v1/gcs/buckets/b/blobs/x.bin")).json()
    assert body["preview"]["kind"] == "none"
    assert body["preview"]["reason"]


async def test_metadata_unknown_blob_404(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await svc.storage.create_bucket(BucketMeta(name="b", time_created="t"))
    r = await client.get("/_emulator/ui-api/v1/gcs/buckets/b/blobs/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
```

- [ ] **Step 2: Run — expect 6 failures.**

Run: `pytest tests/unit/core/test_ui_api_gcs_blob_metadata.py -v`

- [ ] **Step 3: Add a preview helper at the top of `gcs.py` (after the schemas)**

```python
_TEXT_PREVIEW_CAP = 1024 * 1024  # 1 MB
_IMAGE_PREVIEW_CAP = 5 * 1024 * 1024  # 5 MB


def _build_preview(content_type: str, data: bytes) -> BlobPreview:
    import base64

    ct = content_type.lower()
    if ct.startswith("image/"):
        if len(data) > _IMAGE_PREVIEW_CAP:
            return BlobPreview(kind="none", reason="image too large for inline preview; download instead")
        return BlobPreview(
            kind="image",
            image_data_url=f"data:{ct};base64,{base64.b64encode(data).decode()}",
        )
    if ct == "application/json":
        kind: Literal["text", "json", "image", "none"] = "json"
    elif ct.startswith("text/"):
        kind = "text"
    else:
        return BlobPreview(kind="none", reason=f"no inline preview for content-type '{content_type}'")
    truncated = len(data) > _TEXT_PREVIEW_CAP
    text = data[:_TEXT_PREVIEW_CAP].decode("utf-8", errors="replace") if truncated else data.decode(
        "utf-8", errors="replace"
    )
    return BlobPreview(kind=kind, text=text, truncated=truncated)
```

- [ ] **Step 4: Implement the endpoint**

Add inside `build_gcs_router`:

```python
    @router.get(
        "/buckets/{bucket}/blobs/{name:path}",
        response_model=BlobMetadata,
    )
    async def get_blob_metadata(bucket: str, name: str, storage: StorageDep) -> BlobMetadata:
        try:
            record = await storage.get_object(bucket, name)
        except (BucketNotFound, ObjectNotFound):
            raise UiApiError(
                status_code=404,
                code="not_found",
                message=f"blob '{name}' not found in bucket '{bucket}'",
            ) from None
        data = await storage.get_object_bytes(bucket, name)
        preview = _build_preview(record.content_type, data)
        return BlobMetadata(
            bucket=record.bucket,
            name=record.name,
            size=record.size,
            content_type=record.content_type,
            time_created=record.time_created,
            updated=record.updated,
            generation=record.generation,
            metageneration=record.metageneration,
            md5_hash=record.md5_hash,
            crc32c=record.crc32c,
            metadata=record.metadata,
            preview=preview,
        )
```

> **Note on routing:** the `{name:path}` converter lets us match nested names like `logs/2026/01.log`. The download and delete endpoints below also use it.

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/core/test_ui_api_gcs_blob_metadata.py -v`
Expected: 6 pass.

- [ ] **Step 6: Lint + format + mypy**

Run: `ruff check src/gcp_local/core/ui_api tests/unit/core && ruff format src/gcp_local/core/ui_api tests/unit/core && mypy`

- [ ] **Step 7: Commit**

```bash
git add src/gcp_local/core/ui_api/gcs.py tests/unit/core/test_ui_api_gcs_blob_metadata.py
git commit -m "feat(ui-api): blob metadata with text/json/image previews

Inline preview caps: 1 MB for text/JSON (truncated flag on overflow);
5 MB for images (force download above that). Unknown content types
return preview.kind='none' with a friendly reason."
```

---

### Task 12: `GET /gcs/buckets/{bucket}/blobs/{name}/download` — raw bytes

**Files:**
- Modify: `src/gcp_local/core/ui_api/gcs.py`
- Create: `tests/unit/core/test_ui_api_gcs_blob_download.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/core/test_ui_api_gcs_blob_download.py
from gcp_local.services.gcs.models import BucketMeta, ObjectRecord


async def test_download_returns_bytes_with_content_type(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await svc.storage.create_bucket(BucketMeta(name="b", time_created="t"))
    await svc.storage.put_object(
        ObjectRecord(
            bucket="b",
            name="hi.txt",
            size=2,
            generation=1,
            metageneration=1,
            md5_hash="m",
            crc32c="c",
            content_type="text/plain",
            time_created="t",
            updated="t",
        ),
        b"hi",
    )
    r = await client.get("/_emulator/ui-api/v1/gcs/buckets/b/blobs/hi.txt/download")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert r.headers["content-disposition"] == 'attachment; filename="hi.txt"'
    assert r.content == b"hi"


async def test_download_unknown_blob_404(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await svc.storage.create_bucket(BucketMeta(name="b", time_created="t"))
    r = await client.get("/_emulator/ui-api/v1/gcs/buckets/b/blobs/nope/download")
    assert r.status_code == 404
```

- [ ] **Step 2: Run — expect 2 failures.**

Run: `pytest tests/unit/core/test_ui_api_gcs_blob_download.py -v`

- [ ] **Step 3: Implement endpoint**

Add inside `build_gcs_router`:

```python
    @router.get("/buckets/{bucket}/blobs/{name:path}/download")
    async def download_blob(bucket: str, name: str, storage: StorageDep) -> Response:
        try:
            record = await storage.get_object(bucket, name)
            data = await storage.get_object_bytes(bucket, name)
        except (BucketNotFound, ObjectNotFound):
            raise UiApiError(
                status_code=404,
                code="not_found",
                message=f"blob '{name}' not found in bucket '{bucket}'",
            ) from None
        # Force download semantics; the SPA handles inline rendering separately.
        # Quote the filename per RFC 6266 minimum form; the UI never sends
        # exotic names but we still avoid CRLF injection by replacing.
        safe = name.replace('"', "").replace("\r", "").replace("\n", "")
        return Response(
            content=data,
            media_type=record.content_type,
            headers={"content-disposition": f'attachment; filename="{safe}"'},
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/core/test_ui_api_gcs_blob_download.py -v`
Expected: 2 pass.

- [ ] **Step 5: Lint + format + mypy**

Run: `ruff check src/gcp_local/core/ui_api tests/unit/core && ruff format src/gcp_local/core/ui_api tests/unit/core && mypy`

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/core/ui_api/gcs.py tests/unit/core/test_ui_api_gcs_blob_download.py
git commit -m "feat(ui-api): GET /gcs/buckets/{b}/blobs/{n}/download returns bytes"
```

---

### Task 13: `DELETE /gcs/buckets/{bucket}/blobs/{name}`

**Files:**
- Modify: `src/gcp_local/core/ui_api/gcs.py`
- Create: `tests/unit/core/test_ui_api_gcs_blob_delete.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/core/test_ui_api_gcs_blob_delete.py
from gcp_local.services.gcs.models import BucketMeta, ObjectRecord


async def _seed(svc, name="hi.txt") -> None:
    await svc.storage.create_bucket(BucketMeta(name="b", time_created="t"))
    await svc.storage.put_object(
        ObjectRecord(
            bucket="b",
            name=name,
            size=2,
            generation=1,
            metageneration=1,
            md5_hash="m",
            crc32c="c",
            time_created="t",
            updated="t",
        ),
        b"hi",
    )


async def test_delete_blob(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await _seed(svc)
    r = await client.delete("/_emulator/ui-api/v1/gcs/buckets/b/blobs/hi.txt")
    assert r.status_code == 204
    objs, _ = await svc.storage.list_objects_with_prefixes("b")
    assert objs == []


async def test_delete_unknown_blob_404(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await svc.storage.create_bucket(BucketMeta(name="b", time_created="t"))
    r = await client.delete("/_emulator/ui-api/v1/gcs/buckets/b/blobs/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
```

- [ ] **Step 2: Run — expect 2 failures.**

Run: `pytest tests/unit/core/test_ui_api_gcs_blob_delete.py -v`

- [ ] **Step 3: Implement endpoint**

Add inside `build_gcs_router`:

```python
    @router.delete("/buckets/{bucket}/blobs/{name:path}", status_code=204)
    async def delete_blob(bucket: str, name: str, storage: StorageDep) -> Response:
        try:
            await storage.get_object(bucket, name)
        except (BucketNotFound, ObjectNotFound):
            raise UiApiError(
                status_code=404,
                code="not_found",
                message=f"blob '{name}' not found in bucket '{bucket}'",
            ) from None
        await storage.delete_object(bucket, name)
        return Response(status_code=204)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/core -v`
Expected: full ui-api unit suite green.

- [ ] **Step 5: Lint + format + mypy**

Run: `ruff check src/gcp_local/core/ui_api tests/unit/core && ruff format src/gcp_local/core/ui_api tests/unit/core && mypy`

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/core/ui_api/gcs.py tests/unit/core/test_ui_api_gcs_blob_delete.py
git commit -m "feat(ui-api): DELETE /gcs/buckets/{b}/blobs/{n} removes a blob"
```

---

## Phase C — Static UI mount, packaging, integration test

### Task 14: Mount `/ui/` static files with friendly fallback

**Files:**
- Create: `src/gcp_local/ui/__init__.py`
- Create: `src/gcp_local/ui/static/.keep` (placeholder so the directory ships)
- Modify: `src/gcp_local/core/admin_api.py`
- Modify: `tests/unit/test_admin_api.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_admin_api.py`:

```python
async def test_ui_root_returns_friendly_message_when_bundle_missing(client) -> None:
    c, _, _ = client
    r = await c.get("/ui/")
    # Bundle is not built in unit tests; fallback HTML is served.
    assert r.status_code == 200
    assert "gcp-local UI" in r.text
    assert "npm run build" in r.text


async def test_ui_root_serves_bundle_when_present(tmp_path, monkeypatch) -> None:
    # Point the static dir at a tmp tree that contains an index.html.
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html><title>built</title>")
    monkeypatch.setenv("GCP_LOCAL_UI_STATIC_DIR", str(static))

    from gcp_local.core.admin_api import build_admin_app
    from gcp_local.core.context import Context
    from gcp_local.core.lifecycle import Lifecycle
    from httpx import ASGITransport, AsyncClient

    lc = Lifecycle([], Context(persist=False, data_dir=tmp_path))
    app = build_admin_app(lc)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/ui/")
        assert r.status_code == 200
        assert "<title>built</title>" in r.text
```

- [ ] **Step 2: Create the package + placeholder**

```bash
mkdir -p src/gcp_local/ui/static
touch src/gcp_local/ui/static/.keep
```

Create `src/gcp_local/ui/__init__.py`:

```python
"""SPA static-file payload (built by ``npm run build``).

Production wheels and the Docker image ship the built bundle under
``static/``. Editable installs run ``cd web && npm run build`` to produce it
locally; until they do, ``/ui/`` returns a friendly fallback page from
``admin_api`` instead of crashing.
"""

from importlib.resources import files
from pathlib import Path


def static_dir() -> Path:
    """Return the directory containing the built SPA, if any.

    Honours the ``GCP_LOCAL_UI_STATIC_DIR`` env var for tests and dev.
    """
    import os

    override = os.environ.get("GCP_LOCAL_UI_STATIC_DIR")
    if override:
        return Path(override)
    return Path(str(files("gcp_local.ui").joinpath("static")))
```

- [ ] **Step 3: Modify `src/gcp_local/core/admin_api.py`**

After `app.include_router(build_ui_api_router(lc))`, add:

```python
    _mount_ui(app)
    return app


_FALLBACK_HTML = """<!doctype html>
<html>
  <head><title>gcp-local UI</title></head>
  <body style="font-family: system-ui; padding: 32px;">
    <h1>gcp-local UI bundle not built</h1>
    <p>The browser UI ships as a built static bundle. Editable installs need to build it once:</p>
    <pre>cd web &amp;&amp; npm install &amp;&amp; npm run build</pre>
    <p>Then restart the emulator. The rest of the API works without the UI.</p>
  </body>
</html>
"""


def _mount_ui(app: FastAPI) -> None:
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles

    from gcp_local.ui import static_dir

    base = static_dir()
    index = base / "index.html"
    if not index.exists():
        @app.get("/ui/", response_class=HTMLResponse)
        async def _ui_fallback_root() -> HTMLResponse:
            return HTMLResponse(_FALLBACK_HTML)

        @app.get("/ui/{_path:path}", response_class=HTMLResponse)
        async def _ui_fallback_any(_path: str) -> HTMLResponse:
            return HTMLResponse(_FALLBACK_HTML)

        return

    app.mount("/ui", StaticFiles(directory=base, html=True), name="ui")
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_admin_api.py -v`
Expected: 2 new tests pass; old tests still pass.

- [ ] **Step 5: Lint + format + mypy**

Run: `ruff check src/gcp_local tests/unit/test_admin_api.py && ruff format src/gcp_local tests/unit/test_admin_api.py && mypy`

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/ui src/gcp_local/core/admin_api.py tests/unit/test_admin_api.py
git commit -m "feat(ui): mount /ui/ static bundle with friendly fallback

When src/gcp_local/ui/static/index.html is missing (editable installs
without a frontend build), /ui/ returns a clear instruction page rather
than a crash. The rest of the API is unaffected. The
GCP_LOCAL_UI_STATIC_DIR env var is honoured for dev/test overrides."
```

---

### Task 15: Wheel package data — ship `ui/static/**`

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Inspect the current wheel target**

Run: `grep -A3 "tool.hatch.build.targets.wheel" pyproject.toml`
Expected output:

```
[tool.hatch.build.targets.wheel]
packages = ["src/gcp_local"]
```

Hatchling's wheel builder includes all files inside `packages` by default — `ui/static/**` is therefore already shipped. We make this explicit and add a `force-include` rule so the bundle is included even when produced by CI in a separate step that runs after the source layout is materialised.

- [ ] **Step 2: Modify `pyproject.toml`**

Replace the `[tool.hatch.build.targets.wheel]` section with:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/gcp_local"]

[tool.hatch.build.targets.wheel.force-include]
"src/gcp_local/ui/static" = "gcp_local/ui/static"
```

- [ ] **Step 3: Verify the wheel includes the bundle directory**

Run:
```bash
python -m build --wheel
unzip -l dist/gcp_local-*.whl | grep "ui/static"
```
Expected: at minimum the `.keep` file is listed (and any future `index.html`).

- [ ] **Step 4: Clean dist/ to avoid leftover artifacts**

Run: `rm -rf dist/ build/ src/*.egg-info/`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "build: include src/gcp_local/ui/static in the wheel

Hatchling already includes nested files under the wheel package root,
but the explicit force-include guarantees the SPA bundle survives
regardless of CI ordering."
```

---

### Task 16: End-to-end Python integration test for ui-api + GCS

**Files:**
- Create: `tests/integration/test_ui_api_integration.py`

- [ ] **Step 1: Write the test**

```python
# tests/integration/test_ui_api_integration.py
"""End-to-end ui-api flow against a real GCS service with disk persistence."""

import io
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from gcp_local.core.admin_api import build_admin_app
from gcp_local.core.context import Context
from gcp_local.core.lifecycle import Lifecycle
from gcp_local.services.gcs import GcsService


@pytest.fixture
async def integration_client(tmp_path: Path):
    svc = GcsService()
    ctx = Context(persist=True, data_dir=tmp_path)
    lc = Lifecycle([svc], ctx)
    await lc.start_all()
    try:
        app = build_admin_app(lc)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        await lc.stop_all()


async def test_ui_api_full_lifecycle(integration_client) -> None:
    c = integration_client

    # Create bucket
    r = await c.post("/_emulator/ui-api/v1/gcs/buckets", json={"name": "demo"})
    assert r.status_code == 201

    # Upload blob
    r = await c.post(
        "/_emulator/ui-api/v1/gcs/buckets/demo/blobs",
        files={"file": ("greeting.txt", io.BytesIO(b"hi from gcp-local"), "text/plain")},
    )
    assert r.status_code == 201

    # List blobs
    r = await c.get("/_emulator/ui-api/v1/gcs/buckets/demo/blobs")
    assert r.status_code == 200
    assert [b["name"] for b in r.json()["blobs"]] == ["greeting.txt"]

    # Get metadata + preview
    r = await c.get("/_emulator/ui-api/v1/gcs/buckets/demo/blobs/greeting.txt")
    assert r.status_code == 200
    body = r.json()
    assert body["size"] == 17
    assert body["preview"]["text"] == "hi from gcp-local"

    # Download
    r = await c.get("/_emulator/ui-api/v1/gcs/buckets/demo/blobs/greeting.txt/download")
    assert r.status_code == 200
    assert r.content == b"hi from gcp-local"

    # Delete blob
    r = await c.delete("/_emulator/ui-api/v1/gcs/buckets/demo/blobs/greeting.txt")
    assert r.status_code == 204

    # Delete bucket
    r = await c.delete("/_emulator/ui-api/v1/gcs/buckets/demo")
    assert r.status_code == 204

    # Buckets list now empty
    r = await c.get("/_emulator/ui-api/v1/gcs/buckets")
    assert r.json()["buckets"] == []
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/integration/test_ui_api_integration.py -v`
Expected: 1 test passes.

- [ ] **Step 3: Run the full suite to confirm no regressions**

Run: `pytest tests/ --ignore=tests/integration/test_docker_image.py`
Expected: green.

- [ ] **Step 4: Lint + format + mypy**

Run: `ruff check tests/integration/test_ui_api_integration.py && ruff format tests/integration/test_ui_api_integration.py && mypy`

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_ui_api_integration.py
git commit -m "test(ui-api): end-to-end flow with disk-backed GCS"
```

---

## Phase D — Frontend foundation (Vite + React + TS)

### Task 17: `web/` scaffold (Vite, React, TS, eslint, vitest)

**Files:**
- Create: `web/package.json`
- Create: `web/package-lock.json` (generated)
- Create: `web/tsconfig.json`
- Create: `web/tsconfig.node.json`
- Create: `web/vite.config.ts`
- Create: `web/vitest.config.ts`
- Create: `web/.eslintrc.cjs`
- Create: `web/.gitignore`
- Create: `web/index.html`
- Create: `web/src/main.tsx`
- Create: `web/src/App.tsx`
- Create: `web/src/setupTests.ts`
- Create: `web/src/vite-env.d.ts`

- [ ] **Step 1: Create `web/package.json`**

```json
{
  "name": "@gcp-local/web",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "lint": "eslint . --ext ts,tsx --report-unused-disable-directives --max-warnings 0",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.2"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.5.0",
    "@testing-library/react": "^16.0.1",
    "@testing-library/user-event": "^14.5.2",
    "@types/react": "^18.3.5",
    "@types/react-dom": "^18.3.0",
    "@typescript-eslint/eslint-plugin": "^8.5.0",
    "@typescript-eslint/parser": "^8.5.0",
    "@vitejs/plugin-react": "^4.3.1",
    "eslint": "^8.57.0",
    "eslint-plugin-react-hooks": "^4.6.2",
    "eslint-plugin-react-refresh": "^0.4.11",
    "jsdom": "^25.0.0",
    "typescript": "^5.5.4",
    "vite": "^5.4.5",
    "vitest": "^2.1.0"
  }
}
```

- [ ] **Step 2: Create `web/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 3: Create `web/tsconfig.node.json`**

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts", "vitest.config.ts"]
}
```

- [ ] **Step 4: Create `web/vite.config.ts`**

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  base: "/ui/",
  build: {
    outDir: "../src/gcp_local/ui/static",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/_emulator": "http://localhost:4510",
    },
  },
});
```

- [ ] **Step 5: Create `web/vitest.config.ts`**

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
  },
});
```

- [ ] **Step 6: Create `web/.eslintrc.cjs`**

```js
module.exports = {
  root: true,
  env: { browser: true, es2022: true },
  extends: [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "plugin:react-hooks/recommended",
  ],
  ignorePatterns: ["dist", ".eslintrc.cjs"],
  parser: "@typescript-eslint/parser",
  plugins: ["react-refresh"],
  rules: {
    "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
    "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
  },
};
```

- [ ] **Step 7: Create `web/.gitignore`**

```
node_modules
dist
*.log
.vite
```

- [ ] **Step 8: Create `web/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>gcp-local</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 9: Create `web/src/main.tsx`**

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import "./theme/global.css";

const root = document.getElementById("root");
if (!root) throw new Error("missing #root");
ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <BrowserRouter basename="/ui">
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
```

- [ ] **Step 10: Create `web/src/App.tsx`**

```tsx
export default function App() {
  return <div>gcp-local UI scaffold</div>;
}
```

- [ ] **Step 11: Create `web/src/setupTests.ts`**

```ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 12: Create `web/src/vite-env.d.ts`**

```ts
/// <reference types="vite/client" />
```

- [ ] **Step 13: Create the theme dir + global stylesheet**

`web/src/theme/global.css`:

```css
:root {
  color-scheme: light;
  --bg: #ffffff;
  --fg: #18181b;
  --muted: #71717a;
  --border: #e4e4e7;
  --row-alt: #fafafa;
  --accent: #2563eb;
  --danger: #dc2626;
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  font-size: 14px;
  line-height: 1.45;
  color: var(--fg);
  background: var(--bg);
}

* { box-sizing: border-box; }
body { margin: 0; }
button { font: inherit; }
```

- [ ] **Step 14: Install deps and verify everything wires**

```bash
cd web && npm install
npm run lint
npm run build
```

Expected: lint passes, build emits `../src/gcp_local/ui/static/index.html` plus assets.

- [ ] **Step 15: Verify the integration of the bundled UI**

Run: `cd .. && pytest tests/unit/test_admin_api.py::test_ui_root_serves_bundle_when_present -v` — should pass on a fresh shell since the bundle now exists. (The "fallback" test still passes because it doesn't override the env var; FastAPI returns the actual bundle now. Adjust the fallback test to point at a tmp dir without index.html.)

If the fallback test now fails because it sees the real bundle, **modify it** to override `GCP_LOCAL_UI_STATIC_DIR` to a tmp empty dir:

```python
async def test_ui_root_returns_friendly_message_when_bundle_missing(
    tmp_path, monkeypatch
) -> None:
    empty = tmp_path / "empty-static"
    empty.mkdir()
    monkeypatch.setenv("GCP_LOCAL_UI_STATIC_DIR", str(empty))

    from gcp_local.core.admin_api import build_admin_app
    from gcp_local.core.context import Context
    from gcp_local.core.lifecycle import Lifecycle
    from httpx import ASGITransport, AsyncClient

    lc = Lifecycle([], Context(persist=False, data_dir=tmp_path))
    app = build_admin_app(lc)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/ui/")
        assert r.status_code == 200
        assert "gcp-local UI" in r.text
        assert "npm run build" in r.text
```

- [ ] **Step 16: Re-run the affected tests**

Run: `pytest tests/unit/test_admin_api.py -v`
Expected: all admin tests pass with the bundle present.

- [ ] **Step 17: Commit**

```bash
git add web tests/unit/test_admin_api.py src/gcp_local/ui/static
git commit -m "feat(web): scaffold React + Vite + TS + vitest

Adds a web/ source tree, builds to src/gcp_local/ui/static/, proxies
/_emulator/* to localhost:4510 in dev. Bundle is committed alongside
source so editable Python installs work without rebuilding the UI."
```

> **Note on committing the built bundle:** in this PR we ship the bundle in-repo (rebuilt by CI on every change) so editable installs of the Python package work out of the box. The CI pipeline rebuilds it as part of the Python wheel job. If the bundle drifts from source, CI fails the diff check (added in Task 29).

---

### Task 18: Typed API client + tests

**Files:**
- Create: `web/src/api/client.ts`
- Create: `web/src/api/types.ts`
- Create: `web/src/api/client.test.ts`

- [ ] **Step 1: Write a failing test**

`web/src/api/client.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, UiApi } from "./client";

const json = (status: number, body: unknown) =>
  Promise.resolve(
    new Response(typeof body === "string" ? body : JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );

describe("UiApi", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("listBuckets parses the response", async () => {
    fetchMock.mockReturnValueOnce(
      json(200, { buckets: [{ name: "x", location: "US", storage_class: "STANDARD", time_created: "t" }] }),
    );
    const api = new UiApi();
    const out = await api.listBuckets();
    expect(out.buckets[0].name).toBe("x");
  });

  it("throws ApiError with code+message on envelope errors", async () => {
    fetchMock.mockReturnValueOnce(
      json(409, { error: { code: "already_exists", message: "bucket 'x' already exists" } }),
    );
    const api = new UiApi();
    await expect(api.createBucket({ name: "x" })).rejects.toMatchObject({
      code: "already_exists",
      message: "bucket 'x' already exists",
      status: 409,
    });
    await expect(api.createBucket({ name: "x" })).rejects.toBeInstanceOf(ApiError);
  });

  it("throws on network failure with code='network'", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const api = new UiApi();
    await expect(api.listBuckets()).rejects.toMatchObject({ code: "network" });
  });
});
```

- [ ] **Step 2: Run — expect failures.**

Run from `web/`: `npm test`

- [ ] **Step 3: Implement `web/src/api/types.ts`**

```ts
export interface Port {
  number: number;
  protocol: string;
}

export interface ServiceInfo {
  name: string;
  ports: Port[];
  ui_supported: boolean;
}

export interface ServiceList {
  services: ServiceInfo[];
}

export interface BucketSummary {
  name: string;
  location: string;
  storage_class: string;
  time_created: string;
}

export interface BucketList {
  buckets: BucketSummary[];
}

export interface BlobSummary {
  name: string;
  size: number;
  content_type: string;
  updated: string;
  generation: number;
}

export interface BlobList {
  bucket: string;
  prefix: string;
  blobs: BlobSummary[];
  folders: string[];
  next_page_token: string | null;
}

export interface BlobPreview {
  kind: "text" | "json" | "image" | "none";
  text: string | null;
  image_data_url: string | null;
  truncated: boolean;
  reason: string | null;
}

export interface BlobMetadata {
  bucket: string;
  name: string;
  size: number;
  content_type: string;
  time_created: string;
  updated: string;
  generation: number;
  metageneration: number;
  md5_hash: string;
  crc32c: string;
  metadata: Record<string, string>;
  preview: BlobPreview | null;
}
```

- [ ] **Step 4: Implement `web/src/api/client.ts`**

```ts
import type {
  BlobList,
  BlobMetadata,
  BlobSummary,
  BucketList,
  BucketSummary,
  ServiceList,
} from "./types";

export class ApiError extends Error {
  constructor(
    public readonly code: string,
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const BASE = "/_emulator/ui-api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, init);
  } catch (e) {
    throw new ApiError("network", 0, e instanceof Error ? e.message : "network error");
  }
  const text = await res.text();
  let body: unknown = undefined;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      // Non-JSON response (e.g., raw download). Caller handled separately.
    }
  }
  if (!res.ok) {
    const envelope = body as { error?: { code?: string; message?: string } } | undefined;
    throw new ApiError(
      envelope?.error?.code ?? "unknown",
      res.status,
      envelope?.error?.message ?? res.statusText,
    );
  }
  return body as T;
}

export class UiApi {
  listServices(): Promise<ServiceList> {
    return request("/services");
  }

  listBuckets(): Promise<BucketList> {
    return request("/gcs/buckets");
  }

  createBucket(payload: { name: string; location?: string }): Promise<BucketSummary> {
    return request("/gcs/buckets", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  deleteBucket(name: string, force = false): Promise<void> {
    return request(`/gcs/buckets/${encodeURIComponent(name)}?force=${force}`, {
      method: "DELETE",
    });
  }

  listBlobs(
    bucket: string,
    options: { prefix?: string; delimiter?: string; pageToken?: string } = {},
  ): Promise<BlobList> {
    const params = new URLSearchParams();
    if (options.prefix) params.set("prefix", options.prefix);
    if (options.delimiter) params.set("delimiter", options.delimiter);
    if (options.pageToken) params.set("page_token", options.pageToken);
    const qs = params.toString();
    return request(`/gcs/buckets/${encodeURIComponent(bucket)}/blobs${qs ? `?${qs}` : ""}`);
  }

  async uploadBlob(bucket: string, file: File, name?: string): Promise<BlobSummary> {
    const fd = new FormData();
    fd.append("file", file);
    if (name) fd.append("name", name);
    return request(`/gcs/buckets/${encodeURIComponent(bucket)}/blobs`, {
      method: "POST",
      body: fd,
    });
  }

  getBlobMetadata(bucket: string, name: string): Promise<BlobMetadata> {
    return request(
      `/gcs/buckets/${encodeURIComponent(bucket)}/blobs/${encodeURIComponent(name)}`,
    );
  }

  downloadBlobUrl(bucket: string, name: string): string {
    return `${BASE}/gcs/buckets/${encodeURIComponent(bucket)}/blobs/${encodeURIComponent(name)}/download`;
  }

  deleteBlob(bucket: string, name: string): Promise<void> {
    return request(
      `/gcs/buckets/${encodeURIComponent(bucket)}/blobs/${encodeURIComponent(name)}`,
      { method: "DELETE" },
    );
  }
}

export const api = new UiApi();
```

- [ ] **Step 5: Run tests**

From `web/`: `npm test`
Expected: 3 tests pass.

- [ ] **Step 6: Commit**

```bash
git add web/src/api
git commit -m "feat(web): typed UiApi client with envelope error handling"
```

---

### Task 19: AppLayout + ServiceNav + breadcrumbs

**Files:**
- Create: `web/src/components/AppLayout.tsx`
- Create: `web/src/components/AppLayout.module.css`
- Create: `web/src/components/AppLayout.test.tsx`
- Modify: `web/src/App.tsx`

- [ ] **Step 1: Write failing tests**

`web/src/components/AppLayout.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { AppLayout } from "./AppLayout";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppLayout
        services={[
          { name: "gcs", ports: [{ number: 4443, protocol: "rest" }], ui_supported: true },
          { name: "bigquery", ports: [{ number: 9050, protocol: "rest" }], ui_supported: false },
        ]}
        host="localhost:4510"
      >
        <div>page content</div>
      </AppLayout>
    </MemoryRouter>,
  );
}

describe("AppLayout", () => {
  it("shows the host string", () => {
    renderAt("/gcs");
    expect(screen.getByText("localhost:4510")).toBeInTheDocument();
  });

  it("renders nav links for ui-supported services and disables others", () => {
    renderAt("/gcs");
    const gcs = screen.getByRole("link", { name: /gcs/i });
    expect(gcs).toHaveAttribute("href", "/gcs");
    const bq = screen.getByText(/bigquery/i);
    expect(bq.closest("a")).toBeNull(); // not a link, just text
  });

  it("renders children", () => {
    renderAt("/gcs");
    expect(screen.getByText("page content")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run — expect failures.**

Run from `web/`: `npm test`

- [ ] **Step 3: Implement `AppLayout.tsx`**

```tsx
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import type { ServiceInfo } from "../api/types";

import styles from "./AppLayout.module.css";

const SERVICE_LABELS: Record<string, string> = {
  gcs: "GCS",
  bigquery: "BigQuery",
  secret_manager: "Secret Manager",
  pubsub: "Pub/Sub",
  firestore: "Firestore",
};

export interface AppLayoutProps {
  services: ServiceInfo[];
  host: string;
  children: ReactNode;
}

export function AppLayout({ services, host, children }: AppLayoutProps) {
  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>gcp-local</div>
        <div className={styles.section}>Services</div>
        <ul className={styles.nav}>
          {services.map((s) => {
            const label = SERVICE_LABELS[s.name] ?? s.name;
            if (!s.ui_supported) {
              return (
                <li key={s.name} className={styles.disabled} title="UI coming soon">
                  {label}
                </li>
              );
            }
            return (
              <li key={s.name}>
                <NavLink
                  to={`/${s.name}`}
                  className={({ isActive }) => (isActive ? styles.active : "")}
                >
                  {label}
                </NavLink>
              </li>
            );
          })}
        </ul>
      </aside>
      <main className={styles.main}>
        <div className={styles.topbar}>
          <span className={styles.host}>{host}</span>
        </div>
        <div className={styles.content}>{children}</div>
      </main>
    </div>
  );
}
```

- [ ] **Step 4: Implement `AppLayout.module.css`**

```css
.shell {
  display: grid;
  grid-template-columns: 220px 1fr;
  min-height: 100vh;
}

.sidebar {
  background: #f4f4f5;
  border-right: 1px solid var(--border);
  padding: 16px;
}

.brand {
  font-weight: 700;
  margin-bottom: 24px;
}

.section {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--muted);
  margin-bottom: 8px;
}

.nav {
  list-style: none;
  margin: 0;
  padding: 0;
}

.nav li {
  padding: 6px 10px;
  border-radius: 6px;
  margin-bottom: 2px;
}

.nav a {
  color: var(--fg);
  text-decoration: none;
  display: block;
}

.nav .active {
  background: #e4e4e7;
}

.disabled {
  color: var(--muted);
  cursor: not-allowed;
}

.main {
  display: flex;
  flex-direction: column;
}

.topbar {
  height: 44px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 0 16px;
}

.host {
  color: var(--muted);
  font-size: 12px;
}

.content {
  flex: 1;
  padding: 24px;
}
```

- [ ] **Step 5: Update `web/src/App.tsx`**

```tsx
import { Navigate, Route, Routes } from "react-router-dom";

import { AppLayout } from "./components/AppLayout";

export default function App() {
  // Real services list comes from a useServices() hook in Task 22; the scaffold
  // hard-codes GCS so the shell renders during early development.
  const services = [
    { name: "gcs", ports: [{ number: 4443, protocol: "rest" }], ui_supported: true },
  ];
  return (
    <AppLayout services={services} host={window.location.host}>
      <Routes>
        <Route path="/" element={<Navigate to="/gcs" replace />} />
        <Route path="/gcs/*" element={<div>GCS placeholder</div>} />
      </Routes>
    </AppLayout>
  );
}
```

- [ ] **Step 6: Run tests + build**

```bash
cd web && npm test && npm run build && npm run lint
```
Expected: tests pass, build emits to `../src/gcp_local/ui/static/`.

- [ ] **Step 7: Commit**

```bash
git add web src/gcp_local/ui/static
git commit -m "feat(web): AppLayout shell with sidebar nav and disabled services"
```

---

### Task 20: Primitives — EmptyState, Toast/ErrorBanner, ConfirmDialog

**Files:**
- Create: `web/src/components/EmptyState.tsx`
- Create: `web/src/components/EmptyState.module.css`
- Create: `web/src/components/EmptyState.test.tsx`
- Create: `web/src/components/ErrorBanner.tsx`
- Create: `web/src/components/ErrorBanner.module.css`
- Create: `web/src/components/ErrorBanner.test.tsx`
- Create: `web/src/components/ConfirmDialog.tsx`
- Create: `web/src/components/ConfirmDialog.module.css`
- Create: `web/src/components/ConfirmDialog.test.tsx`

- [ ] **Step 1: Write tests**

`EmptyState.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { EmptyState } from "./EmptyState";

it("renders title, description, and action", async () => {
  const onClick = vi.fn();
  render(
    <EmptyState
      title="No buckets yet"
      description="Create one to get started."
      actionLabel="Create bucket"
      onAction={onClick}
    />,
  );
  expect(screen.getByRole("heading", { name: "No buckets yet" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Create bucket" }));
  expect(onClick).toHaveBeenCalledOnce();
});
```

`ErrorBanner.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ApiError } from "../api/client";
import { ErrorBanner } from "./ErrorBanner";

it("shows error message and supports retry", async () => {
  const onRetry = vi.fn();
  render(<ErrorBanner error={new ApiError("network", 0, "boom")} onRetry={onRetry} />);
  expect(screen.getByText(/boom/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /retry/i }));
  expect(onRetry).toHaveBeenCalled();
});
```

`ConfirmDialog.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ConfirmDialog } from "./ConfirmDialog";

it("calls onConfirm and onCancel", async () => {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  const { rerender } = render(
    <ConfirmDialog
      open
      title="Delete bucket"
      message="This cannot be undone."
      confirmLabel="Delete"
      onConfirm={onConfirm}
      onCancel={onCancel}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: /cancel/i }));
  expect(onCancel).toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: /delete/i }));
  expect(onConfirm).toHaveBeenCalled();
  rerender(<ConfirmDialog open={false} title="" onConfirm={onConfirm} onCancel={onCancel} />);
  expect(screen.queryByText("Delete bucket")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Implement `EmptyState.tsx`**

```tsx
import styles from "./EmptyState.module.css";

interface Props {
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
}

export function EmptyState({ title, description, actionLabel, onAction }: Props) {
  return (
    <div className={styles.empty}>
      <h2 className={styles.title}>{title}</h2>
      {description && <p className={styles.desc}>{description}</p>}
      {actionLabel && onAction && (
        <button className={styles.action} onClick={onAction}>
          {actionLabel}
        </button>
      )}
    </div>
  );
}
```

`EmptyState.module.css`:

```css
.empty { text-align: center; padding: 48px 24px; color: var(--muted); }
.title { color: var(--fg); margin-bottom: 8px; }
.desc { margin-bottom: 16px; }
.action { padding: 8px 16px; border-radius: 6px; border: 1px solid var(--border); background: var(--accent); color: white; cursor: pointer; }
.action:hover { opacity: 0.9; }
```

- [ ] **Step 3: Implement `ErrorBanner.tsx`**

```tsx
import type { ApiError } from "../api/client";

import styles from "./ErrorBanner.module.css";

interface Props {
  error: ApiError | Error;
  onRetry?: () => void;
}

export function ErrorBanner({ error, onRetry }: Props) {
  return (
    <div role="alert" className={styles.banner}>
      <div className={styles.message}>{error.message}</div>
      {onRetry && (
        <button className={styles.retry} onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}
```

`ErrorBanner.module.css`:

```css
.banner { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 16px; border-radius: 6px; background: #fef2f2; color: var(--danger); border: 1px solid #fecaca; margin-bottom: 16px; }
.retry { padding: 4px 12px; border-radius: 4px; border: 1px solid var(--danger); background: white; color: var(--danger); cursor: pointer; }
```

- [ ] **Step 4: Implement `ConfirmDialog.tsx`**

```tsx
import type { ReactNode } from "react";

import styles from "./ConfirmDialog.module.css";

interface Props {
  open: boolean;
  title: string;
  message?: ReactNode;
  confirmLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  destructive?: boolean;
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Confirm",
  onConfirm,
  onCancel,
  destructive = false,
}: Props) {
  if (!open) return null;
  return (
    <div className={styles.backdrop} role="dialog" aria-modal="true">
      <div className={styles.modal}>
        <h2 className={styles.title}>{title}</h2>
        {message && <div className={styles.body}>{message}</div>}
        <div className={styles.actions}>
          <button onClick={onCancel} className={styles.cancel}>
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className={destructive ? styles.destructive : styles.confirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
```

`ConfirmDialog.module.css`:

```css
.backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: white; border-radius: 8px; padding: 24px; min-width: 360px; max-width: 480px; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.1); }
.title { margin: 0 0 12px 0; }
.body { margin-bottom: 16px; color: var(--muted); }
.actions { display: flex; gap: 8px; justify-content: flex-end; }
.cancel { padding: 8px 16px; border-radius: 6px; border: 1px solid var(--border); background: white; cursor: pointer; }
.confirm { padding: 8px 16px; border-radius: 6px; border: 1px solid var(--accent); background: var(--accent); color: white; cursor: pointer; }
.destructive { padding: 8px 16px; border-radius: 6px; border: 1px solid var(--danger); background: var(--danger); color: white; cursor: pointer; }
```

- [ ] **Step 5: Run tests + build**

```bash
cd web && npm test && npm run build
```
Expected: 3 + earlier tests all pass.

- [ ] **Step 6: Commit**

```bash
git add web/src/components src/gcp_local/ui/static
git commit -m "feat(web): EmptyState, ErrorBanner, ConfirmDialog primitives"
```

---

### Task 21: Services list hook + GCS landing page wired with router

**Files:**
- Create: `web/src/hooks/useAsync.ts`
- Create: `web/src/hooks/useAsync.test.ts`
- Create: `web/src/services/gcs/GcsLanding.tsx` (placeholder, expanded in Phase E)
- Modify: `web/src/App.tsx`

- [ ] **Step 1: Write a test for `useAsync`**

`web/src/hooks/useAsync.test.ts`:

```ts
import { act, renderHook, waitFor } from "@testing-library/react";

import { useAsync } from "./useAsync";

it("resolves and exposes data", async () => {
  const { result } = renderHook(() => useAsync(() => Promise.resolve(42), []));
  await waitFor(() => expect(result.current.status).toBe("success"));
  expect(result.current.data).toBe(42);
});

it("captures errors and supports refresh", async () => {
  let calls = 0;
  const fn = vi.fn(() => (calls++ === 0 ? Promise.reject(new Error("nope")) : Promise.resolve(7)));
  const { result } = renderHook(() => useAsync(fn, []));
  await waitFor(() => expect(result.current.status).toBe("error"));
  expect(result.current.error?.message).toBe("nope");
  await act(async () => {
    await result.current.refresh();
  });
  expect(result.current.data).toBe(7);
});
```

- [ ] **Step 2: Implement `useAsync`**

```ts
// web/src/hooks/useAsync.ts
import { useCallback, useEffect, useRef, useState } from "react";

export type AsyncStatus = "idle" | "loading" | "success" | "error";

export interface AsyncState<T> {
  status: AsyncStatus;
  data: T | null;
  error: Error | null;
  refresh: () => Promise<void>;
}

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [state, setState] = useState<{ status: AsyncStatus; data: T | null; error: Error | null }>(
    { status: "idle", data: null, error: null },
  );
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const run = useCallback(async () => {
    setState((s) => ({ ...s, status: "loading", error: null }));
    try {
      const data = await fnRef.current();
      setState({ status: "success", data, error: null });
    } catch (e) {
      setState({ status: "error", data: null, error: e instanceof Error ? e : new Error(String(e)) });
    }
  }, []);

  useEffect(() => {
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { ...state, refresh: run };
}
```

- [ ] **Step 3: Create `GcsLanding.tsx` (placeholder, real content in Phase E)**

```tsx
export default function GcsLanding() {
  return <div>GCS UI loading…</div>;
}
```

- [ ] **Step 4: Update `App.tsx`**

```tsx
import { Navigate, Route, Routes } from "react-router-dom";

import { api } from "./api/client";
import { AppLayout } from "./components/AppLayout";
import { ErrorBanner } from "./components/ErrorBanner";
import { useAsync } from "./hooks/useAsync";
import GcsLanding from "./services/gcs/GcsLanding";

export default function App() {
  const services = useAsync(() => api.listServices(), []);

  if (services.status === "loading" || services.status === "idle") {
    return <div style={{ padding: 24 }}>Loading…</div>;
  }
  if (services.status === "error") {
    return <ErrorBanner error={services.error!} onRetry={services.refresh} />;
  }
  const list = services.data!.services;
  return (
    <AppLayout services={list} host={window.location.host}>
      <Routes>
        <Route path="/" element={<Navigate to="/gcs" replace />} />
        <Route path="/gcs/*" element={<GcsLanding />} />
      </Routes>
    </AppLayout>
  );
}
```

- [ ] **Step 5: Run tests + build**

```bash
cd web && npm test && npm run lint && npm run build
```
Expected: hook tests pass, full suite green, build emits.

- [ ] **Step 6: Commit**

```bash
git add web src/gcp_local/ui/static
git commit -m "feat(web): useAsync hook and wire services list into App"
```

---

## Phase E — Frontend GCS pilot

### Task 22: BucketList + Create dialog + delete with confirm

**Files:**
- Create: `web/src/services/gcs/BucketList.tsx`
- Create: `web/src/services/gcs/BucketList.module.css`
- Create: `web/src/services/gcs/BucketList.test.tsx`
- Create: `web/src/services/gcs/CreateBucketDialog.tsx`
- Modify: `web/src/services/gcs/GcsLanding.tsx`

- [ ] **Step 1: Write `BucketList.test.tsx`**

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { ApiError, UiApi } from "../../api/client";

import { BucketList } from "./BucketList";

const mkApi = (overrides: Partial<UiApi> = {}): UiApi => {
  const api = new UiApi();
  Object.assign(api, overrides);
  return api;
};

describe("BucketList", () => {
  it("renders empty state when there are no buckets", async () => {
    const api = mkApi({
      listBuckets: vi.fn().mockResolvedValue({ buckets: [] }),
    });
    render(
      <MemoryRouter>
        <BucketList api={api} />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText(/create your first bucket/i)).toBeInTheDocument());
  });

  it("lists buckets", async () => {
    const api = mkApi({
      listBuckets: vi.fn().mockResolvedValue({
        buckets: [
          { name: "alpha", location: "US", storage_class: "STANDARD", time_created: "t" },
          { name: "beta", location: "EU", storage_class: "STANDARD", time_created: "t" },
        ],
      }),
    });
    render(
      <MemoryRouter>
        <BucketList api={api} />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText("alpha")).toBeInTheDocument());
    expect(screen.getByText("beta")).toBeInTheDocument();
  });

  it("creates a bucket and refreshes the list", async () => {
    const list = vi
      .fn()
      .mockResolvedValueOnce({ buckets: [] })
      .mockResolvedValueOnce({
        buckets: [{ name: "x", location: "US", storage_class: "STANDARD", time_created: "t" }],
      });
    const create = vi.fn().mockResolvedValue({
      name: "x",
      location: "US",
      storage_class: "STANDARD",
      time_created: "t",
    });
    const api = mkApi({ listBuckets: list, createBucket: create });
    render(
      <MemoryRouter>
        <BucketList api={api} />
      </MemoryRouter>,
    );
    await userEvent.click(await screen.findByRole("button", { name: /create your first bucket/i }));
    await userEvent.type(screen.getByLabelText(/name/i), "x");
    await userEvent.click(screen.getByRole("button", { name: /^create$/i }));
    await waitFor(() => expect(create).toHaveBeenCalledWith({ name: "x", location: "US" }));
    await waitFor(() => expect(screen.getByText("x")).toBeInTheDocument());
  });

  it("surfaces API errors on create", async () => {
    const list = vi.fn().mockResolvedValue({ buckets: [] });
    const create = vi.fn().mockRejectedValue(new ApiError("already_exists", 409, "boom"));
    const api = mkApi({ listBuckets: list, createBucket: create });
    render(
      <MemoryRouter>
        <BucketList api={api} />
      </MemoryRouter>,
    );
    await userEvent.click(await screen.findByRole("button", { name: /create your first bucket/i }));
    await userEvent.type(screen.getByLabelText(/name/i), "dup");
    await userEvent.click(screen.getByRole("button", { name: /^create$/i }));
    await waitFor(() => expect(screen.getByText(/boom/)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run — expect failures.**

Run: `cd web && npm test`

- [ ] **Step 3: Implement `CreateBucketDialog.tsx`**

```tsx
import { useState } from "react";

import { ConfirmDialog } from "../../components/ConfirmDialog";

interface Props {
  open: boolean;
  onClose: () => void;
  onSubmit: (payload: { name: string; location: string }) => Promise<void>;
  error: Error | null;
}

const LOCATIONS = ["US", "EU", "ASIA"];

export function CreateBucketDialog({ open, onClose, onSubmit, error }: Props) {
  const [name, setName] = useState("");
  const [location, setLocation] = useState("US");
  const [submitting, setSubmitting] = useState(false);

  const handleConfirm = async () => {
    setSubmitting(true);
    try {
      await onSubmit({ name, location });
      setName("");
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;
  return (
    <ConfirmDialog
      open
      title="Create bucket"
      message={
        <div>
          <label>
            Name <input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </label>
          <div style={{ marginTop: 12 }}>
            <label>
              Location{" "}
              <select value={location} onChange={(e) => setLocation(e.target.value)}>
                {LOCATIONS.map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {error && <div style={{ color: "var(--danger)", marginTop: 12 }}>{error.message}</div>}
        </div>
      }
      confirmLabel={submitting ? "Creating…" : "Create"}
      onConfirm={handleConfirm}
      onCancel={onClose}
    />
  );
}
```

- [ ] **Step 4: Implement `BucketList.tsx`**

```tsx
import { useState } from "react";
import { Link } from "react-router-dom";

import { UiApi } from "../../api/client";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { useAsync } from "../../hooks/useAsync";

import { CreateBucketDialog } from "./CreateBucketDialog";
import styles from "./BucketList.module.css";

interface Props {
  api: UiApi;
}

export function BucketList({ api }: Props) {
  const buckets = useAsync(() => api.listBuckets(), []);
  const [createOpen, setCreateOpen] = useState(false);
  const [createError, setCreateError] = useState<Error | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const handleCreate = async (payload: { name: string; location: string }) => {
    setCreateError(null);
    try {
      await api.createBucket(payload);
      setCreateOpen(false);
      await buckets.refresh();
    } catch (e) {
      setCreateError(e instanceof Error ? e : new Error(String(e)));
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    await api.deleteBucket(pendingDelete);
    setPendingDelete(null);
    await buckets.refresh();
  };

  if (buckets.status === "loading" || buckets.status === "idle") {
    return <div>Loading…</div>;
  }
  if (buckets.status === "error") {
    return <ErrorBanner error={buckets.error!} onRetry={buckets.refresh} />;
  }
  const list = buckets.data!.buckets;
  if (list.length === 0) {
    return (
      <>
        <EmptyState
          title="No buckets yet"
          description="GCS is ready — create your first bucket to start storing objects."
          actionLabel="Create your first bucket"
          onAction={() => setCreateOpen(true)}
        />
        <CreateBucketDialog
          open={createOpen}
          onClose={() => setCreateOpen(false)}
          onSubmit={handleCreate}
          error={createError}
        />
      </>
    );
  }

  return (
    <div>
      <header className={styles.header}>
        <h2>Buckets</h2>
        <button className={styles.create} onClick={() => setCreateOpen(true)}>
          Create bucket
        </button>
      </header>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Name</th>
            <th>Location</th>
            <th>Created</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {list.map((b) => (
            <tr key={b.name}>
              <td>
                <Link to={`/gcs/buckets/${encodeURIComponent(b.name)}`}>{b.name}</Link>
              </td>
              <td>{b.location}</td>
              <td>{b.time_created}</td>
              <td>
                <button onClick={() => setPendingDelete(b.name)} className={styles.delete}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <CreateBucketDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onSubmit={handleCreate}
        error={createError}
      />
      <ConfirmDialog
        open={pendingDelete !== null}
        title={`Delete bucket "${pendingDelete}"?`}
        message="This deletes the bucket. If it isn't empty the request will fail; rerun with force from the CLI if needed."
        confirmLabel="Delete"
        destructive
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}
```

- [ ] **Step 5: `BucketList.module.css`**

```css
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.create { padding: 6px 14px; border-radius: 6px; background: var(--accent); color: white; border: none; cursor: pointer; }
.table { width: 100%; border-collapse: collapse; }
.table th, .table td { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--border); }
.table th { background: var(--row-alt); font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); }
.delete { background: none; border: none; color: var(--danger); cursor: pointer; }
```

- [ ] **Step 6: Wire into `GcsLanding.tsx`**

```tsx
import { Route, Routes } from "react-router-dom";

import { api } from "../../api/client";

import { BucketList } from "./BucketList";

export default function GcsLanding() {
  return (
    <Routes>
      <Route index element={<BucketList api={api} />} />
      <Route path="buckets/:bucket/*" element={<div>Bucket detail (next task)</div>} />
    </Routes>
  );
}
```

- [ ] **Step 7: Run tests + build**

```bash
cd web && npm test && npm run lint && npm run build
```
Expected: 4 BucketList tests pass, lint clean, build emits.

- [ ] **Step 8: Commit**

```bash
git add web src/gcp_local/ui/static
git commit -m "feat(web): GCS bucket list with create + delete-with-confirm"
```

---

### Task 23: BucketView + BlobList with prefix navigation

**Files:**
- Create: `web/src/services/gcs/BucketView.tsx`
- Create: `web/src/services/gcs/BlobList.tsx`
- Create: `web/src/services/gcs/BlobList.module.css`
- Create: `web/src/services/gcs/BlobList.test.tsx`
- Modify: `web/src/services/gcs/GcsLanding.tsx`

- [ ] **Step 1: Write `BlobList.test.tsx`**

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";

import { UiApi } from "../../api/client";

import { BlobList } from "./BlobList";

const mkApi = (overrides: Partial<UiApi>): UiApi => {
  const api = new UiApi();
  Object.assign(api, overrides);
  return api;
};

const renderAt = (path: string, api: UiApi) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/gcs/buckets/:bucket/*" element={<BlobList api={api} />} />
      </Routes>
    </MemoryRouter>,
  );

it("renders blobs and folders for the current prefix", async () => {
  const api = mkApi({
    listBlobs: vi.fn().mockResolvedValue({
      bucket: "b",
      prefix: "",
      blobs: [{ name: "a.txt", size: 3, content_type: "text/plain", updated: "t", generation: 1 }],
      folders: ["logs/"],
      next_page_token: null,
    }),
  });
  renderAt("/gcs/buckets/b", api);
  await waitFor(() => expect(screen.getByText("a.txt")).toBeInTheDocument());
  expect(screen.getByText("logs/")).toBeInTheDocument();
});

it("navigates into a folder", async () => {
  const list = vi
    .fn()
    .mockResolvedValueOnce({
      bucket: "b",
      prefix: "",
      blobs: [],
      folders: ["logs/"],
      next_page_token: null,
    })
    .mockResolvedValueOnce({
      bucket: "b",
      prefix: "logs/",
      blobs: [{ name: "logs/a.log", size: 1, content_type: "text/plain", updated: "t", generation: 1 }],
      folders: [],
      next_page_token: null,
    });
  const api = mkApi({ listBlobs: list });
  renderAt("/gcs/buckets/b", api);
  await userEvent.click(await screen.findByText("logs/"));
  await waitFor(() => expect(screen.getByText("logs/a.log")).toBeInTheDocument());
  expect(list).toHaveBeenLastCalledWith("b", { prefix: "logs/", delimiter: "/" });
});
```

- [ ] **Step 2: Implement `BlobList.tsx`**

```tsx
import { useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import type { UiApi } from "../../api/client";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { useAsync } from "../../hooks/useAsync";

import styles from "./BlobList.module.css";

interface Props {
  api: UiApi;
  onUploadClick?: () => void;
  onPreview?: (name: string) => void;
}

export function BlobList({ api, onUploadClick, onPreview }: Props) {
  const { bucket = "" } = useParams<{ bucket: string }>();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const prefix = params.get("prefix") ?? "";
  const blobs = useAsync(
    () => api.listBlobs(bucket, { prefix, delimiter: "/" }),
    [bucket, prefix],
  );
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const goTo = (newPrefix: string) => {
    const next = new URLSearchParams(params);
    if (newPrefix) next.set("prefix", newPrefix);
    else next.delete("prefix");
    setParams(next);
  };

  const goUp = () => {
    if (!prefix) return;
    const trimmed = prefix.replace(/\/$/, "");
    const idx = trimmed.lastIndexOf("/");
    goTo(idx === -1 ? "" : trimmed.slice(0, idx + 1));
  };

  if (blobs.status === "loading" || blobs.status === "idle") {
    return <div>Loading…</div>;
  }
  if (blobs.status === "error") {
    return <ErrorBanner error={blobs.error!} onRetry={blobs.refresh} />;
  }

  const data = blobs.data!;
  const empty = data.blobs.length === 0 && data.folders.length === 0;

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    await api.deleteBlob(bucket, pendingDelete);
    setPendingDelete(null);
    await blobs.refresh();
  };

  return (
    <div>
      <header className={styles.header}>
        <div>
          <button onClick={() => navigate("/gcs")} className={styles.back}>
            ← Buckets
          </button>
          <span className={styles.crumb}>
            {bucket}
            {prefix ? ` / ${prefix}` : ""}
          </span>
        </div>
        <button onClick={onUploadClick} className={styles.upload}>
          Upload
        </button>
      </header>
      {empty ? (
        <EmptyState
          title="This folder is empty"
          description="Upload a file to get started."
          actionLabel="Upload"
          onAction={onUploadClick}
        />
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Name</th>
              <th>Size</th>
              <th>Content-Type</th>
              <th>Updated</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {prefix && (
              <tr>
                <td colSpan={5}>
                  <button onClick={goUp} className={styles.link}>
                    ../
                  </button>
                </td>
              </tr>
            )}
            {data.folders.map((f) => (
              <tr key={f}>
                <td>
                  <button onClick={() => goTo(f)} className={styles.link}>
                    📁 {f.slice(prefix.length)}
                  </button>
                </td>
                <td colSpan={4}></td>
              </tr>
            ))}
            {data.blobs.map((b) => (
              <tr key={b.name}>
                <td>
                  <button onClick={() => onPreview?.(b.name)} className={styles.link}>
                    📄 {b.name.slice(prefix.length)}
                  </button>
                </td>
                <td>{b.size}</td>
                <td>{b.content_type}</td>
                <td>{b.updated}</td>
                <td>
                  <a href={api.downloadBlobUrl(bucket, b.name)} download>
                    Download
                  </a>{" "}
                  <button onClick={() => setPendingDelete(b.name)} className={styles.delete}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <ConfirmDialog
        open={pendingDelete !== null}
        title={`Delete "${pendingDelete}"?`}
        confirmLabel="Delete"
        destructive
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}
```

- [ ] **Step 3: `BlobList.module.css`**

```css
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.back { background: none; border: none; color: var(--accent); cursor: pointer; padding: 0; margin-right: 16px; }
.crumb { color: var(--muted); }
.upload { padding: 6px 14px; border-radius: 6px; background: var(--accent); color: white; border: none; cursor: pointer; }
.table { width: 100%; border-collapse: collapse; }
.table th, .table td { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--border); }
.link { background: none; border: none; color: var(--accent); cursor: pointer; padding: 0; }
.delete { background: none; border: none; color: var(--danger); cursor: pointer; }
```

- [ ] **Step 4: `BucketView.tsx` is just the container that owns the upload dialog state — implemented inline in Task 24. For now `GcsLanding.tsx` mounts BlobList directly:**

```tsx
import { Route, Routes } from "react-router-dom";

import { api } from "../../api/client";

import { BlobList } from "./BlobList";
import { BucketList } from "./BucketList";

export default function GcsLanding() {
  return (
    <Routes>
      <Route index element={<BucketList api={api} />} />
      <Route path="buckets/:bucket/*" element={<BlobList api={api} />} />
    </Routes>
  );
}
```

- [ ] **Step 5: Run tests + build**

```bash
cd web && npm test && npm run lint && npm run build
```

- [ ] **Step 6: Commit**

```bash
git add web src/gcp_local/ui/static
git commit -m "feat(web): blob list with prefix navigation and delete-with-confirm"
```

---

### Task 24: BlobUploadDialog (drag-drop + file picker)

**Files:**
- Create: `web/src/services/gcs/BlobUploadDialog.tsx`
- Create: `web/src/services/gcs/BlobUploadDialog.module.css`
- Create: `web/src/services/gcs/BlobUploadDialog.test.tsx`
- Modify: `web/src/services/gcs/GcsLanding.tsx`

- [ ] **Step 1: Write tests**

```tsx
// web/src/services/gcs/BlobUploadDialog.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { ApiError } from "../../api/client";

import { BlobUploadDialog } from "./BlobUploadDialog";

it("uploads via the file input", async () => {
  const onUpload = vi.fn().mockResolvedValue(undefined);
  const onClose = vi.fn();
  render(<BlobUploadDialog open onClose={onClose} onUpload={onUpload} />);
  const file = new File(["hi"], "hi.txt", { type: "text/plain" });
  await userEvent.upload(screen.getByLabelText(/select file/i), file);
  await userEvent.click(screen.getByRole("button", { name: /^upload$/i }));
  await waitFor(() => expect(onUpload).toHaveBeenCalledWith(file));
  expect(onClose).toHaveBeenCalled();
});

it("shows API error on failure and stays open", async () => {
  const onUpload = vi.fn().mockRejectedValue(new ApiError("payload_too_large", 413, "too big"));
  const onClose = vi.fn();
  render(<BlobUploadDialog open onClose={onClose} onUpload={onUpload} />);
  const file = new File(["hi"], "hi.txt", { type: "text/plain" });
  await userEvent.upload(screen.getByLabelText(/select file/i), file);
  await userEvent.click(screen.getByRole("button", { name: /^upload$/i }));
  await waitFor(() => expect(screen.getByText(/too big/)).toBeInTheDocument());
  expect(onClose).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Implement `BlobUploadDialog.tsx`**

```tsx
import { useState } from "react";

import styles from "./BlobUploadDialog.module.css";

interface Props {
  open: boolean;
  onClose: () => void;
  onUpload: (file: File) => Promise<void>;
}

export function BlobUploadDialog({ open, onClose, onUpload }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [dragActive, setDragActive] = useState(false);

  if (!open) return null;

  const handleSubmit = async () => {
    if (!file) return;
    setSubmitting(true);
    setError(null);
    try {
      await onUpload(file);
      setFile(null);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className={styles.backdrop} role="dialog" aria-modal="true">
      <div className={styles.modal}>
        <h2>Upload file</h2>
        <div
          className={`${styles.drop} ${dragActive ? styles.active : ""}`}
          onDragEnter={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragOver={(e) => e.preventDefault()}
          onDragLeave={() => setDragActive(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragActive(false);
            const f = e.dataTransfer.files?.[0];
            if (f) setFile(f);
          }}
        >
          {file ? (
            <div>
              {file.name} ({file.size} bytes)
            </div>
          ) : (
            <div>Drag a file here, or use the picker below.</div>
          )}
        </div>
        <label className={styles.picker}>
          Select file
          <input
            type="file"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        {error && <div className={styles.error}>{error.message}</div>}
        <div className={styles.actions}>
          <button onClick={onClose} disabled={submitting}>
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!file || submitting}
            className={styles.confirm}
          >
            {submitting ? "Uploading…" : "Upload"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: `BlobUploadDialog.module.css`**

```css
.backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: white; border-radius: 8px; padding: 24px; min-width: 480px; max-width: 600px; }
.drop { border: 2px dashed var(--border); border-radius: 8px; padding: 32px; text-align: center; color: var(--muted); margin: 12px 0; transition: all 0.15s; }
.drop.active { border-color: var(--accent); color: var(--accent); background: #eff6ff; }
.picker { display: inline-block; cursor: pointer; }
.error { color: var(--danger); margin: 12px 0; }
.actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px; }
.confirm { background: var(--accent); color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; }
.confirm:disabled { opacity: 0.5; cursor: not-allowed; }
```

- [ ] **Step 4: Wire upload into `BlobList`**

The simplest wiring is to keep the dialog inside `BlobList` so it shares the bucket/prefix context. Modify `BlobList` to manage `uploadOpen` state and render the dialog. Replace the existing implementation with:

```tsx
// inside BlobList()
const [uploadOpen, setUploadOpen] = useState(false);
// remove the onUploadClick prop; use setUploadOpen instead
// in JSX, where you call onUploadClick, call setUploadOpen(true)
// at the end of the component, before </div>:
<BlobUploadDialog
  open={uploadOpen}
  onClose={() => setUploadOpen(false)}
  onUpload={async (file) => {
    await api.uploadBlob(bucket, file, (prefix ?? "") + file.name);
    await blobs.refresh();
  }}
/>
```

(Remove `onUploadClick` and `onPreview` props from the `Props` interface — preview is wired in Task 25.)

- [ ] **Step 5: Run tests + build**

```bash
cd web && npm test && npm run lint && npm run build
```

- [ ] **Step 6: Commit**

```bash
git add web src/gcp_local/ui/static
git commit -m "feat(web): blob upload with drag-drop and file picker"
```

---

### Task 25: BlobPreview (text / JSON / image / fallback)

**Files:**
- Create: `web/src/services/gcs/BlobPreview.tsx`
- Create: `web/src/services/gcs/BlobPreview.module.css`
- Create: `web/src/services/gcs/BlobPreview.test.tsx`
- Modify: `web/src/services/gcs/BlobList.tsx`

- [ ] **Step 1: Write tests**

```tsx
// BlobPreview.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import { UiApi } from "../../api/client";

import { BlobPreview } from "./BlobPreview";

const mkApi = (overrides: Partial<UiApi>): UiApi => {
  const api = new UiApi();
  Object.assign(api, overrides);
  return api;
};

it("renders text content", async () => {
  const api = mkApi({
    getBlobMetadata: vi.fn().mockResolvedValue({
      bucket: "b",
      name: "x.txt",
      size: 2,
      content_type: "text/plain",
      time_created: "t",
      updated: "t",
      generation: 1,
      metageneration: 1,
      md5_hash: "",
      crc32c: "",
      metadata: {},
      preview: { kind: "text", text: "hi", image_data_url: null, truncated: false, reason: null },
    }),
  });
  render(<BlobPreview api={api} bucket="b" name="x.txt" onClose={() => {}} />);
  await waitFor(() => expect(screen.getByText("hi")).toBeInTheDocument());
});

it("renders truncated banner when text was cut", async () => {
  const api = mkApi({
    getBlobMetadata: vi.fn().mockResolvedValue({
      bucket: "b",
      name: "big.txt",
      size: 999999,
      content_type: "text/plain",
      time_created: "t",
      updated: "t",
      generation: 1,
      metageneration: 1,
      md5_hash: "",
      crc32c: "",
      metadata: {},
      preview: { kind: "text", text: "abc", image_data_url: null, truncated: true, reason: null },
    }),
  });
  render(<BlobPreview api={api} bucket="b" name="big.txt" onClose={() => {}} />);
  await waitFor(() => expect(screen.getByText(/truncated/i)).toBeInTheDocument());
});

it("falls back to a download link for non-previewable content", async () => {
  const api = mkApi({
    getBlobMetadata: vi.fn().mockResolvedValue({
      bucket: "b",
      name: "x.bin",
      size: 4,
      content_type: "application/octet-stream",
      time_created: "t",
      updated: "t",
      generation: 1,
      metageneration: 1,
      md5_hash: "",
      crc32c: "",
      metadata: {},
      preview: { kind: "none", text: null, image_data_url: null, truncated: false, reason: "no preview" },
    }),
  });
  render(<BlobPreview api={api} bucket="b" name="x.bin" onClose={() => {}} />);
  await waitFor(() => expect(screen.getByText(/no preview/i)).toBeInTheDocument());
  expect(screen.getByRole("link", { name: /download/i })).toHaveAttribute(
    "href",
    expect.stringContaining("/_emulator/ui-api/v1/gcs/buckets/b/blobs/x.bin/download"),
  );
});
```

- [ ] **Step 2: Implement `BlobPreview.tsx`**

```tsx
import type { UiApi } from "../../api/client";
import { ErrorBanner } from "../../components/ErrorBanner";
import { useAsync } from "../../hooks/useAsync";

import styles from "./BlobPreview.module.css";

interface Props {
  api: UiApi;
  bucket: string;
  name: string;
  onClose: () => void;
}

export function BlobPreview({ api, bucket, name, onClose }: Props) {
  const meta = useAsync(() => api.getBlobMetadata(bucket, name), [bucket, name]);

  return (
    <div className={styles.backdrop} role="dialog" aria-modal="true">
      <div className={styles.modal}>
        <header className={styles.header}>
          <h2>{name}</h2>
          <button onClick={onClose} aria-label="close">×</button>
        </header>
        <div className={styles.body}>
          {meta.status === "loading" || meta.status === "idle" ? (
            <div>Loading…</div>
          ) : meta.status === "error" ? (
            <ErrorBanner error={meta.error!} onRetry={meta.refresh} />
          ) : (
            <PreviewBody api={api} data={meta.data!} />
          )}
        </div>
      </div>
    </div>
  );
}

function PreviewBody({
  api,
  data,
}: {
  api: UiApi;
  data: NonNullable<Awaited<ReturnType<UiApi["getBlobMetadata"]>>>;
}) {
  const downloadHref = api.downloadBlobUrl(data.bucket, data.name);
  const preview = data.preview;
  return (
    <>
      <dl className={styles.meta}>
        <dt>Size</dt><dd>{data.size}</dd>
        <dt>Content-Type</dt><dd>{data.content_type}</dd>
        <dt>Updated</dt><dd>{data.updated}</dd>
      </dl>
      <a href={downloadHref} className={styles.download} download>
        Download
      </a>
      {preview?.kind === "text" || preview?.kind === "json" ? (
        <>
          {preview.truncated && (
            <div className={styles.truncated}>Preview truncated to first 1 MB.</div>
          )}
          <pre className={styles.text}>{preview.text}</pre>
        </>
      ) : preview?.kind === "image" && preview.image_data_url ? (
        <img src={preview.image_data_url} alt={data.name} className={styles.image} />
      ) : (
        <div className={styles.none}>{preview?.reason ?? "No inline preview."}</div>
      )}
    </>
  );
}
```

- [ ] **Step 3: `BlobPreview.module.css`**

```css
.backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: white; border-radius: 8px; min-width: 600px; max-width: 80vw; max-height: 80vh; display: flex; flex-direction: column; }
.header { display: flex; justify-content: space-between; align-items: center; padding: 16px 24px; border-bottom: 1px solid var(--border); }
.header button { background: none; border: none; font-size: 20px; cursor: pointer; }
.body { padding: 16px 24px; overflow: auto; }
.meta { display: grid; grid-template-columns: 120px 1fr; gap: 4px 12px; margin-bottom: 12px; }
.meta dt { color: var(--muted); }
.download { display: inline-block; padding: 6px 14px; border-radius: 6px; background: var(--accent); color: white; text-decoration: none; margin-bottom: 16px; }
.truncated { background: #fef9c3; color: #854d0e; padding: 8px 12px; border-radius: 6px; margin-bottom: 12px; }
.text { background: var(--row-alt); padding: 12px; border-radius: 6px; max-height: 50vh; overflow: auto; white-space: pre-wrap; }
.image { max-width: 100%; max-height: 50vh; }
.none { color: var(--muted); padding: 24px; text-align: center; }
```

- [ ] **Step 4: Wire BlobPreview into BlobList**

In `BlobList.tsx`, manage preview state:

```tsx
const [previewName, setPreviewName] = useState<string | null>(null);
// in the file-row button: onClick={() => setPreviewName(b.name)}
// at end of JSX:
{previewName && (
  <BlobPreview
    api={api}
    bucket={bucket}
    name={previewName}
    onClose={() => setPreviewName(null)}
  />
)}
```

- [ ] **Step 5: Run tests + build**

```bash
cd web && npm test && npm run lint && npm run build
```

- [ ] **Step 6: Commit**

```bash
git add web src/gcp_local/ui/static
git commit -m "feat(web): blob preview with text/json/image and download"
```

---

### Task 26: Frontend smoke run against the running server

**Files:**
- (no new files; this task verifies the full UI works against a real backend)

- [ ] **Step 1: Build the bundle**

```bash
cd web && npm run build && cd ..
```

- [ ] **Step 2: Start the emulator**

```bash
python -m gcp_local
```

Leave running in another terminal.

- [ ] **Step 3: Manual smoke test**

Open `http://localhost:4510/ui/` in a browser. Verify:

- Sidebar lists GCS as active and other services as disabled.
- "No buckets yet" empty state shows.
- Create a bucket named `demo`. It appears in the list.
- Click into `demo`. "This folder is empty" empty state shows.
- Upload a small text file. It appears in the list with size + content-type + updated.
- Click the file. Preview shows the text.
- Download. The browser saves the file with the right name.
- Delete the file (confirm modal). It disappears.
- Delete the bucket. It disappears from the list.

- [ ] **Step 4: Stop the server.** Kill the emulator (`Ctrl-C`).

- [ ] **Step 5: No commit needed** — this is a manual verification step. If anything failed, file the bug as a follow-up commit on the feature branch and re-run.

---

## Phase F — CI / Docker / packaging

### Task 27: Extend Docker smoke test to cover `/ui/` and ui-api

**Files:**
- Modify: `tests/integration/test_docker_image.py`

- [ ] **Step 1: Read the current Docker test to understand its shape**

Run: `cat tests/integration/test_docker_image.py | head -60`

- [ ] **Step 2: Add new assertions**

Append to the existing test (or add a new test in the same file):

```python
def test_ui_root_served_in_container(emulator_container):
    """The Docker image must ship the SPA bundle at /ui/."""
    import httpx

    base = emulator_container.admin_base_url  # e.g., http://localhost:4510
    r = httpx.get(f"{base}/ui/", follow_redirects=True, timeout=10)
    assert r.status_code == 200
    assert "<html" in r.text.lower()
    # The fallback page contains "npm run build"; the real bundle does not.
    assert "npm run build" not in r.text


def test_ui_api_round_trip_in_container(emulator_container):
    import httpx

    base = emulator_container.admin_base_url
    with httpx.Client(base_url=base, timeout=10) as c:
        r = c.get("/_emulator/ui-api/v1/services")
        assert r.status_code == 200
        body = r.json()
        names = {s["name"] for s in body["services"]}
        assert "gcs" in names
```

> Adapt the `emulator_container` fixture to whatever the existing test uses; the file itself defines the fixture or imports it from `tests/integration/conftest.py`. Keep test naming consistent with the surrounding code.

- [ ] **Step 3: Build the image and run the test**

```bash
docker build -f docker/Dockerfile -t gcp-local:dev .
pytest tests/integration/test_docker_image.py -v
```

> The Dockerfile must include the bundle. That work is in Task 28; this task may temporarily fail until that lands. **If running tasks in order, build the Dockerfile change first (Task 28), then run this test.**

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_docker_image.py
git commit -m "test(docker): assert /ui/ bundle and ui-api respond in container"
```

---

### Task 28: Multi-stage Dockerfile builds the SPA

**Files:**
- Modify: `docker/Dockerfile`

- [ ] **Step 1: Replace the contents of `docker/Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1.6

# Stage 1 — build the SPA
FROM node:20-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
RUN npm run build
# Output is at /web/dist (per vite.config.ts), but vite writes into
# ../src/gcp_local/ui/static at the repo level — emulate that here.
# We mount the python tree so the build writes to the expected path inside
# the build context. To keep the Docker stages independent, copy the bundle
# explicitly in stage 2 instead of relying on vite's outDir.
RUN mkdir -p /tmp/static && cp -r /web/dist/* /tmp/static/ 2>/dev/null || true
# vite's outDir was overridden in vite.config.ts to ../src/gcp_local/ui/static.
# Detect the right output path:
RUN if [ -d /web/dist ]; then cp -r /web/dist/. /tmp/static/; fi
# In case vite wrote to the python static dir (its configured outDir), pick that up:
RUN if [ -d /web/../src/gcp_local/ui/static ]; then cp -r /web/../src/gcp_local/ui/static/. /tmp/static/; fi

# Stage 2 — Python runtime
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

# Replace the in-repo ui/static placeholder with the freshly-built bundle.
COPY --from=web /tmp/static/ ./src/gcp_local/ui/static/

RUN pip install .

RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 4510

ENTRYPOINT ["gcp-local"]
```

> **Why the duplicated copies in stage 1:** `vite.config.ts` writes to `../src/gcp_local/ui/static` relative to `web/`, but that path doesn't exist in the standalone `web/` build context. We coerce both possible layouts into `/tmp/static` so the COPY in stage 2 is unambiguous.

A cleaner alternative is to override the outDir inside Docker via env var. **Implement this cleaner approach instead:**

Replace the stage-1 build with:

```dockerfile
FROM node:20-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
RUN VITE_OUT_DIR=/web/dist npx vite build --outDir /web/dist --emptyOutDir
```

And update `web/vite.config.ts` so `outDir` honours the env var when set:

```ts
build: {
  outDir: process.env.VITE_OUT_DIR ?? "../src/gcp_local/ui/static",
  emptyOutDir: true,
},
```

Stage 2 becomes:

```dockerfile
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY --from=web /web/dist/ ./src/gcp_local/ui/static/

RUN pip install .

RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 4510

ENTRYPOINT ["gcp-local"]
```

- [ ] **Step 2: Apply the cleaner approach (env-var outDir + simple COPY)**

Use the second Dockerfile variant above. Update `web/vite.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  base: "/ui/",
  build: {
    outDir: process.env.VITE_OUT_DIR ?? "../src/gcp_local/ui/static",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/_emulator": "http://localhost:4510",
    },
  },
});
```

- [ ] **Step 3: Build the image and run the smoke test**

```bash
docker build -f docker/Dockerfile -t gcp-local:dev .
pytest tests/integration/test_docker_image.py -v
```
Expected: green.

- [ ] **Step 4: Commit**

```bash
git add docker/Dockerfile web/vite.config.ts
git commit -m "build(docker): multi-stage build runs the SPA build in node:20

Stage 1 emits the bundle to /web/dist (overriding the dev outDir via
VITE_OUT_DIR). Stage 2 copies it into the Python source tree before
pip install."
```

---

### Task 29: GitHub Actions web job + bundle freshness check

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Add the `web` job and gate Python jobs on it**

Replace `.github/workflows/ci.yml` with:

```yaml
name: ci

on:
  push:
    branches: [master]
    tags: ['v*']
  pull_request:

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  web:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
          cache-dependency-path: web/package-lock.json
      - run: npm ci
        working-directory: web
      - run: npm run lint
        working-directory: web
      - run: npm test
        working-directory: web
      - run: npm run build
        working-directory: web
      - name: Verify the committed bundle matches the source
        # If `npm run build` produced a diff against the committed
        # src/gcp_local/ui/static, the contributor forgot to rebuild.
        run: |
          if ! git diff --quiet src/gcp_local/ui/static; then
            echo "::error::web bundle is stale. Run 'cd web && npm run build' and commit."
            git diff --stat src/gcp_local/ui/static
            exit 1
          fi

  lint-type-unit:
    runs-on: ubuntu-latest
    needs: web
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
          cache: pip
      - run: pip install -e ".[dev]"
      - run: ruff check .
      - run: ruff format --check .
      - run: mypy
      - run: pytest tests/unit -v

  integration:
    runs-on: ubuntu-latest
    needs: lint-type-unit
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
          cache: pip
      - run: pip install -e ".[dev]"
      - run: pytest tests/integration -v -k "not docker"

  docker:
    runs-on: ubuntu-latest
    needs: lint-type-unit
    steps:
      - uses: actions/checkout@v6
      - uses: docker/setup-buildx-action@v4
      - name: Build image
        run: docker build -f docker/Dockerfile -t gcp-local:dev .
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
          cache: pip
      - run: pip install -e ".[dev]"
      - run: pytest tests/integration/test_docker_image.py -v

  publish-image:
    runs-on: ubuntu-latest
    needs: [docker, integration]
    if: github.event_name == 'push'
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v6
      - uses: docker/setup-qemu-action@v4
      - uses: docker/setup-buildx-action@v4
      - uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - id: meta
        uses: docker/metadata-action@v6
        with:
          images: ghcr.io/${{ github.repository_owner }}/gcp-local
          tags: |
            type=ref,event=branch
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=sha,prefix=master-,enable=${{ github.ref == 'refs/heads/master' }}
            type=raw,value=latest,enable=${{ github.ref == 'refs/heads/master' }}
      - uses: docker/build-push-action@v7
        with:
          context: .
          file: docker/Dockerfile
          push: true
          platforms: linux/amd64,linux/arm64
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

- [ ] **Step 2: Verify locally that the freshness check works**

```bash
cd web && npm run build && cd ..
git status src/gcp_local/ui/static
```
Expected: clean (no diff). If there's a diff, you forgot to commit a previous build artifact.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add web job and gate python jobs on it

Builds the SPA, lints, runs vitest, and asserts the committed bundle
matches a fresh build (catches contributors who forgot to rebuild)."
```

---

## Phase G — Documentation

### Task 30: New `docs/development/ui.md`

**Files:**
- Create: `docs/development/ui.md`

- [ ] **Step 1: Write the file**

```markdown
# Browser UI

The `gcp-local` browser UI is a React SPA mounted on the admin port (`4510`) at `/ui/`. This document covers architecture, the dev loop, and how to add a new service to the UI in a follow-up spec.

## Architecture at a glance

- **Source tree:** `web/` (Vite + React + TypeScript).
- **Build output:** `src/gcp_local/ui/static/`. Committed in-repo so editable Python installs work without rebuilding the UI.
- **Mount:** `src/gcp_local/core/admin_api.py` mounts `StaticFiles` at `/ui/`. When the bundle is missing, a friendly fallback HTML page tells the user to run `npm run build`.
- **JSON API:** `/_emulator/ui-api/v1/...` (versioned, internal). Implemented in `src/gcp_local/core/ui_api/`. The router lives in `router.py`; per-service modules (e.g., `gcs.py`) hang off that.

The ui-api is **not** a public wire surface — it's a thin presenter over the same storage backends each service already uses. The GCS REST API on port 4443 remains the canonical wire emulation.

## Dev loop

```bash
cd web
npm install         # one-time
npm run dev         # starts Vite at http://localhost:5173 with /_emulator/* proxied to :4510
```

In another terminal, run the emulator:

```bash
python -m gcp_local
```

Open http://localhost:5173/ui/ for the live-reload dev experience, or build and serve from the emulator directly:

```bash
cd web && npm run build && cd ..
python -m gcp_local
# open http://localhost:4510/ui/
```

## Quality gates

```bash
cd web
npm run lint   # eslint
npm test       # vitest + React Testing Library
npm run build  # tsc -b + vite build
```

CI runs all three on every PR and fails if the committed bundle differs from a fresh build.

## Adding a service to the UI

A follow-up spec ships each remaining service (BigQuery, Secret Manager, Pub/Sub, Firestore). The recipe:

1. Add per-service ui-api endpoints under `src/gcp_local/core/ui_api/<service>.py`. Reuse the same envelope error pattern (`UiApiError`).
2. Mount the new router from `src/gcp_local/core/ui_api/router.py`.
3. Add typed methods on `UiApi` and types in `web/src/api/types.ts`.
4. Create components under `web/src/services/<service>/`. Follow the GCS pilot layout: list view → detail view → action dialogs.
5. Add the service name to `UI_SUPPORTED_SERVICES` in `router.py` and update the sidebar label map in `web/src/components/AppLayout.tsx`.
6. Wire routes in `App.tsx`.
7. Update `docs/services/<service>.md` with a Browser UI section, and `docs/architecture/<service>.md` with the ui-api consumer note.
```

- [ ] **Step 2: Commit**

```bash
git add docs/development/ui.md
git commit -m "docs(ui): how the browser UI is structured and how to extend it"
```

---

### Task 31: Update GCS user/architecture docs

**Files:**
- Modify: `docs/services/gcs.md`
- Modify: `docs/architecture/gcs.md`
- Modify: `docs/architecture/overview.md`

- [ ] **Step 1: Add a "Browser UI" section to `docs/services/gcs.md`**

Insert after the existing "Connect a client" or "Quickstart" section (whichever exists; check the actual file structure first by `head -50 docs/services/gcs.md`):

```markdown
## Browser UI

Open http://localhost:4510/ui/ to browse buckets and objects in a browser.

The UI lets you:

- List, create, and delete buckets.
- List blobs with prefix-folder navigation.
- Upload files (drag-drop or file picker; default 100 MB cap, configurable via `GCP_LOCAL_UI_MAX_UPLOAD_MB`).
- Download blobs.
- Preview text, JSON, and image blobs inline (1 MB / 5 MB caps respectively).
- Delete blobs.

The UI is read/write — there is no auth — and runs on the same admin port (`4510`) as the existing health/reset endpoints. The browser UI calls the internal `/_emulator/ui-api/v1` namespace; client libraries continue to use the GCS REST endpoints on port 4443.
```

- [ ] **Step 2: Add a note to `docs/architecture/gcs.md`**

In the "Internals" or "Components" section of the existing file (locate with `grep -n "## " docs/architecture/gcs.md`), add:

```markdown
### ui-api consumer

`src/gcp_local/core/ui_api/gcs.py` reads from and writes to the same `GcsStorage`
backend used by the public REST routes. The browser UI therefore sees a single,
authoritative state — uploads through `gsutil` show up immediately in the UI,
and vice versa.
```

- [ ] **Step 3: Update `docs/architecture/overview.md`**

Add a brief paragraph explaining the new layer:

```markdown
### Browser UI

A React SPA built into `src/gcp_local/ui/static/` is served at `/ui/` on the
admin port. It calls a versioned, internal namespace `/_emulator/ui-api/v1/...`
that presents the same in-process state the wire-level REST/gRPC services
expose. See `docs/development/ui.md` for architecture and the dev loop.
```

- [ ] **Step 4: Commit**

```bash
git add docs/services/gcs.md docs/architecture/gcs.md docs/architecture/overview.md
git commit -m "docs(gcs): document the browser UI and ui-api consumer"
```

---

### Task 32: README, CHANGELOG, ROADMAP, CONTRIBUTING

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `ROADMAP.md`
- Modify: `CONTRIBUTING.md`

- [ ] **Step 1: README — add a Browser UI section under Quickstart**

After the existing health-check curl example, add:

```markdown
### Browser UI

Open http://localhost:4510/ui/ to browse buckets and objects in your browser.
GCS ships in v1; BigQuery, Secret Manager, Pub/Sub, and Firestore land in
follow-ups (the sidebar greys those out for now). The UI is read/write,
local-only, and has no auth — never expose port 4510 on a non-loopback
interface.
```

- [ ] **Step 2: CHANGELOG — add an `Added` entry under `[Unreleased]`**

```markdown
### Added
- Browser UI mounted on the admin port (`4510`) at `/ui/`. Foundation + GCS
  pilot: list/create/delete buckets, list/upload/download/preview/delete blobs.
- Internal `/_emulator/ui-api/v1` JSON namespace consumed by the UI.
```

- [ ] **Step 3: ROADMAP — adjust UI bullets**

If the roadmap currently mentions a future UI, replace the bullet with:

```markdown
- Browser UI: GCS pilot landed in v0.3 (foundation). Follow-ups for BigQuery,
  Secret Manager, Pub/Sub, and Firestore are tracked as separate specs.
```

- [ ] **Step 4: CONTRIBUTING — document the node toolchain**

Add a section near the existing tooling instructions:

```markdown
## Frontend toolchain

The browser UI lives under `web/` (Vite + React + TypeScript). Working on the
UI requires Node 20 LTS:

```bash
cd web
npm install           # once
npm run dev           # http://localhost:5173/ui (hot reload)
npm run lint
npm test              # vitest
npm run build         # emits to ../src/gcp_local/ui/static
```

After changing UI source, **rebuild and commit the bundle** in
`src/gcp_local/ui/static/`. CI fails if the committed bundle drifts from
source. See `docs/development/ui.md` for the architecture overview.
```

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md ROADMAP.md CONTRIBUTING.md
git commit -m "docs: README, CHANGELOG, ROADMAP, CONTRIBUTING updates for UI"
```

---

### Task 33: Final audit per the repo Definition of Done

**Files:**
- (audit only — fix any inconsistencies surfaced)

- [ ] **Step 1: Run the full quality gate**

```bash
ruff check src/ tests/
ruff format src/ tests/
pytest tests/ --ignore=tests/integration/test_docker_image.py
cd web && npm run lint && npm test && npm run build && cd ..
git status src/gcp_local/ui/static  # bundle freshness
```

Expected: all clean.

- [ ] **Step 2: Walk the docs audit checklist from `CLAUDE.md`**

For each bullet, write down what was updated:

- `docs/services/gcs.md` — Browser UI section added (Task 31).
- `docs/architecture/gcs.md` — ui-api consumer note added (Task 31).
- `docs/architecture/overview.md` — UI paragraph added (Task 31).
- `README.md` — Browser UI under Quickstart (Task 32).
- `CHANGELOG.md` — Added entry under Unreleased (Task 32).
- `ROADMAP.md` — UI bullet adjusted (Task 32).
- `CONTRIBUTING.md` — Node toolchain section (Task 32).
- `docs/development/ui.md` — new (Task 30).
- `pyproject.toml` — wheel package data (Task 15).
- Inline comments — none stale; the spec is the source of truth.

- [ ] **Step 3: Walk the tests audit checklist**

- Unit: ui-api errors, router, gcs router (per endpoint), service-wiring storage property — all in place.
- Integration: ui-api end-to-end + Docker `/ui/` + ui-api round-trip.
- Frontend: vitest covers API client, AppLayout, primitives, BucketList, BlobList (folder nav), BlobUpload, BlobPreview.
- Defaults: `GCP_LOCAL_UI_MAX_UPLOAD_MB` default of 100 verified via env-var override test.

- [ ] **Step 4: Verify the full Docker build + smoke test once more**

```bash
docker build -f docker/Dockerfile -t gcp-local:dev .
pytest tests/integration/test_docker_image.py -v
```

- [ ] **Step 5: Open the PR**

Use the body template at the project root and reference both the spec and this plan. Call out the deliberate single-PR boundary and the size justification.

```bash
git push -u origin feat/services-ui-foundation
gh pr create --title "feat: services UI foundation + GCS pilot" --body "..."
```

(Body left to the engineer; they should describe the why and link to `docs/superpowers/specs/2026-05-03-services-ui-design.md` and this plan.)

- [ ] **Step 6: Verify CI passes**

```bash
gh pr checks
```
Expected: all green.

---

## Plan self-review (run before handing off)

- **Spec coverage**
  - Architecture (FastAPI mount + ui-api namespace) → Tasks 2, 3, 14.
  - GCS pilot ops (B1–B3, O1–O5, N2) → Tasks 6–13 (Python) + 22–25 (UI).
  - Auth (none, local-only) → no task; documented in README/CHANGELOG (Task 32) and the fallback HTML.
  - Dev workflow → Task 17 (Vite dev/build), `docs/development/ui.md` (Task 30).
  - Build/CI/Docker → Tasks 15, 28, 29.
  - Testing strategy → Phases B (unit), C (integration), D/E (frontend), F (Docker).
  - Error handling/empty states/upload caps → Tasks 1, 10, 20, 25.
  - Docs updates → Tasks 30–32.
  - Out of scope (other services, O6/O7, etc.) → not touched, as designed.
- **Placeholder scan:** every task has explicit code, exact paths, and exact commands. No "fill in", "TBD", or "as needed".
- **Type consistency:** `BucketSummary`, `BlobSummary`, `BlobMetadata`, `BlobPreview`, `UiApi.method()` names match between Python schemas, TS types, and component usage.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-03-services-ui-foundation.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
