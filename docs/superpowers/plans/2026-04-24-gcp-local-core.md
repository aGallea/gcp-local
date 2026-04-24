# gcp-local Core Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the core framework of `gcp-local` — service registry, lifecycle, state hub, storage base, error envelopes, admin API, CLI, Dockerfile, and CI — plus a dummy service used only to exercise the framework end-to-end. No real GCP services in this plan; those come in follow-on plans, one per service.

**Architecture:** Single Python process with pluggable services registered via entry points. Selected by runtime `SERVICES` env var. Each service runs its own listener(s); shared state via an in-process event hub. Admin API on a dedicated port. Docker image is the primary distribution.

**Tech Stack:** Python 3.13, asyncio, FastAPI (admin REST + REST services later), grpcio (later services), pytest + pytest-asyncio, ruff, mypy, Docker (buildx for multi-arch), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-04-24-gcp-local-core-design.md`

**Commit policy:** The plan includes `git commit` steps at natural TDD checkpoints, showing what a well-committed history would look like. If you prefer to review and commit in larger chunks, coalesce them — the content of each commit is what matters, not the granularity.

---

## Task 0: Repo initialization

**Files:**
- Create: `/Users/asafgallea/workspace/gcp-local/` (already exists with `docs/`)

- [ ] **Step 1: Initialize git**

```bash
cd /Users/asafgallea/workspace/gcp-local
git init -b main
git add docs/
git commit -m "docs: initial design spec and plan"
```

---

## Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/gcp_local/__init__.py`
- Create: `src/gcp_local/core/__init__.py`
- Create: `src/gcp_local/services/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/integration/__init__.py`
- Create: `.gitignore`
- Create: `README.md`
- Create: `LICENSE`
- Create: `ruff.toml`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "gcp-local"
version = "0.0.1"
description = "Local emulator for Google Cloud Platform services."
readme = "README.md"
license = { file = "LICENSE" }
requires-python = ">=3.13"
authors = [{ name = "Asaf Gallea" }]
classifiers = [
    "Development Status :: 3 - Alpha",
    "License :: OSI Approved :: Apache Software License",
    "Programming Language :: Python :: 3.13",
]
dependencies = [
    "fastapi>=0.110",
    "uvicorn>=0.27",
    "pydantic>=2.6",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.26",
    "ruff>=0.3",
    "mypy>=1.9",
    "google-cloud-storage>=2.14",
    "google-cloud-bigquery>=3.17",
    "google-cloud-pubsub>=2.19",
    "google-cloud-firestore>=2.14",
    "google-cloud-secret-manager>=2.18",
]

[project.scripts]
gcp-local = "gcp_local.cli:entrypoint"

[tool.hatch.build.targets.wheel]
packages = ["src/gcp_local"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.mypy]
python_version = "3.13"
strict = true
packages = ["gcp_local"]
mypy_path = "src"
```

- [ ] **Step 2: Create `ruff.toml`**

```toml
target-version = "py313"
line-length = 100

[lint]
select = ["E", "F", "W", "I", "UP", "B", "SIM", "RUF"]
ignore = ["E501"]  # line length handled by formatter
```

- [ ] **Step 3: Create `.gitignore`**

```
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.venv/
venv/
dist/
build/
.DS_Store
data/
*.duckdb
*.db
```

- [ ] **Step 4: Create `LICENSE`**

Paste the full text of the Apache License 2.0 from <https://www.apache.org/licenses/LICENSE-2.0.txt>.

- [ ] **Step 5: Create `README.md`**

```markdown
# gcp-local

Local emulator for Google Cloud Platform services — the GCP counterpart to LocalStack.

## Status

Early development. Not yet usable.

## Disclaimer

gcp-local is an independent open-source project. It is not affiliated with, endorsed by, or sponsored by Google LLC or Google Cloud. "Google Cloud Platform," "GCP," and related product names are trademarks of Google LLC.

## License

Apache 2.0.
```

- [ ] **Step 6: Create empty `__init__.py` files**

Create these five files, each empty:
- `src/gcp_local/__init__.py`
- `src/gcp_local/core/__init__.py`
- `src/gcp_local/services/__init__.py`
- `tests/__init__.py`
- `tests/unit/__init__.py`
- `tests/integration/__init__.py`

- [ ] **Step 7: Install and verify scaffold**

Run:
```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Expected: "collected 0 items" (no tests yet, but pytest runs cleanly).

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml ruff.toml .gitignore LICENSE README.md src/ tests/
git commit -m "chore: project scaffold"
```

---

## Task 2: Service Protocol and core data types

**Files:**
- Create: `src/gcp_local/core/service.py`
- Test: `tests/unit/test_service_protocol.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_service_protocol.py`:

```python
from gcp_local.core.service import HealthStatus, Port, Service


class GoodService:
    name = "good"
    default_ports = [Port(1234, "rest")]

    async def start(self, ctx):
        return None

    async def stop(self):
        return None

    async def reset_state(self):
        return None

    def health(self):
        return HealthStatus(ok=True)


def test_port_is_frozen():
    p = Port(1234, "rest")
    assert p.number == 1234
    assert p.protocol == "rest"


def test_health_status_defaults():
    hs = HealthStatus(ok=True)
    assert hs.ok is True
    assert hs.message == ""


def test_service_protocol_structural():
    svc = GoodService()
    assert isinstance(svc, Service)
```

- [ ] **Step 2: Run — should fail (import error)**

```bash
pytest tests/unit/test_service_protocol.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gcp_local.core.service'`.

- [ ] **Step 3: Implement `service.py`**

`src/gcp_local/core/service.py`:

```python
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

Protocol_ = Literal["rest", "grpc"]


@dataclass(frozen=True)
class Port:
    number: int
    protocol: Protocol_


@dataclass
class HealthStatus:
    ok: bool
    message: str = ""


@runtime_checkable
class Service(Protocol):
    name: str
    default_ports: list[Port]

    async def start(self, ctx: "Context") -> None: ...
    async def stop(self) -> None: ...
    async def reset_state(self) -> None: ...
    def health(self) -> HealthStatus: ...


# Forward-declared to avoid a circular import with context.py
class Context: ...
```

- [ ] **Step 4: Run — should pass**

```bash
pytest tests/unit/test_service_protocol.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/core/service.py tests/unit/test_service_protocol.py
git commit -m "feat(core): Service protocol, Port, HealthStatus"
```

---

## Task 3: Context object

**Files:**
- Create: `src/gcp_local/core/context.py`
- Modify: `src/gcp_local/core/service.py` (remove forward-declared stub)
- Test: `tests/unit/test_context.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_context.py`:

```python
from pathlib import Path

from gcp_local.core.context import Context


def test_context_fields(tmp_path: Path):
    ctx = Context(
        persist=True,
        data_dir=tmp_path,
        port_overrides={"gcs": 5555},
    )
    assert ctx.persist is True
    assert ctx.data_dir == tmp_path
    assert ctx.port_overrides["gcs"] == 5555


def test_context_defaults(tmp_path: Path):
    ctx = Context(persist=False, data_dir=tmp_path)
    assert ctx.port_overrides == {}
```

- [ ] **Step 2: Run — should fail**

```bash
pytest tests/unit/test_context.py -v
```

Expected: FAIL (import error).

- [ ] **Step 3: Implement `context.py`**

`src/gcp_local/core/context.py`:

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gcp_local.core.state_hub import StateHub


@dataclass
class Context:
    persist: bool
    data_dir: Path
    port_overrides: dict[str, int] = field(default_factory=dict)
    state_hub: "StateHub | None" = None
```

- [ ] **Step 4: Update `service.py` — remove forward-declared stub**

In `src/gcp_local/core/service.py`, replace the placeholder `class Context: ...` at the bottom with a proper import under `TYPE_CHECKING`:

```python
from dataclasses import dataclass
from typing import Literal, Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:
    from gcp_local.core.context import Context

Protocol_ = Literal["rest", "grpc"]


@dataclass(frozen=True)
class Port:
    number: int
    protocol: Protocol_


@dataclass
class HealthStatus:
    ok: bool
    message: str = ""


@runtime_checkable
class Service(Protocol):
    name: str
    default_ports: list[Port]

    async def start(self, ctx: "Context") -> None: ...
    async def stop(self) -> None: ...
    async def reset_state(self) -> None: ...
    def health(self) -> HealthStatus: ...
```

- [ ] **Step 5: Run both test files — should pass**

```bash
pytest tests/unit/test_context.py tests/unit/test_service_protocol.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/core/context.py src/gcp_local/core/service.py tests/unit/test_context.py
git commit -m "feat(core): Context object"
```

---

## Task 4: State hub (in-process pub/sub)

**Files:**
- Create: `src/gcp_local/core/state_hub.py`
- Test: `tests/unit/test_state_hub.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_state_hub.py`:

```python
import asyncio

import pytest

from gcp_local.core.state_hub import StateHub


async def test_publish_with_no_subscribers_is_noop():
    hub = StateHub()
    await hub.publish("nobody.listening", {"x": 1})  # should not raise


async def test_single_subscriber_receives_event():
    hub = StateHub()
    received: list[dict] = []

    async def handler(event: dict) -> None:
        received.append(event)

    hub.subscribe("gcs.object.created", handler)
    await hub.publish("gcs.object.created", {"bucket": "b", "name": "o"})
    assert received == [{"bucket": "b", "name": "o"}]


async def test_multiple_subscribers_all_receive():
    hub = StateHub()
    count = {"a": 0, "b": 0}

    async def ha(event: dict) -> None:
        count["a"] += 1

    async def hb(event: dict) -> None:
        count["b"] += 1

    hub.subscribe("topic", ha)
    hub.subscribe("topic", hb)
    await hub.publish("topic", {})
    assert count == {"a": 1, "b": 1}


async def test_handler_exception_does_not_stop_others():
    hub = StateHub()
    received: list[int] = []

    async def broken(event: dict) -> None:
        raise RuntimeError("boom")

    async def ok(event: dict) -> None:
        received.append(1)

    hub.subscribe("t", broken)
    hub.subscribe("t", ok)
    await hub.publish("t", {})
    assert received == [1]
```

- [ ] **Step 2: Run — should fail**

```bash
pytest tests/unit/test_state_hub.py -v
```

Expected: FAIL (import error).

- [ ] **Step 3: Implement `state_hub.py`**

`src/gcp_local/core/state_hub.py`:

```python
import asyncio
import logging
from collections import defaultdict
from typing import Awaitable, Callable

log = logging.getLogger(__name__)

Handler = Callable[[dict], Awaitable[None]]


class StateHub:
    """In-process async pub/sub bus for cross-service events."""

    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subs[topic].append(handler)

    async def publish(self, topic: str, event: dict) -> None:
        handlers = list(self._subs.get(topic, ()))
        if not handlers:
            return
        results = await asyncio.gather(
            *(self._safe(h, event) for h in handlers),
            return_exceptions=False,
        )
        del results

    async def _safe(self, handler: Handler, event: dict) -> None:
        try:
            await handler(event)
        except Exception:
            log.exception("state_hub handler raised for event %r", event)
```

- [ ] **Step 4: Run — should pass**

```bash
pytest tests/unit/test_state_hub.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/core/state_hub.py tests/unit/test_state_hub.py
git commit -m "feat(core): in-process state hub for cross-service events"
```

---

## Task 5: Storage base helpers

**Files:**
- Create: `src/gcp_local/core/storage.py`
- Test: `tests/unit/test_storage.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_storage.py`:

```python
from pathlib import Path

from gcp_local.core.storage import data_path


def test_data_path_creates_nested_dir(tmp_path: Path):
    result = data_path("gcs", tmp_path)
    assert result == tmp_path / "gcs"
    assert result.is_dir()


def test_data_path_idempotent(tmp_path: Path):
    p1 = data_path("bigquery", tmp_path)
    p2 = data_path("bigquery", tmp_path)
    assert p1 == p2
    assert p1.is_dir()
```

- [ ] **Step 2: Run — should fail**

```bash
pytest tests/unit/test_storage.py -v
```

Expected: FAIL (import error).

- [ ] **Step 3: Implement `storage.py`**

`src/gcp_local/core/storage.py`:

```python
from pathlib import Path
from typing import Protocol


class Storage(Protocol):
    """Marker protocol for per-service storage backends.

    Each service defines its own richer protocol inheriting from this.
    The core only needs to know how to locate on-disk state dirs.
    """


def data_path(service_name: str, base: Path) -> Path:
    """Return (and create) the on-disk directory for a service under `base`."""
    p = base / service_name
    p.mkdir(parents=True, exist_ok=True)
    return p
```

- [ ] **Step 4: Run — should pass**

```bash
pytest tests/unit/test_storage.py -v
```

Expected: all 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/core/storage.py tests/unit/test_storage.py
git commit -m "feat(core): storage base marker and data_path helper"
```

---

## Task 6: Error envelope builders

**Files:**
- Create: `src/gcp_local/core/errors.py`
- Test: `tests/unit/test_errors.py`

Scope note: gRPC status helpers are stubbed in this task (returning a tuple of `(code_name, message)`) because grpcio is not yet a runtime dependency — it's added when the first gRPC service lands. The REST envelope is fully implemented.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_errors.py`:

```python
from gcp_local.core.errors import GcpError, rest_error_body


def test_rest_envelope_shape():
    err = GcpError(code=404, reason="notFound", message="Bucket b does not exist")
    body = rest_error_body(err)
    assert body == {
        "error": {
            "code": 404,
            "message": "Bucket b does not exist",
            "errors": [
                {
                    "domain": "global",
                    "reason": "notFound",
                    "message": "Bucket b does not exist",
                }
            ],
            "status": "NOT_FOUND",
        }
    }


def test_rest_envelope_unknown_status_uses_unknown():
    err = GcpError(code=418, reason="iamATeapot", message="hi")
    body = rest_error_body(err)
    assert body["error"]["status"] == "UNKNOWN"
```

- [ ] **Step 2: Run — should fail**

```bash
pytest tests/unit/test_errors.py -v
```

Expected: FAIL (import error).

- [ ] **Step 3: Implement `errors.py`**

`src/gcp_local/core/errors.py`:

```python
from dataclasses import dataclass

_HTTP_TO_STATUS: dict[int, str] = {
    400: "INVALID_ARGUMENT",
    401: "UNAUTHENTICATED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    409: "ALREADY_EXISTS",
    412: "FAILED_PRECONDITION",
    429: "RESOURCE_EXHAUSTED",
    499: "CANCELLED",
    500: "INTERNAL",
    501: "UNIMPLEMENTED",
    503: "UNAVAILABLE",
    504: "DEADLINE_EXCEEDED",
}


@dataclass
class GcpError(Exception):
    code: int
    reason: str
    message: str

    def __str__(self) -> str:
        return f"{self.code} {self.reason}: {self.message}"


def rest_error_body(err: GcpError) -> dict:
    """Build the JSON body in the shape `google-api-core` expects.

    Shape matches the `googleapiclient`-style error envelope:
    https://cloud.google.com/apis/design/errors
    """
    return {
        "error": {
            "code": err.code,
            "message": err.message,
            "errors": [
                {
                    "domain": "global",
                    "reason": err.reason,
                    "message": err.message,
                }
            ],
            "status": _HTTP_TO_STATUS.get(err.code, "UNKNOWN"),
        }
    }
```

- [ ] **Step 4: Run — should pass**

```bash
pytest tests/unit/test_errors.py -v
```

Expected: all 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/core/errors.py tests/unit/test_errors.py
git commit -m "feat(core): REST error envelope matching GCP shape"
```

---

## Task 7: Service registry

**Files:**
- Create: `src/gcp_local/core/registry.py`
- Test: `tests/unit/test_registry.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_registry.py`:

```python
import pytest

from gcp_local.core.registry import ServiceRegistry, UnknownServiceError
from gcp_local.core.service import HealthStatus, Port


class FakeA:
    name = "a"
    default_ports = [Port(1, "rest")]

    async def start(self, ctx): ...
    async def stop(self): ...
    async def reset_state(self): ...
    def health(self) -> HealthStatus:
        return HealthStatus(ok=True)


class FakeB:
    name = "b"
    default_ports = [Port(2, "grpc")]

    async def start(self, ctx): ...
    async def stop(self): ...
    async def reset_state(self): ...
    def health(self) -> HealthStatus:
        return HealthStatus(ok=True)


def test_register_and_get():
    r = ServiceRegistry()
    r.register("a", FakeA)
    assert r.get("a") is FakeA


def test_duplicate_registration_raises():
    r = ServiceRegistry()
    r.register("a", FakeA)
    with pytest.raises(ValueError, match="already registered"):
        r.register("a", FakeA)


def test_get_unknown_raises():
    r = ServiceRegistry()
    with pytest.raises(UnknownServiceError):
        r.get("nope")


def test_names_sorted():
    r = ServiceRegistry()
    r.register("b", FakeB)
    r.register("a", FakeA)
    assert r.names() == ["a", "b"]


def test_resolve_all():
    r = ServiceRegistry()
    r.register("a", FakeA)
    r.register("b", FakeB)
    assert r.resolve_selection("all") == ["a", "b"]


def test_resolve_subset():
    r = ServiceRegistry()
    r.register("a", FakeA)
    r.register("b", FakeB)
    assert r.resolve_selection("a") == ["a"]
    assert r.resolve_selection("a,b") == ["a", "b"]
    assert r.resolve_selection(" a , b ") == ["a", "b"]


def test_resolve_unknown_name_raises():
    r = ServiceRegistry()
    r.register("a", FakeA)
    with pytest.raises(UnknownServiceError, match="nope"):
        r.resolve_selection("a,nope")


def test_resolve_empty_is_empty():
    r = ServiceRegistry()
    r.register("a", FakeA)
    assert r.resolve_selection("") == []
```

- [ ] **Step 2: Run — should fail**

```bash
pytest tests/unit/test_registry.py -v
```

Expected: FAIL (import error).

- [ ] **Step 3: Implement `registry.py`**

`src/gcp_local/core/registry.py`:

```python
from importlib.metadata import entry_points

from gcp_local.core.service import Service


class UnknownServiceError(KeyError):
    pass


class ServiceRegistry:
    """Holds the set of services that have been registered in this process.

    Services can be registered programmatically (tests) or discovered via
    Python entry points in the `gcp_local.services` group.
    """

    def __init__(self) -> None:
        self._classes: dict[str, type[Service]] = {}

    def register(self, name: str, service_cls: type[Service]) -> None:
        if name in self._classes:
            raise ValueError(f"service {name!r} already registered")
        self._classes[name] = service_cls

    def get(self, name: str) -> type[Service]:
        try:
            return self._classes[name]
        except KeyError:
            raise UnknownServiceError(name) from None

    def names(self) -> list[str]:
        return sorted(self._classes)

    def discover_from_entry_points(self, group: str = "gcp_local.services") -> None:
        for ep in entry_points(group=group):
            cls = ep.load()
            self.register(ep.name, cls)

    def resolve_selection(self, spec: str) -> list[str]:
        """Resolve a `SERVICES` env value to a sorted list of service names.

        Accepted values:
          - "all"  -> every registered service
          - ""     -> no services
          - comma-separated names -> those services, sorted
        """
        spec = spec.strip()
        if spec == "all":
            return self.names()
        if not spec:
            return []
        requested = sorted({s.strip() for s in spec.split(",") if s.strip()})
        unknown = [s for s in requested if s not in self._classes]
        if unknown:
            raise UnknownServiceError(", ".join(unknown))
        return requested
```

- [ ] **Step 4: Run — should pass**

```bash
pytest tests/unit/test_registry.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/core/registry.py tests/unit/test_registry.py
git commit -m "feat(core): service registry with entry-point discovery"
```

---

## Task 8: Lifecycle orchestrator

**Files:**
- Create: `src/gcp_local/core/lifecycle.py`
- Test: `tests/unit/test_lifecycle.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_lifecycle.py`:

```python
import asyncio
from pathlib import Path

import pytest

from gcp_local.core.context import Context
from gcp_local.core.lifecycle import Lifecycle, ServiceStartError
from gcp_local.core.service import HealthStatus, Port


class RecordingService:
    def __init__(self, name: str) -> None:
        self.name = name
        self.default_ports = [Port(1, "rest")]
        self.started = False
        self.stopped = False
        self.resets = 0

    async def start(self, ctx):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def reset_state(self):
        self.resets += 1

    def health(self) -> HealthStatus:
        return HealthStatus(ok=self.started)


class FailingStart(RecordingService):
    async def start(self, ctx):
        raise RuntimeError("boom")


def make_ctx(tmp_path: Path) -> Context:
    return Context(persist=False, data_dir=tmp_path)


async def test_start_all_starts_every_service(tmp_path: Path):
    a, b = RecordingService("a"), RecordingService("b")
    lc = Lifecycle([a, b], make_ctx(tmp_path))
    await lc.start_all()
    assert a.started and b.started


async def test_stop_all_stops_every_service(tmp_path: Path):
    a, b = RecordingService("a"), RecordingService("b")
    lc = Lifecycle([a, b], make_ctx(tmp_path))
    await lc.start_all()
    await lc.stop_all()
    assert a.stopped and b.stopped


async def test_start_failure_rolls_back(tmp_path: Path):
    a = RecordingService("a")
    bad = FailingStart("bad")
    lc = Lifecycle([a, bad], make_ctx(tmp_path))
    with pytest.raises(ServiceStartError, match="bad"):
        await lc.start_all()
    # `a` had started, so it must be stopped during rollback
    assert a.stopped is True


async def test_reset_all_resets_every_service(tmp_path: Path):
    a, b = RecordingService("a"), RecordingService("b")
    lc = Lifecycle([a, b], make_ctx(tmp_path))
    await lc.reset_all()
    assert a.resets == 1 and b.resets == 1


async def test_reset_specific_service(tmp_path: Path):
    a, b = RecordingService("a"), RecordingService("b")
    lc = Lifecycle([a, b], make_ctx(tmp_path))
    await lc.reset("b")
    assert a.resets == 0 and b.resets == 1


async def test_reset_unknown_raises(tmp_path: Path):
    a = RecordingService("a")
    lc = Lifecycle([a], make_ctx(tmp_path))
    with pytest.raises(KeyError):
        await lc.reset("nope")
```

- [ ] **Step 2: Run — should fail**

```bash
pytest tests/unit/test_lifecycle.py -v
```

Expected: FAIL (import error).

- [ ] **Step 3: Implement `lifecycle.py`**

`src/gcp_local/core/lifecycle.py`:

```python
import asyncio
import logging

from gcp_local.core.context import Context
from gcp_local.core.service import HealthStatus, Service

log = logging.getLogger(__name__)


class ServiceStartError(RuntimeError):
    """Raised when a service fails to start. The rest of the stack has been rolled back."""


class Lifecycle:
    """Orchestrates concurrent start/stop of a fixed set of service instances."""

    def __init__(self, services: list[Service], ctx: Context) -> None:
        self.services = services
        self.ctx = ctx
        self._started: list[Service] = []

    def _by_name(self, name: str) -> Service:
        for s in self.services:
            if s.name == name:
                return s
        raise KeyError(name)

    async def start_all(self) -> None:
        # Start serially so rollback on failure is unambiguous.
        for svc in self.services:
            try:
                await svc.start(self.ctx)
            except Exception as e:
                log.exception("service %s failed to start", svc.name)
                await self._rollback()
                raise ServiceStartError(f"{svc.name}: {e}") from e
            self._started.append(svc)

    async def _rollback(self) -> None:
        for svc in reversed(self._started):
            try:
                await svc.stop()
            except Exception:
                log.exception("service %s failed to stop during rollback", svc.name)
        self._started.clear()

    async def stop_all(self) -> None:
        for svc in reversed(self._started):
            try:
                await svc.stop()
            except Exception:
                log.exception("service %s failed to stop", svc.name)
        self._started.clear()

    async def reset_all(self) -> None:
        await asyncio.gather(*(s.reset_state() for s in self.services))

    async def reset(self, name: str) -> None:
        await self._by_name(name).reset_state()

    def health_all(self) -> dict[str, HealthStatus]:
        return {s.name: s.health() for s in self.services}
```

- [ ] **Step 4: Run — should pass**

```bash
pytest tests/unit/test_lifecycle.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/core/lifecycle.py tests/unit/test_lifecycle.py
git commit -m "feat(core): lifecycle orchestrator with rollback on start failure"
```

---

## Task 9: Admin API

**Files:**
- Create: `src/gcp_local/core/admin_api.py`
- Test: `tests/unit/test_admin_api.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_admin_api.py`:

```python
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from gcp_local.core.admin_api import build_admin_app
from gcp_local.core.context import Context
from gcp_local.core.lifecycle import Lifecycle
from gcp_local.core.service import HealthStatus, Port


class TinyService:
    def __init__(self, name: str) -> None:
        self.name = name
        self.default_ports = [Port(9999, "rest")]
        self.resets = 0

    async def start(self, ctx): ...
    async def stop(self): ...
    async def reset_state(self):
        self.resets += 1

    def health(self) -> HealthStatus:
        return HealthStatus(ok=True, message=f"{self.name} healthy")


@pytest.fixture
def client(tmp_path: Path):
    svc_a = TinyService("a")
    svc_b = TinyService("b")
    lc = Lifecycle(
        [svc_a, svc_b],
        Context(persist=False, data_dir=tmp_path),
    )
    app = build_admin_app(lc)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test"), svc_a, svc_b


async def test_health(client):
    c, _, _ = client
    r = await c.get("/_emulator/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert set(body["services"].keys()) == {"a", "b"}


async def test_services_list(client):
    c, _, _ = client
    r = await c.get("/_emulator/services")
    assert r.status_code == 200
    body = r.json()
    names = {s["name"] for s in body["services"]}
    assert names == {"a", "b"}


async def test_reset_all(client):
    c, a, b = client
    r = await c.post("/_emulator/reset")
    assert r.status_code == 204
    assert a.resets == 1 and b.resets == 1


async def test_reset_specific(client):
    c, a, b = client
    r = await c.post("/_emulator/reset", params={"service": "b"})
    assert r.status_code == 204
    assert a.resets == 0 and b.resets == 1


async def test_reset_unknown_service_404(client):
    c, _, _ = client
    r = await c.post("/_emulator/reset", params={"service": "nope"})
    assert r.status_code == 404
```

- [ ] **Step 2: Run — should fail**

```bash
pytest tests/unit/test_admin_api.py -v
```

Expected: FAIL (import error).

- [ ] **Step 3: Implement `admin_api.py`**

`src/gcp_local/core/admin_api.py`:

```python
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from gcp_local.core.lifecycle import Lifecycle


def build_admin_app(lc: Lifecycle) -> FastAPI:
    app = FastAPI(title="gcp-local admin API", version="0.0.1")

    @app.get("/_emulator/health")
    async def health() -> JSONResponse:
        statuses = lc.health_all()
        overall = all(s.ok for s in statuses.values())
        return JSONResponse(
            {
                "ok": overall,
                "services": {
                    name: {"ok": s.ok, "message": s.message}
                    for name, s in statuses.items()
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
                        {"number": p.number, "protocol": p.protocol}
                        for p in s.default_ports
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
                raise HTTPException(
                    status_code=404, detail=f"unknown service: {service}"
                ) from None
        return Response(status_code=204)

    return app
```

- [ ] **Step 4: Run — should pass**

```bash
pytest tests/unit/test_admin_api.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/core/admin_api.py tests/unit/test_admin_api.py
git commit -m "feat(core): admin API with health, services, reset endpoints"
```

---

## Task 10: CLI entrypoint

**Files:**
- Create: `src/gcp_local/cli.py`
- Test: `tests/unit/test_cli.py`

The CLI's job: read env (`SERVICES`, `PERSIST`, `GCP_LOCAL_DATA_DIR`, `GCP_LOCAL_ADMIN_PORT`, per-service port overrides), build the `Context`, instantiate selected services, start them, start the admin API, wait for SIGINT/SIGTERM, stop cleanly.

Testing strategy: the `main` coroutine is split so the env-parsing logic is pure (and easy to unit-test), and the boot is exercised later in the integration test task.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_cli.py`:

```python
from pathlib import Path

import pytest

from gcp_local.cli import Settings, build_settings
from gcp_local.core.registry import ServiceRegistry, UnknownServiceError
from gcp_local.core.service import HealthStatus, Port


class Svc:
    name = ""
    default_ports = [Port(1, "rest")]
    async def start(self, ctx): ...
    async def stop(self): ...
    async def reset_state(self): ...
    def health(self) -> HealthStatus:
        return HealthStatus(ok=True)


def make_registry() -> ServiceRegistry:
    r = ServiceRegistry()
    for name in ("gcs", "bigquery"):
        cls = type(f"{name}Svc", (Svc,), {"name": name})
        r.register(name, cls)
    return r


def test_defaults(tmp_path: Path):
    s = build_settings(env={}, registry=make_registry(), default_data_dir=tmp_path)
    assert s.services == ["bigquery", "gcs"]
    assert s.persist is False
    assert s.data_dir == tmp_path
    assert s.admin_port == 4510
    assert s.port_overrides == {}


def test_services_subset(tmp_path: Path):
    s = build_settings(
        env={"SERVICES": "gcs"},
        registry=make_registry(),
        default_data_dir=tmp_path,
    )
    assert s.services == ["gcs"]


def test_persist_truthy(tmp_path: Path):
    for val in ("1", "true", "TRUE", "yes"):
        s = build_settings(
            env={"PERSIST": val},
            registry=make_registry(),
            default_data_dir=tmp_path,
        )
        assert s.persist is True, val


def test_persist_falsy(tmp_path: Path):
    for val in ("0", "false", "no", ""):
        s = build_settings(
            env={"PERSIST": val},
            registry=make_registry(),
            default_data_dir=tmp_path,
        )
        assert s.persist is False, val


def test_port_overrides(tmp_path: Path):
    s = build_settings(
        env={"GCS_EMULATOR_PORT": "5555", "BIGQUERY_EMULATOR_PORT": "9051"},
        registry=make_registry(),
        default_data_dir=tmp_path,
    )
    assert s.port_overrides == {"gcs": 5555, "bigquery": 9051}


def test_admin_port_override(tmp_path: Path):
    s = build_settings(
        env={"GCP_LOCAL_ADMIN_PORT": "4600"},
        registry=make_registry(),
        default_data_dir=tmp_path,
    )
    assert s.admin_port == 4600


def test_unknown_service_raises(tmp_path: Path):
    with pytest.raises(UnknownServiceError):
        build_settings(
            env={"SERVICES": "gcs,nope"},
            registry=make_registry(),
            default_data_dir=tmp_path,
        )
```

- [ ] **Step 2: Run — should fail**

```bash
pytest tests/unit/test_cli.py -v
```

Expected: FAIL (import error).

- [ ] **Step 3: Implement `cli.py`**

`src/gcp_local/cli.py`:

```python
import asyncio
import logging
import os
import signal
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import uvicorn

from gcp_local.core.admin_api import build_admin_app
from gcp_local.core.context import Context
from gcp_local.core.lifecycle import Lifecycle
from gcp_local.core.registry import ServiceRegistry
from gcp_local.core.state_hub import StateHub

log = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}


@dataclass
class Settings:
    services: list[str]
    persist: bool
    data_dir: Path
    admin_port: int
    port_overrides: dict[str, int]


def build_settings(
    env: Mapping[str, str],
    registry: ServiceRegistry,
    default_data_dir: Path,
) -> Settings:
    selection = env.get("SERVICES", "all")
    services = registry.resolve_selection(selection)
    persist = env.get("PERSIST", "").strip().lower() in _TRUTHY
    data_dir = Path(env.get("GCP_LOCAL_DATA_DIR") or default_data_dir)
    admin_port = int(env.get("GCP_LOCAL_ADMIN_PORT", "4510"))

    port_overrides: dict[str, int] = {}
    for name in registry.names():
        key = f"{name.upper()}_EMULATOR_PORT"
        if key in env and env[key].strip():
            port_overrides[name] = int(env[key])

    return Settings(
        services=services,
        persist=persist,
        data_dir=data_dir,
        admin_port=admin_port,
        port_overrides=port_overrides,
    )


async def run(registry: ServiceRegistry, settings: Settings) -> int:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    hub = StateHub()
    ctx = Context(
        persist=settings.persist,
        data_dir=settings.data_dir,
        port_overrides=settings.port_overrides,
        state_hub=hub,
    )
    services = [registry.get(n)() for n in settings.services]
    lc = Lifecycle(services, ctx)

    log.info("starting services: %s", ", ".join(settings.services) or "(none)")
    await lc.start_all()

    admin = build_admin_app(lc)
    admin_server = uvicorn.Server(
        uvicorn.Config(
            admin,
            host="0.0.0.0",
            port=settings.admin_port,
            log_level="info",
            access_log=False,
        )
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass  # Windows CI

    admin_task = asyncio.create_task(admin_server.serve(), name="admin")
    stop_task = asyncio.create_task(stop_event.wait(), name="stop")
    done, _ = await asyncio.wait(
        {admin_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
    )

    admin_server.should_exit = True
    for t in (admin_task, stop_task):
        if not t.done():
            t.cancel()
    await asyncio.gather(admin_task, stop_task, return_exceptions=True)
    await lc.stop_all()
    return 0


def entrypoint() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    registry = ServiceRegistry()
    registry.discover_from_entry_points()
    settings = build_settings(
        env=os.environ,
        registry=registry,
        default_data_dir=Path("/data"),
    )
    sys.exit(asyncio.run(run(registry, settings)))


if __name__ == "__main__":
    entrypoint()
```

- [ ] **Step 4: Run — should pass**

```bash
pytest tests/unit/test_cli.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/cli.py tests/unit/test_cli.py
git commit -m "feat(core): CLI entrypoint with settings parsing"
```

---

## Task 11: Dummy service + integration test harness

This task exists only to prove the core framework works end-to-end without waiting for a real service to land. The dummy service will be deleted (or moved under `tests/`) when the first real service arrives.

**Files:**
- Create: `src/gcp_local/services/_dummy/__init__.py`
- Create: `src/gcp_local/services/_dummy/service.py`
- Modify: `pyproject.toml` (register the dummy entry point)
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_core_end_to_end.py`

- [ ] **Step 1: Create the dummy service**

`src/gcp_local/services/_dummy/__init__.py`:

```python
from gcp_local.services._dummy.service import DummyService

__all__ = ["DummyService"]
```

`src/gcp_local/services/_dummy/service.py`:

```python
from gcp_local.core.context import Context
from gcp_local.core.service import HealthStatus, Port


class DummyService:
    """Minimal Service implementation used only to exercise the core framework.

    Will be removed once the first real GCP service lands.
    """

    name = "dummy"
    default_ports = [Port(4599, "rest")]

    def __init__(self) -> None:
        self._started = False
        self._resets = 0

    async def start(self, ctx: Context) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def reset_state(self) -> None:
        self._resets += 1

    def health(self) -> HealthStatus:
        return HealthStatus(
            ok=self._started,
            message=f"resets={self._resets}",
        )
```

- [ ] **Step 2: Register the dummy via entry points**

In `pyproject.toml`, add:

```toml
[project.entry-points."gcp_local.services"]
dummy = "gcp_local.services._dummy:DummyService"
```

Reinstall to pick up the entry point:

```bash
pip install -e ".[dev]"
```

- [ ] **Step 3: Create the integration test fixture**

`tests/integration/conftest.py`:

```python
import asyncio
import socket
from pathlib import Path
from typing import AsyncIterator

import pytest_asyncio

from gcp_local.cli import Settings, run
from gcp_local.core.registry import ServiceRegistry
from gcp_local.services._dummy import DummyService


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_for_port(port: int, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
            return
        except OSError:
            await asyncio.sleep(0.05)
    raise TimeoutError(f"port {port} did not open within {timeout}s")


@pytest_asyncio.fixture
async def emulator(tmp_path: Path) -> AsyncIterator[dict]:
    """Boot the emulator in-process with only the dummy service."""
    registry = ServiceRegistry()
    registry.register("dummy", DummyService)

    admin_port = _free_port()
    settings = Settings(
        services=["dummy"],
        persist=False,
        data_dir=tmp_path,
        admin_port=admin_port,
        port_overrides={},
    )
    task = asyncio.create_task(run(registry, settings), name="emulator")
    try:
        await _wait_for_port(admin_port)
        yield {"admin_port": admin_port}
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
```

- [ ] **Step 4: Write the failing integration test**

`tests/integration/test_core_end_to_end.py`:

```python
import httpx


async def test_health_reports_dummy_service_healthy(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{url}/_emulator/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "dummy" in body["services"]
    assert body["services"]["dummy"]["ok"] is True


async def test_services_endpoint_lists_dummy(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{url}/_emulator/services")
    assert r.status_code == 200
    names = {s["name"] for s in r.json()["services"]}
    assert "dummy" in names


async def test_reset_all_succeeds(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{url}/_emulator/reset")
    assert r.status_code == 204


async def test_reset_dummy_succeeds(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{url}/_emulator/reset", params={"service": "dummy"})
    assert r.status_code == 204


async def test_reset_unknown_404(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{url}/_emulator/reset", params={"service": "nope"})
    assert r.status_code == 404
```

- [ ] **Step 5: Run the integration tests**

```bash
pytest tests/integration/ -v
```

Expected: all 5 tests PASS.

- [ ] **Step 6: Run the full test suite**

```bash
pytest -v
```

Expected: everything green.

- [ ] **Step 7: Commit**

```bash
git add src/gcp_local/services/_dummy/ tests/integration/ pyproject.toml
git commit -m "feat: dummy service and in-process integration harness"
```

---

## Task 12: Dockerfile and image build

**Files:**
- Create: `docker/Dockerfile`
- Create: `.dockerignore`
- Create: `tests/integration/test_docker_image.py`

- [ ] **Step 1: Write the Dockerfile**

`docker/Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1.6
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install .

RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 4510

ENTRYPOINT ["gcp-local"]
```

- [ ] **Step 2: Write `.dockerignore`**

```
.git
.github
.venv
venv
__pycache__
*.pyc
.pytest_cache
.mypy_cache
.ruff_cache
dist
build
docs
tests
```

- [ ] **Step 3: Build the image locally**

```bash
docker build -f docker/Dockerfile -t gcp-local:dev .
```

Expected: image builds; final line is `Successfully tagged gcp-local:dev` (or buildkit equivalent).

- [ ] **Step 4: Smoke-run the image**

```bash
docker run --rm -d --name gcp-local-smoke \
  -e SERVICES=dummy \
  -p 4510:4510 \
  gcp-local:dev
sleep 2
curl -s http://127.0.0.1:4510/_emulator/health
docker stop gcp-local-smoke
```

Expected: JSON response `{"ok": true, "services": {"dummy": {"ok": true, ...}}}`.

- [ ] **Step 5: Write a Docker-backed integration test**

`tests/integration/test_docker_image.py`:

```python
import asyncio
import shutil
import subprocess
import time

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None, reason="docker not available"
)

IMAGE = "gcp-local:dev"


@pytest.fixture
def docker_emulator():
    # Assumes the image has already been built. CI builds it before running tests.
    cid = subprocess.check_output(
        [
            "docker", "run", "--rm", "-d",
            "-e", "SERVICES=dummy",
            "-p", "4510:4510",
            IMAGE,
        ],
        text=True,
    ).strip()
    try:
        # Wait for readiness.
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                r = httpx.get("http://127.0.0.1:4510/_emulator/health", timeout=1)
                if r.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        else:
            pytest.fail("emulator container did not become healthy in time")
        yield "http://127.0.0.1:4510"
    finally:
        subprocess.run(["docker", "stop", cid], check=False)


def test_docker_image_health(docker_emulator):
    r = httpx.get(f"{docker_emulator}/_emulator/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "dummy" in body["services"]
```

- [ ] **Step 6: Run the docker-backed test**

```bash
pytest tests/integration/test_docker_image.py -v
```

Expected: PASS (given the image was built in step 3).

- [ ] **Step 7: Commit**

```bash
git add docker/ .dockerignore tests/integration/test_docker_image.py
git commit -m "feat: Dockerfile and image-level integration test"
```

---

## Task 13: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Write the CI workflow**

`.github/workflows/ci.yml`:

```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint-type-unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
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
      - uses: actions/checkout@v4
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
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - name: Build image
        run: docker build -f docker/Dockerfile -t gcp-local:dev .
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
          cache: pip
      - run: pip install -e ".[dev]"
      - run: pytest tests/integration/test_docker_image.py -v
```

- [ ] **Step 2: Verify locally that the matrix would pass**

Run each step the workflow runs, locally:

```bash
ruff check .
ruff format --check .
mypy
pytest tests/unit -v
pytest tests/integration -v -k "not docker"
docker build -f docker/Dockerfile -t gcp-local:dev .
pytest tests/integration/test_docker_image.py -v
```

Expected: every command green. If `ruff format --check` complains, run `ruff format .` and commit the diff.

- [ ] **Step 3: Commit**

```bash
git add .github/
git commit -m "ci: lint, type, unit, integration, docker workflow"
```

---

## Done

At this point, `gcp-local` has:

- A plugin-based core framework (service registry, lifecycle, state hub, storage base, error envelopes).
- An admin API (`/_emulator/health`, `/services`, `/reset`).
- A CLI entrypoint that reads env vars and boots selected services.
- A dummy service proving the framework end-to-end.
- Docker image building cleanly and passing an integration test against a running container.
- CI covering lint, type-check, unit tests, integration tests, and docker-backed tests.

**Next plans (one per service):**
1. `YYYY-MM-DD-gcp-local-gcs.md`
2. `YYYY-MM-DD-gcp-local-bigquery.md`
3. `YYYY-MM-DD-gcp-local-pubsub.md`
4. `YYYY-MM-DD-gcp-local-firestore.md`
5. `YYYY-MM-DD-gcp-local-secrets.md`

The dummy service is deleted in whichever of the above lands first.
