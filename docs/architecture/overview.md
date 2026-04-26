# gcp-local internals — overview

## Audience

This document is for contributors who need to modify or extend the gcp-local
emulator itself — adding a new GCP service, changing the startup sequence,
adjusting the admin API, or working on the core framework. If you are a user
who wants to connect an application to the emulator, read
[`docs/services/`](../services/) instead. If you want to run the emulator in
Docker, Kubernetes, or Rancher Desktop, see
[`docs/deployment.md`](../deployment.md).

---

## Repository tour

**`src/gcp_local/core/`** — the service-agnostic framework. All cross-cutting
concerns live here: the `Service` protocol, `ServiceRegistry`,
`Lifecycle` orchestrator, `Context` dataclass, `StateHub` event bus, admin API
(`admin_api.py`), persistence helpers (`storage.py`), and the shared error
envelope helpers (`errors.py`). The CLI entry-point is `src/gcp_local/cli.py`.

**`src/gcp_local/services/`** — one sub-package per emulated GCP service:
`bigquery/`, `gcs/`, `secret_manager/`. Each sub-package contains a
`service.py` (the `Service` implementation) plus whatever route handlers,
storage classes, and engine code that service needs.

**`src/gcp_local/generated/`** — vendored protobuf / gRPC stubs, checked in
and regenerated via `scripts/gen_protos.sh`. See
[Generated proto stubs](#generated-proto-stubs) below.

**`tests/unit/`** — fast, in-process tests with no network dependency.
**`tests/integration/`** — drive the real `google-cloud-*` Python clients
against an in-process emulator instance; these are the authoritative
compatibility tests.

**`docs/`** — user-facing service guides (`docs/services/`), this architecture
directory (`docs/architecture/`), and the developer guide
(`docs/development/`).

**`docker/`** — `Dockerfile` for building the published image.

**`scripts/`** — `gen_protos.sh`, which compiles `.proto` files under
`protos/` into Python stubs and writes them to `src/gcp_local/generated/`.

---

## Service protocol

Every emulated GCP service must satisfy this
[`runtime_checkable` Protocol](https://docs.python.org/3/library/typing.html#typing.runtime_checkable)
defined in `src/gcp_local/core/service.py`:

```python
@runtime_checkable
class Service(Protocol):
    name: str
    default_ports: list[Port]

    async def start(self, ctx: "Context") -> None: ...
    async def stop(self) -> None: ...
    async def reset_state(self) -> None: ...
    def health(self) -> HealthStatus: ...
```

`name` is the canonical service identifier (matches the entry-point key in
`pyproject.toml`, e.g. `"bigquery"`). `default_ports` is a list of
`Port(number: int, protocol: Literal["rest", "grpc"])` — most services expose
a single port; the list type leaves room for services that need more than one.
`HealthStatus(ok: bool, message: str = "")` is the health report the admin API
surfaces.

Everything that a service actually does — starting a FastAPI app, spinning up a
gRPC server, running background tasks — is encapsulated behind this four-method
interface. The framework never inspects the internals of any service; it only
calls `start`, `stop`, `reset_state`, and `health`.

---

## Service registry

`ServiceRegistry` (in `src/gcp_local/core/registry.py`) maps service names to
their classes. Services can be registered in two ways:

1. **Programmatically** (primarily for tests): `registry.register("bigquery",
   BigQueryService)`. Raises `ValueError` if the name is already taken.
2. **Via entry-point discovery**: `registry.discover_from_entry_points()` reads
   the `gcp_local.services` group from the installed package metadata.

The entry-point block in `pyproject.toml` currently declares:

```toml
[project.entry-points."gcp_local.services"]
gcs = "gcp_local.services.gcs:GcsService"
secret_manager = "gcp_local.services.secret_manager:SecretManagerService"
bigquery = "gcp_local.services.bigquery:BigQueryService"
```

At startup the CLI calls `discover_from_entry_points()` and then
`resolve_selection(SERVICES)`, where `SERVICES` is an environment variable
whose accepted values are `"all"` (default), `""` (no services), or a
comma-separated subset of registered names. The resulting list of instantiated
services is passed to `Lifecycle`.

---

## Lifecycle

`Lifecycle` (in `src/gcp_local/core/lifecycle.py`) orchestrates starting and
stopping a fixed set of `Service` instances. The sequence is:

1. **Context construction** — `cli.py` builds a `Context` once, before any
   service starts. `Context` carries:
   - `persist: bool` — whether services should write to disk.
   - `data_dir: Path` — base directory for on-disk state (default `/data`).
   - `port_overrides: dict[str, int]` — per-service port overrides read from
     environment variables.
   - `state_hub: StateHub | None` — the cross-service event bus (always set
     by the CLI; may be `None` in test fixtures that do not need it).

2. **`start_all()`** — services start **serially** (not concurrently), so
   rollback on failure is unambiguous. If any `start()` raises, every already-
   started service is stopped in reverse order and `ServiceStartError` is
   raised.

3. **Running** — after all services are up, `cli.py` starts the admin API on
   port 4510 and blocks until `SIGINT` or `SIGTERM`.

4. **`stop_all()`** — services stop in reverse start order. Exceptions during
   stop are logged and swallowed so that all services get a chance to clean up.

5. **`reset_all()` / `reset(name)`** — delegates to each service's
   `reset_state()`. This drops in-memory state and, if `PERSIST=1`, re-
   initializes the on-disk state directory. It is also callable via the admin
   API without restarting the process.

---

## Admin API

A lightweight FastAPI app runs on port 4510 (configurable via
`GCP_LOCAL_ADMIN_PORT`). It exposes three endpoints:

### `GET /_emulator/health`

Returns the `HealthStatus` of every running service and an overall `ok` flag.

```json
{
  "ok": true,
  "services": {
    "bigquery":       {"ok": true,  "message": ""},
    "gcs":            {"ok": true,  "message": ""},
    "secret_manager": {"ok": true,  "message": ""}
  }
}
```

### `GET /_emulator/services`

Lists every running service with its ports and protocol.

```json
{
  "services": [
    {"name": "bigquery",       "ports": [{"number": 9050, "protocol": "rest"}]},
    {"name": "gcs",            "ports": [{"number": 4443, "protocol": "rest"}]},
    {"name": "secret_manager", "ports": [{"number": 8086, "protocol": "grpc"}]}
  ]
}
```

### `POST /_emulator/reset?service=<name>`

Calls `reset_state()` on a single service (or on all services when the
`service` query parameter is omitted). Returns HTTP 204 on success, 404 if the
name is not recognized.

---

## Port overrides

Each service reads its port at `start()` time from `ctx.port_overrides`, using
its `default_ports[0].number` as the fallback:

```python
port = ctx.port_overrides.get(self.name, _DEFAULT_PORT)
```

The CLI populates `port_overrides` by looking for environment variables of the
form `<SERVICE_NAME_UPPER>_EMULATOR_PORT`. For example:

```
BIGQUERY_EMULATOR_PORT=19050
GCS_EMULATOR_PORT=14443
SECRET_MANAGER_EMULATOR_PORT=18086
```

Note that `SECRET_MANAGER` maps to the entry-point key `secret_manager`
(underscores, not hyphens), so the env var key is derived by
`name.upper() + "_EMULATOR_PORT"`. If a service declares multiple ports in
`default_ports`, it is the service's own responsibility to use
`port_overrides` (or a related convention) for each additional port; the core
framework only handles the single override key.

---

## Persistence

`Context.persist` toggles between two storage modes:

- **`PERSIST=0` (default)** — state is held entirely in memory. Process restart
  wipes all data. This is the correct mode for CI and short-lived test
  containers.
- **`PERSIST=1`** — state is written to `Context.data_dir / <service_name>/`.
  The `storage.data_path()` helper creates this directory on first use.

Each service decides independently how to honor `persist`:

| Service | In-memory mode | On-disk mode |
|---|---|---|
| BigQuery | DuckDB `:memory:` database | DuckDB file at `<data_dir>/bigquery/bq.duckdb` |
| GCS | Dict of bucket/object entries | Object files under `<data_dir>/gcs/` |
| Secret Manager | Dict of secrets/versions | JSON catalog at `<data_dir>/secret_manager/` |

The Dockerfile sets `VOLUME /data` and passes `GCP_LOCAL_DATA_DIR=/data`, so
any volume mount lands in the right place automatically.

Restart semantics (what survives a `reset_state()` vs a process restart) are
documented in each service's architecture doc.

---

## State hub

`StateHub` (in `src/gcp_local/core/state_hub.py`) is an in-process async
pub/sub bus for cross-service events. Services can call
`hub.subscribe(topic, handler)` to register an async callback, and
`hub.publish(topic, event_dict)` to fan out to all subscribers. The hub is
passed into every service via `Context.state_hub`.

At present no service emits or subscribes to any event — the hub is reserved
infrastructure for future cross-service workflows (for example, a GCS write
triggering a BigQuery load job). When the hub has no subscribers for a topic,
`publish()` is a no-op.

---

## Common patterns

**REST error envelope** — all REST services return errors in the shape that
`google-api-core` expects:

```json
{
  "error": {
    "code": 404,
    "message": "dataset not found: my_project:my_dataset",
    "errors": [
      {
        "domain": "global",
        "reason": "notFound",
        "message": "dataset not found: my_project:my_dataset"
      }
    ],
    "status": "NOT_FOUND"
  }
}
```

The `rest_error_body()` helper in `src/gcp_local/core/errors.py` builds this
dict from a `GcpError(code, reason, message)` instance. Each REST service
wraps `GcpError` in a `JSONResponse` with the matching HTTP status code.
gRPC services raise `GrpcError(code, message)` instead, which the gRPC
servicer converts to a `grpc.StatusCode` abort.

**No authentication** — every endpoint accepts requests without credentials.
Callers must initialize their clients with
`google.auth.credentials.AnonymousCredentials()`. The emulator does not
validate tokens, project membership, or IAM bindings.

**Resource-name validation** — services parse resource names with a
`names.py` helper that splits on `/` and validates segment count. Loose
validation is intentional: the emulator mirrors GCP's parsing behavior rather
than enforcing additional constraints.

**In-memory vs disk-backed storage** — each service defines its own storage
protocol (a class that satisfies a service-specific `Protocol`). The storage
implementation is chosen at `start()` time based on `ctx.persist`, which keeps
the route handlers and servicers transport-agnostic.

---

## Generated proto stubs

Secret Manager uses gRPC, and the generated Python stubs are vendored directly
into the repository under `src/gcp_local/generated/`. The stubs are regenerated
by running:

```bash
bash scripts/gen_protos.sh
```

The script compiles `.proto` files from `protos/` using `grpc_tools.protoc`
and writes the output to `src/gcp_local/generated/`. The generated files are
committed to the repository so that:

- The build is fully hermetic — `protoc` is not required at install time.
- Diffs to the generated code are reviewable in PRs.
- `mypy` can type-check the stubs without a separate compilation step (the
  `src/gcp_local/generated/` directory is excluded from strict checking via
  `pyproject.toml`'s `[tool.mypy] exclude` setting).

When updating a `.proto` file, re-run `gen_protos.sh` and commit the result
alongside the proto change.
