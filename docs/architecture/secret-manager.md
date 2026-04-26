# Secret Manager — internals

## At a glance

The Secret Manager emulator is a pure gRPC service that exposes the full secret-and-version
lifecycle defined by the Google Cloud Secret Manager v1 API. It implements:

- **Secret CRUD** — `CreateSecret`, `GetSecret`, `ListSecrets`, `UpdateSecret`, `DeleteSecret`
- **Version lifecycle** — `AddSecretVersion`, `GetSecretVersion`, `ListSecretVersions`,
  `AccessSecretVersion`
- **State transitions** — `EnableSecretVersion`, `DisableSecretVersion`, `DestroySecretVersion`

Storage is either all-in-memory (the default) or write-through JSON on disk when the container
is started with `PERSIST=1`. Payload checksums (`data_crc32c`) are computed on `AddSecretVersion`
using `google-crc32c` and returned on `AccessSecretVersion` for client-side verification. IAM,
CMEK, rotation schedules, and replication-routing configuration are out of scope for v1. For a
usage-oriented guide (client connection recipe, environment variables), see
[docs/services/secret-manager.md](../services/secret-manager.md).

---

## Wire & port

The service listens on gRPC port **8086** by default.

Unlike GCS (which reads `STORAGE_EMULATOR_HOST`) or BigQuery (which reads
`BIGQUERY_EMULATOR_HOST`), there is **no `SECRET_MANAGER_EMULATOR_HOST` environment variable**.
The official `google-cloud-secret-manager` client does not consult one. Callers must redirect
explicitly by either:

- Setting `client_options=ClientOptions(api_endpoint="localhost:8086")` with
  `transport="grpc"`, or
- Constructing a `SecretManagerServiceGrpcTransport` over a `grpc.insecure_channel`.

The gcp-local admin HTTP API runs on the shared **port 4510** (`GCP_LOCAL_ADMIN_PORT`) and
provides the standard `/health`, `/services`, and `/reset` endpoints used by all services.

---

## gRPC server setup

`SecretManagerService.start()` in `service.py` creates a **dedicated** `grpc.aio.Server`
instance. Each gRPC service in gcp-local owns its own server so that client libraries connect
to canonical per-service ports without any internal routing or multiplexing.

The startup sequence is:

1. Resolve the port: `ctx.port_overrides.get("secret_manager", 8086)`.
2. Create the server: `grpc.aio.server()`.
3. Bind: `server.add_insecure_port(f"[::]:{port}")`.
4. Instantiate `SecretManagerServicer(storage=self._storage)`.
5. Register: `service_pb2_grpc.add_SecretManagerServiceServicer_to_server(servicer, server)`.
6. Start: `await server.start()`.

`stop()` calls `await server.stop(grace=None)`, which drops in-flight calls immediately rather
than draining them. `health()` returns `HealthStatus(ok=True)` only after a successful `start()`
has completed.

The `_make_storage` helper, also in `service.py`, branches on `ctx.persist`: when persistence is
enabled it creates the `<data_dir>/secret_manager/` directory and returns a `DiskStorage`
instance; otherwise it returns `InMemoryStorage`.

---

## Vendored proto stubs

Rather than shipping `.proto` files or running `protoc` at install time, gcp-local ships
**pre-generated Python stubs** checked into the repository under:

```
src/gcp_local/generated/google/cloud/secretmanager/v1/
    __init__.py
    resources_pb2.py   # Secret, SecretVersion, SecretPayload messages
    resources_pb2.pyi  # type stubs
    resources_pb2_grpc.py
    service_pb2.py     # request/response wrapper messages
    service_pb2.pyi
    service_pb2_grpc.py  # SecretManagerServiceServicer base class + registration helper
```

Regeneration is performed by `scripts/gen_protos.sh`, which:

1. Runs `grpc_tools.protoc` against `.proto` sources in `protos/` with `googleapis-common-protos`
   on the proto path.
2. Post-processes the generated files with a small Python snippet that rewrites all
   `from google.cloud.secretmanager.v1 import ...` lines to
   `from gcp_local.generated.google.cloud.secretmanager.v1 import ...` so imports resolve
   inside the package tree.

The upstream proto source is the canonical
`google/cloud/secretmanager/v1/resources.proto` and `service.proto` from the Google APIs
repository. Vendoring keeps the build hermetic (no `protoc` at install time), makes import paths
auditable, and ensures proto changes are visible in code review diffs.

---

## Storage model

Two interchangeable backends both implement the `SecretManagerStorage` `Protocol` from
`storage.py`. `service.py` selects the backend once at startup; all servicer code is
backend-agnostic.

### InMemoryStorage

State lives in a single `dict[tuple[str, str], SecretRecord]` keyed by `(project, secret_id)`.
Each `SecretRecord` carries its list of `SecretVersion` objects inline. Version IDs are
monotonically incrementing integers starting at `1`, computed as
`max(v.id for v in existing_versions, default=0) + 1`. An `asyncio.Lock` serialises every
mutation that reads-then-writes to prevent ID collisions under concurrent `AddSecretVersion`
calls.

### DiskStorage

State is written to a single JSON file at
`<data_dir>/secret_manager/secret_manager.json`. Every mutation follows a
**load → mutate → save** cycle under an `asyncio.Lock`. Secret payloads are base64-encoded in
the JSON; CRC32c checksums are stored alongside them. On `reset()`, the file is deleted
entirely (rather than emptied) so disk usage is reclaimed.

### Common interface

Both backends expose the same twelve async methods: `create_secret`, `get_secret`,
`list_secrets`, `update_secret`, `delete_secret`, `add_version`, `get_version`,
`list_versions`, `update_version_state`, and `reset`. Pagination is handled by the shared
`_paginate` helper, which caps page size at 250 and uses base64-encoded cursor tokens.

---

## Resource names

The emulator enforces the same two resource-name shapes as the real Secret Manager:

| Resource | Shape |
|---|---|
| Secret | `projects/<project>/secrets/<secret_id>` |
| Version | `projects/<project>/secrets/<secret_id>/versions/<version_id>` |

`names.py` validates both shapes using anchored regular expressions:

```python
_SECRET_RE  = re.compile(r"^projects/([^/]+)/secrets/([^/]+)$")
_VERSION_RE = re.compile(r"^projects/([^/]+)/secrets/([^/]+)/versions/([^/]+)$")
```

Any non-matching input raises `InvalidResourceName` (a `ValueError` subclass), which the
servicer catches and converts to a `INVALID_ARGUMENT` abort.

`secret_id` undergoes a second validation pass via `validate_secret_id`:
it must match `[A-Za-z0-9_-]{1,255}`. The `version_id` segment is either a decimal integer
string or the literal `"latest"`. The `"latest"` alias is resolved at request time by
`SecretRecord.highest_enabled_version()`, which scans the version list and returns the entry
with the highest integer `id` whose `state` is `ENABLED`.

---

## Request lifecycle: AccessSecretVersion

`AccessSecretVersion` is the most-exercised call. Here is the full path from wire to response:

1. **Name parsing** — `parse_version_name(request.name)` splits the name into
   `(project, sid, vid_raw)`. If the name does not match `_VERSION_RE`, it aborts
   with `INVALID_ARGUMENT`.

2. **`"latest"` branch** — if `vid_raw == "latest"`:
   - Load the `SecretRecord` via `storage.get_secret(project, sid)`.
     `SecretNotFound` → `NOT_FOUND`.
   - Call `rec.highest_enabled_version()`. If the result is `None` (no enabled version),
     abort with `FAILED_PRECONDITION`.

3. **Numeric-ID branch** — otherwise cast `vid_raw` to `int` (non-integer → `INVALID_ARGUMENT`)
   and call `storage.get_version(project, sid, vid)`.
   `SecretNotFound` or `VersionNotFound` → `NOT_FOUND`.

4. **State guard** — for the numeric path, check `v.state == SecretVersionState.ENABLED`.
   If not (i.e. `DISABLED` or `DESTROYED`), abort with `FAILED_PRECONDITION` and include the
   current state name in the error message. (The `"latest"` path skips this check because
   `highest_enabled_version` already guarantees the returned version is `ENABLED`.)

5. **Response** — return `AccessSecretVersionResponse(name=<canonical name>,
   payload=SecretPayload(data=v.payload, data_crc32c=v.data_crc32c))`.
   The CRC was computed with `google_crc32c.value(payload)` at `AddSecretVersion` time.

---

## Version state machine

Every new version enters the `ENABLED` state immediately on `AddSecretVersion`. Three RPCs
drive state transitions:

```
         DisableSecretVersion          DestroySecretVersion
ENABLED ─────────────────────▶ DISABLED ──────────────────────▶ DESTROYED
  ▲                                │                                  (terminal)
  └──────── EnableSecretVersion ───┘
```

Direct `ENABLED → DESTROYED` is also legal (skip the `DISABLED` step).

`DESTROYED` is terminal. The `_validate_transition` helper in `storage.py` raises
`InvalidStateTransition` for any attempt to leave `DESTROYED`; the servicer maps that to
`FAILED_PRECONDITION`.

**On destruction**, the storage backend:
- Zeroes `v.payload` to `b""` (payload bytes are irrecoverably discarded).
- Sets `v.destroy_time` to the current RFC 3339 timestamp.

The version record is **not deleted** — metadata (`id`, `create_time`, `destroy_time`, `state`)
remains accessible via `GetSecretVersion` and `ListSecretVersions`, matching real Secret Manager
behaviour.

All three state-transition RPCs (`EnableSecretVersion`, `DisableSecretVersion`,
`DestroySecretVersion`) share the private `_set_state` helper in `servicer.py`, which parses
the version name, calls `storage.update_version_state`, and converts exceptions to gRPC aborts.

---

## IAM policy stubs

`SetIamPolicy`, `GetIamPolicy`, and `TestIamPermissions` are **not implemented** in the
emulator.

`SecretManagerServicer` does not override these methods. Calls fall through to the generated
base class `SecretManagerServiceServicer` in `service_pb2_grpc.py`, whose default
implementation does:

```python
context.set_code(grpc.StatusCode.UNIMPLEMENTED)
context.set_details('Method not implemented!')
raise NotImplementedError('Method not implemented!')
```

There is **no round-tripping, no storage, and no enforcement** of any IAM policy. Callers that
issue these RPCs will receive a gRPC `UNIMPLEMENTED` error.

---

## Errors

| gRPC status | When it is returned |
|---|---|
| `INVALID_ARGUMENT` | Resource name does not match the expected pattern; `secret_id` contains disallowed characters or exceeds 255 characters; `version_id` is not a decimal integer or `"latest"` |
| `NOT_FOUND` | Secret or version does not exist in the backend |
| `ALREADY_EXISTS` | `CreateSecret` is called with a `secret_id` that already exists in the same project |
| `FAILED_PRECONDITION` | `AccessSecretVersion` on a non-`ENABLED` version; `"latest"` resolution finds no enabled version; state-transition from `DESTROYED` |
| `UNIMPLEMENTED` | `SetIamPolicy`, `GetIamPolicy`, `TestIamPermissions` |

All statuses are produced by `await context.abort(grpc.StatusCode.X, message)` inside the
async servicer methods. The generated base class uses the synchronous `context.set_code` pattern
for the `UNIMPLEMENTED` cases — a minor inconsistency that does not affect clients.

---

## Tests

**Unit tests** live under `tests/unit/services/secret_manager/` and are organised by module:

| File | What it covers |
|---|---|
| `test_models.py` | `SecretRecord` / `SecretVersion` dataclass behaviour; `highest_enabled_version` edge cases |
| `test_names.py` | `parse_secret_name`, `parse_version_name`, `validate_secret_id` — acceptance and rejection |
| `test_servicer_secrets.py` | Secret CRUD RPCs with mock storage and mock gRPC context |
| `test_servicer_versions.py` | Version RPCs, state-transition logic, `"latest"` resolution |
| `test_storage_memory.py` | Full storage contract against `InMemoryStorage` |
| `test_storage_disk.py` | Full storage contract against `DiskStorage` (tmp-dir fixture) |

**Integration tests** in `tests/integration/test_secret_manager_integration.py` start the
emulator in-process and exercise it end-to-end using the real `google-cloud-secret-manager`
Python client library over a live gRPC channel. They cover the complete lifecycle: create,
add version, access, disable, destroy, and expected error responses.

---

## Internals-level limitations

The following are known gaps between the emulator and the production Secret Manager service:

- **No authentication or authorization.** Any caller can read or modify any secret in any
  project. IAM methods return `UNIMPLEMENTED` rather than enforcing access control.
- **Payloads stored in cleartext.** Both the in-memory dict and the on-disk JSON carry raw
  secret bytes (base64 on disk). There is no encryption at rest.
- **No CMEK enforcement.** Customer-managed encryption key fields are accepted by the proto and
  silently ignored.
- **No rotation support.** `rotation` and `topics` fields in secret create/update requests are
  not parsed, stored, or acted on.
- **No replication routing.** The `replication` field is deserialized by the proto but discarded
  by the servicer; there is no multi-region or per-region semantics.
- **No audit logging.** Access and mutation events are not recorded anywhere.
- **No `expire_time` / TTL enforcement.** Version expiry is not implemented.
- **In-memory state is ephemeral.** `InMemoryStorage` does not survive process restart.
  `DiskStorage` does persist across restarts via the JSON file.
