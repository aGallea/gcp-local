# gcp-local Secret Manager Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Secret Manager service so the official `google-cloud-secret-manager` Python client library works unchanged against the emulator over gRPC. This is also the first gRPC service in the project, so it adds the minimal core-framework pieces that future gRPC services (Pub/Sub, Firestore) will reuse.

**Architecture:** New `gcp_local.services.secret_manager` package registered as a Service. The service owns its own `grpc.aio.Server` on port 8086 and serves `SecretManagerServiceServicer` methods. Storage is abstracted behind a protocol with in-memory and disk-backed JSON implementations. Proto stubs are pre-generated from googleapis `.proto` files and committed to the repo (no build-time codegen).

**Tech Stack:** Python 3.13, grpcio / grpcio-tools, proto-plus (transitive via google-cloud-secret-manager), google-cloud-secret-manager (test-only driver), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-04-24-gcp-local-secret-manager-design.md`

**Branch:** `secret-manager` (already created). This plan's commits land on the branch; when all tasks pass, open a PR to `master`.

**Commit policy:** Commits allowed in this session. Use `python -m pip` (not bare `pip`). Do not bypass signing/hooks. Trailer on every commit (HEREDOC):
```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## File structure

```
protos/google/cloud/secretmanager/v1/
  resources.proto
  service.proto
scripts/
  gen_protos.sh                          # one-shot: runs grpc_tools.protoc
src/gcp_local/generated/
  __init__.py                            # empty
  google/
    __init__.py                          # namespace
    cloud/
      __init__.py                        # namespace
      secretmanager/
        __init__.py
        v1/
          __init__.py
          resources_pb2.py               # GENERATED
          resources_pb2.pyi              # GENERATED
          service_pb2.py                 # GENERATED
          service_pb2.pyi                # GENERATED
          service_pb2_grpc.py            # GENERATED (servicer + stub)

src/gcp_local/core/
  errors.py                              # ADD: grpc_error helper + GrpcError

src/gcp_local/services/secret_manager/
  __init__.py                            # exports SecretManagerService
  service.py                             # SecretManagerService (Service protocol impl)
  servicer.py                            # SecretManagerServicer (gRPC handler)
  models.py                              # SecretRecord, SecretVersion, SecretVersionState
  names.py                               # resource-name parser/builder
  storage.py                             # SecretManagerStorage + InMemoryStorage + DiskStorage

tests/unit/services/secret_manager/
  __init__.py
  test_names.py
  test_models.py
  test_storage_memory.py
  test_storage_disk.py
  test_servicer.py

tests/integration/
  test_secret_manager_integration.py
```

---

## Task 1: Core — grpc_error helper + grpcio runtime dep

**Files:**
- Modify: `pyproject.toml` (add `grpcio>=1.60`, `googleapis-common-protos>=1.63` to runtime deps; add `grpcio-tools>=1.60` to dev deps)
- Modify: `src/gcp_local/core/errors.py` (add `GrpcError`, `grpc_status_for_http`)
- Test: `tests/unit/test_core_errors_grpc.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_core_errors_grpc.py`:

```python
import grpc

from gcp_local.core.errors import GrpcError


def test_grpc_error_dataclass_fields():
    err = GrpcError(code=grpc.StatusCode.NOT_FOUND, message="nope")
    assert err.code == grpc.StatusCode.NOT_FOUND
    assert err.message == "nope"
    assert err.reason is None


def test_grpc_error_with_reason():
    err = GrpcError(
        code=grpc.StatusCode.ALREADY_EXISTS,
        message="already there",
        reason="ALREADY_EXISTS",
    )
    assert err.reason == "ALREADY_EXISTS"


def test_grpc_error_str_includes_code_and_message():
    err = GrpcError(code=grpc.StatusCode.INVALID_ARGUMENT, message="bad")
    s = str(err)
    assert "INVALID_ARGUMENT" in s
    assert "bad" in s
```

- [ ] **Step 2: Run — fails**

```bash
. .venv/bin/activate && pytest tests/unit/test_core_errors_grpc.py -v
```

Expected: `ImportError` on `GrpcError`.

- [ ] **Step 3: Add deps to pyproject.toml**

Replace `dependencies = [...]` with:

```toml
dependencies = [
    "fastapi>=0.110",
    "uvicorn>=0.27",
    "pydantic>=2.6",
    "google-crc32c>=1.5",
    "grpcio>=1.60",
    "googleapis-common-protos>=1.63",
]
```

Add to `[project.optional-dependencies].dev`:

```toml
    "grpcio-tools>=1.60",
```

Reinstall:

```bash
. .venv/bin/activate && python -m pip install -e ".[dev]"
```

- [ ] **Step 4: Extend `src/gcp_local/core/errors.py`**

Append to the existing file:

```python
import grpc


@dataclass
class GrpcError(Exception):
    code: grpc.StatusCode
    message: str
    reason: str | None = None

    def __str__(self) -> str:
        return f"{self.code.name}: {self.message}"
```

(The `dataclass` decorator is already imported at the top of `errors.py` from Task 6 of the core plan. If not, add `from dataclasses import dataclass`.)

- [ ] **Step 5: Run — pass**

```bash
. .venv/bin/activate && pytest tests/unit/test_core_errors_grpc.py -v
```

All 3 PASS.

- [ ] **Step 6: Quality gate**

```bash
. .venv/bin/activate && ruff check . && ruff format --check . && mypy && pytest
```

All green. Full suite now includes the 3 new tests.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/gcp_local/core/errors.py tests/unit/test_core_errors_grpc.py
git commit -m "$(cat <<'EOF'
feat(core): add grpcio runtime dep and GrpcError helper

First gRPC-supporting change in the core, in preparation for the
Secret Manager service (and later Pub/Sub and Firestore).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Vendor protos + generate stubs

**Files:**
- Create: `protos/google/cloud/secretmanager/v1/resources.proto` (fetched)
- Create: `protos/google/cloud/secretmanager/v1/service.proto` (fetched)
- Create: `scripts/gen_protos.sh`
- Create: `src/gcp_local/generated/__init__.py` (empty)
- Create: `src/gcp_local/generated/google/__init__.py` (empty)
- Create: `src/gcp_local/generated/google/cloud/__init__.py` (empty)
- Create: `src/gcp_local/generated/google/cloud/secretmanager/__init__.py` (empty)
- Create: `src/gcp_local/generated/google/cloud/secretmanager/v1/__init__.py` (empty)
- Generated (by running the script): `src/gcp_local/generated/google/cloud/secretmanager/v1/{resources_pb2.py,resources_pb2.pyi,service_pb2.py,service_pb2.pyi,service_pb2_grpc.py}`
- Test: `tests/unit/test_generated_stubs.py`

- [ ] **Step 1: Fetch the proto files**

Fetch from the googleapis repo's `main` branch (or a pinned tag if network flake is a concern). The canonical URLs are:

- `https://raw.githubusercontent.com/googleapis/googleapis/master/google/cloud/secretmanager/v1/resources.proto`
- `https://raw.githubusercontent.com/googleapis/googleapis/master/google/cloud/secretmanager/v1/service.proto`

```bash
mkdir -p protos/google/cloud/secretmanager/v1
curl -fsSL -o protos/google/cloud/secretmanager/v1/resources.proto \
  https://raw.githubusercontent.com/googleapis/googleapis/master/google/cloud/secretmanager/v1/resources.proto
curl -fsSL -o protos/google/cloud/secretmanager/v1/service.proto \
  https://raw.githubusercontent.com/googleapis/googleapis/master/google/cloud/secretmanager/v1/service.proto
```

Verify the files exist and contain proto definitions (look for `syntax = "proto3";` and `service SecretManagerService`).

- [ ] **Step 2: Create the generation script**

`scripts/gen_protos.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="src/gcp_local/generated"
mkdir -p "$OUT"

python -m grpc_tools.protoc \
  --proto_path=protos \
  --proto_path="$(python -c 'import google.api; import os; print(os.path.dirname(os.path.dirname(os.path.dirname(google.api.__file__))))')" \
  --python_out="$OUT" \
  --pyi_out="$OUT" \
  --grpc_python_out="$OUT" \
  protos/google/cloud/secretmanager/v1/resources.proto \
  protos/google/cloud/secretmanager/v1/service.proto

# grpcio-tools emits imports as `from google.cloud.secretmanager.v1 import ...`.
# Our generated files live under `gcp_local.generated.google.cloud.secretmanager.v1`.
# Rewrite the import lines so they resolve inside our package tree.
python -c "
import pathlib, re, sys
out = pathlib.Path('$OUT/google/cloud/secretmanager/v1')
for p in out.glob('*.py'):
    text = p.read_text()
    new = re.sub(
        r'^from google\.cloud\.secretmanager\.v1 import',
        'from gcp_local.generated.google.cloud.secretmanager.v1 import',
        text,
        flags=re.MULTILINE,
    )
    if new != text:
        p.write_text(new)
        print(f'rewrote imports in {p}')
"

echo 'generated:'
ls -1 "$OUT/google/cloud/secretmanager/v1/"
```

Make it executable:

```bash
chmod +x scripts/gen_protos.sh
```

- [ ] **Step 3: Create the `__init__.py` tree for the generated package**

Create these empty files:

```bash
mkdir -p src/gcp_local/generated/google/cloud/secretmanager/v1
touch src/gcp_local/generated/__init__.py
touch src/gcp_local/generated/google/__init__.py
touch src/gcp_local/generated/google/cloud/__init__.py
touch src/gcp_local/generated/google/cloud/secretmanager/__init__.py
touch src/gcp_local/generated/google/cloud/secretmanager/v1/__init__.py
```

- [ ] **Step 4: Run the generation script**

```bash
. .venv/bin/activate && ./scripts/gen_protos.sh
```

Expected output: five generated files listed (resources_pb2.py, resources_pb2.pyi, service_pb2.py, service_pb2.pyi, service_pb2_grpc.py). The script also rewrites internal imports.

If the script fails with a missing `google/api/annotations.proto` (a common first-generation issue), check that `googleapis-common-protos` is installed; the script's `--proto_path` already includes its location.

- [ ] **Step 5: Failing test — verify the generated stubs import and expose the servicer**

`tests/unit/test_generated_stubs.py`:

```python
def test_servicer_base_class_importable():
    from gcp_local.generated.google.cloud.secretmanager.v1 import service_pb2_grpc
    assert hasattr(service_pb2_grpc, "SecretManagerServiceServicer")
    assert hasattr(service_pb2_grpc, "add_SecretManagerServiceServicer_to_server")


def test_message_types_importable():
    from gcp_local.generated.google.cloud.secretmanager.v1 import resources_pb2, service_pb2
    # Resource messages
    assert hasattr(resources_pb2, "Secret")
    assert hasattr(resources_pb2, "SecretVersion")
    # Request messages
    assert hasattr(service_pb2, "CreateSecretRequest")
    assert hasattr(service_pb2, "AddSecretVersionRequest")
    assert hasattr(service_pb2, "AccessSecretVersionRequest")


def test_servicer_has_expected_methods():
    from gcp_local.generated.google.cloud.secretmanager.v1 import service_pb2_grpc
    servicer_cls = service_pb2_grpc.SecretManagerServiceServicer
    for m in (
        "CreateSecret", "GetSecret", "ListSecrets", "UpdateSecret", "DeleteSecret",
        "AddSecretVersion", "GetSecretVersion", "ListSecretVersions",
        "AccessSecretVersion",
        "EnableSecretVersion", "DisableSecretVersion", "DestroySecretVersion",
    ):
        assert hasattr(servicer_cls, m), f"missing method: {m}"
```

- [ ] **Step 6: Run — pass**

```bash
. .venv/bin/activate && pytest tests/unit/test_generated_stubs.py -v
```

All 3 PASS. If any import fails, revisit the generation script.

- [ ] **Step 7: Add generated dir to `.gitignore`? NO.**

The generated files are intentionally committed — they are not regenerated at install time. They only change when the vendored `.proto` files change.

Verify:

```bash
git status --short
```

Should show the new `protos/`, `scripts/gen_protos.sh`, `src/gcp_local/generated/**`, and the new test.

- [ ] **Step 8: Quality gate**

```bash
. .venv/bin/activate && ruff check . && ruff format --check . && mypy && pytest
```

Expected issues:
- **Ruff:** generated `_pb2.py` files often contain protobuf boilerplate that ruff doesn't like. Add `src/gcp_local/generated/` to ruff's exclude list. Append to `ruff.toml`:

```toml
extend-exclude = ["src/gcp_local/generated"]
```

- **Mypy:** similar. Add to `pyproject.toml` under `[tool.mypy]`:

```toml
exclude = ["src/gcp_local/generated/"]
```

After those exclusions, full suite green.

- [ ] **Step 9: Commit**

```bash
git add protos/ scripts/gen_protos.sh src/gcp_local/generated/ tests/unit/test_generated_stubs.py ruff.toml pyproject.toml
git commit -m "$(cat <<'EOF'
feat(secret_manager): vendor protos and generate gRPC stubs

Vendors google/cloud/secretmanager/v1/{resources,service}.proto from
googleapis and commits the generated _pb2.py / _pb2_grpc.py files so
the runtime has no proto-compilation step. scripts/gen_protos.sh is
the one-shot regenerator for when the protos need to be refreshed.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Service scaffold + entry-point registration

**Files:**
- Create: `src/gcp_local/services/secret_manager/__init__.py`
- Create: `src/gcp_local/services/secret_manager/service.py`
- Modify: `pyproject.toml` (add secret_manager entry point)
- Modify: `tests/integration/conftest.py` (extend fixture to include secret_manager service)
- Modify: `tests/integration/test_core_end_to_end.py` (expect both services)

- [ ] **Step 1: Package init**

`src/gcp_local/services/secret_manager/__init__.py`:

```python
from gcp_local.services.secret_manager.service import SecretManagerService

__all__ = ["SecretManagerService"]
```

- [ ] **Step 2: Service skeleton**

`src/gcp_local/services/secret_manager/service.py`:

```python
import asyncio
import contextlib
import logging
from typing import ClassVar

import grpc

from gcp_local.core.context import Context
from gcp_local.core.service import HealthStatus, Port

log = logging.getLogger(__name__)

_DEFAULT_PORT = 8086


class SecretManagerService:
    """Emulates Google Cloud Secret Manager over gRPC."""

    name = "secret_manager"
    default_ports: ClassVar[list[Port]] = [Port(_DEFAULT_PORT, "grpc")]

    def __init__(self) -> None:
        self._server: grpc.aio.Server | None = None
        self._started = False

    async def start(self, ctx: Context) -> None:
        port = ctx.port_overrides.get(self.name, _DEFAULT_PORT)
        self._server = grpc.aio.server()
        self._server.add_insecure_port(f"[::]:{port}")
        # Servicer registration happens in Task 9 once we have one; for now
        # the server starts empty and accepts connections but has no methods.
        await self._server.start()
        self._started = True
        log.info("secret_manager service listening on :%d", port)

    async def stop(self) -> None:
        if self._server is not None:
            with contextlib.suppress(Exception):
                await self._server.stop(grace=5.0)
        self._started = False

    async def reset_state(self) -> None:
        # Storage wiring comes in Task 9.
        pass

    def health(self) -> HealthStatus:
        return HealthStatus(
            ok=self._started, message="running" if self._started else "stopped"
        )
```

- [ ] **Step 3: Register entry point**

In `pyproject.toml` under `[project.entry-points."gcp_local.services"]`, add one more line so the block reads:

```toml
[project.entry-points."gcp_local.services"]
gcs = "gcp_local.services.gcs:GcsService"
secret_manager = "gcp_local.services.secret_manager:SecretManagerService"
```

Reinstall:

```bash
. .venv/bin/activate && python -m pip install -e ".[dev]"
```

Verify entry points:

```bash
. .venv/bin/activate && python -c "from importlib.metadata import entry_points; print(sorted(ep.name for ep in entry_points(group='gcp_local.services')))"
```

Expected: `['gcs', 'secret_manager']`.

- [ ] **Step 4: Extend the integration fixture**

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
from gcp_local.services.secret_manager import SecretManagerService


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
    """Boot the emulator in-process with gcs + secret_manager on free ports."""
    registry = ServiceRegistry()
    registry.register("gcs", GcsService)
    registry.register("secret_manager", SecretManagerService)

    admin_port = _free_port()
    gcs_port = _free_port()
    secret_manager_port = _free_port()
    settings = Settings(
        services=["gcs", "secret_manager"],
        persist=False,
        data_dir=tmp_path,
        admin_port=admin_port,
        port_overrides={"gcs": gcs_port, "secret_manager": secret_manager_port},
    )
    task = asyncio.create_task(run(registry, settings), name="emulator")
    try:
        await _wait_for_port(admin_port)
        await _wait_for_port(gcs_port)
        await _wait_for_port(secret_manager_port)
        yield {
            "admin_port": admin_port,
            "gcs_port": gcs_port,
            "secret_manager_port": secret_manager_port,
        }
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
```

- [ ] **Step 5: Update core integration tests**

Adjust `tests/integration/test_core_end_to_end.py` — update both `test_health_reports_gcs_service_healthy` and `test_services_endpoint_lists_gcs` to assert both services, and rename:

```python
import httpx


async def test_health_reports_both_services_healthy(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{url}/_emulator/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert set(body["services"].keys()) == {"gcs", "secret_manager"}
    assert body["services"]["gcs"]["ok"] is True
    assert body["services"]["secret_manager"]["ok"] is True


async def test_services_endpoint_lists_both(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{url}/_emulator/services")
    assert r.status_code == 200
    names = {s["name"] for s in r.json()["services"]}
    assert names == {"gcs", "secret_manager"}


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


async def test_reset_secret_manager_succeeds(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.post(
            f"{url}/_emulator/reset", params={"service": "secret_manager"}
        )
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


async def test_secret_manager_grpc_port_open(emulator):
    """The secret_manager port should accept TCP connections (gRPC server up)."""
    import asyncio
    _, writer = await asyncio.open_connection(
        "127.0.0.1", emulator["secret_manager_port"]
    )
    writer.close()
    await writer.wait_closed()
```

- [ ] **Step 6: Run — pass**

```bash
. .venv/bin/activate && pytest tests/integration/test_core_end_to_end.py -v
```

All 8 PASS. Full suite:

```bash
. .venv/bin/activate && pytest -v
```

- [ ] **Step 7: Quality gate** (ruff/format/mypy) all green.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
feat(secret_manager): service scaffold + registration

Registers SecretManagerService via entry point and wires it into the
shared integration fixture alongside gcs. Server is empty (no methods
yet) — the servicer is added in Task 9.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Resource-name parser

**Files:**
- Create: `src/gcp_local/services/secret_manager/names.py`
- Test: `tests/unit/services/secret_manager/__init__.py` (empty)
- Test: `tests/unit/services/secret_manager/test_names.py`

- [ ] **Step 1: Failing tests**

`tests/unit/services/secret_manager/test_names.py`:

```python
import pytest

from gcp_local.services.secret_manager.names import (
    InvalidResourceName,
    build_secret_name,
    build_version_name,
    parse_secret_name,
    parse_version_name,
    validate_secret_id,
)


def test_parse_secret_name():
    project, sid = parse_secret_name("projects/p1/secrets/db-password")
    assert project == "p1"
    assert sid == "db-password"


def test_parse_version_name():
    project, sid, vid = parse_version_name("projects/p1/secrets/db-password/versions/2")
    assert (project, sid, vid) == ("p1", "db-password", "2")


def test_parse_version_name_latest():
    project, sid, vid = parse_version_name("projects/p1/secrets/x/versions/latest")
    assert vid == "latest"


def test_build_secret_name():
    assert build_secret_name("p1", "my-secret") == "projects/p1/secrets/my-secret"


def test_build_version_name():
    assert build_version_name("p1", "my-secret", 3) == "projects/p1/secrets/my-secret/versions/3"


def test_build_version_name_latest():
    assert build_version_name("p1", "my-secret", "latest") == "projects/p1/secrets/my-secret/versions/latest"


def test_parse_secret_name_rejects_malformed():
    bad = [
        "",
        "projects/p1",
        "projects/p1/secrets/",
        "secrets/p1",
        "projects/p1/secrets/x/versions/1",  # version name into secret parser
    ]
    for name in bad:
        with pytest.raises(InvalidResourceName):
            parse_secret_name(name)


def test_parse_version_name_rejects_malformed():
    bad = [
        "projects/p/secrets/x",
        "projects/p/secrets/x/versions/",
    ]
    for name in bad:
        with pytest.raises(InvalidResourceName):
            parse_version_name(name)


def test_validate_secret_id_happy():
    for ok in ("abc", "abc-123", "abc_123", "ABC", "A"):
        validate_secret_id(ok)


def test_validate_secret_id_rejects():
    for bad in ("", "a/b", "a.b", "a b", "a" * 256):
        with pytest.raises(InvalidResourceName):
            validate_secret_id(bad)
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

`src/gcp_local/services/secret_manager/names.py`:

```python
import re


class InvalidResourceName(ValueError):
    pass


_SECRET_RE = re.compile(r"^projects/([^/]+)/secrets/([^/]+)$")
_VERSION_RE = re.compile(r"^projects/([^/]+)/secrets/([^/]+)/versions/([^/]+)$")
_SECRET_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,255}$")


def parse_secret_name(name: str) -> tuple[str, str]:
    m = _SECRET_RE.match(name)
    if not m:
        raise InvalidResourceName(f"not a secret name: {name!r}")
    project, secret_id = m.group(1), m.group(2)
    if not project or not secret_id:
        raise InvalidResourceName(f"empty segment in {name!r}")
    return project, secret_id


def parse_version_name(name: str) -> tuple[str, str, str]:
    m = _VERSION_RE.match(name)
    if not m:
        raise InvalidResourceName(f"not a version name: {name!r}")
    project, secret_id, version_id = m.group(1), m.group(2), m.group(3)
    if not project or not secret_id or not version_id:
        raise InvalidResourceName(f"empty segment in {name!r}")
    return project, secret_id, version_id


def build_secret_name(project: str, secret_id: str) -> str:
    return f"projects/{project}/secrets/{secret_id}"


def build_version_name(project: str, secret_id: str, version_id: int | str) -> str:
    return f"projects/{project}/secrets/{secret_id}/versions/{version_id}"


def validate_secret_id(secret_id: str) -> None:
    if not _SECRET_ID_RE.match(secret_id):
        raise InvalidResourceName(
            f"invalid secret id {secret_id!r}: must match [A-Za-z0-9_-]{{1,255}}"
        )
```

- [ ] **Step 4: Run — pass**

Expected: 10 PASS.

- [ ] **Step 5: Quality gate** all green.

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/services/secret_manager/names.py tests/unit/services/secret_manager/
git commit -m "$(cat <<'EOF'
feat(secret_manager): resource-name parser

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Domain models

**Files:**
- Create: `src/gcp_local/services/secret_manager/models.py`
- Test: `tests/unit/services/secret_manager/test_models.py`

- [ ] **Step 1: Failing tests**

```python
import pytest

from gcp_local.services.secret_manager.models import (
    SecretRecord,
    SecretVersion,
    SecretVersionState,
)


def test_secret_version_state_values():
    assert SecretVersionState.ENABLED.value == "ENABLED"
    assert SecretVersionState.DISABLED.value == "DISABLED"
    assert SecretVersionState.DESTROYED.value == "DESTROYED"


def test_secret_version_defaults():
    v = SecretVersion(
        id=1, state=SecretVersionState.ENABLED, create_time="t",
        destroy_time=None, payload=b"p", data_crc32c=123,
    )
    assert v.id == 1
    assert v.destroy_time is None


def test_secret_record_defaults():
    r = SecretRecord(
        project="p", secret_id="s",
        labels={}, annotations={},
        create_time="t", versions=[],
    )
    assert r.versions == []
    assert r.labels == {}


def test_secret_record_highest_enabled_version():
    r = SecretRecord(
        project="p", secret_id="s",
        labels={}, annotations={}, create_time="t",
        versions=[
            SecretVersion(id=1, state=SecretVersionState.ENABLED, create_time="t",
                          destroy_time=None, payload=b"a", data_crc32c=0),
            SecretVersion(id=2, state=SecretVersionState.DISABLED, create_time="t",
                          destroy_time=None, payload=b"b", data_crc32c=0),
            SecretVersion(id=3, state=SecretVersionState.ENABLED, create_time="t",
                          destroy_time=None, payload=b"c", data_crc32c=0),
        ],
    )
    assert r.highest_enabled_version().id == 3


def test_secret_record_highest_enabled_version_none():
    r = SecretRecord(
        project="p", secret_id="s",
        labels={}, annotations={}, create_time="t",
        versions=[
            SecretVersion(id=1, state=SecretVersionState.DISABLED, create_time="t",
                          destroy_time=None, payload=b"a", data_crc32c=0),
            SecretVersion(id=2, state=SecretVersionState.DESTROYED, create_time="t",
                          destroy_time="t", payload=b"", data_crc32c=0),
        ],
    )
    assert r.highest_enabled_version() is None


def test_secret_record_get_version_by_id():
    r = SecretRecord(
        project="p", secret_id="s",
        labels={}, annotations={}, create_time="t",
        versions=[
            SecretVersion(id=1, state=SecretVersionState.ENABLED, create_time="t",
                          destroy_time=None, payload=b"a", data_crc32c=0),
        ],
    )
    assert r.get_version(1).id == 1
    assert r.get_version(99) is None
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

`src/gcp_local/services/secret_manager/models.py`:

```python
from dataclasses import dataclass, field
from enum import Enum


class SecretVersionState(str, Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    DESTROYED = "DESTROYED"


@dataclass
class SecretVersion:
    id: int
    state: SecretVersionState
    create_time: str
    destroy_time: str | None
    payload: bytes
    data_crc32c: int


@dataclass
class SecretRecord:
    project: str
    secret_id: str
    labels: dict[str, str]
    annotations: dict[str, str]
    create_time: str
    versions: list[SecretVersion] = field(default_factory=list)

    def highest_enabled_version(self) -> SecretVersion | None:
        enabled = [v for v in self.versions if v.state == SecretVersionState.ENABLED]
        if not enabled:
            return None
        return max(enabled, key=lambda v: v.id)

    def get_version(self, version_id: int) -> SecretVersion | None:
        for v in self.versions:
            if v.id == version_id:
                return v
        return None
```

- [ ] **Step 4: Run — pass**

6 PASS.

- [ ] **Step 5: Quality gate** all green.

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/services/secret_manager/models.py tests/unit/services/secret_manager/test_models.py
git commit -m "$(cat <<'EOF'
feat(secret_manager): domain models

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Storage protocol + InMemoryStorage

**Files:**
- Create: `src/gcp_local/services/secret_manager/storage.py`
- Test: `tests/unit/services/secret_manager/test_storage_memory.py`

- [ ] **Step 1: Failing tests**

```python
import pytest

from gcp_local.services.secret_manager.models import (
    SecretRecord,
    SecretVersion,
    SecretVersionState,
)
from gcp_local.services.secret_manager.storage import (
    InMemoryStorage,
    InvalidStateTransition,
    SecretAlreadyExists,
    SecretNotFound,
    VersionNotFound,
)


def make_record(project="p", secret_id="s") -> SecretRecord:
    return SecretRecord(
        project=project, secret_id=secret_id,
        labels={}, annotations={}, create_time="t",
    )


async def test_create_and_get_secret():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="mine"))
    got = await s.get_secret("p", "mine")
    assert got.secret_id == "mine"


async def test_create_duplicate_raises():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="x"))
    with pytest.raises(SecretAlreadyExists):
        await s.create_secret(make_record(secret_id="x"))


async def test_get_missing_raises():
    s = InMemoryStorage()
    with pytest.raises(SecretNotFound):
        await s.get_secret("p", "nope")


async def test_list_secrets_sorted_by_id():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="b"))
    await s.create_secret(make_record(secret_id="a"))
    items, _ = await s.list_secrets("p")
    assert [r.secret_id for r in items] == ["a", "b"]


async def test_list_secrets_scoped_to_project():
    s = InMemoryStorage()
    await s.create_secret(make_record(project="p1", secret_id="a"))
    await s.create_secret(make_record(project="p2", secret_id="b"))
    items, _ = await s.list_secrets("p1")
    assert [r.secret_id for r in items] == ["a"]


async def test_update_secret_replaces_labels():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="x"))
    rec = await s.get_secret("p", "x")
    rec.labels = {"env": "dev"}
    await s.update_secret(rec)
    got = await s.get_secret("p", "x")
    assert got.labels == {"env": "dev"}


async def test_delete_secret_removes_it():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="x"))
    await s.delete_secret("p", "x")
    with pytest.raises(SecretNotFound):
        await s.get_secret("p", "x")


async def test_delete_missing_raises():
    s = InMemoryStorage()
    with pytest.raises(SecretNotFound):
        await s.delete_secret("p", "x")


async def test_add_version_starts_at_1_and_increments():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="x"))
    v1 = await s.add_version("p", "x", b"a")
    v2 = await s.add_version("p", "x", b"b")
    assert v1.id == 1 and v2.id == 2
    assert v1.state == SecretVersionState.ENABLED
    # crc32c should be non-zero for non-empty payload
    assert v1.data_crc32c != 0


async def test_add_version_ids_do_not_recycle_after_destroy():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="x"))
    await s.add_version("p", "x", b"a")
    await s.update_version_state("p", "x", 1, SecretVersionState.DESTROYED)
    v2 = await s.add_version("p", "x", b"b")
    assert v2.id == 2


async def test_get_version():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="x"))
    await s.add_version("p", "x", b"hi")
    v = await s.get_version("p", "x", 1)
    assert v.payload == b"hi"


async def test_get_missing_version_raises():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="x"))
    with pytest.raises(VersionNotFound):
        await s.get_version("p", "x", 99)


async def test_list_versions_ordered_ascending():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="x"))
    for i in range(3):
        await s.add_version("p", "x", f"v{i}".encode())
    items, _ = await s.list_versions("p", "x")
    assert [v.id for v in items] == [1, 2, 3]


async def test_update_version_state_transitions():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="x"))
    await s.add_version("p", "x", b"hi")
    # ENABLED -> DISABLED
    await s.update_version_state("p", "x", 1, SecretVersionState.DISABLED)
    v = await s.get_version("p", "x", 1)
    assert v.state == SecretVersionState.DISABLED
    # DISABLED -> ENABLED
    await s.update_version_state("p", "x", 1, SecretVersionState.ENABLED)
    v = await s.get_version("p", "x", 1)
    assert v.state == SecretVersionState.ENABLED
    # ENABLED -> DESTROYED
    await s.update_version_state("p", "x", 1, SecretVersionState.DESTROYED)
    v = await s.get_version("p", "x", 1)
    assert v.state == SecretVersionState.DESTROYED
    assert v.payload == b""
    assert v.destroy_time is not None


async def test_transitions_from_destroyed_forbidden():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="x"))
    await s.add_version("p", "x", b"hi")
    await s.update_version_state("p", "x", 1, SecretVersionState.DESTROYED)
    with pytest.raises(InvalidStateTransition):
        await s.update_version_state("p", "x", 1, SecretVersionState.ENABLED)


async def test_reset():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="x"))
    await s.reset()
    with pytest.raises(SecretNotFound):
        await s.get_secret("p", "x")


async def test_pagination():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="a"))
    await s.create_secret(make_record(secret_id="b"))
    await s.create_secret(make_record(secret_id="c"))
    page1, token = await s.list_secrets("p", page_size=2)
    assert [r.secret_id for r in page1] == ["a", "b"]
    assert token is not None
    page2, token2 = await s.list_secrets("p", page_size=2, page_token=token)
    assert [r.secret_id for r in page2] == ["c"]
    assert token2 is None
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

`src/gcp_local/services/secret_manager/storage.py`:

```python
from __future__ import annotations

import asyncio
import base64
from typing import Protocol

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
        self, project: str, *, page_size: int | None = None, page_token: str | None = None
    ) -> tuple[list[SecretRecord], str | None]: ...
    async def update_secret(self, record: SecretRecord) -> None: ...
    async def delete_secret(self, project: str, secret_id: str) -> None: ...

    async def add_version(self, project: str, secret_id: str, payload: bytes) -> SecretVersion: ...
    async def get_version(self, project: str, secret_id: str, version_id: int) -> SecretVersion: ...
    async def list_versions(
        self, project: str, secret_id: str, *,
        page_size: int | None = None, page_token: str | None = None,
    ) -> tuple[list[SecretVersion], str | None]: ...
    async def update_version_state(
        self, project: str, secret_id: str, version_id: int, new_state: SecretVersionState
    ) -> SecretVersion: ...

    async def reset(self) -> None: ...


def _encode_token(cursor: str) -> str:
    return base64.urlsafe_b64encode(cursor.encode()).decode()


def _decode_token(token: str) -> str:
    return base64.urlsafe_b64decode(token.encode()).decode()


def _paginate[T](
    items: list[T],
    key: callable,
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


def _validate_transition(
    current: SecretVersionState, new_state: SecretVersionState
) -> None:
    if current == SecretVersionState.DESTROYED and new_state != SecretVersionState.DESTROYED:
        raise InvalidStateTransition(
            f"cannot transition from DESTROYED to {new_state.value}"
        )


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
        self, project: str, *, page_size: int | None = None, page_token: str | None = None
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

    async def add_version(
        self, project: str, secret_id: str, payload: bytes
    ) -> SecretVersion:
        async with self._lock:
            rec = await self.get_secret(project, secret_id)
            next_id = (max((v.id for v in rec.versions), default=0)) + 1
            version = SecretVersion(
                id=next_id,
                state=SecretVersionState.ENABLED,
                create_time=rfc3339_now(),
                destroy_time=None,
                payload=payload,
                data_crc32c=google_crc32c.value(payload),
            )
            rec.versions.append(version)
            rec.versions.sort(key=lambda v: v.id)
            return version

    async def get_version(
        self, project: str, secret_id: str, version_id: int
    ) -> SecretVersion:
        rec = await self.get_secret(project, secret_id)
        v = rec.get_version(version_id)
        if v is None:
            raise VersionNotFound(version_id)
        return v

    async def list_versions(
        self, project: str, secret_id: str, *,
        page_size: int | None = None, page_token: str | None = None,
    ) -> tuple[list[SecretVersion], str | None]:
        rec = await self.get_secret(project, secret_id)
        items = sorted(rec.versions, key=lambda v: v.id)
        return _paginate(items, lambda v: str(v.id).zfill(20), page_size, page_token)

    async def update_version_state(
        self, project: str, secret_id: str, version_id: int, new_state: SecretVersionState
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
```

- [ ] **Step 4: Run — pass**

~17 PASS.

- [ ] **Step 5: Quality gate** all green.

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/services/secret_manager/storage.py tests/unit/services/secret_manager/test_storage_memory.py
git commit -m "$(cat <<'EOF'
feat(secret_manager): storage protocol and in-memory backend

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: DiskStorage

**Files:**
- Modify: `src/gcp_local/services/secret_manager/storage.py` (append DiskStorage)
- Test: `tests/unit/services/secret_manager/test_storage_disk.py`

- [ ] **Step 1: Failing tests**

`tests/unit/services/secret_manager/test_storage_disk.py`:

```python
import json
from pathlib import Path

import pytest

from gcp_local.services.secret_manager.models import (
    SecretRecord,
    SecretVersion,
    SecretVersionState,
)
from gcp_local.services.secret_manager.storage import (
    DiskStorage,
    SecretAlreadyExists,
    SecretNotFound,
)


def make_record(project="p", secret_id="s") -> SecretRecord:
    return SecretRecord(
        project=project, secret_id=secret_id,
        labels={}, annotations={}, create_time="t",
    )


async def test_create_writes_json_file(tmp_path: Path):
    s = DiskStorage(tmp_path)
    await s.create_secret(make_record(secret_id="mine"))
    data_file = tmp_path / "secret_manager.json"
    assert data_file.exists()
    body = json.loads(data_file.read_text())
    assert body["secrets"][0]["secret_id"] == "mine"


async def test_roundtrip_through_disk(tmp_path: Path):
    s1 = DiskStorage(tmp_path)
    await s1.create_secret(make_record(secret_id="x"))
    await s1.add_version("p", "x", b"hello")
    # Fresh instance reads from disk
    s2 = DiskStorage(tmp_path)
    v = await s2.get_version("p", "x", 1)
    assert v.payload == b"hello"


async def test_version_payload_base64_on_disk(tmp_path: Path):
    s = DiskStorage(tmp_path)
    await s.create_secret(make_record(secret_id="x"))
    await s.add_version("p", "x", b"\x00\x01\x02")
    body = json.loads((tmp_path / "secret_manager.json").read_text())
    # Payload is base64-encoded, not raw bytes
    v = body["secrets"][0]["versions"][0]
    assert "payload_b64" in v
    assert v["payload_b64"] == "AAEC"  # base64 of b"\x00\x01\x02"


async def test_destroy_clears_payload_on_disk(tmp_path: Path):
    s = DiskStorage(tmp_path)
    await s.create_secret(make_record(secret_id="x"))
    await s.add_version("p", "x", b"secret")
    await s.update_version_state("p", "x", 1, SecretVersionState.DESTROYED)
    body = json.loads((tmp_path / "secret_manager.json").read_text())
    v = body["secrets"][0]["versions"][0]
    assert v["state"] == "DESTROYED"
    assert v["payload_b64"] == ""


async def test_delete_secret_removes_from_disk(tmp_path: Path):
    s = DiskStorage(tmp_path)
    await s.create_secret(make_record(secret_id="x"))
    await s.delete_secret("p", "x")
    body = json.loads((tmp_path / "secret_manager.json").read_text())
    assert body["secrets"] == []


async def test_reset_wipes_disk(tmp_path: Path):
    s = DiskStorage(tmp_path)
    await s.create_secret(make_record(secret_id="x"))
    await s.reset()
    with pytest.raises(SecretNotFound):
        await s.get_secret("p", "x")


async def test_fresh_instance_on_empty_dir(tmp_path: Path):
    s = DiskStorage(tmp_path)
    items, _ = await s.list_secrets("p")
    assert items == []
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Append to storage.py**

Append to the end of `src/gcp_local/services/secret_manager/storage.py`:

```python
import json
from pathlib import Path


def _serialize_record(r: SecretRecord) -> dict:
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


def _deserialize_record(body: dict) -> SecretRecord:
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
        body = {
            "secrets": [_serialize_record(rec) for rec in state.values()],
        }
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
        self, project: str, *, page_size: int | None = None, page_token: str | None = None
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

    async def add_version(
        self, project: str, secret_id: str, payload: bytes
    ) -> SecretVersion:
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
                data_crc32c=google_crc32c.value(payload),
            )
            rec.versions.append(version)
            rec.versions.sort(key=lambda v: v.id)
            self._save(state)
            return version

    async def get_version(
        self, project: str, secret_id: str, version_id: int
    ) -> SecretVersion:
        rec = await self.get_secret(project, secret_id)
        v = rec.get_version(version_id)
        if v is None:
            raise VersionNotFound(version_id)
        return v

    async def list_versions(
        self, project: str, secret_id: str, *,
        page_size: int | None = None, page_token: str | None = None,
    ) -> tuple[list[SecretVersion], str | None]:
        rec = await self.get_secret(project, secret_id)
        items = sorted(rec.versions, key=lambda v: v.id)
        return _paginate(items, lambda v: str(v.id).zfill(20), page_size, page_token)

    async def update_version_state(
        self, project: str, secret_id: str, version_id: int, new_state: SecretVersionState
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
```

- [ ] **Step 4: Run — pass**

7 new PASS. Full suite green.

- [ ] **Step 5: Quality gate** all green.

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/services/secret_manager/storage.py tests/unit/services/secret_manager/test_storage_disk.py
git commit -m "$(cat <<'EOF'
feat(secret_manager): disk-backed storage

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Servicer — secret lifecycle

**Files:**
- Create: `src/gcp_local/services/secret_manager/servicer.py`
- Test: `tests/unit/services/secret_manager/test_servicer_secrets.py`

Scope for this task: `CreateSecret`, `GetSecret`, `ListSecrets`, `UpdateSecret`, `DeleteSecret`. Version methods come in Task 9.

The servicer inherits from the generated `SecretManagerServiceServicer`. The method bodies translate between proto messages and our `SecretRecord`/`SecretVersion` dataclasses and delegate to the storage protocol.

- [ ] **Step 1: Failing tests**

`tests/unit/services/secret_manager/test_servicer_secrets.py`:

```python
import asyncio

import grpc
import pytest
from google.protobuf.field_mask_pb2 import FieldMask

from gcp_local.generated.google.cloud.secretmanager.v1 import service_pb2
from gcp_local.services.secret_manager.servicer import SecretManagerServicer
from gcp_local.services.secret_manager.storage import InMemoryStorage


class FakeContext:
    """Minimal grpc.aio.ServicerContext substitute for unit tests."""

    def __init__(self) -> None:
        self.aborted: tuple[grpc.StatusCode, str] | None = None

    async def abort(self, code: grpc.StatusCode, details: str) -> None:
        self.aborted = (code, details)
        raise grpc.aio.AioRpcError(code, None, None, details=details)


def servicer() -> SecretManagerServicer:
    return SecretManagerServicer(storage=InMemoryStorage())


async def test_create_secret_returns_proto():
    svc = servicer()
    req = service_pb2.CreateSecretRequest(
        parent="projects/p1",
        secret_id="my-secret",
        secret=service_pb2.Secret(labels={"env": "dev"}),
    )
    result = await svc.CreateSecret(req, FakeContext())
    assert result.name == "projects/p1/secrets/my-secret"
    assert dict(result.labels) == {"env": "dev"}


async def test_create_secret_already_exists():
    svc = servicer()
    req = service_pb2.CreateSecretRequest(
        parent="projects/p1", secret_id="x", secret=service_pb2.Secret()
    )
    await svc.CreateSecret(req, FakeContext())
    ctx = FakeContext()
    with pytest.raises(grpc.aio.AioRpcError):
        await svc.CreateSecret(req, ctx)
    assert ctx.aborted is not None
    assert ctx.aborted[0] == grpc.StatusCode.ALREADY_EXISTS


async def test_create_secret_invalid_id():
    svc = servicer()
    req = service_pb2.CreateSecretRequest(
        parent="projects/p1", secret_id="bad/name", secret=service_pb2.Secret()
    )
    ctx = FakeContext()
    with pytest.raises(grpc.aio.AioRpcError):
        await svc.CreateSecret(req, ctx)
    assert ctx.aborted[0] == grpc.StatusCode.INVALID_ARGUMENT


async def test_get_secret_returns_labels_and_annotations():
    svc = servicer()
    await svc.CreateSecret(
        service_pb2.CreateSecretRequest(
            parent="projects/p1", secret_id="x",
            secret=service_pb2.Secret(labels={"k": "v"}, annotations={"a": "b"}),
        ),
        FakeContext(),
    )
    result = await svc.GetSecret(
        service_pb2.GetSecretRequest(name="projects/p1/secrets/x"),
        FakeContext(),
    )
    assert result.name == "projects/p1/secrets/x"
    assert dict(result.labels) == {"k": "v"}
    assert dict(result.annotations) == {"a": "b"}


async def test_get_secret_not_found():
    svc = servicer()
    ctx = FakeContext()
    with pytest.raises(grpc.aio.AioRpcError):
        await svc.GetSecret(
            service_pb2.GetSecretRequest(name="projects/p1/secrets/nope"),
            ctx,
        )
    assert ctx.aborted[0] == grpc.StatusCode.NOT_FOUND


async def test_list_secrets():
    svc = servicer()
    for sid in ("b", "a"):
        await svc.CreateSecret(
            service_pb2.CreateSecretRequest(
                parent="projects/p1", secret_id=sid, secret=service_pb2.Secret()
            ),
            FakeContext(),
        )
    result = await svc.ListSecrets(
        service_pb2.ListSecretsRequest(parent="projects/p1"),
        FakeContext(),
    )
    names = [s.name for s in result.secrets]
    assert names == [
        "projects/p1/secrets/a",
        "projects/p1/secrets/b",
    ]


async def test_update_secret_applies_mask():
    svc = servicer()
    await svc.CreateSecret(
        service_pb2.CreateSecretRequest(
            parent="projects/p1", secret_id="x",
            secret=service_pb2.Secret(labels={"old": "true"}),
        ),
        FakeContext(),
    )
    req = service_pb2.UpdateSecretRequest(
        secret=service_pb2.Secret(
            name="projects/p1/secrets/x",
            labels={"new": "true"},
            annotations={"ann": "1"},
        ),
        update_mask=FieldMask(paths=["labels"]),
    )
    result = await svc.UpdateSecret(req, FakeContext())
    assert dict(result.labels) == {"new": "true"}
    # annotations NOT in update_mask, so remain empty (original was empty)
    assert dict(result.annotations) == {}


async def test_delete_secret():
    svc = servicer()
    await svc.CreateSecret(
        service_pb2.CreateSecretRequest(
            parent="projects/p1", secret_id="x", secret=service_pb2.Secret()
        ),
        FakeContext(),
    )
    await svc.DeleteSecret(
        service_pb2.DeleteSecretRequest(name="projects/p1/secrets/x"),
        FakeContext(),
    )
    ctx = FakeContext()
    with pytest.raises(grpc.aio.AioRpcError):
        await svc.GetSecret(
            service_pb2.GetSecretRequest(name="projects/p1/secrets/x"),
            ctx,
        )
    assert ctx.aborted[0] == grpc.StatusCode.NOT_FOUND
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

`src/gcp_local/services/secret_manager/servicer.py`:

```python
from __future__ import annotations

import logging

import grpc
from google.protobuf.timestamp_pb2 import Timestamp

from gcp_local.generated.google.cloud.secretmanager.v1 import (
    resources_pb2,
    service_pb2,
    service_pb2_grpc,
)
from gcp_local.services.gcs.ids import rfc3339_now
from gcp_local.services.secret_manager.models import (
    SecretRecord,
    SecretVersion,
    SecretVersionState,
)
from gcp_local.services.secret_manager.names import (
    InvalidResourceName,
    build_secret_name,
    build_version_name,
    parse_secret_name,
    parse_version_name,
    validate_secret_id,
)
from gcp_local.services.secret_manager.storage import (
    InvalidStateTransition,
    SecretAlreadyExists,
    SecretManagerStorage,
    SecretNotFound,
    VersionNotFound,
)

log = logging.getLogger(__name__)


def _parse_parent(parent: str) -> str:
    """projects/<project> -> <project>. Raises if shape wrong."""
    prefix = "projects/"
    if not parent.startswith(prefix) or len(parent) <= len(prefix):
        raise InvalidResourceName(f"bad parent: {parent!r}")
    project = parent[len(prefix):]
    if "/" in project:
        raise InvalidResourceName(f"bad parent: {parent!r}")
    return project


def _timestamp(rfc3339: str | None) -> Timestamp:
    ts = Timestamp()
    if rfc3339:
        ts.FromJsonString(rfc3339)
    return ts


def _record_to_proto(r: SecretRecord) -> resources_pb2.Secret:
    return resources_pb2.Secret(
        name=build_secret_name(r.project, r.secret_id),
        create_time=_timestamp(r.create_time),
        labels=dict(r.labels),
        annotations=dict(r.annotations),
    )


def _version_to_proto(project: str, secret_id: str, v: SecretVersion) -> resources_pb2.SecretVersion:
    state_map = {
        SecretVersionState.ENABLED: resources_pb2.SecretVersion.ENABLED,
        SecretVersionState.DISABLED: resources_pb2.SecretVersion.DISABLED,
        SecretVersionState.DESTROYED: resources_pb2.SecretVersion.DESTROYED,
    }
    return resources_pb2.SecretVersion(
        name=build_version_name(project, secret_id, v.id),
        create_time=_timestamp(v.create_time),
        destroy_time=_timestamp(v.destroy_time) if v.destroy_time else Timestamp(),
        state=state_map[v.state],
    )


class SecretManagerServicer(service_pb2_grpc.SecretManagerServiceServicer):
    def __init__(self, *, storage: SecretManagerStorage) -> None:
        self._storage = storage

    # --- secret lifecycle -----------------------------------------------

    async def CreateSecret(self, request, context):
        try:
            project = _parse_parent(request.parent)
            validate_secret_id(request.secret_id)
        except InvalidResourceName as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        rec = SecretRecord(
            project=project,
            secret_id=request.secret_id,
            labels=dict(request.secret.labels),
            annotations=dict(request.secret.annotations),
            create_time=rfc3339_now(),
        )
        try:
            await self._storage.create_secret(rec)
        except SecretAlreadyExists:
            await context.abort(
                grpc.StatusCode.ALREADY_EXISTS,
                f"secret {request.secret_id!r} already exists",
            )
        return _record_to_proto(rec)

    async def GetSecret(self, request, context):
        try:
            project, sid = parse_secret_name(request.name)
        except InvalidResourceName as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        try:
            rec = await self._storage.get_secret(project, sid)
        except SecretNotFound:
            await context.abort(
                grpc.StatusCode.NOT_FOUND, f"secret {request.name!r} not found"
            )
        return _record_to_proto(rec)

    async def ListSecrets(self, request, context):
        try:
            project = _parse_parent(request.parent)
        except InvalidResourceName as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        page_size = request.page_size or None
        page_token = request.page_token or None
        items, next_token = await self._storage.list_secrets(
            project, page_size=page_size, page_token=page_token
        )
        return service_pb2.ListSecretsResponse(
            secrets=[_record_to_proto(r) for r in items],
            next_page_token=next_token or "",
            total_size=len(items),
        )

    async def UpdateSecret(self, request, context):
        try:
            project, sid = parse_secret_name(request.secret.name)
        except InvalidResourceName as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        try:
            rec = await self._storage.get_secret(project, sid)
        except SecretNotFound:
            await context.abort(
                grpc.StatusCode.NOT_FOUND, f"secret {request.secret.name!r} not found"
            )
        mask = set(request.update_mask.paths)
        if "labels" in mask:
            rec.labels = dict(request.secret.labels)
        if "annotations" in mask:
            rec.annotations = dict(request.secret.annotations)
        await self._storage.update_secret(rec)
        return _record_to_proto(rec)

    async def DeleteSecret(self, request, context):
        try:
            project, sid = parse_secret_name(request.name)
        except InvalidResourceName as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        try:
            await self._storage.delete_secret(project, sid)
        except SecretNotFound:
            await context.abort(
                grpc.StatusCode.NOT_FOUND, f"secret {request.name!r} not found"
            )
        # DeleteSecret returns google.protobuf.Empty
        from google.protobuf import empty_pb2
        return empty_pb2.Empty()
```

- [ ] **Step 4: Run — pass**

8 PASS.

- [ ] **Step 5: Quality gate** all green.

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/services/secret_manager/servicer.py tests/unit/services/secret_manager/test_servicer_secrets.py
git commit -m "$(cat <<'EOF'
feat(secret_manager): servicer for secret lifecycle (Create/Get/List/Update/Delete)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Servicer — version lifecycle + wire into service

**Files:**
- Modify: `src/gcp_local/services/secret_manager/servicer.py` (add version methods)
- Modify: `src/gcp_local/services/secret_manager/service.py` (register servicer, instantiate storage)
- Test: `tests/unit/services/secret_manager/test_servicer_versions.py`

- [ ] **Step 1: Failing tests**

`tests/unit/services/secret_manager/test_servicer_versions.py`:

```python
import grpc
import pytest

from gcp_local.generated.google.cloud.secretmanager.v1 import resources_pb2, service_pb2
from gcp_local.services.secret_manager.servicer import SecretManagerServicer
from gcp_local.services.secret_manager.storage import InMemoryStorage


class FakeContext:
    def __init__(self) -> None:
        self.aborted: tuple[grpc.StatusCode, str] | None = None

    async def abort(self, code, details):
        self.aborted = (code, details)
        raise grpc.aio.AioRpcError(code, None, None, details=details)


async def _create(svc, secret_id="x", project="p1"):
    await svc.CreateSecret(
        service_pb2.CreateSecretRequest(
            parent=f"projects/{project}",
            secret_id=secret_id,
            secret=service_pb2.Secret(),
        ),
        FakeContext(),
    )


async def test_add_secret_version_returns_id_1():
    svc = SecretManagerServicer(storage=InMemoryStorage())
    await _create(svc)
    result = await svc.AddSecretVersion(
        service_pb2.AddSecretVersionRequest(
            parent="projects/p1/secrets/x",
            payload=resources_pb2.SecretPayload(data=b"hello"),
        ),
        FakeContext(),
    )
    assert result.name == "projects/p1/secrets/x/versions/1"


async def test_access_secret_version_returns_payload():
    svc = SecretManagerServicer(storage=InMemoryStorage())
    await _create(svc)
    await svc.AddSecretVersion(
        service_pb2.AddSecretVersionRequest(
            parent="projects/p1/secrets/x",
            payload=resources_pb2.SecretPayload(data=b"hello"),
        ),
        FakeContext(),
    )
    result = await svc.AccessSecretVersion(
        service_pb2.AccessSecretVersionRequest(
            name="projects/p1/secrets/x/versions/1"
        ),
        FakeContext(),
    )
    assert result.name == "projects/p1/secrets/x/versions/1"
    assert result.payload.data == b"hello"
    # data_crc32c must be set (non-zero for non-empty payload)
    assert result.payload.data_crc32c != 0


async def test_access_latest_returns_highest_enabled():
    svc = SecretManagerServicer(storage=InMemoryStorage())
    await _create(svc)
    await svc.AddSecretVersion(
        service_pb2.AddSecretVersionRequest(
            parent="projects/p1/secrets/x",
            payload=resources_pb2.SecretPayload(data=b"v1"),
        ),
        FakeContext(),
    )
    await svc.AddSecretVersion(
        service_pb2.AddSecretVersionRequest(
            parent="projects/p1/secrets/x",
            payload=resources_pb2.SecretPayload(data=b"v2"),
        ),
        FakeContext(),
    )
    result = await svc.AccessSecretVersion(
        service_pb2.AccessSecretVersionRequest(
            name="projects/p1/secrets/x/versions/latest"
        ),
        FakeContext(),
    )
    assert result.payload.data == b"v2"


async def test_access_latest_none_enabled_raises_failed_precondition():
    svc = SecretManagerServicer(storage=InMemoryStorage())
    await _create(svc)
    await svc.AddSecretVersion(
        service_pb2.AddSecretVersionRequest(
            parent="projects/p1/secrets/x",
            payload=resources_pb2.SecretPayload(data=b"v1"),
        ),
        FakeContext(),
    )
    await svc.DisableSecretVersion(
        service_pb2.DisableSecretVersionRequest(
            name="projects/p1/secrets/x/versions/1"
        ),
        FakeContext(),
    )
    ctx = FakeContext()
    with pytest.raises(grpc.aio.AioRpcError):
        await svc.AccessSecretVersion(
            service_pb2.AccessSecretVersionRequest(
                name="projects/p1/secrets/x/versions/latest"
            ),
            ctx,
        )
    assert ctx.aborted[0] == grpc.StatusCode.FAILED_PRECONDITION


async def test_access_disabled_version_fails_precondition():
    svc = SecretManagerServicer(storage=InMemoryStorage())
    await _create(svc)
    await svc.AddSecretVersion(
        service_pb2.AddSecretVersionRequest(
            parent="projects/p1/secrets/x",
            payload=resources_pb2.SecretPayload(data=b"v1"),
        ),
        FakeContext(),
    )
    await svc.DisableSecretVersion(
        service_pb2.DisableSecretVersionRequest(
            name="projects/p1/secrets/x/versions/1"
        ),
        FakeContext(),
    )
    ctx = FakeContext()
    with pytest.raises(grpc.aio.AioRpcError):
        await svc.AccessSecretVersion(
            service_pb2.AccessSecretVersionRequest(
                name="projects/p1/secrets/x/versions/1"
            ),
            ctx,
        )
    assert ctx.aborted[0] == grpc.StatusCode.FAILED_PRECONDITION


async def test_enable_disable_destroy_cycle():
    svc = SecretManagerServicer(storage=InMemoryStorage())
    await _create(svc)
    await svc.AddSecretVersion(
        service_pb2.AddSecretVersionRequest(
            parent="projects/p1/secrets/x",
            payload=resources_pb2.SecretPayload(data=b"v1"),
        ),
        FakeContext(),
    )
    disabled = await svc.DisableSecretVersion(
        service_pb2.DisableSecretVersionRequest(
            name="projects/p1/secrets/x/versions/1"
        ),
        FakeContext(),
    )
    assert disabled.state == resources_pb2.SecretVersion.DISABLED
    enabled = await svc.EnableSecretVersion(
        service_pb2.EnableSecretVersionRequest(
            name="projects/p1/secrets/x/versions/1"
        ),
        FakeContext(),
    )
    assert enabled.state == resources_pb2.SecretVersion.ENABLED
    destroyed = await svc.DestroySecretVersion(
        service_pb2.DestroySecretVersionRequest(
            name="projects/p1/secrets/x/versions/1"
        ),
        FakeContext(),
    )
    assert destroyed.state == resources_pb2.SecretVersion.DESTROYED


async def test_list_secret_versions():
    svc = SecretManagerServicer(storage=InMemoryStorage())
    await _create(svc)
    for _ in range(3):
        await svc.AddSecretVersion(
            service_pb2.AddSecretVersionRequest(
                parent="projects/p1/secrets/x",
                payload=resources_pb2.SecretPayload(data=b"p"),
            ),
            FakeContext(),
        )
    result = await svc.ListSecretVersions(
        service_pb2.ListSecretVersionsRequest(parent="projects/p1/secrets/x"),
        FakeContext(),
    )
    ids = [int(v.name.rsplit("/", 1)[1]) for v in result.versions]
    assert ids == [1, 2, 3]


async def test_get_secret_version_not_found():
    svc = SecretManagerServicer(storage=InMemoryStorage())
    await _create(svc)
    ctx = FakeContext()
    with pytest.raises(grpc.aio.AioRpcError):
        await svc.GetSecretVersion(
            service_pb2.GetSecretVersionRequest(
                name="projects/p1/secrets/x/versions/99"
            ),
            ctx,
        )
    assert ctx.aborted[0] == grpc.StatusCode.NOT_FOUND
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Append version methods to `servicer.py`**

Inside the `SecretManagerServicer` class (add after `DeleteSecret`):

```python
    # --- version lifecycle -----------------------------------------------

    async def AddSecretVersion(self, request, context):
        try:
            project, sid = parse_secret_name(request.parent)
        except InvalidResourceName as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        try:
            version = await self._storage.add_version(
                project, sid, bytes(request.payload.data)
            )
        except SecretNotFound:
            await context.abort(
                grpc.StatusCode.NOT_FOUND, f"secret {request.parent!r} not found"
            )
        proto = _version_to_proto(project, sid, version)
        # Note: AddSecretVersion response is a SecretVersion proto.
        # data_crc32c lives on the *payload* in Access responses only.
        return proto

    async def GetSecretVersion(self, request, context):
        try:
            project, sid, vid_raw = parse_version_name(request.name)
        except InvalidResourceName as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        if vid_raw == "latest":
            try:
                rec = await self._storage.get_secret(project, sid)
            except SecretNotFound:
                await context.abort(grpc.StatusCode.NOT_FOUND, f"secret {sid!r} not found")
            v = rec.highest_enabled_version()
            if v is None:
                await context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    f"no enabled version for secret {sid!r}",
                )
            return _version_to_proto(project, sid, v)
        try:
            vid = int(vid_raw)
        except ValueError:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, f"bad version id: {vid_raw!r}"
            )
        try:
            version = await self._storage.get_version(project, sid, vid)
        except (SecretNotFound, VersionNotFound):
            await context.abort(
                grpc.StatusCode.NOT_FOUND, f"version {request.name!r} not found"
            )
        return _version_to_proto(project, sid, version)

    async def ListSecretVersions(self, request, context):
        try:
            project, sid = parse_secret_name(request.parent)
        except InvalidResourceName as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        try:
            items, next_token = await self._storage.list_versions(
                project, sid,
                page_size=request.page_size or None,
                page_token=request.page_token or None,
            )
        except SecretNotFound:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"secret {sid!r} not found")
        return service_pb2.ListSecretVersionsResponse(
            versions=[_version_to_proto(project, sid, v) for v in items],
            next_page_token=next_token or "",
            total_size=len(items),
        )

    async def AccessSecretVersion(self, request, context):
        try:
            project, sid, vid_raw = parse_version_name(request.name)
        except InvalidResourceName as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))

        if vid_raw == "latest":
            try:
                rec = await self._storage.get_secret(project, sid)
            except SecretNotFound:
                await context.abort(grpc.StatusCode.NOT_FOUND, f"secret {sid!r} not found")
            v = rec.highest_enabled_version()
            if v is None:
                await context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    f"no enabled version for secret {sid!r}",
                )
        else:
            try:
                vid = int(vid_raw)
            except ValueError:
                await context.abort(
                    grpc.StatusCode.INVALID_ARGUMENT, f"bad version id: {vid_raw!r}"
                )
            try:
                v = await self._storage.get_version(project, sid, vid)
            except (SecretNotFound, VersionNotFound):
                await context.abort(
                    grpc.StatusCode.NOT_FOUND, f"version {request.name!r} not found"
                )
            if v.state != SecretVersionState.ENABLED:
                await context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    f"version {request.name!r} is in state {v.state.value}",
                )

        return service_pb2.AccessSecretVersionResponse(
            name=build_version_name(project, sid, v.id),
            payload=resources_pb2.SecretPayload(
                data=v.payload, data_crc32c=v.data_crc32c
            ),
        )

    async def _set_state(self, request_name: str, new_state: SecretVersionState, context):
        try:
            project, sid, vid_raw = parse_version_name(request_name)
            vid = int(vid_raw)
        except (InvalidResourceName, ValueError) as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        try:
            version = await self._storage.update_version_state(
                project, sid, vid, new_state
            )
        except (SecretNotFound, VersionNotFound):
            await context.abort(
                grpc.StatusCode.NOT_FOUND, f"version {request_name!r} not found"
            )
        except InvalidStateTransition as e:
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(e))
        return _version_to_proto(project, sid, version)

    async def EnableSecretVersion(self, request, context):
        return await self._set_state(request.name, SecretVersionState.ENABLED, context)

    async def DisableSecretVersion(self, request, context):
        return await self._set_state(request.name, SecretVersionState.DISABLED, context)

    async def DestroySecretVersion(self, request, context):
        return await self._set_state(request.name, SecretVersionState.DESTROYED, context)
```

The servicer body flows: `DeleteSecret` → `AddSecretVersion` → `GetSecretVersion` → `ListSecretVersions` → `AccessSecretVersion` → `_set_state` helper → `EnableSecretVersion` / `DisableSecretVersion` / `DestroySecretVersion`.

- [ ] **Step 4: Wire the servicer into `SecretManagerService.start()`**

Replace the body of `service.py` with:

```python
import asyncio
import contextlib
import logging
from pathlib import Path
from typing import ClassVar

import grpc

from gcp_local.core.context import Context
from gcp_local.core.service import HealthStatus, Port
from gcp_local.generated.google.cloud.secretmanager.v1 import service_pb2_grpc
from gcp_local.services.secret_manager.servicer import SecretManagerServicer
from gcp_local.services.secret_manager.storage import (
    DiskStorage,
    InMemoryStorage,
    SecretManagerStorage,
)

log = logging.getLogger(__name__)

_DEFAULT_PORT = 8086


class SecretManagerService:
    name = "secret_manager"
    default_ports: ClassVar[list[Port]] = [Port(_DEFAULT_PORT, "grpc")]

    def __init__(self) -> None:
        self._server: grpc.aio.Server | None = None
        self._started = False
        self._storage: SecretManagerStorage | None = None

    async def start(self, ctx: Context) -> None:
        self._storage = self._make_storage(ctx)
        port = ctx.port_overrides.get(self.name, _DEFAULT_PORT)
        self._server = grpc.aio.server()
        self._server.add_insecure_port(f"[::]:{port}")
        servicer = SecretManagerServicer(storage=self._storage)
        service_pb2_grpc.add_SecretManagerServiceServicer_to_server(
            servicer, self._server
        )
        await self._server.start()
        self._started = True
        log.info("secret_manager service listening on :%d", port)

    async def stop(self) -> None:
        if self._server is not None:
            with contextlib.suppress(Exception):
                await self._server.stop(grace=5.0)
        self._started = False

    async def reset_state(self) -> None:
        if self._storage is not None:
            await self._storage.reset()

    def health(self) -> HealthStatus:
        return HealthStatus(
            ok=self._started, message="running" if self._started else "stopped"
        )

    def _make_storage(self, ctx: Context) -> SecretManagerStorage:
        if ctx.persist:
            root = Path(ctx.data_dir) / "secret_manager"
            root.mkdir(parents=True, exist_ok=True)
            return DiskStorage(root)
        return InMemoryStorage()
```

- [ ] **Step 5: Run — pass**

8 new PASS. Full suite green, including the 8 core end-to-end tests that now boot with both services.

- [ ] **Step 6: Quality gate** all green.

- [ ] **Step 7: Commit**

```bash
git add src/gcp_local/services/secret_manager/servicer.py src/gcp_local/services/secret_manager/service.py tests/unit/services/secret_manager/test_servicer_versions.py
git commit -m "$(cat <<'EOF'
feat(secret_manager): version lifecycle + wire servicer into service

Adds AddSecretVersion / GetSecretVersion / ListSecretVersions /
AccessSecretVersion / Enable / Disable / DestroySecretVersion with
'latest' alias resolution and state-transition enforcement. Wires
the servicer into SecretManagerService.start() with in-memory or
disk storage depending on ctx.persist.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Integration tests with real `google-cloud-secret-manager` client

**Files:**
- Create: `tests/integration/test_secret_manager_integration.py`

- [ ] **Step 1: Write the tests**

```python
"""Integration tests driving the emulator with the real google-cloud-secret-manager client."""
import grpc
import pytest
from google.api_core import exceptions as gce
from google.cloud import secretmanager_v1
from google.cloud.secretmanager_v1.services.secret_manager_service.transports.grpc import (
    SecretManagerServiceGrpcTransport,
)
from google.protobuf.field_mask_pb2 import FieldMask


@pytest.fixture
def client(emulator):
    channel = grpc.insecure_channel(f"127.0.0.1:{emulator['secret_manager_port']}")
    transport = SecretManagerServiceGrpcTransport(channel=channel)
    return secretmanager_v1.SecretManagerServiceClient(transport=transport)


def test_create_get_list_delete_secret(client):
    parent = "projects/p1"
    secret = secretmanager_v1.Secret(labels={"env": "dev"})
    created = client.create_secret(
        request={"parent": parent, "secret_id": "my-secret", "secret": secret}
    )
    assert created.name == "projects/p1/secrets/my-secret"
    assert dict(created.labels) == {"env": "dev"}

    got = client.get_secret(request={"name": created.name})
    assert got.name == created.name

    listed = list(client.list_secrets(request={"parent": parent}))
    assert any(s.name == created.name for s in listed)

    client.delete_secret(request={"name": created.name})
    with pytest.raises(gce.NotFound):
        client.get_secret(request={"name": created.name})


def test_add_and_access_secret_version(client):
    parent = "projects/p1"
    client.create_secret(
        request={"parent": parent, "secret_id": "s", "secret": secretmanager_v1.Secret()}
    )
    added = client.add_secret_version(
        request={
            "parent": f"{parent}/secrets/s",
            "payload": {"data": b"hello"},
        }
    )
    assert added.name == f"{parent}/secrets/s/versions/1"
    accessed = client.access_secret_version(request={"name": added.name})
    assert accessed.payload.data == b"hello"
    # crc32c present and non-zero
    assert accessed.payload.data_crc32c != 0


def test_access_latest_alias_returns_newest_enabled(client):
    parent = "projects/p1"
    client.create_secret(
        request={"parent": parent, "secret_id": "s", "secret": secretmanager_v1.Secret()}
    )
    client.add_secret_version(
        request={"parent": f"{parent}/secrets/s", "payload": {"data": b"v1"}}
    )
    client.add_secret_version(
        request={"parent": f"{parent}/secrets/s", "payload": {"data": b"v2"}}
    )
    latest = client.access_secret_version(
        request={"name": f"{parent}/secrets/s/versions/latest"}
    )
    assert latest.payload.data == b"v2"


def test_disable_destroy_blocks_access(client):
    parent = "projects/p1"
    client.create_secret(
        request={"parent": parent, "secret_id": "s", "secret": secretmanager_v1.Secret()}
    )
    v = client.add_secret_version(
        request={"parent": f"{parent}/secrets/s", "payload": {"data": b"secret"}}
    )
    client.disable_secret_version(request={"name": v.name})
    with pytest.raises(gce.FailedPrecondition):
        client.access_secret_version(request={"name": v.name})
    # Re-enable and access again
    client.enable_secret_version(request={"name": v.name})
    again = client.access_secret_version(request={"name": v.name})
    assert again.payload.data == b"secret"
    # Destroy and confirm payload is gone (FailedPrecondition on access)
    client.destroy_secret_version(request={"name": v.name})
    with pytest.raises(gce.FailedPrecondition):
        client.access_secret_version(request={"name": v.name})


def test_update_secret_labels_only(client):
    parent = "projects/p1"
    client.create_secret(
        request={
            "parent": parent,
            "secret_id": "s",
            "secret": secretmanager_v1.Secret(labels={"old": "1"}),
        }
    )
    updated = client.update_secret(
        request={
            "secret": secretmanager_v1.Secret(
                name=f"{parent}/secrets/s",
                labels={"new": "2"},
                annotations={"ann": "x"},
            ),
            "update_mask": FieldMask(paths=["labels"]),
        }
    )
    assert dict(updated.labels) == {"new": "2"}
    # annotations not in mask → not applied
    assert dict(updated.annotations) == {}


def test_list_secret_versions(client):
    parent = "projects/p1"
    client.create_secret(
        request={"parent": parent, "secret_id": "s", "secret": secretmanager_v1.Secret()}
    )
    for _ in range(3):
        client.add_secret_version(
            request={"parent": f"{parent}/secrets/s", "payload": {"data": b"p"}}
        )
    versions = list(
        client.list_secret_versions(request={"parent": f"{parent}/secrets/s"})
    )
    ids = sorted(int(v.name.rsplit("/", 1)[1]) for v in versions)
    assert ids == [1, 2, 3]


def test_get_secret_not_found_raises(client):
    with pytest.raises(gce.NotFound):
        client.get_secret(request={"name": "projects/p1/secrets/nope"})
```

- [ ] **Step 2: Run — expect pass (no fixes expected)**

```bash
. .venv/bin/activate && pytest tests/integration/test_secret_manager_integration.py -v
```

7 tests. **If any fail, diagnose the root cause.** Common suspects:
- Servicer method signature mismatch (proto-plus vs raw protobuf wrappers)
- `data_crc32c` not populated or wrong type
- `latest` resolution returning wrong version
- Status code mapping

Don't weaken the tests. Fix the emulator.

- [ ] **Step 3: Full suite sanity**

```bash
. .venv/bin/activate && pytest -v
```

All green. Docker test remains skipped unless daemon is available.

- [ ] **Step 4: Quality gate** all green.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_secret_manager_integration.py
git commit -m "$(cat <<'EOF'
test(secret_manager): integration tests driving real google-cloud-secret-manager client

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Open PR

**Files:** none.

- [ ] **Step 1: Push branch**

```bash
git push -u origin secret-manager
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --base master --head secret-manager \
  --title "Secret Manager service + first gRPC integration" \
  --body "$(cat <<'EOF'
## Summary

- Adds Secret Manager as the second real GCP service in the emulator
- First gRPC service — establishes the pattern for Pub/Sub and Firestore later
- Vendors `google/cloud/secretmanager/v1/*.proto` files and commits generated stubs under `src/gcp_local/generated/` (one-shot regen via `scripts/gen_protos.sh`)
- Extends core with `grpcio`/`googleapis-common-protos` runtime deps and a `GrpcError` helper in `gcp_local.core.errors`

## Scope (v1)

- Secret lifecycle: Create / Get / List / Update (labels + annotations) / Delete
- Version lifecycle: AddSecretVersion / GetSecretVersion / ListSecretVersions / AccessSecretVersion / Enable / Disable / Destroy
- `"latest"` alias → highest enabled version
- `data_crc32c` checksum on AddSecretVersion
- In-memory and disk-backed JSON storage
- Project namespacing (`projects/<project>/secrets/<id>`)

## Deferred (v2+)

- IAM methods (no auth model)
- Rotation config, CMEK, TTL
- REST transport (client library uses gRPC by default)

## Test plan

- [x] Unit tests for names, models, storage (in-mem + disk), servicer (secrets + versions)
- [x] Integration tests driving the real `google-cloud-secret-manager` Python client over a real gRPC socket
- [x] Core integration tests updated — assert both `gcs` and `secret_manager` boot
- [x] `ruff check`, `ruff format --check`, `mypy --strict` all green

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Return PR URL**

---

## Done

With Task 11, the Secret Manager service is complete, the core has gRPC support, and there is a PR awaiting human review and merge to `master`.

**What this unblocks:** Pub/Sub and Firestore plans can now assume the core has gRPC support and the `gcp_local.generated/` proto-vendoring pattern is established.
