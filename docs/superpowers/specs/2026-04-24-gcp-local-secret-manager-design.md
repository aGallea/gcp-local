# gcp-local — Secret Manager Service Design

**Date:** 2026-04-24
**Status:** Draft for review
**Scope:** Second GCP service — Secret Manager. First gRPC service in the project.
**Core design:** [2026-04-24-gcp-local-core-design.md](./2026-04-24-gcp-local-core-design.md)

## 1. Overview

This document specifies the **Secret Manager emulator** — the second real service in `gcp-local` and the first that speaks gRPC. Success criterion: the official `google-cloud-secret-manager` Python client library works unchanged against the emulator for the full secret / version lifecycle.

The spec also defines the **core-framework extensions** required to host gRPC services for the first time. Those extensions (grpc runtime dependency, `grpc_error` helper, per-service gRPC server pattern) unblock Pub/Sub and Firestore later.

## 2. Scope (v1)

### In scope

- **Secret lifecycle:** `CreateSecret`, `GetSecret`, `ListSecrets`, `UpdateSecret` (labels + annotations only), `DeleteSecret`
- **Version lifecycle:** `AddSecretVersion`, `GetSecretVersion`, `ListSecretVersions`, `AccessSecretVersion`, `EnableSecretVersion`, `DisableSecretVersion`, `DestroySecretVersion`
- **`"latest"` alias** on version access → resolves to the highest-id version in `ENABLED` state
- **Payload checksums:** server computes `data_crc32c` on `AddSecretVersion`; clients use it to verify round-trips
- **Labels and annotations** on secret resource
- **Project namespacing:** `projects/<project>/secrets/<name>` is the primary key; different projects can hold same secret name independently
- **gRPC error shapes** matching real Secret Manager responses
- **In-memory and on-disk storage backends** (opt-in disk via `PERSIST=1`)

### Out of v1 (deferred)

- **IAM** (`GetIamPolicy`, `SetIamPolicy`, `TestIamPermissions`) — no auth model in the emulator
- **Rotation config** (`rotation`, `topics`) — uncommon in local-dev use
- **CMEK** (customer-managed encryption keys) — requires a KMS emulator
- **Replication config actions** — `replication` accepted in requests and stored as-is; not acted on
- **Secret version `expire_time` / TTL** — deferred
- **REST API surface** — `google-cloud-secret-manager` defaults to gRPC; REST not covered in v1

## 3. Core framework extensions

This is the first gRPC service, so the core framework picks up a small set of additions. They live in the core (not the secret_manager package) so Pub/Sub and Firestore can reuse them.

### 3.1 New runtime dependencies

Added to `pyproject.toml`:
- `grpcio>=1.60`
- `googleapis-common-protos>=1.63`

### 3.2 `grpc_error` helper

A new helper in `src/gcp_local/core/errors.py`:

```python
import grpc
from google.rpc import error_details_pb2, status_pb2

@dataclass
class GrpcError(Exception):
    code: grpc.StatusCode
    message: str
    reason: str | None = None  # optional extended reason for error_details
```

Plus `async def abort_with(context: grpc.aio.ServicerContext, err: GrpcError) -> NoReturn:` that calls `context.abort(err.code, err.message)` with standard error-details encoding. Services import this to keep error shapes uniform.

### 3.3 Per-service gRPC server pattern

Each gRPC service owns its own `grpc.aio.Server`. The core does not host a shared gRPC server — client libraries expect canonical per-service ports, and sharing a port across services would break plug-and-play.

Pattern captured (informally, not as a base class) by the Secret Manager service and reused by later gRPC services:

```python
async def start(self, ctx: Context) -> None:
    port = ctx.port_overrides.get(self.name, _DEFAULT_PORT)
    self._server = grpc.aio.server()
    self._server.add_insecure_port(f"[::]:{port}")
    servicer = SecretManagerServicer(storage=self._storage, state_hub=ctx.state_hub)
    add_SecretManagerServiceServicer_to_server(servicer, self._server)
    await self._server.start()
```

### 3.4 Using pre-generated Google stubs

We **do not** ship `.proto` files or run `grpcio-tools` in the build. Instead, we subclass the `SecretManagerServiceServicer` already shipped inside `google-cloud-secret-manager`:

```python
from google.cloud.secretmanager_v1.services.secret_manager_service.transports.base import (
    SecretManagerServiceTransport,
)
# Actual servicer import path is the generated pb2_grpc module inside the installed package:
from google.cloud.secretmanager_v1.proto import service_pb2_grpc
```

The exact import path is finalized during implementation (install the package, `grep -r SecretManagerServiceServicer` under `site-packages`). The point is: the servicer base class comes from the installed client library; we implement its methods.

This keeps us wire-compatible with whatever version of the client we test against, and avoids a `.proto` compilation step at build time.

**`google-cloud-secret-manager` is moved from dev-only to a runtime dependency** for this reason. It is the least-bad option for bringing gRPC protos into the server process; a cleaner long-term solution is regenerating from vendored `.proto` files, which we can do in v2 if the client-library dependency becomes a problem.

## 4. Service architecture

### 4.1 Package layout

```
src/gcp_local/services/secret_manager/
  __init__.py                  # exports SecretManagerService
  service.py                   # SecretManagerService (implements core Service protocol)
  servicer.py                  # SecretManagerServicer — gRPC handler
  models.py                    # SecretRecord, SecretVersion, SecretVersionState
  storage.py                   # Storage protocol + InMemoryStorage + DiskStorage
  names.py                     # resource-name parser/builder
  errors.py                    # maps internal exceptions to grpc_error calls
```

### 4.2 Port

Default **8086** (as noted in the core design). Override via `SECRET_MANAGER_EMULATOR_PORT` env var through the existing `port_overrides` machinery.

### 4.3 Connection from client code

The official client does not read an emulator env var. The README documents the connection recipe:

```python
from google.cloud import secretmanager_v1
from google.cloud.secretmanager_v1.services.secret_manager_service.transports.grpc import (
    SecretManagerServiceGrpcTransport,
)
import grpc

channel = grpc.insecure_channel("localhost:8086")
client = secretmanager_v1.SecretManagerServiceClient(
    transport=SecretManagerServiceGrpcTransport(channel=channel)
)
```

## 5. Data model

### 5.1 Resource names

Shape:
- Secret: `projects/<project>/secrets/<secret_id>`
- Version: `projects/<project>/secrets/<secret_id>/versions/<version_id>`

Where `<version_id>` is either an integer string (`"1"`, `"2"`, …) or the literal `"latest"`.

`secret_id` allowed characters (per real SM): `[A-Za-z0-9_-]`, length 1–255. We validate on create and reject malformed names with `INVALID_ARGUMENT`.

### 5.2 Secret record

```python
class SecretVersionState(str, Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    DESTROYED = "DESTROYED"


@dataclass
class SecretVersion:
    id: int
    state: SecretVersionState
    create_time: str  # RFC3339
    destroy_time: str | None
    payload: bytes        # zeroed on destroy
    data_crc32c: int      # int64 of google-crc32c


@dataclass
class SecretRecord:
    project: str
    secret_id: str
    labels: dict[str, str]
    annotations: dict[str, str]
    create_time: str
    versions: list[SecretVersion]  # sorted by id ascending
```

### 5.3 Version ID allocation

On `AddSecretVersion`, the new version's `id` is `max(existing_ids) + 1`, or `1` if none exist. IDs are monotonic per secret and are never reused (including after `DestroySecretVersion`).

### 5.4 `"latest"` alias

`AccessSecretVersion` and `GetSecretVersion` accept `"latest"` and resolve to the **highest-id version whose state is `ENABLED`**. Disabled and destroyed versions are skipped. If no enabled version exists, return `FAILED_PRECONDITION` (matches real SM).

### 5.5 State transitions

| From \ To | ENABLED | DISABLED | DESTROYED |
|---|---|---|---|
| **ENABLED** | no-op | allowed | allowed |
| **DISABLED** | allowed | no-op | allowed |
| **DESTROYED** | `FAILED_PRECONDITION` | `FAILED_PRECONDITION` | no-op |

`DestroySecretVersion` additionally:
- Sets `payload = b""`
- Sets `destroy_time = now()`

## 6. Storage backends

Same pattern as GCS: a `SecretManagerStorage` Protocol with two implementations.

### 6.1 Protocol

```python
class SecretManagerStorage(Protocol):
    async def create_secret(self, record: SecretRecord) -> None: ...
    async def get_secret(self, project: str, secret_id: str) -> SecretRecord: ...
    async def list_secrets(self, project: str, *, page_size: int | None = None, page_token: str | None = None) -> tuple[list[SecretRecord], str | None]: ...
    async def update_secret(self, record: SecretRecord) -> None: ...
    async def delete_secret(self, project: str, secret_id: str) -> None: ...

    async def add_version(self, project: str, secret_id: str, payload: bytes) -> SecretVersion: ...
    async def get_version(self, project: str, secret_id: str, version_id: int) -> SecretVersion: ...
    async def list_versions(self, project: str, secret_id: str, *, page_size: int | None = None, page_token: str | None = None) -> tuple[list[SecretVersion], str | None]: ...
    async def update_version_state(self, project: str, secret_id: str, version_id: int, new_state: SecretVersionState) -> SecretVersion: ...

    async def reset(self) -> None: ...
```

Exceptions: `SecretNotFound`, `SecretAlreadyExists`, `VersionNotFound`, `InvalidStateTransition`, `NoEnabledVersion` (for `"latest"` miss).

### 6.2 In-memory

`dict[tuple[project, secret_id], SecretRecord]`. Versions sorted by id.

### 6.3 On-disk

Single file at `/data/secret_manager.json`:

```json
{
  "secrets": [
    {
      "project": "my-project",
      "secret_id": "db-password",
      "labels": {"env": "dev"},
      "annotations": {},
      "create_time": "2026-04-24T10:00:00.000Z",
      "versions": [
        {
          "id": 1,
          "state": "ENABLED",
          "create_time": "2026-04-24T10:05:00.000Z",
          "destroy_time": null,
          "payload_b64": "c2VjcmV0",
          "data_crc32c": 1234567890
        }
      ]
    }
  ]
}
```

Write-through: every mutation rewrites the entire file (secrets are small, simple, and this avoids partial-update consistency bugs). Load on first access via lazy init in `DiskStorage.__init__`.

## 7. gRPC servicer

### 7.1 Method mapping

| RPC | Servicer method | Notes |
|---|---|---|
| `CreateSecret` | `async def CreateSecret(request, context)` | Validates name, creates empty secret |
| `GetSecret` | — | Returns secret with labels/annotations |
| `ListSecrets` | — | Pagination via `page_size` + `page_token` |
| `UpdateSecret` | — | Applies `update_mask` (labels, annotations); ignores rotation/CMEK silently |
| `DeleteSecret` | — | Respects `etag` if provided (compared against secret's last-updated hash) |
| `AddSecretVersion` | — | Computes crc32c; returns new version record |
| `GetSecretVersion` | — | Accepts `latest` alias |
| `ListSecretVersions` | — | Includes destroyed versions (with cleared payload) |
| `AccessSecretVersion` | — | Returns payload bytes; rejects disabled/destroyed versions |
| `EnableSecretVersion` / `DisableSecretVersion` / `DestroySecretVersion` | — | State transitions per §5.5 |

Unimplemented methods (IAM, Get/Set/TestIamPermissions) return `UNIMPLEMENTED` through a default handler.

### 7.2 Error mapping

All servicer methods catch internal storage exceptions and convert them via `grpc_error`:

| Internal exception | gRPC status |
|---|---|
| `SecretNotFound` / `VersionNotFound` | `NOT_FOUND` |
| `SecretAlreadyExists` | `ALREADY_EXISTS` |
| `InvalidStateTransition` | `FAILED_PRECONDITION` |
| `NoEnabledVersion` (on `"latest"` access with no enabled versions) | `FAILED_PRECONDITION` |
| Malformed resource name | `INVALID_ARGUMENT` |
| Any uncaught → `INTERNAL` | |

### 7.3 Payload checksum

`AddSecretVersion` computes `google_crc32c.value(payload)` and stores as `int64`. The response's `SecretVersion` proto carries `data_crc32c` in its `AddSecretVersionResponse`. Clients use it for round-trip integrity checks — the test suite explicitly asserts clients see the right checksum.

## 8. Testing

### 8.1 Unit tests

- `test_names.py` — parse/build/validate resource names, reject malformed secret IDs
- `test_storage_memory.py` + `test_storage_disk.py` — CRUD for secrets + versions, state transitions, `"latest"` alias, pagination, reset (symmetric test suite parameterized over both backends)
- `test_errors.py` — exception → gRPC status mapping
- `test_servicer.py` — servicer methods directly, using an in-memory channel (grpcio's `grpc.aio.server` + a pair of in-process client stubs) to avoid real socket I/O

### 8.2 Integration tests

Real `google-cloud-secret-manager` client driving the emulator over a real gRPC socket. Single file `test_secret_manager_integration.py` covering:

- `create_secret(...)` → `get_secret(...)` → round-trip labels
- `add_secret_version(payload=...)` → `access_secret_version(name="...versions/latest")` → payload match + crc32c check
- `list_secrets(...)` → new secret listed
- Multi-version path: add v1, add v2, access latest → v2 payload; `access_secret_version(name="...versions/1")` → v1 payload
- `disable_secret_version` → `access` on that version → `FailedPrecondition`
- `destroy_secret_version` → `access` → `FailedPrecondition` + version payload is empty
- `update_secret(secret=..., update_mask=FieldMask(paths=["labels"]))` → labels change, other fields untouched
- `delete_secret(...)` → subsequent `get_secret` → `NotFound`

Test fixture extends the existing `emulator` fixture pattern: boots the emulator in-process with both `gcs` and `secret_manager` registered (so GCS tests still pass), opens an `grpc.insecure_channel("localhost:<port>")` for Secret Manager, constructs a client with that transport.

### 8.3 Core integration test update

The existing core integration test (`tests/integration/test_core_end_to_end.py`) should assert both services show up in `/_emulator/services` after this work. Minor test touch-up.

## 9. HTTP / admin surface

The admin API (`/_emulator/health`, `/services`, `/reset`) is REST-only and unaffected. `Service.health()` returns the same `HealthStatus` shape. Reset is handled by `SecretManagerStorage.reset()` plus clearing any in-memory version id generator state.

## 10. Dependencies summary

**New runtime (added in pyproject.toml):**
- `grpcio>=1.60`
- `googleapis-common-protos>=1.63`
- `google-cloud-secret-manager>=2.18` — moved from dev-only to runtime (we import its generated pb2_grpc stubs at server start)

**New dev:**
- None beyond what's already in `[project.optional-dependencies].dev`

## 11. Open items

Handled with explicit defaults; noted here for awareness:

- **`etag` semantics on `UpdateSecret` and `DeleteSecret`:** real SM returns an `etag` in response bodies; clients may echo it back in subsequent requests for optimistic concurrency. **Default: accept any etag on write, return a computed etag (SHA1 of record JSON) on read.** This matches common client usage without full optimistic-concurrency enforcement.
- **`UpdateSecret` fields outside `update_mask`:** **Default: ignore.** Real SM does the same.
- **Pagination:** **Default: `page_size` caps at 250; `page_token` is an opaque base64-encoded `secret_id` cursor.**
- **Running the `google-cloud-secret-manager` dependency as a runtime dep:** a necessary evil for importing generated stubs; if the dependency size or version pinning becomes problematic, v2 should vendor the `.proto` files and generate stubs in our build.

## 12. Non-goals recap

This spec does not describe: IAM policies on secrets, rotation config, CMEK, TTL, replication mechanics, the REST transport, or any cross-region behavior.
