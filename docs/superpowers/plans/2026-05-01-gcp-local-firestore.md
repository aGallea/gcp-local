# gcp-local Firestore Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Firestore service so the official `google-cloud-firestore` Python client library works unchanged against the emulator over gRPC. Covers Native-mode CRUD, structured queries (filters/orderBy/cursors/limit), aggregations (count/sum/avg), batched commits, field transforms (SERVER_TIMESTAMP, increment, arrayUnion/arrayRemove, max/min), optimistic-concurrency transactions, multi-database namespacing, FirestoreAdmin index accept-and-ignore, and JSON-on-disk persistence under `PERSIST=1`. `Listen`, security rules, exports/imports, and PartitionQuery are out of v1 (return `UNIMPLEMENTED`).

**Architecture:** New `gcp_local.services.firestore` package registered as a Service. The service owns its own `grpc.aio.Server` on port 8080 (Firebase Local Emulator Suite default). Two servicers are registered on the same server: `FirestoreServicer` (data API) and `FirestoreAdminServicer` (index management stub). Storage is a per-`(project, database)` dict of `DocumentRecord`s; query evaluation is a brute-force pipeline (candidate set → filter → sort → cursor → limit). Field transforms and transactions live in an `engine/` subpackage. Proto stubs are vendored under `protos/google/firestore/{v1,admin/v1}/` and generated into `src/gcp_local/generated/`.

**Tech Stack:** Python 3.13, grpcio (existing runtime dep), googleapis-common-protos (existing), grpcio-tools + google-cloud-firestore (new dev deps), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-05-01-gcp-local-firestore-design.md`

**Branch:** `feat/firestore-service` (create at start of Task 1). All implementation tasks land on this branch; when all tasks pass, open a PR to `master`.

**Commit policy:** Per-task commits allowed. Use `.venv/bin/python` (not bare `python`). Do not bypass signing/hooks. Trailer on every commit (HEREDOC):
```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

**Single-PR override:** Per user direction, this lands as one PR rather than the usual <500 LOC cuts. The components (servicer, query evaluator, transforms, transactions) are tightly interdependent and the official Python client uses field transforms on common idiomatic writes — a CRUD-only first PR would not pass the "client works unchanged" success criterion.

---

## File structure

```
protos/google/firestore/v1/
  firestore.proto                              # NEW (vendored from googleapis)
  document.proto                               # NEW
  query.proto                                  # NEW
  write.proto                                  # NEW
  common.proto                                 # NEW
  aggregation_result.proto                     # NEW
protos/google/firestore/admin/v1/
  firestore_admin.proto                        # NEW
  index.proto                                  # NEW
  field.proto                                  # NEW
  database.proto                               # NEW
  operation.proto                              # NEW

scripts/
  gen_protos.sh                                # MODIFY: add firestore generation block

src/gcp_local/generated/google/firestore/
  __init__.py                                  # NEW (empty)
  v1/__init__.py                               # NEW (empty)
  v1/firestore_pb2.py                          # GENERATED
  v1/firestore_pb2_grpc.py                     # GENERATED
  v1/document_pb2.py                           # GENERATED
  v1/query_pb2.py                              # GENERATED
  v1/write_pb2.py                              # GENERATED
  v1/common_pb2.py                             # GENERATED
  v1/aggregation_result_pb2.py                 # GENERATED
  admin/__init__.py                            # NEW (empty)
  admin/v1/__init__.py                         # NEW (empty)
  admin/v1/firestore_admin_pb2.py              # GENERATED
  admin/v1/firestore_admin_pb2_grpc.py         # GENERATED
  admin/v1/index_pb2.py                        # GENERATED
  admin/v1/field_pb2.py                        # GENERATED
  admin/v1/database_pb2.py                     # GENERATED
  admin/v1/operation_pb2.py                    # GENERATED

src/gcp_local/services/firestore/
  __init__.py                                  # exports FirestoreService
  service.py                                   # FirestoreService (Service protocol)
  servicer.py                                  # FirestoreServicer + FirestoreAdminServicer
  values.py                                    # Value <-> Python codec + comparator
  models.py                                    # DocumentRecord, TransactionRecord, IndexRecord
  storage.py                                   # Storage protocol + InMemoryStorage + JsonDiskStorage
  names.py                                     # path parsers + ID validators
  errors.py                                    # exception types + grpc_error mapper
  engine/
    __init__.py
    query.py                                   # filter / orderBy / cursor / limit pipeline
    transforms.py                              # field transforms (SERVER_TIMESTAMP, increment, ...)
    transactions.py                            # transaction registry + TTL sweeper
    aggregations.py                            # count / sum / avg

tests/unit/services/firestore/
  __init__.py
  test_names.py
  test_values.py
  test_models.py
  test_storage.py
  test_storage_persistence.py
  test_transforms.py
  test_query_filters.py
  test_query_orderby.py
  test_query_cursors.py
  test_query_collection_group.py
  test_aggregations.py
  test_transactions.py
  test_servicer_documents.py
  test_servicer_commit.py
  test_servicer_run_query.py
  test_servicer_admin.py
  test_errors.py
  test_service_scaffold.py

tests/integration/
  test_firestore_integration.py
  conftest.py                                  # MODIFY: include "firestore" in default service list

docs/services/firestore.md                     # NEW
docs/architecture/firestore.md                 # NEW

pyproject.toml                                 # MODIFY: register entry point + dev dep
README.md                                      # MODIFY: flip Firestore Planned → Alpha; add port 8080
ROADMAP.md                                     # MODIFY: remove Firestore from Planned; add follow-ups
CHANGELOG.md                                   # MODIFY: [Unreleased] entry
docs/deployment.md                             # MODIFY: add 8080 to ports table
```

---

## Task 1: Branch + vendor protos + extend gen_protos.sh

**Files:**
- Create: `protos/google/firestore/v1/{firestore,document,query,write,common,aggregation_result}.proto`
- Create: `protos/google/firestore/admin/v1/{firestore_admin,index,field,database,operation}.proto`
- Modify: `scripts/gen_protos.sh`
- Create: empty `__init__.py` files under `src/gcp_local/generated/google/firestore/{,v1,admin,admin/v1}/`

- [ ] **Step 1: Create the feature branch**

```bash
git checkout -b feat/firestore-service
```

- [ ] **Step 2: Fetch all proto files from googleapis**

```bash
mkdir -p protos/google/firestore/v1 protos/google/firestore/admin/v1
BASE=https://raw.githubusercontent.com/googleapis/googleapis/master
for f in firestore document query write common aggregation_result; do
  curl -sSL -o protos/google/firestore/v1/$f.proto $BASE/google/firestore/v1/$f.proto
done
for f in firestore_admin index field database operation; do
  curl -sSL -o protos/google/firestore/admin/v1/$f.proto $BASE/google/firestore/admin/v1/$f.proto
done
```

Verify each file has `package google.firestore.v1;` or `package google.firestore.admin.v1;` and that `firestore.proto` contains `service Firestore` and `firestore_admin.proto` contains `service FirestoreAdmin`.

- [ ] **Step 3: Extend `scripts/gen_protos.sh`**

Append to the script after the existing pubsub block (do not remove anything):

```bash
# Firestore (data + admin APIs)
python -m grpc_tools.protoc \
  --proto_path=protos \
  --proto_path="$EXTRA_PROTO_PATH" \
  --python_out="$OUT" \
  --pyi_out="$OUT" \
  --grpc_python_out="$OUT" \
  protos/google/firestore/v1/*.proto \
  protos/google/firestore/admin/v1/*.proto
```

Look at the existing pubsub generation block in the same script for the import-rewrite step (the script uses `sed` to rewrite `from google.pubsub.v1` → `from gcp_local.generated.google.pubsub.v1`); add the analogous rewrite for `google.firestore.v1` → `gcp_local.generated.google.firestore.v1` and `google.firestore.admin.v1` → `gcp_local.generated.google.firestore.admin.v1`. Match the existing sed pattern exactly.

- [ ] **Step 4: Run the generator and create the package skeletons**

```bash
mkdir -p src/gcp_local/generated/google/firestore/v1 src/gcp_local/generated/google/firestore/admin/v1
touch src/gcp_local/generated/google/firestore/__init__.py
touch src/gcp_local/generated/google/firestore/v1/__init__.py
touch src/gcp_local/generated/google/firestore/admin/__init__.py
touch src/gcp_local/generated/google/firestore/admin/v1/__init__.py
.venv/bin/bash scripts/gen_protos.sh
```

Expected: generated `*_pb2.py`, `*_pb2.pyi`, `*_pb2_grpc.py` under both v1 and admin/v1.

- [ ] **Step 5: Verify imports work**

```bash
.venv/bin/python -c "from gcp_local.generated.google.firestore.v1 import firestore_pb2_grpc; print(firestore_pb2_grpc.FirestoreServicer)"
.venv/bin/python -c "from gcp_local.generated.google.firestore.admin.v1 import firestore_admin_pb2_grpc; print(firestore_admin_pb2_grpc.FirestoreAdminServicer)"
```

Expected: prints two class objects. If imports fail, debug the sed rewrite step.

- [ ] **Step 6: Commit**

```bash
git add protos/google/firestore scripts/gen_protos.sh src/gcp_local/generated/google/firestore
git commit -m "$(cat <<'EOF'
chore(firestore): vendor protos and extend gen_protos.sh

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Service scaffold + entry-point registration

**Files:**
- Create: `src/gcp_local/services/firestore/__init__.py`
- Create: `src/gcp_local/services/firestore/service.py`
- Create: `src/gcp_local/services/firestore/servicer.py` (skeleton — empty servicers)
- Create: `src/gcp_local/services/firestore/storage.py` (skeleton — empty `InMemoryStorage` class)
- Create: `tests/unit/services/firestore/__init__.py`
- Create: `tests/unit/services/firestore/test_service_scaffold.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write the scaffold test**

`tests/unit/services/firestore/test_service_scaffold.py`:

```python
import pytest

from gcp_local.core.context import Context
from gcp_local.core.state_hub import StateHub
from gcp_local.services.firestore import FirestoreService


@pytest.mark.asyncio
async def test_service_starts_and_health_reports_running():
    svc = FirestoreService()
    ctx = Context(persist=False, port_overrides={"firestore": 0}, state_hub=StateHub())
    try:
        await svc.start(ctx)
        assert svc.health().ok is True
    finally:
        await svc.stop()
    assert svc.health().ok is False


def test_service_default_port_is_8080():
    svc = FirestoreService()
    ports = list(svc.default_ports)
    assert len(ports) == 1
    assert ports[0].port == 8080
    assert ports[0].protocol == "grpc"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/bin/pytest tests/unit/services/firestore/test_service_scaffold.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gcp_local.services.firestore'`.

- [ ] **Step 3: Implement service.py**

`src/gcp_local/services/firestore/service.py`:

```python
"""Firestore Service — owns the gRPC server lifecycle."""

import contextlib
import logging
from typing import ClassVar

import grpc

from gcp_local.core.context import Context
from gcp_local.core.service import HealthStatus, Port
from gcp_local.generated.google.firestore.admin.v1 import firestore_admin_pb2_grpc
from gcp_local.generated.google.firestore.v1 import firestore_pb2_grpc
from gcp_local.services.firestore.servicer import (
    FirestoreAdminServicer,
    FirestoreServicer,
)
from gcp_local.services.firestore.storage import InMemoryStorage, FirestoreStorage

log = logging.getLogger(__name__)

_DEFAULT_PORT = 8080


class FirestoreService:
    """Emulates Google Cloud Firestore (Native mode) over gRPC."""

    name = "firestore"
    default_ports: ClassVar[list[Port]] = [Port(_DEFAULT_PORT, "grpc")]

    def __init__(self) -> None:
        self._server: grpc.aio.Server | None = None
        self._started = False
        self._storage: FirestoreStorage | None = None

    async def start(self, ctx: Context) -> None:
        # JsonDiskStorage wiring lands in a later task; for now use InMemoryStorage
        # always. Persistence is opt-in via PERSIST=1 once Task 16 lands.
        self._storage = InMemoryStorage()
        port = ctx.port_overrides.get(self.name, _DEFAULT_PORT)
        self._server = grpc.aio.server()
        self._server.add_insecure_port(f"[::]:{port}")
        firestore_servicer = FirestoreServicer(storage=self._storage, state_hub=ctx.state_hub)
        admin_servicer = FirestoreAdminServicer(storage=self._storage)
        firestore_pb2_grpc.add_FirestoreServicer_to_server(firestore_servicer, self._server)  # type: ignore[no-untyped-call]
        firestore_admin_pb2_grpc.add_FirestoreAdminServicer_to_server(admin_servicer, self._server)  # type: ignore[no-untyped-call]
        await self._server.start()
        self._started = True
        log.info("firestore service listening on :%d", port)

    async def stop(self) -> None:
        if self._server is not None:
            with contextlib.suppress(Exception):
                await self._server.stop(grace=0)
        self._started = False

    async def reset_state(self) -> None:
        if self._storage is not None:
            await self._storage.reset()

    def health(self) -> HealthStatus:
        return HealthStatus(ok=self._started, message="running" if self._started else "stopped")
```

`src/gcp_local/services/firestore/__init__.py`:

```python
from gcp_local.services.firestore.service import FirestoreService

__all__ = ["FirestoreService"]
```

`src/gcp_local/services/firestore/servicer.py` (skeleton):

```python
"""Firestore gRPC servicers. RPCs are filled in by later tasks."""

from gcp_local.core.state_hub import StateHub
from gcp_local.generated.google.firestore.admin.v1 import firestore_admin_pb2_grpc
from gcp_local.generated.google.firestore.v1 import firestore_pb2_grpc
from gcp_local.services.firestore.storage import FirestoreStorage


class FirestoreServicer(firestore_pb2_grpc.FirestoreServicer):  # type: ignore[misc, name-defined]
    def __init__(self, storage: FirestoreStorage, state_hub: StateHub) -> None:
        self._storage = storage
        self._state_hub = state_hub


class FirestoreAdminServicer(firestore_admin_pb2_grpc.FirestoreAdminServicer):  # type: ignore[misc, name-defined]
    def __init__(self, storage: FirestoreStorage) -> None:
        self._storage = storage
```

`src/gcp_local/services/firestore/storage.py` (skeleton):

```python
"""Firestore storage. CRUD primitives land in Task 6."""

from typing import Protocol


class FirestoreStorage(Protocol):
    async def reset(self) -> None: ...


class InMemoryStorage:
    async def reset(self) -> None:
        return None
```

- [ ] **Step 4: Register the entry point in pyproject.toml**

In `pyproject.toml`, find the `[project.entry-points."gcp_local.services"]` block and add:

```toml
firestore = "gcp_local.services.firestore:FirestoreService"
```

Add `google-cloud-firestore` to the `[project.optional-dependencies] dev` list (the test-only client lib).

- [ ] **Step 5: Reinstall in editable mode**

```bash
.venv/bin/pip install -e ".[dev]"
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
.venv/bin/pytest tests/unit/services/firestore/test_service_scaffold.py -v
```

Expected: 2 passed.

- [ ] **Step 7: Verify firestore appears in health**

```bash
.venv/bin/python -m gcp_local &
sleep 2
curl -s http://localhost:4510/_emulator/services | grep firestore
kill %1 2>/dev/null
```

Expected: `firestore` listed with status `running`.

- [ ] **Step 8: Commit**

```bash
git add src/gcp_local/services/firestore tests/unit/services/firestore pyproject.toml
git commit -m "$(cat <<'EOF'
feat(firestore): service scaffold registered on port 8080

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Names + errors

**Files:**
- Create: `src/gcp_local/services/firestore/names.py`
- Create: `src/gcp_local/services/firestore/errors.py`
- Create: `tests/unit/services/firestore/test_names.py`
- Create: `tests/unit/services/firestore/test_errors.py`

- [ ] **Step 1: Write the names tests**

`tests/unit/services/firestore/test_names.py`:

```python
import pytest

from gcp_local.services.firestore.errors import InvalidName
from gcp_local.services.firestore.names import (
    parse_database_root,
    parse_document_path,
    validate_collection_id,
    validate_document_id,
)


class TestParseDatabaseRoot:
    def test_default_database(self):
        project, database = parse_database_root("projects/p1/databases/(default)")
        assert project == "p1"
        assert database == "(default)"

    def test_named_database(self):
        project, database = parse_database_root("projects/p1/databases/staging")
        assert project == "p1"
        assert database == "staging"

    def test_rejects_garbage(self):
        with pytest.raises(InvalidName):
            parse_database_root("nope")
        with pytest.raises(InvalidName):
            parse_database_root("projects/p/databases/")


class TestParseDocumentPath:
    def test_simple_path(self):
        project, database, path = parse_document_path(
            "projects/p1/databases/(default)/documents/users/alice"
        )
        assert project == "p1"
        assert database == "(default)"
        assert path == "users/alice"

    def test_subcollection_path(self):
        project, database, path = parse_document_path(
            "projects/p/databases/(default)/documents/users/alice/posts/p1"
        )
        assert path == "users/alice/posts/p1"

    def test_rejects_odd_segment_count(self):
        # documents path must have even segment count (collection/doc pairs)
        with pytest.raises(InvalidName):
            parse_document_path("projects/p/databases/(default)/documents/users")


class TestValidateDocumentId:
    @pytest.mark.parametrize("doc_id", ["alice", "alice-1", "a.b", "x_y", "🦀"])
    def test_accepts_valid(self, doc_id):
        validate_document_id(doc_id)

    @pytest.mark.parametrize("doc_id", ["", ".", "..", "a/b", "x" * 1501])
    def test_rejects_invalid(self, doc_id):
        with pytest.raises(InvalidName):
            validate_document_id(doc_id)


class TestValidateCollectionId:
    def test_rejects_reserved_prefix(self):
        with pytest.raises(InvalidName):
            validate_collection_id("__name__")
        with pytest.raises(InvalidName):
            validate_collection_id("__custom__")

    def test_accepts_double_underscore_only_at_one_end(self):
        validate_collection_id("__name")  # not surrounded
        validate_collection_id("name__")
```

- [ ] **Step 2: Write the errors tests**

`tests/unit/services/firestore/test_errors.py`:

```python
import grpc
import pytest

from gcp_local.services.firestore.errors import (
    DocumentAlreadyExists,
    DocumentNotFound,
    FailedPrecondition,
    FirestoreError,
    InvalidArgument,
    InvalidName,
    TransactionAborted,
    TransactionNotFound,
    Unimplemented,
    grpc_error_for,
)


@pytest.mark.parametrize(
    "exc, code",
    [
        (DocumentNotFound("users/alice"), grpc.StatusCode.NOT_FOUND),
        (DocumentAlreadyExists("users/alice"), grpc.StatusCode.ALREADY_EXISTS),
        (InvalidName("bad"), grpc.StatusCode.INVALID_ARGUMENT),
        (InvalidArgument("missing field"), grpc.StatusCode.INVALID_ARGUMENT),
        (FailedPrecondition("update_time mismatch"), grpc.StatusCode.FAILED_PRECONDITION),
        (TransactionAborted("read-set conflict"), grpc.StatusCode.ABORTED),
        (TransactionNotFound("txn-x"), grpc.StatusCode.INVALID_ARGUMENT),
        (Unimplemented("Listen"), grpc.StatusCode.UNIMPLEMENTED),
    ],
)
def test_grpc_error_for_known_exception(exc, code):
    err = grpc_error_for(exc)
    assert err.code() == code
    assert exc.args[0] in err.details()


def test_grpc_error_for_unknown_exception_is_internal():
    err = grpc_error_for(RuntimeError("oops"))
    assert err.code() == grpc.StatusCode.INTERNAL


def test_firestore_error_is_base_class():
    assert issubclass(DocumentNotFound, FirestoreError)
    assert issubclass(InvalidArgument, FirestoreError)
```

- [ ] **Step 3: Run them to verify they fail**

```bash
.venv/bin/pytest tests/unit/services/firestore/test_names.py tests/unit/services/firestore/test_errors.py -v
```

Expected: collection errors / module-not-found.

- [ ] **Step 4: Implement errors.py**

`src/gcp_local/services/firestore/errors.py`:

```python
"""Firestore exception types and gRPC error mapping."""

from dataclasses import dataclass

import grpc


class FirestoreError(Exception):
    """Base for all Firestore service exceptions."""


class DocumentNotFound(FirestoreError):
    pass


class CollectionNotFound(FirestoreError):
    pass


class DatabaseNotFound(FirestoreError):
    pass


class DocumentAlreadyExists(FirestoreError):
    pass


class InvalidName(FirestoreError):
    pass


class InvalidArgument(FirestoreError):
    pass


class FailedPrecondition(FirestoreError):
    pass


class TransactionAborted(FirestoreError):
    pass


class TransactionNotFound(FirestoreError):
    pass


class Unimplemented(FirestoreError):
    pass


@dataclass
class _GrpcError:
    """Lightweight grpc.RpcError stand-in for use in tests + handler return."""
    _code: grpc.StatusCode
    _details: str

    def code(self) -> grpc.StatusCode:
        return self._code

    def details(self) -> str:
        return self._details


_NOT_FOUND = (DocumentNotFound, CollectionNotFound, DatabaseNotFound)
_INVALID = (InvalidName, InvalidArgument, TransactionNotFound)


def grpc_error_for(exc: Exception) -> _GrpcError:
    if isinstance(exc, _NOT_FOUND):
        return _GrpcError(grpc.StatusCode.NOT_FOUND, str(exc))
    if isinstance(exc, DocumentAlreadyExists):
        return _GrpcError(grpc.StatusCode.ALREADY_EXISTS, str(exc))
    if isinstance(exc, _INVALID):
        return _GrpcError(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
    if isinstance(exc, FailedPrecondition):
        return _GrpcError(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
    if isinstance(exc, TransactionAborted):
        return _GrpcError(grpc.StatusCode.ABORTED, str(exc))
    if isinstance(exc, Unimplemented):
        return _GrpcError(grpc.StatusCode.UNIMPLEMENTED, str(exc))
    return _GrpcError(grpc.StatusCode.INTERNAL, "internal error")


def abort_with(context: grpc.ServicerContext, exc: Exception) -> None:
    """Convert a Firestore exception into a grpc.aio context.abort."""
    err = grpc_error_for(exc)
    context.abort(err.code(), err.details())
```

- [ ] **Step 5: Implement names.py**

`src/gcp_local/services/firestore/names.py`:

```python
"""Path parsers and ID validators for Firestore resource names."""

import re

from gcp_local.services.firestore.errors import InvalidName

_DB_ROOT_RE = re.compile(r"^projects/([^/]+)/databases/([^/]+)$")
_DOC_PATH_RE = re.compile(r"^projects/([^/]+)/databases/([^/]+)/documents/(.+)$")
_RESERVED_COLLECTION_RE = re.compile(r"^__.*__$")


def parse_database_root(name: str) -> tuple[str, str]:
    m = _DB_ROOT_RE.match(name)
    if not m:
        raise InvalidName(f"invalid database root: {name}")
    project, database = m.group(1), m.group(2)
    if not project or not database:
        raise InvalidName(f"invalid database root: {name}")
    return project, database


def parse_document_path(name: str) -> tuple[str, str, str]:
    m = _DOC_PATH_RE.match(name)
    if not m:
        raise InvalidName(f"invalid document path: {name}")
    project, database, path = m.group(1), m.group(2), m.group(3)
    segments = path.split("/")
    if len(segments) % 2 != 0:
        raise InvalidName(
            f"document path must have even segment count: {name}"
        )
    for seg in segments[::2]:
        validate_collection_id(seg)
    for seg in segments[1::2]:
        validate_document_id(seg)
    return project, database, path


def validate_document_id(doc_id: str) -> None:
    if not doc_id:
        raise InvalidName("document ID must be non-empty")
    if doc_id in (".", ".."):
        raise InvalidName(f"document ID cannot be {doc_id!r}")
    if "/" in doc_id:
        raise InvalidName("document ID cannot contain '/'")
    if len(doc_id.encode("utf-8")) > 1500:
        raise InvalidName("document ID exceeds 1500 bytes")


def validate_collection_id(coll_id: str) -> None:
    if not coll_id:
        raise InvalidName("collection ID must be non-empty")
    if "/" in coll_id:
        raise InvalidName("collection ID cannot contain '/'")
    if _RESERVED_COLLECTION_RE.match(coll_id):
        raise InvalidName(f"collection ID cannot match __.*__: {coll_id}")
    if len(coll_id.encode("utf-8")) > 1500:
        raise InvalidName("collection ID exceeds 1500 bytes")
```

- [ ] **Step 6: Run the tests**

```bash
.venv/bin/pytest tests/unit/services/firestore/test_names.py tests/unit/services/firestore/test_errors.py -v
```

Expected: all green.

- [ ] **Step 7: Lint + commit**

```bash
.venv/bin/ruff check src/gcp_local/services/firestore tests/unit/services/firestore
.venv/bin/ruff format src/gcp_local/services/firestore tests/unit/services/firestore
git add src/gcp_local/services/firestore tests/unit/services/firestore
git commit -m "$(cat <<'EOF'
feat(firestore): name parsers + error mapping

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Values codec + comparator

**Files:**
- Create: `src/gcp_local/services/firestore/values.py`
- Create: `tests/unit/services/firestore/test_values.py`

The `values.py` module is a single source of truth for converting between the Firestore `Value` proto and Python objects, plus the type-aware `compare(a, b) -> int` function used by orderBy and cursors.

- [ ] **Step 1: Write the test (covers all Value kinds + comparator rules)**

`tests/unit/services/firestore/test_values.py`:

```python
import math

import pytest
from google.protobuf import timestamp_pb2
from google.type import latlng_pb2

from gcp_local.generated.google.firestore.v1 import document_pb2
from gcp_local.services.firestore.values import (
    DocumentReference,
    GeoPoint,
    compare,
    from_proto,
    to_proto,
)


def _v(**kwargs) -> document_pb2.Value:
    return document_pb2.Value(**kwargs)


class TestRoundTrip:
    @pytest.mark.parametrize("py_val, kind", [
        (None, "null_value"),
        (True, "boolean_value"),
        (False, "boolean_value"),
        (42, "integer_value"),
        (3.14, "double_value"),
        (float("nan"), "double_value"),
        ("hello", "string_value"),
        (b"\x00\x01", "bytes_value"),
        ([1, "two", None], "array_value"),
        ({"a": 1, "b": "two"}, "map_value"),
    ])
    def test_round_trip(self, py_val, kind):
        proto = to_proto(py_val)
        assert proto.WhichOneof("value_type") == kind
        if isinstance(py_val, float) and math.isnan(py_val):
            assert math.isnan(from_proto(proto))
        else:
            assert from_proto(proto) == py_val

    def test_geo_point_round_trip(self):
        gp = GeoPoint(lat=37.4, lng=-122.1)
        proto = to_proto(gp)
        assert proto.WhichOneof("value_type") == "geo_point_value"
        assert from_proto(proto) == gp

    def test_reference_round_trip(self):
        ref = DocumentReference(project="p", database="(default)", path="users/a")
        proto = to_proto(ref)
        assert proto.WhichOneof("value_type") == "reference_value"
        assert proto.reference_value == "projects/p/databases/(default)/documents/users/a"
        assert from_proto(proto) == ref


class TestCompareTypeOrdering:
    @pytest.mark.parametrize("a, b", [
        (None, False),
        (False, 0),
        (0, "x"),
        ("x", b"x"),
        (b"x", DocumentReference("p", "(default)", "x/y")),
        (DocumentReference("p", "(default)", "x/y"), GeoPoint(0, 0)),
        (GeoPoint(0, 0), [0]),
        ([0], {"a": 0}),
    ])
    def test_type_order(self, a, b):
        # All across-type comparisons: a < b
        assert compare(a, b) < 0
        assert compare(b, a) > 0


class TestCompareWithinType:
    def test_nan_sorts_smallest_among_numbers(self):
        assert compare(float("nan"), 0) < 0
        assert compare(float("nan"), float("-inf")) < 0
        assert compare(float("nan"), float("nan")) == 0

    def test_int_double_mix(self):
        assert compare(1, 1.5) < 0
        assert compare(2, 1.5) > 0
        assert compare(1, 1.0) == 0

    def test_strings_byte_wise(self):
        assert compare("a", "b") < 0
        assert compare("z", "aa") > 0  # byte-wise, "z" (0x7A) > "a" (0x61)

    def test_arrays_lexicographic(self):
        assert compare([1, 2], [1, 3]) < 0
        assert compare([1], [1, 0]) < 0  # shorter prefix sorts first
        assert compare([1, 2], [1, 2]) == 0

    def test_maps_key_then_value(self):
        # Firestore maps compare by sorted keys, then by value at each key
        assert compare({"a": 1}, {"a": 2}) < 0
        assert compare({"a": 1}, {"b": 1}) < 0  # key "a" < "b"

    def test_geo_point_compare_lat_then_lng(self):
        assert compare(GeoPoint(1.0, 0.0), GeoPoint(2.0, 0.0)) < 0
        assert compare(GeoPoint(1.0, 0.0), GeoPoint(1.0, 1.0)) < 0
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/bin/pytest tests/unit/services/firestore/test_values.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement values.py**

```python
"""Firestore Value <-> Python codec and type-aware comparator.

Type ordering (per Firestore docs):
  null < bool < number < timestamp < string < bytes < ref < geopoint < array < map

Within-type rules:
- numbers: NaN sorts smallest; int and double compared numerically.
- strings: byte-wise UTF-8.
- bytes: byte-wise.
- arrays: lexicographic.
- maps: by sorted keys, then by value at each key.
- geo points: by latitude, then longitude.
- references: by full path string, byte-wise.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from google.protobuf import timestamp_pb2
from google.type import latlng_pb2

from gcp_local.generated.google.firestore.v1 import document_pb2


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lng: float


@dataclass(frozen=True)
class DocumentReference:
    project: str
    database: str
    path: str

    def to_resource_name(self) -> str:
        return f"projects/{self.project}/databases/{self.database}/documents/{self.path}"

    @classmethod
    def from_resource_name(cls, name: str) -> "DocumentReference":
        # Lazy import to avoid a circular dependency: names imports errors,
        # which doesn't import values, but values importing names would
        # invert that direction unnecessarily.
        from gcp_local.services.firestore.names import parse_document_path
        project, database, path = parse_document_path(name)
        return cls(project, database, path)


_TYPE_ORDER = {
    "null_value": 0,
    "boolean_value": 1,
    "_number": 2,
    "timestamp_value": 3,
    "string_value": 4,
    "bytes_value": 5,
    "reference_value": 6,
    "geo_point_value": 7,
    "array_value": 8,
    "map_value": 9,
}


def _kind(py: object) -> str:
    if py is None:
        return "null_value"
    if isinstance(py, bool):
        return "boolean_value"
    if isinstance(py, (int, float)):
        return "_number"
    if isinstance(py, datetime):
        return "timestamp_value"
    if isinstance(py, str):
        return "string_value"
    if isinstance(py, bytes):
        return "bytes_value"
    if isinstance(py, DocumentReference):
        return "reference_value"
    if isinstance(py, GeoPoint):
        return "geo_point_value"
    if isinstance(py, list):
        return "array_value"
    if isinstance(py, dict):
        return "map_value"
    raise TypeError(f"unsupported value type: {type(py).__name__}")


def to_proto(py: object) -> document_pb2.Value:
    k = _kind(py)
    if k == "null_value":
        return document_pb2.Value(null_value=0)
    if k == "boolean_value":
        return document_pb2.Value(boolean_value=py)
    if k == "_number":
        if isinstance(py, bool):  # bool is a subclass of int — already handled above
            return document_pb2.Value(boolean_value=py)
        if isinstance(py, int):
            return document_pb2.Value(integer_value=py)
        return document_pb2.Value(double_value=py)
    if k == "timestamp_value":
        ts = timestamp_pb2.Timestamp()
        ts.FromDatetime(py if py.tzinfo else py.replace(tzinfo=timezone.utc))
        return document_pb2.Value(timestamp_value=ts)
    if k == "string_value":
        return document_pb2.Value(string_value=py)
    if k == "bytes_value":
        return document_pb2.Value(bytes_value=py)
    if k == "reference_value":
        return document_pb2.Value(reference_value=py.to_resource_name())
    if k == "geo_point_value":
        return document_pb2.Value(geo_point_value=latlng_pb2.LatLng(latitude=py.lat, longitude=py.lng))
    if k == "array_value":
        return document_pb2.Value(array_value=document_pb2.ArrayValue(values=[to_proto(x) for x in py]))
    if k == "map_value":
        return document_pb2.Value(map_value=document_pb2.MapValue(fields={k2: to_proto(v) for k2, v in py.items()}))
    raise AssertionError(f"unhandled kind {k}")


def from_proto(value: document_pb2.Value) -> object:
    which = value.WhichOneof("value_type")
    if which is None or which == "null_value":
        return None
    if which == "boolean_value":
        return value.boolean_value
    if which == "integer_value":
        return int(value.integer_value)
    if which == "double_value":
        return float(value.double_value)
    if which == "timestamp_value":
        return value.timestamp_value.ToDatetime().replace(tzinfo=timezone.utc)
    if which == "string_value":
        return value.string_value
    if which == "bytes_value":
        return bytes(value.bytes_value)
    if which == "reference_value":
        return DocumentReference.from_resource_name(value.reference_value)
    if which == "geo_point_value":
        gp = value.geo_point_value
        return GeoPoint(lat=gp.latitude, lng=gp.longitude)
    if which == "array_value":
        return [from_proto(v) for v in value.array_value.values]
    if which == "map_value":
        return {k: from_proto(v) for k, v in value.map_value.fields.items()}
    raise AssertionError(f"unknown value kind {which}")


def _bucket(py: object) -> int:
    return _TYPE_ORDER[_kind(py)]


def compare(a: object, b: object) -> int:  # noqa: C901
    """Total order matching Firestore's documented type ordering."""
    ba, bb = _bucket(a), _bucket(b)
    if ba != bb:
        return -1 if ba < bb else 1
    # Same bucket — within-type comparison
    if a is None and b is None:
        return 0
    if isinstance(a, bool):
        return (a > b) - (a < b)
    if isinstance(a, (int, float)):
        a_nan = isinstance(a, float) and math.isnan(a)
        b_nan = isinstance(b, float) and math.isnan(b)
        if a_nan and b_nan:
            return 0
        if a_nan:
            return -1
        if b_nan:
            return 1
        return (float(a) > float(b)) - (float(a) < float(b))
    if isinstance(a, datetime):
        return (a > b) - (a < b)
    if isinstance(a, str):
        ab, bb_ = a.encode("utf-8"), b.encode("utf-8")
        return (ab > bb_) - (ab < bb_)
    if isinstance(a, bytes):
        return (a > b) - (a < b)
    if isinstance(a, DocumentReference):
        ap, bp = a.to_resource_name(), b.to_resource_name()
        return (ap > bp) - (ap < bp)
    if isinstance(a, GeoPoint):
        c = (a.lat > b.lat) - (a.lat < b.lat)
        if c != 0:
            return c
        return (a.lng > b.lng) - (a.lng < b.lng)
    if isinstance(a, list):
        for x, y in zip(a, b):
            c = compare(x, y)
            if c != 0:
                return c
        return (len(a) > len(b)) - (len(a) < len(b))
    if isinstance(a, dict):
        a_keys = sorted(a.keys())
        b_keys = sorted(b.keys())
        for ak, bk in zip(a_keys, b_keys):
            c = (ak > bk) - (ak < bk)
            if c != 0:
                return c
            c = compare(a[ak], b[bk])
            if c != 0:
                return c
        return (len(a_keys) > len(b_keys)) - (len(a_keys) < len(b_keys))
    raise TypeError(f"unsupported comparison: {type(a).__name__}")
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/services/firestore/test_values.py -v
```

Expected: all green.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check src/gcp_local/services/firestore tests/unit/services/firestore
.venv/bin/ruff format src/gcp_local/services/firestore tests/unit/services/firestore
git add src/gcp_local/services/firestore/values.py tests/unit/services/firestore/test_values.py
git commit -m "$(cat <<'EOF'
feat(firestore): Value codec and type-aware comparator

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Models + InMemoryStorage CRUD

**Files:**
- Create: `src/gcp_local/services/firestore/models.py`
- Modify: `src/gcp_local/services/firestore/storage.py` (replace skeleton)
- Create: `tests/unit/services/firestore/test_models.py`
- Create: `tests/unit/services/firestore/test_storage.py`

- [ ] **Step 1: Write models.py**

```python
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
```

- [ ] **Step 2: Write the storage tests**

`tests/unit/services/firestore/test_storage.py`:

```python
from datetime import datetime, timezone

import pytest

from gcp_local.services.firestore.errors import DocumentNotFound
from gcp_local.services.firestore.models import DocumentRecord
from gcp_local.services.firestore.storage import InMemoryStorage

P, DB = "p1", "(default)"


def _doc(path: str, fields: dict | None = None, version: int = 1) -> DocumentRecord:
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    return DocumentRecord(P, DB, path, fields or {"x": 1}, now, now, version)


@pytest.mark.asyncio
async def test_put_and_get_round_trip():
    s = InMemoryStorage()
    rec = _doc("users/alice")
    await s.put_document(rec)
    fetched = await s.get_document(P, DB, "users/alice")
    assert fetched == rec


@pytest.mark.asyncio
async def test_get_missing_raises():
    s = InMemoryStorage()
    with pytest.raises(DocumentNotFound):
        await s.get_document(P, DB, "users/nope")


@pytest.mark.asyncio
async def test_delete_removes():
    s = InMemoryStorage()
    await s.put_document(_doc("users/alice"))
    await s.delete_document(P, DB, "users/alice")
    with pytest.raises(DocumentNotFound):
        await s.get_document(P, DB, "users/alice")


@pytest.mark.asyncio
async def test_databases_isolated():
    s = InMemoryStorage()
    await s.put_document(_doc("users/alice"))
    rec_other = DocumentRecord(P, "staging", "users/alice", {"x": 99}, _doc("u").create_time, _doc("u").update_time, 1)
    await s.put_document(rec_other)
    a = await s.get_document(P, DB, "users/alice")
    b = await s.get_document(P, "staging", "users/alice")
    assert a.fields == {"x": 1}
    assert b.fields == {"x": 99}


@pytest.mark.asyncio
async def test_next_version_monotonic_per_database():
    s = InMemoryStorage()
    v1 = await s.next_version(P, DB)
    v2 = await s.next_version(P, DB)
    v3 = await s.next_version(P, "staging")
    assert v2 == v1 + 1
    assert v3 == 1  # independent counter per database


@pytest.mark.asyncio
async def test_iter_collection_returns_only_direct_children():
    s = InMemoryStorage()
    await s.put_document(_doc("users/alice"))
    await s.put_document(_doc("users/bob"))
    await s.put_document(_doc("users/alice/posts/p1"))  # subcollection — excluded
    docs = [d async for d in s.iter_collection(P, DB, "users", all_descendants=False)]
    assert sorted(d.path for d in docs) == ["users/alice", "users/bob"]


@pytest.mark.asyncio
async def test_iter_collection_group_finds_all_descendants():
    s = InMemoryStorage()
    await s.put_document(_doc("users/alice/posts/p1"))
    await s.put_document(_doc("teams/eng/posts/q1"))
    await s.put_document(_doc("users/alice"))  # not a "posts" doc
    docs = [d async for d in s.iter_collection(P, DB, "posts", all_descendants=True)]
    assert sorted(d.path for d in docs) == ["teams/eng/posts/q1", "users/alice/posts/p1"]


@pytest.mark.asyncio
async def test_lock_serializes_per_database():
    s = InMemoryStorage()
    async with s.lock(P, DB):
        # acquiring again would deadlock — verify it's a real lock by trying-and-releasing in
        # a separate task with a timeout would be elaborate; instead, just smoke-test that
        # the context manager returns cleanly.
        pass
```

- [ ] **Step 3: Implement storage.py (replace the Task 2 skeleton)**

```python
"""Firestore storage. In-memory implementation; JSON-on-disk lands in Task 16."""

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
        self, project: str, database: str, collection_id: str, *, all_descendants: bool, parent_path: str = ""
    ) -> AsyncIterator[DocumentRecord]: ...
    def lock(self, project: str, database: str) -> "asyncio.Lock": ...
    async def snapshot(self, project: str, database: str) -> None: ...  # no-op for InMemory; fsync for JsonDisk (Task 14)
    # transactions
    async def put_transaction(self, txn: TransactionRecord) -> None: ...
    async def get_transaction(self, project: str, database: str, txn_id: str) -> TransactionRecord | None: ...
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
            collection_segments = segments[:-1:2]
            if all_descendants:
                if collection_id in collection_segments:
                    yield rec
            else:
                # parent path "" matches top-level; otherwise the doc must live exactly under
                # parent_path/<collection_id>
                doc_collection_path = "/".join(segments[:-1])
                expected = (
                    f"{parent_path}/{collection_id}" if parent_path else collection_id
                )
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

    async def get_transaction(self, project: str, database: str, txn_id: str) -> TransactionRecord | None:
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
```

- [ ] **Step 4: Add a quick models test**

`tests/unit/services/firestore/test_models.py`:

```python
from datetime import datetime, timezone

from gcp_local.services.firestore.models import DocumentRecord, IndexRecord, TransactionRecord


def test_document_record_holds_fields():
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    rec = DocumentRecord("p", "(default)", "u/a", {"x": 1}, now, now, 7)
    assert rec.version == 7
    assert rec.fields == {"x": 1}


def test_transaction_record_defaults_empty_read_set_and_writes():
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    txn = TransactionRecord("t-1", "p", "(default)", 5, False, now)
    assert txn.read_set == set()
    assert txn.writes == []
    assert txn.read_time is None


def test_index_record_defaults_state_ready():
    idx = IndexRecord(name="projects/p/.../indexes/i1", fields=[])
    assert idx.state == "READY"
```

- [ ] **Step 5: Run all tests so far**

```bash
.venv/bin/pytest tests/unit/services/firestore/ -v
```

Expected: all green.

- [ ] **Step 6: Lint + commit**

```bash
.venv/bin/ruff check src/gcp_local/services/firestore tests/unit/services/firestore
.venv/bin/ruff format src/gcp_local/services/firestore tests/unit/services/firestore
git add src/gcp_local/services/firestore tests/unit/services/firestore
git commit -m "$(cat <<'EOF'
feat(firestore): records and InMemoryStorage CRUD

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Document CRUD servicer

**Files:**
- Modify: `src/gcp_local/services/firestore/servicer.py`
- Create: `tests/unit/services/firestore/test_servicer_documents.py`

Implement `GetDocument`, `CreateDocument`, `UpdateDocument`, `DeleteDocument`, `BatchGetDocuments`, `ListDocuments`, `ListCollectionIds`. `Commit` and `BatchWrite` and `RunQuery` come in later tasks; leave them as `Unimplemented` stubs that call `abort_with(context, Unimplemented(rpc_name))`.

For each RPC, the test pattern is: spin up an in-process gRPC channel pointing at a test server with `FirestoreServicer` registered, then drive RPCs. See `tests/unit/services/pubsub/test_servicer_topics.py` for the in-process channel fixture pattern.

Key implementation details:

- **`CreateDocument`**: validate name; if `document_id` empty in request, mint a random 20-char ID; check `current_document.exists` precondition (rejects if doc exists). Set `create_time = update_time = now()`; bump version; return the proto Document.
- **`UpdateDocument`**: write the doc; if `update_mask` set, merge selected fields into existing doc (creating if missing unless precondition denies); if `update_mask` empty, replace entirely. Bump version, set `update_time = now()`.
- **`DeleteDocument`**: if `current_document` precondition set, validate; delete; respond with empty `Empty` message (the RPC returns `google.protobuf.Empty`).
- **`GetDocument`**: lookup; raise `DocumentNotFound` if missing.
- **`BatchGetDocuments`**: streams a `BatchGetDocumentsResponse` per requested document — `found`, `missing`, or transaction-related fields. For now (no transaction support yet), only emit `found`/`missing`.
- **`ListDocuments`**: page through `iter_collection(...)` with `all_descendants=False`, applying `parent` from the request and `collection_id` (last segment of `parent`). Honor `page_size` and `page_token` (token = last yielded doc's path).
- **`ListCollectionIds`**: walk all docs under the parent path, collect distinct collection IDs from segments, return sorted.

- [ ] **Step 1: Write the servicer test file**

The test file should cover at least: get-found, get-missing, create-with-id, create-without-id (server-mints), create-conflict (`ALREADY_EXISTS`), update-replace, update-with-mask (partial), update-precondition-fail (`FAILED_PRECONDITION`), delete, delete-precondition-update_time-mismatch, batch-get-mixed (some found / some missing), list-documents-pagination, list-collection-ids.

Each test follows this pattern:

```python
import asyncio

import grpc
import pytest
from google.protobuf import empty_pb2

from gcp_local.core.state_hub import StateHub
from gcp_local.generated.google.firestore.v1 import document_pb2, firestore_pb2, firestore_pb2_grpc
from gcp_local.services.firestore.servicer import FirestoreServicer
from gcp_local.services.firestore.storage import InMemoryStorage


@pytest.fixture
async def firestore_stub():
    storage = InMemoryStorage()
    server = grpc.aio.server()
    port = server.add_insecure_port("[::]:0")
    firestore_pb2_grpc.add_FirestoreServicer_to_server(
        FirestoreServicer(storage=storage, state_hub=StateHub()), server
    )
    await server.start()
    channel = grpc.aio.insecure_channel(f"localhost:{port}")
    stub = firestore_pb2_grpc.FirestoreStub(channel)
    yield stub, storage
    await channel.close()
    await server.stop(grace=0)


@pytest.mark.asyncio
async def test_get_missing_returns_not_found(firestore_stub):
    stub, _ = firestore_stub
    with pytest.raises(grpc.aio.AioRpcError) as ei:
        await stub.GetDocument(firestore_pb2.GetDocumentRequest(
            name="projects/p/databases/(default)/documents/users/nope"
        ))
    assert ei.value.code() == grpc.StatusCode.NOT_FOUND


# ... and so on for each RPC, asserting both happy path and error envelope.
```

Write 12+ tests covering all RPCs and the listed error cases.

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/unit/services/firestore/test_servicer_documents.py -v
```

Expected: failures (RPCs return `UNIMPLEMENTED` from the skeleton).

- [ ] **Step 3: Implement the document RPCs in servicer.py**

Replace the bare-skeleton `FirestoreServicer` with a full implementation. The full code (~300 LOC) follows the structure outlined above. Look at `src/gcp_local/services/secret_manager/servicer.py` for the `try/except FirestoreError → abort_with` boilerplate.

Key helpers to add at the top of the module:

```python
import secrets
from datetime import datetime, timezone

from gcp_local.services.firestore import errors, names
from gcp_local.services.firestore.models import DocumentRecord
from gcp_local.services.firestore.values import from_proto, to_proto


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _mint_doc_id() -> str:
    # 20-char base62-ish — same length and shape as real Firestore auto-IDs
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(20))


def _doc_to_proto(rec: DocumentRecord) -> document_pb2.Document:
    name = f"projects/{rec.project}/databases/{rec.database}/documents/{rec.path}"
    fields = {k: to_proto(v) for k, v in rec.fields.items()}
    proto = document_pb2.Document(name=name, fields=fields)
    proto.create_time.FromDatetime(rec.create_time)
    proto.update_time.FromDatetime(rec.update_time)
    return proto


def _doc_from_proto(proto: document_pb2.Document) -> dict:
    return {k: from_proto(v) for k, v in proto.fields.items()}
```

Each RPC handler wraps its logic in `try/except` and converts `FirestoreError`s through `errors.abort_with(context, exc)`.

- [ ] **Step 4: Run all servicer tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/services/firestore/test_servicer_documents.py -v
```

Expected: all green.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check src/gcp_local/services/firestore tests/unit/services/firestore
.venv/bin/ruff format src/gcp_local/services/firestore tests/unit/services/firestore
git add src/gcp_local/services/firestore/servicer.py tests/unit/services/firestore/test_servicer_documents.py
git commit -m "$(cat <<'EOF'
feat(firestore): document CRUD RPCs

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Field transforms

**Files:**
- Create: `src/gcp_local/services/firestore/engine/__init__.py` (empty)
- Create: `src/gcp_local/services/firestore/engine/transforms.py`
- Create: `tests/unit/services/firestore/test_transforms.py`

`apply_transform(fields, transform_proto, server_time) -> (new_fields, transform_result_value)` mutates a copy of the fields dict per the transform and returns both the resulting fields and the post-transform value (for `WriteResult.transform_results`).

- [ ] **Step 1: Write the test**

```python
import math
from datetime import datetime, timezone

import pytest
from google.protobuf import timestamp_pb2

from gcp_local.generated.google.firestore.v1 import document_pb2, write_pb2
from gcp_local.services.firestore.engine.transforms import apply_transform
from gcp_local.services.firestore.values import to_proto

NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)


def _t(field_path: str, **kwargs) -> write_pb2.DocumentTransform.FieldTransform:
    return write_pb2.DocumentTransform.FieldTransform(field_path=field_path, **kwargs)


class TestServerTimestamp:
    def test_sets_to_server_time_on_missing_field(self):
        fields = {}
        t = _t("created", set_to_server_value=write_pb2.DocumentTransform.FieldTransform.REQUEST_TIME)
        new_fields, result = apply_transform(fields, t, NOW)
        assert new_fields["created"] == NOW

    def test_overwrites_existing(self):
        fields = {"created": datetime(2020, 1, 1, tzinfo=timezone.utc)}
        t = _t("created", set_to_server_value=write_pb2.DocumentTransform.FieldTransform.REQUEST_TIME)
        new_fields, _ = apply_transform(fields, t, NOW)
        assert new_fields["created"] == NOW


class TestIncrement:
    def test_int_plus_int_stays_int(self):
        fields = {"score": 10}
        t = _t("score", increment=to_proto(5))
        new_fields, result = apply_transform(fields, t, NOW)
        assert new_fields["score"] == 15
        assert isinstance(new_fields["score"], int)

    def test_double_anywhere_promotes(self):
        fields = {"score": 10}
        t = _t("score", increment=to_proto(0.5))
        new_fields, _ = apply_transform(fields, t, NOW)
        assert new_fields["score"] == 10.5
        assert isinstance(new_fields["score"], float)

    def test_missing_field_treated_as_zero(self):
        fields = {}
        t = _t("counter", increment=to_proto(1))
        new_fields, _ = apply_transform(fields, t, NOW)
        assert new_fields["counter"] == 1


class TestMaximumMinimum:
    def test_maximum_picks_larger(self):
        fields = {"score": 10}
        t = _t("score", maximum=to_proto(20))
        new_fields, _ = apply_transform(fields, t, NOW)
        assert new_fields["score"] == 20

    def test_minimum_with_missing_uses_value(self):
        fields = {}
        t = _t("score", minimum=to_proto(5))
        new_fields, _ = apply_transform(fields, t, NOW)
        assert new_fields["score"] == 5


class TestArrayUnion:
    def test_appends_only_missing(self):
        fields = {"tags": ["a", "b"]}
        t = _t("tags", append_missing_elements=document_pb2.ArrayValue(
            values=[to_proto("b"), to_proto("c")]))
        new_fields, _ = apply_transform(fields, t, NOW)
        assert new_fields["tags"] == ["a", "b", "c"]

    def test_creates_array_when_missing(self):
        fields = {}
        t = _t("tags", append_missing_elements=document_pb2.ArrayValue(values=[to_proto("x")]))
        new_fields, _ = apply_transform(fields, t, NOW)
        assert new_fields["tags"] == ["x"]


class TestArrayRemove:
    def test_drops_all_matching(self):
        fields = {"tags": ["a", "b", "a", "c"]}
        t = _t("tags", remove_all_from_array=document_pb2.ArrayValue(values=[to_proto("a")]))
        new_fields, _ = apply_transform(fields, t, NOW)
        assert new_fields["tags"] == ["b", "c"]

    def test_no_op_on_missing_field(self):
        fields = {}
        t = _t("tags", remove_all_from_array=document_pb2.ArrayValue(values=[to_proto("a")]))
        new_fields, _ = apply_transform(fields, t, NOW)
        assert "tags" not in new_fields
```

- [ ] **Step 2: Implement transforms.py**

```python
"""Firestore field transforms applied during Commit."""

from datetime import datetime
from typing import Any

from gcp_local.generated.google.firestore.v1 import write_pb2
from gcp_local.services.firestore.errors import InvalidArgument
from gcp_local.services.firestore.values import compare, from_proto


def _set_dotted(fields: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = fields
    for p in parts[:-1]:
        if not isinstance(cur.get(p), dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def _get_dotted(fields: dict[str, Any], path: str) -> Any:
    cur: Any = fields
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return _MISSING
        cur = cur[p]
    return cur


_MISSING = object()


def apply_transform(
    fields: dict[str, Any],
    transform: write_pb2.DocumentTransform.FieldTransform,
    server_time: datetime,
) -> tuple[dict[str, Any], Any]:
    """Apply one field transform to a copy of `fields`. Returns (new_fields, result_value)."""
    new_fields = _deep_copy(fields)
    path = transform.field_path
    which = transform.WhichOneof("transform_type")

    if which == "set_to_server_value":
        if transform.set_to_server_value != write_pb2.DocumentTransform.FieldTransform.REQUEST_TIME:
            raise InvalidArgument("only REQUEST_TIME server values supported")
        _set_dotted(new_fields, path, server_time)
        return new_fields, server_time

    if which == "increment":
        delta = from_proto(transform.increment)
        if not isinstance(delta, (int, float)) or isinstance(delta, bool):
            raise InvalidArgument(f"increment requires numeric value, got {type(delta).__name__}")
        existing = _get_dotted(new_fields, path)
        if existing is _MISSING or not isinstance(existing, (int, float)) or isinstance(existing, bool):
            existing = 0
        result = existing + delta
        # Type promotion: int+int → int; double anywhere → float
        if isinstance(existing, int) and isinstance(delta, int):
            result = int(result)
        else:
            result = float(result)
        _set_dotted(new_fields, path, result)
        return new_fields, result

    if which == "maximum":
        candidate = from_proto(transform.maximum)
        existing = _get_dotted(new_fields, path)
        if existing is _MISSING:
            result = candidate
        else:
            result = candidate if compare(candidate, existing) > 0 else existing
        _set_dotted(new_fields, path, result)
        return new_fields, result

    if which == "minimum":
        candidate = from_proto(transform.minimum)
        existing = _get_dotted(new_fields, path)
        if existing is _MISSING:
            result = candidate
        else:
            result = candidate if compare(candidate, existing) < 0 else existing
        _set_dotted(new_fields, path, result)
        return new_fields, result

    if which == "append_missing_elements":
        elements = [from_proto(v) for v in transform.append_missing_elements.values]
        existing = _get_dotted(new_fields, path)
        if existing is _MISSING or not isinstance(existing, list):
            existing = []
        result = list(existing)
        for e in elements:
            if not any(compare(e, x) == 0 for x in result):
                result.append(e)
        _set_dotted(new_fields, path, result)
        return new_fields, result

    if which == "remove_all_from_array":
        elements = [from_proto(v) for v in transform.remove_all_from_array.values]
        existing = _get_dotted(new_fields, path)
        if existing is _MISSING or not isinstance(existing, list):
            return new_fields, existing if existing is not _MISSING else None
        result = [x for x in existing if not any(compare(x, e) == 0 for e in elements)]
        _set_dotted(new_fields, path, result)
        return new_fields, result

    raise InvalidArgument(f"unsupported transform: {which}")


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _deep_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_copy(v) for v in value]
    return value
```

- [ ] **Step 3: Run, lint, commit**

```bash
.venv/bin/pytest tests/unit/services/firestore/test_transforms.py -v
.venv/bin/ruff check src/gcp_local/services/firestore tests/unit/services/firestore
.venv/bin/ruff format src/gcp_local/services/firestore tests/unit/services/firestore
git add src/gcp_local/services/firestore/engine tests/unit/services/firestore/test_transforms.py
git commit -m "$(cat <<'EOF'
feat(firestore): field transforms (timestamp, increment, max/min, arrayUnion/Remove)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Commit + BatchWrite + StateHub event

**Files:**
- Modify: `src/gcp_local/services/firestore/servicer.py`
- Create: `tests/unit/services/firestore/test_servicer_commit.py`

`Commit` accepts a list of `Write`s. Each `Write` has one of: `update` (a Document with optional `update_mask`), `delete` (a doc resource name), `transform` (a `DocumentTransform` with field transforms only — used inside transactions but accepted standalone too), plus `current_document` precondition and `update_transforms` (list of `FieldTransform`s applied alongside an `update`). `BatchWrite` is the same but writes are independent (no transactional semantics) — return per-write status in `BatchWriteResponse`.

For each successful write, emit a `firestore.document.written` event onto the StateHub: `{project, database, path, operation, update_time}` where `operation` is `"create"`, `"update"`, or `"delete"` depending on whether the doc previously existed and what the write did.

- [ ] **Step 1: Write tests covering**:
  - Single update write returns commit_time + WriteResult.update_time + transform_results.
  - Multi-write Commit applies all atomically; failure of any write causes none to be applied.
  - update_mask merges only the masked fields, leaving others.
  - update_transforms (e.g. SERVER_TIMESTAMP) populates transform_results in order.
  - delete write removes the doc.
  - Precondition exists=true on missing doc → FAILED_PRECONDITION.
  - Precondition update_time mismatch → FAILED_PRECONDITION.
  - StateHub receives `firestore.document.written` for every successful write.
  - BatchWrite: independent failures don't roll back successes (status array reflects per-write outcome).

- [ ] **Step 2: Implement Commit and BatchWrite**

Sketch:

```python
from gcp_local.services.firestore.engine.transforms import apply_transform

async def Commit(self, request, context):
    try:
        project, database = names.parse_database_root(request.database)
        async with self._storage.lock(project, database):
            commit_time = _now()
            results = []
            # Apply all writes in order; if any raises, undo by not persisting.
            staged: list[tuple[str, DocumentRecord | None]] = []  # (path, new_record_or_None_for_delete)
            for write in request.writes:
                rec_or_delete, transform_results = await self._apply_write(
                    project, database, write, commit_time
                )
                staged.append(rec_or_delete)
                results.append(firestore_pb2.WriteResult(
                    update_time=Timestamp().FromDatetime(commit_time) if rec_or_delete[1] else None,
                    transform_results=transform_results,
                ))
            # Persist all staged writes
            for path, new_rec in staged:
                if new_rec is None:
                    await self._storage.delete_document(project, database, path)
                    op = "delete"
                else:
                    existed = await self._storage.has_document(project, database, path)
                    await self._storage.put_document(new_rec)
                    op = "update" if existed else "create"
                await self._state_hub.publish("firestore.document.written", {
                    "project": project,
                    "database": database,
                    "path": path,
                    "operation": op,
                    "update_time": commit_time.isoformat(),
                })
            response = firestore_pb2.CommitResponse(write_results=results)
            response.commit_time.FromDatetime(commit_time)
            return response
    except errors.FirestoreError as exc:
        errors.abort_with(context, exc)
```

(Note: transactional commits with `request.transaction` set go through `engine/transactions.py` in Task 11. For Task 8, just reject any commit with `transaction` set: `Unimplemented("transactional Commit")` — Task 11 swaps it in.)

- [ ] **Step 3: Run, lint, commit**

```bash
.venv/bin/pytest tests/unit/services/firestore/test_servicer_commit.py -v
.venv/bin/ruff check src/gcp_local/services/firestore tests/unit/services/firestore
.venv/bin/ruff format src/gcp_local/services/firestore tests/unit/services/firestore
git add src/gcp_local/services/firestore/servicer.py tests/unit/services/firestore/test_servicer_commit.py
git commit -m "$(cat <<'EOF'
feat(firestore): Commit + BatchWrite with transforms and StateHub events

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Query evaluator — filters

**Files:**
- Create: `src/gcp_local/services/firestore/engine/query.py`
- Create: `tests/unit/services/firestore/test_query_filters.py`

`evaluate_filter(filter_proto, document_record) -> bool`. Top-level dispatch on `filter.WhichOneof("filter_type")`:
- `composite_filter` → recurse over `filters`, combine via `op` (AND short-circuits on False, OR short-circuits on True).
- `field_filter` → look up `field.field_path` on doc fields (dotted path; missing field → False); apply operator over `(doc_value, filter.value)` using `values.compare` and `to_proto/from_proto`.
- `unary_filter` → look up field; check `IS_NAN`/`IS_NOT_NAN`/`IS_NULL`/`IS_NOT_NULL`.

Field path special case: `__name__` resolves to the document's full path (as a `DocumentReference`). This is how Firestore implements the implicit `__name__` orderBy.

- [ ] **Step 1: Write filter tests** covering: EQUAL, LESS_THAN, GREATER_THAN, NOT_EQUAL, ARRAY_CONTAINS, ARRAY_CONTAINS_ANY, IN, NOT_IN (excludes nulls per Firestore docs), unary filters, composite AND, composite OR, missing field returns False for most operators, `__name__` resolves to doc path.

- [ ] **Step 2: Implement `evaluate_filter`**

```python
from typing import Any

from gcp_local.generated.google.firestore.v1 import query_pb2
from gcp_local.services.firestore.errors import InvalidArgument
from gcp_local.services.firestore.models import DocumentRecord
from gcp_local.services.firestore.values import DocumentReference, compare, from_proto

_MISSING = object()


def _field(rec: DocumentRecord, path: str) -> Any:
    if path == "__name__":
        return DocumentReference(rec.project, rec.database, rec.path)
    cur: Any = rec.fields
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return _MISSING
        cur = cur[p]
    return cur


def evaluate_filter(filter_proto: query_pb2.StructuredQuery.Filter, rec: DocumentRecord) -> bool:
    which = filter_proto.WhichOneof("filter_type")
    if which == "composite_filter":
        cf = filter_proto.composite_filter
        op = cf.op
        if op == query_pb2.StructuredQuery.CompositeFilter.AND:
            return all(evaluate_filter(f, rec) for f in cf.filters)
        if op == query_pb2.StructuredQuery.CompositeFilter.OR:
            return any(evaluate_filter(f, rec) for f in cf.filters)
        raise InvalidArgument(f"unknown composite op: {op}")
    if which == "field_filter":
        return _eval_field(filter_proto.field_filter, rec)
    if which == "unary_filter":
        return _eval_unary(filter_proto.unary_filter, rec)
    raise InvalidArgument(f"unknown filter type: {which}")


def _eval_field(ff: query_pb2.StructuredQuery.FieldFilter, rec: DocumentRecord) -> bool:
    op = ff.op
    OP = query_pb2.StructuredQuery.FieldFilter.Operator
    lhs = _field(rec, ff.field.field_path)
    rhs = from_proto(ff.value)
    if lhs is _MISSING:
        # Per Firestore: most comparisons against missing fields are false.
        return False
    if op == OP.EQUAL:
        return compare(lhs, rhs) == 0
    if op == OP.NOT_EQUAL:
        return compare(lhs, rhs) != 0
    if op == OP.LESS_THAN:
        return compare(lhs, rhs) < 0
    if op == OP.LESS_THAN_OR_EQUAL:
        return compare(lhs, rhs) <= 0
    if op == OP.GREATER_THAN:
        return compare(lhs, rhs) > 0
    if op == OP.GREATER_THAN_OR_EQUAL:
        return compare(lhs, rhs) >= 0
    if op == OP.ARRAY_CONTAINS:
        return isinstance(lhs, list) and any(compare(x, rhs) == 0 for x in lhs)
    if op == OP.ARRAY_CONTAINS_ANY:
        if not isinstance(lhs, list) or not isinstance(rhs, list):
            return False
        return any(any(compare(x, y) == 0 for x in lhs) for y in rhs)
    if op == OP.IN:
        if not isinstance(rhs, list):
            return False
        return any(compare(lhs, y) == 0 for y in rhs)
    if op == OP.NOT_IN:
        if not isinstance(rhs, list):
            return False
        # NOT_IN excludes null per Firestore docs
        if lhs is None:
            return False
        return not any(compare(lhs, y) == 0 for y in rhs)
    raise InvalidArgument(f"unknown field op: {op}")


def _eval_unary(uf: query_pb2.StructuredQuery.UnaryFilter, rec: DocumentRecord) -> bool:
    OP = query_pb2.StructuredQuery.UnaryFilter.Operator
    val = _field(rec, uf.field.field_path)
    if val is _MISSING:
        # IS_NULL on a missing field is False; IS_NOT_NULL is also False (field absence ≠ null)
        return False
    if uf.op == OP.IS_NAN:
        return isinstance(val, float) and val != val
    if uf.op == OP.IS_NOT_NAN:
        return not (isinstance(val, float) and val != val)
    if uf.op == OP.IS_NULL:
        return val is None
    if uf.op == OP.IS_NOT_NULL:
        return val is not None
    raise InvalidArgument(f"unknown unary op: {uf.op}")
```

- [ ] **Step 3: Run, lint, commit**

```bash
.venv/bin/pytest tests/unit/services/firestore/test_query_filters.py -v
.venv/bin/ruff check src/gcp_local/services/firestore tests/unit/services/firestore
.venv/bin/ruff format src/gcp_local/services/firestore tests/unit/services/firestore
git add src/gcp_local/services/firestore/engine/query.py tests/unit/services/firestore/test_query_filters.py
git commit -m "$(cat <<'EOF'
feat(firestore): query filter evaluator

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Query evaluator — orderBy, cursors, limit; collection-group

**Files:**
- Modify: `src/gcp_local/services/firestore/engine/query.py`
- Create: `tests/unit/services/firestore/test_query_orderby.py`
- Create: `tests/unit/services/firestore/test_query_cursors.py`
- Create: `tests/unit/services/firestore/test_query_collection_group.py`

Add a top-level `run_query(storage, project, database, structured_query, parent_path) -> list[DocumentRecord]` that does the full pipeline:

1. Determine candidate set from `structured_query.from_`:
   - Each `CollectionSelector(collection_id, all_descendants)` contributes docs via `storage.iter_collection(...)`.
   - Multiple selectors are union-ed.
2. Apply `where` filter via `evaluate_filter`.
3. Build effective orderBy: explicit `order_by` list + implicit additions:
   - For every inequality field in the filter (LT/LE/GT/GE/NE/NOT_IN), if not already in orderBy, append it ASC.
   - If `__name__` not in orderBy, append `__name__ <last_direction>` (matches the last orderBy's direction; defaults to ASC).
4. Sort using `compare` on the orderBy keys, applying ASC/DESC.
5. Apply cursors `start_at`, `end_at` (with their `before` flags translating to startAt/startAfter/endAt/endBefore semantics); cursor values are compared positionally against the orderBy fields.
6. Apply offset.
7. Apply limit; if `limit_type == LAST`, take the last N from the sorted result and reverse for delivery.

- [ ] **Step 1: Write tests** for orderBy (single + multi-field, ASC/DESC, implicit `__name__` tiebreak, implicit on inequality), cursors (startAt-equal, startAfter, endAt, endBefore, partial cursor with fewer values than orderBy fields), limit (positive, limit-to-last), collection-group (`all_descendants=True`).

- [ ] **Step 2: Implement the pipeline** (~150 LOC). Helper:

```python
def _doc_orderby_key(rec, order_by_fields):
    return tuple(_field(rec, f.field.field_path) for f in order_by_fields)


def _compare_keys(a, b, directions):
    for av, bv, direction in zip(a, b, directions):
        c = compare(av, bv)
        if c != 0:
            return -c if direction == "DESCENDING" else c
    return 0
```

- [ ] **Step 3: Run, lint, commit** (combined commit for the three test files + query.py edits)

---

## Task 11: RunQuery + RunAggregationQuery + aggregations

**Files:**
- Modify: `src/gcp_local/services/firestore/servicer.py`
- Create: `src/gcp_local/services/firestore/engine/aggregations.py`
- Create: `tests/unit/services/firestore/test_aggregations.py`
- Create: `tests/unit/services/firestore/test_servicer_run_query.py`

`RunQuery` is a server-streaming RPC. It yields a `RunQueryResponse` per matching document plus a final response with `read_time` set. `RunAggregationQuery` yields a single `RunAggregationQueryResponse` with the aggregated values.

`aggregations.py`:

```python
def aggregate(records: list[DocumentRecord], aggregations: list[StructuredAggregationQuery.Aggregation]) -> dict[str, Any]:
    out = {}
    for agg in aggregations:
        which = agg.WhichOneof("operator")
        alias = agg.alias or which
        if which == "count":
            n = len(records)
            if agg.count.HasField("up_to"):
                n = min(n, agg.count.up_to.value)
            out[alias] = n
        elif which == "sum":
            field_path = agg.sum.field.field_path
            total: float | int = 0
            seen_double = False
            for rec in records:
                v = _field(rec, field_path)
                if isinstance(v, bool) or v is _MISSING:
                    continue
                if isinstance(v, float):
                    seen_double = True
                if isinstance(v, (int, float)):
                    total += v
            out[alias] = float(total) if seen_double else int(total)
        elif which == "avg":
            field_path = agg.avg.field.field_path
            total = 0.0
            count = 0
            for rec in records:
                v = _field(rec, field_path)
                if isinstance(v, bool) or v is _MISSING:
                    continue
                if isinstance(v, (int, float)):
                    total += v
                    count += 1
            out[alias] = (total / count) if count else None
    return out
```

- [ ] **Step 1: Write `test_aggregations.py`** — count empty, count with up_to clamp, sum int+int, sum mixed (float result), avg, avg empty (None), ignore non-numeric / boolean fields.

- [ ] **Step 2: Write `test_servicer_run_query.py`** — RunQuery happy path (multiple docs streamed), RunQuery on empty collection, RunAggregationQuery count, RunAggregationQuery with where filter, RunQuery with cursor pagination across two calls.

- [ ] **Step 3: Implement RunQuery + RunAggregationQuery in servicer.py**

```python
async def RunQuery(self, request, context):
    try:
        parent = request.parent  # projects/p/databases/(default)/documents/<parent_path>
        # parent format: projects/.../documents OR .../documents/users/alice
        # collection group walks happen relative to documents root if all_descendants=True
        # Use names parser for the database root + parent_path
        ...
        records = run_query(self._storage, project, database, request.structured_query, parent_path)
        for rec in records:
            yield firestore_pb2.RunQueryResponse(document=_doc_to_proto(rec))
    except errors.FirestoreError as exc:
        errors.abort_with(context, exc)
```

- [ ] **Step 4: Run, lint, commit.**

---

## Task 12: Transactions + TTL sweeper

**Files:**
- Create: `src/gcp_local/services/firestore/engine/transactions.py`
- Modify: `src/gcp_local/services/firestore/servicer.py` (add BeginTransaction, Rollback; finish Commit-with-transaction; track read_set in RunQuery and Get* RPCs when transaction passed)
- Modify: `src/gcp_local/services/firestore/service.py` (start the TTL sweeper)
- Create: `tests/unit/services/firestore/test_transactions.py`

`engine/transactions.py`:

```python
import asyncio
import secrets
from datetime import datetime, timedelta, timezone

from gcp_local.services.firestore.errors import InvalidArgument, TransactionAborted, TransactionNotFound
from gcp_local.services.firestore.models import TransactionRecord
from gcp_local.services.firestore.storage import FirestoreStorage

_TXN_TTL = timedelta(seconds=60)


async def begin_transaction(storage, project, database, *, read_only=False, read_time=None) -> str:
    txn_id = "txn-" + secrets.token_hex(8)
    snapshot = await storage.current_version(project, database)
    txn = TransactionRecord(
        txn_id=txn_id,
        project=project,
        database=database,
        snapshot_version=snapshot,
        read_only=read_only,
        started_at=datetime.now(tz=timezone.utc),
        read_time=read_time,
    )
    await storage.put_transaction(txn)
    return txn_id


async def record_read(storage, project, database, txn_id: str, path: str) -> None:
    txn = await storage.get_transaction(project, database, txn_id)
    if txn is None:
        raise TransactionNotFound(txn_id)
    txn.read_set.add(path)


async def commit_transaction(storage, project, database, txn_id: str) -> TransactionRecord:
    """Validate that no doc in read_set has changed; raise TransactionAborted if so. Caller drops the txn after applying writes."""
    txn = await storage.get_transaction(project, database, txn_id)
    if txn is None:
        raise TransactionNotFound(txn_id)
    if txn.read_only and txn.writes:
        raise InvalidArgument("read-only transactions cannot have writes")
    for path in txn.read_set:
        try:
            rec = await storage.get_document(project, database, path)
        except Exception:
            continue  # missing now; if it existed when read it would have a higher version
        if rec.version > txn.snapshot_version:
            raise TransactionAborted(f"read-set conflict on {path}")
    return txn


async def rollback(storage, project, database, txn_id: str) -> None:
    await storage.drop_transaction(project, database, txn_id)


class TransactionTtlSweeper:
    def __init__(self, storage: FirestoreStorage, *, interval_s: float = 30.0, ttl: timedelta = _TXN_TTL):
        self._storage = storage
        self._interval = interval_s
        self._ttl = ttl
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._interval)
                now = datetime.now(tz=timezone.utc)
                cutoff = now - self._ttl
                for txn in await self._storage.all_transactions():
                    if txn.started_at < cutoff:
                        await self._storage.drop_transaction(txn.project, txn.database, txn.txn_id)
        except asyncio.CancelledError:
            return
```

Wire the sweeper into `service.py` (`start`/`stop`) like Pub/Sub's `RedeliverySweeper`.

In the servicer:
- `BeginTransaction` → call `begin_transaction`, return token.
- `Rollback` → call `rollback`.
- For `GetDocument`/`BatchGetDocuments`/`RunQuery`/`RunAggregationQuery` with `transaction` set, call `record_read` for every doc visited (including filtered-out ones).
- For `Commit` with `transaction` set: call `commit_transaction` first; if it doesn't raise, apply writes under the lock as in Task 8, then `drop_transaction`.

- [ ] **Step 1: Write `test_transactions.py`** — happy commit, conflict (mutate a read-set doc between begin and commit) raises ABORTED, read-only rejects writes, rollback drops the txn, TTL sweeper drops a stale txn (use a small `interval_s` and `ttl` in the test fixture), read-only transaction with `read_time` filters out a newer doc.

- [ ] **Step 2: Implement** as above.

- [ ] **Step 3: Run, lint, commit.**

---

## Task 13: FirestoreAdmin — index accept-and-ignore

**Files:**
- Modify: `src/gcp_local/services/firestore/servicer.py`
- Create: `tests/unit/services/firestore/test_servicer_admin.py`

Implement on `FirestoreAdminServicer`:
- `CreateIndex` → mint a name (`projects/<p>/databases/<db>/collectionGroups/<g>/indexes/<id>`), store an `IndexRecord`, return a completed `Operation` immediately (the `done=true` form with `response` set to the index proto).
- `ListIndexes`, `GetIndex`, `DeleteIndex` → round-trip stored records.
- All other RPCs (`UpdateField`, `Export*`, `Import*`, `*Database*`, `*Backup*`) → `abort_with(context, Unimplemented(rpc_name))`.

- [ ] **Step 1: Write `test_servicer_admin.py`** covering:
  - CreateIndex returns a completed Operation with the new index name.
  - GetIndex round-trips the stored definition.
  - ListIndexes returns all indexes for the database, paginated by `page_size`.
  - DeleteIndex removes the record.
  - ExportDocuments → UNIMPLEMENTED.
  - CreateDatabase → UNIMPLEMENTED.

- [ ] **Step 2: Implement.**

- [ ] **Step 3: Run, lint, commit.**

---

## Task 14: JsonDiskStorage + persistence

**Files:**
- Modify: `src/gcp_local/services/firestore/storage.py` (add `JsonDiskStorage`)
- Modify: `src/gcp_local/services/firestore/service.py` (wire `JsonDiskStorage` when `ctx.persist`)
- Create: `tests/unit/services/firestore/test_storage_persistence.py`

`JsonDiskStorage` wraps `InMemoryStorage`. Per spec §6.1, snapshots happen at the end of every mutating RPC (one fsync per RPC, not per individual write) — implement this by exposing `snapshot(project, database)` on the storage protocol and calling it from `Commit`/`BatchWrite`/`CreateDocument`/`UpdateDocument`/`DeleteDocument` *after* the write batch is applied under the database lock. `InMemoryStorage.snapshot` is a no-op; `JsonDiskStorage.snapshot` writes the file. This avoids fsync-per-write churn inside multi-write Commits. Snapshots are written to `<state_dir>/firestore/<project>__<database>.json`.

JSON encoding:
- `datetime` → ISO 8601 string.
- `bytes` → base64 string with type tag (`{"__bytes__": "..."}`).
- `DocumentReference` → resource name string with type tag.
- `GeoPoint` → `{"__geopoint__": [lat, lng]}`.
- `dict` and `list` recurse.
- `int`, `float`, `bool`, `str`, `None` → JSON natively.

Look at `src/gcp_local/services/secret_manager/storage.py` for the disk-storage pattern.

On startup: `glob` `<state_dir>/firestore/*.json`, load each, populate `documents` and `indexes`, recompute `versions[(project, database)] = max(record.version)`. Refuse-to-load (with a clear error) if `schema_version` doesn't match.

- [ ] **Step 1: Write tests** — write/reload round-trip across all Value types; multi-database isolation in separate files; `versions` recomputed correctly; corrupt file (`schema_version` mismatch) raises a clean error rather than crashing.

- [ ] **Step 2: Implement `JsonDiskStorage`** as a subclass of `InMemoryStorage` that overrides mutating methods to call `super()` then `_snapshot()`.

- [ ] **Step 3: Run, lint, commit.**

---

## Task 15: Integration tests against the real client

**Files:**
- Create: `tests/integration/test_firestore_integration.py`
- Modify: `tests/integration/conftest.py` (add `firestore` to default service list; extend cross-service health assertion to include firestore)

The `emulator` fixture starts the in-process emulator and exports `FIRESTORE_EMULATOR_HOST=localhost:<port>`. The test file uses `from google.cloud import firestore`.

- [ ] **Step 1: Add the integration tests** covering the §9.2 list from the spec:
  - Set/Get/Update/Delete on a doc with subcollections.
  - `where`/`order_by`/`limit` returning ordered docs.
  - Composite filter (`firestore.And`, `firestore.Or`).
  - Aggregation `.count()`.
  - Collection-group query.
  - `db.transaction()` happy path; deliberate conflict asserts `Aborted`.
  - `firestore.Increment(1)` round-trip.
  - `firestore.SERVER_TIMESTAMP` round-trip.
  - Multi-database isolation (`Client(database="staging")`).
  - Resource-not-found and duplicate-create error mapping.

- [ ] **Step 2: Update `tests/integration/conftest.py`**:
  - Add `firestore` to the default service list and assert the health endpoint reports it `running`.
  - Set the `FIRESTORE_EMULATOR_HOST` env var pointing at the emulator port.

- [ ] **Step 3: Run the integration suite**

```bash
.venv/bin/pytest tests/integration/test_firestore_integration.py -v
```

Expected: all green.

- [ ] **Step 4: Run the full suite**

```bash
.venv/bin/pytest tests/ --ignore=tests/integration/test_docker_image.py
```

Expected: all green (no regressions in the other four services).

- [ ] **Step 5: Commit**

```bash
git add tests/integration
git commit -m "$(cat <<'EOF'
test(firestore): integration coverage against google-cloud-firestore

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: Documentation

**Files:**
- Create: `docs/services/firestore.md`
- Create: `docs/architecture/firestore.md`
- Modify: `README.md`
- Modify: `ROADMAP.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/deployment.md`

- [ ] **Step 1: Write `docs/services/firestore.md`**

Use the Pub/Sub doc (`docs/services/pubsub.md`) as the structural template. Required sections:
- Elevator pitch.
- What's emulated (CRUD, queries with filters/orderBy/cursors, aggregations, transactions, transforms, multi-database, subcollections, collection-group queries, persistence under `PERSIST=1`).
- What's not (Listen, security rules, exports/imports, partition query, composite-index enforcement, document-history retention).
- Connection recipe: `FIRESTORE_EMULATOR_HOST=localhost:8080`.
- Code examples (CRUD, queries, transactions, transforms, multi-database).
- Limits & quirks.

- [ ] **Step 2: Write `docs/architecture/firestore.md`**

Use the Pub/Sub architecture doc as template. Required sections:
- At-a-glance.
- Wire & port (gRPC, 8080).
- Storage model (in-memory dict + JSON-on-disk under PERSIST).
- Request lifecycle (Commit happy path, RunQuery pipeline).
- Query pipeline diagram (the §5.1 pipeline from the spec).
- Transaction state machine (begin → reads record into read_set → commit checks read_set vs current versions → ABORTED or apply writes).
- Value comparator rules.
- Error mapping table.
- Internals-level limitations (carry the §12 list from the spec).

- [ ] **Step 3: Update `README.md`**:
  - Flip Firestore row from Planned → Alpha; fill default port (8080), wire (gRPC), usage and architecture links.
  - Update the "Status" intro: "Five services are implemented today; v1 is feature-complete."
  - Add 8080 to any port-list section.

- [ ] **Step 4: Update `ROADMAP.md`**:
  - Remove Firestore row from "Planned (v1)".
  - Add a new "Per-service follow-ups → Firestore" subsection with: `Listen` streaming RPC, security rules, exports/imports/backups, PartitionQuery, composite-index enforcement, document-history retention, FirestoreAdmin field-level operations (TTL).

- [ ] **Step 5: Update `CHANGELOG.md`**:
  - `[Unreleased] ### Added` entry: "Firestore (Native mode) emulator: CRUD, structured queries with filters/orderBy/cursors/limit, aggregations (count/sum/avg), batched commits, field transforms (SERVER_TIMESTAMP, increment, arrayUnion/Remove, max/min), optimistic-concurrency transactions with TTL sweeping, multi-database namespacing, FirestoreAdmin index accept-and-ignore, JSON-on-disk persistence under PERSIST=1. `Listen`, security rules, exports/imports, and PartitionQuery deferred."

- [ ] **Step 6: Update `docs/deployment.md`** — add 8080 to the default-ports table.

- [ ] **Step 7: Run the final suite + linters one more time**

```bash
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format src/ tests/
.venv/bin/pytest tests/ --ignore=tests/integration/test_docker_image.py
```

- [ ] **Step 8: Build the Docker image and verify firestore container becomes healthy** (per CLAUDE.md "Docker test when changing imports / deps")

```bash
docker build -f docker/Dockerfile -t gcp-local:dev .
docker run --rm -d -p 4510:4510 -p 8080:8080 -e SERVICES=firestore --name gcp-local-fs-test gcp-local:dev
sleep 3
curl -s http://localhost:4510/_emulator/services | grep firestore
docker stop gcp-local-fs-test
```

Expected: `firestore` listed and `running`.

- [ ] **Step 9: Commit docs and prepare PR**

```bash
git add docs README.md ROADMAP.md CHANGELOG.md docs/deployment.md
git commit -m "$(cat <<'EOF'
docs(firestore): user + architecture docs, README/ROADMAP/CHANGELOG updates

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"

git push -u origin feat/firestore-service
```

- [ ] **Step 10: Open the PR**

```bash
gh pr create --title "feat(firestore): v1 Native-mode service" --body "$(cat <<'EOF'
## Summary

- New Firestore (Native mode) emulator on port 8080 — fifth and final v1 service.
- Implements: CRUD (Get/Create/Update/Delete/BatchGet/ListDocuments/ListCollectionIds), structured queries (filters/orderBy/cursors/limit), aggregations (count/sum/avg), batched commits, field transforms (SERVER_TIMESTAMP, Increment, arrayUnion/arrayRemove, max/min), optimistic-concurrency transactions with 60s TTL, multi-database namespacing, FirestoreAdmin index accept-and-ignore, JSON-on-disk persistence under PERSIST=1.
- Deferred to follow-ups: `Listen` streaming RPC, security rules, exports/imports/backups, PartitionQuery, composite-index enforcement, document-history retention.

## Size override

This PR is intentionally larger than the project's <500 LOC ceiling. The components (servicer, query evaluator, transforms, transactions) are tightly interdependent — the official Python client uses field transforms on common idiomatic writes (`Increment`, `SERVER_TIMESTAMP`), so a CRUD-only first PR would not pass the "client works unchanged" success criterion. See spec §10.

## Spec

`docs/superpowers/specs/2026-05-01-gcp-local-firestore-design.md`

## Test plan

- [ ] `.venv/bin/pytest tests/unit/services/firestore/ -v` — green
- [ ] `.venv/bin/pytest tests/integration/test_firestore_integration.py -v` — green
- [ ] `.venv/bin/pytest tests/ --ignore=tests/integration/test_docker_image.py` — green (no regressions)
- [ ] `docker build -f docker/Dockerfile -t gcp-local:dev .` — succeeds
- [ ] `docker run -e SERVICES=firestore` — firestore service reports `running`
- [ ] CI green

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Definition-of-Done audit (run before merging)

Per `CLAUDE.md`, walk both checklists and report:

**Docs:**
- [x] `docs/services/firestore.md` — created.
- [x] `docs/architecture/firestore.md` — created.
- [x] `README.md` — Firestore row flipped Planned → Alpha; port 8080 added.
- [x] `ROADMAP.md` — Firestore removed from "Planned (v1)"; deferred items added under "Per-service follow-ups → Firestore".
- [x] `CHANGELOG.md` — `[Unreleased] ### Added` entry.
- [x] `docs/deployment.md` — port 8080 added.
- [x] Spec `2026-05-01-gcp-local-firestore-design.md` — no annotations needed (nothing it said is reversed by this PR; deferred features are deferred as intended).
- [x] No dangling `# TODO` comments.
- [x] `pyproject.toml` — `google-cloud-firestore` is dev-only (test client); no runtime deps added.

**Tests:**
- [x] Unit tests for every helper (names, values, transforms, query, aggregations, transactions, storage).
- [x] Integration test driving `google-cloud-firestore` end-to-end.
- [x] Error paths (NOT_FOUND, ALREADY_EXISTS, FAILED_PRECONDITION, ABORTED, INVALID_ARGUMENT, UNIMPLEMENTED).
- [x] Default behavior verified when optional flags absent.
- [x] Full suite green.
- [x] Docker image rebuilt with firestore service, container reports healthy.

**Quality gates:**
- [x] `ruff check src/ tests/` clean.
- [x] `ruff format src/ tests/` clean.
- [x] `pytest tests/ --ignore=tests/integration/test_docker_image.py` green.
- [x] `gh pr checks <N>` green before declaring CI green.
