# gcp-local — Core Design

**Date:** 2026-04-24
**Status:** Draft for review
**Scope:** Core framework + v1 service set

## 1. Overview

`gcp-local` is an open-source, local emulator for Google Cloud Platform services — the GCP counterpart to [LocalStack](https://localstack.cloud/) for AWS. It runs as a single Docker container, exposes the canonical endpoints that Google's official client libraries expect, and lets users develop and test GCP-dependent code without touching real cloud infrastructure.

**Primary goal:** plug-and-play compatibility with official GCP client libraries. A user points `google-cloud-storage`, `google-cloud-bigquery`, etc. at the emulator via the standard environment variables, and their existing code runs unchanged.

**Positioning:** a serious open-source product aimed at being *the* GCP local-emulation tool. Personal GitHub, Apache 2.0 license, community contributions expected.

This document specifies the **core framework and v1 service set**. Each service receives its own follow-on spec during implementation. Cloud Functions is explicitly v2.

## 2. Scope

### In scope (v1)

- Core framework: service registry, lifecycle, per-service listeners, shared storage/state hub, admin API
- Five services: **GCS**, **BigQuery**, **Pub/Sub**, **Firestore**, **Secret Manager**
- Both transports: REST (for GCS, BigQuery) and gRPC (for Pub/Sub, Firestore, Secret Manager)
- In-memory persistence by default; opt-in disk persistence
- Exact-shape error responses matching GCP's error envelope
- Integration test suite driven by real `google-cloud-*` client libraries
- Docker image (multi-arch: amd64, arm64)
- PyPI package

### Out of scope (deferred to v2+)

- **Cloud Functions** and serverless compute (v2 marquee feature)
- **Auth / IAM emulation** (v1 accepts any token, ignores projects)
- **Fault injection** (latency, redelivery, error rates) — v2 differentiator
- **Conformance tests against real GCP** — structure v1 tests to allow this later
- **Snapshot / restore** of state
- **Web UI**
- **Additional services** (Cloud Tasks, Scheduler, Spanner, Bigtable, etc.)
- **ML, geo (`ST_*`), and procedural SQL** in BigQuery
- **Firestore real-time listeners**

## 3. Architecture

### 3.1 Process model

**Single Python process, multiple listeners.** One `docker run`, one container, one main process. Each enabled service binds its own canonical port(s). Shared state is in-process.

Rationale:
- "One container, plug-and-play" is the core UX promise. A docker-compose setup with per-service containers would violate it.
- Cross-service integration (GCS object notifications into Pub/Sub, for example) is trivial with in-process shared state.
- A crash in one service kills the whole emulator — acceptable for local dev; users restart the container.

Concurrency: `asyncio` for I/O-bound work (REST handlers, gRPC servers). CPU-bound work (BigQuery via DuckDB) runs on a thread pool to avoid blocking the event loop.

### 3.2 Service registry and selection

Each service is a plugin implementing a common interface:

```python
class Service(Protocol):
    name: str                          # "gcs", "bigquery", ...
    default_ports: list[Port]          # canonical ports for client-lib compat
    async def start(self, ctx: Context) -> None: ...
    async def stop(self) -> None: ...
    async def reset_state(self) -> None: ...
    def health(self) -> HealthStatus: ...
```

Registration via Python entry points (`gcp_local.services`), so the core discovers services without hard-coding. Third parties can publish their own services as separate packages that register via entry points.

**Selection at runtime via `SERVICES` env var:**

```
docker run -e SERVICES=gcs,pubsub,firestore -p 4443:4443 -p 8085:8085 -p 8080:8080 gcp-local
```

- `SERVICES=all` (default): start every registered service.
- `SERVICES=gcs,bq`: start only those; other services never initialize, other ports never bind.
- Unknown service names → startup error with a list of valid names.
- A `--list-services` CLI flag prints registered services and their ports.

### 3.3 Ports and listeners

Each service declares its canonical port matching what its client library expects by default. Ports are configurable per-service via env vars (`GCS_EMULATOR_PORT`, etc.) for users running multiple emulators or avoiding conflicts.

| Service | Protocol | Default port | Client-library env var |
|---|---|---|---|
| GCS | REST | 4443 | `STORAGE_EMULATOR_HOST` |
| BigQuery | REST | 9050 | `BIGQUERY_EMULATOR_HOST` |
| Pub/Sub | gRPC | 8085 | `PUBSUB_EMULATOR_HOST` |
| Firestore | gRPC | 8080 | `FIRESTORE_EMULATOR_HOST` |
| Secret Manager | gRPC | 8086 | *(custom — no standard emulator env var)* |
| **Admin API** | REST | **4510** | *(gcp-local–specific)* |

Port values are not sacred — if a canonical port conflicts with something real on the user's host, they remap in Docker (`-p 4443:4443`). The relevant constraint: inside the container, each service listens on the port its client library expects when `<SERVICE>_EMULATOR_HOST` is set.

**Note on Secret Manager:** The official Google Secret Manager client does not support an emulator env var out of the box. Users must construct the client with an explicit `api_endpoint="localhost:8086"` and insecure channel credentials. A helper snippet in the docs will make this copy-pasteable.

### 3.4 Shared state hub

Services do not talk to each other directly. They publish into and subscribe from an in-process event hub:

```python
class StateHub:
    def publish(self, topic: str, event: dict) -> None: ...
    def subscribe(self, topic: str, handler: Callable) -> None: ...
```

v1 use case: GCS object notifications → Pub/Sub subscriptions (real GCS feature). The GCS service publishes `object.created` / `object.deleted` events; Pub/Sub subscribes and, if a notification config exists, fans out messages to the configured topic.

Services remain runnable standalone (if their consumer isn't loaded, events are dropped). This keeps the `SERVICES` selection model honest.

## 4. Storage and persistence

### 4.1 Model

Per-service storage backend abstraction. Each service defines a `Storage` protocol; two implementations per service: **in-memory** (default) and **on-disk** (enabled via `PERSIST=1`).

With `PERSIST=1`, state lives under `/data/` inside the container. Users mount a volume:

```
docker run -e PERSIST=1 -v gcp-local-data:/data ...
```

Without `PERSIST=1`, everything is ephemeral.

### 4.2 Per-service backends

| Service | In-memory | On-disk |
|---|---|---|
| GCS | `dict[path → bytes + metadata]` | files at `/data/gcs/<bucket>/<object>`; `.meta.json` sidecars |
| BigQuery | DuckDB `:memory:` connection | DuckDB file at `/data/bigquery.duckdb` |
| Pub/Sub | in-process `asyncio.Queue`s + topic/subscription dicts | JSON snapshot at `/data/pubsub.json`; write on shutdown + periodic |
| Firestore | nested dict + index dicts | SQLite at `/data/firestore.db` with JSON1 extension |
| Secret Manager | dict | JSON file at `/data/secrets.json` |

### 4.3 BigQuery engine rationale

DuckDB is the BigQuery execution engine. It is columnar, embedded, analytics-focused, and supports nested types (STRUCT, LIST), UNNEST, window functions, and `QUALIFY` — a meaningful portion of BigQuery's value.

The gold-standard OSS BQ emulator ([goccy/bigquery-emulator](https://github.com/goccy/bigquery-emulator)) uses Google's own ZetaSQL parser/analyzer via cgo. No production-grade Python binding for ZetaSQL exists. DuckDB is the best available choice in a Python codebase; we pay the fidelity gap explicitly.

**SQL dialect translation:** [sqlglot](https://github.com/tobymao/sqlglot) ships a BigQuery → DuckDB transpiler. Incoming SQL is parsed as BigQuery dialect, transpiled to DuckDB, executed.

**BQ-specific function shims:** a small set of hand-written UDFs register on the DuckDB connection at startup: `GENERATE_UUID`, `SAFE.*` prefix handling, `FORMAT_DATE` / `PARSE_DATE` with BQ format strings, `APPROX_QUANTILES` (approximation via DuckDB quantiles), etc. Complete list refined during implementation.

**Ignored / stubbed:** partitioning DDL (accepted, ignored), clustering (accepted, ignored), wildcard tables (resolved at query time via table enumeration).

**Known v1 gaps (documented in README):** `ML.*` functions, most `ST_*` geo functions, scripting / procedural SQL, recursive CTE edge cases, exact `TIMESTAMP` vs `DATETIME` semantics differences.

### 4.4 Firestore engine rationale

SQLite with the JSON1 extension is Firestore's storage engine. Documents are rows with a JSON column; composite indexes are materialized as expression indexes over `json_extract(data, '$.field')`. Transactions use `BEGIN IMMEDIATE`, matching Firestore's optimistic-with-retry model.

**Query planner:** custom code maps Firestore query operators (`where`, `orderBy`, `limit`, `startAt`, `endAt`) onto SQL. Composite queries require matching indexes; when none exists, the emulator emits the "missing index" error that real Firestore emits (a concrete, well-known error with a fake-but-valid index-creation URL in the message). This matches real Firestore behavior.

**Array-contains / `in` queries:** fan-out index entries at write time (standard Firestore trick).

## 5. Admin API

A separate REST server on its own port (default 4510) provides operational endpoints. Namespaced `/_emulator/` to avoid any collision with a service API.

| Endpoint | Method | Purpose |
|---|---|---|
| `/_emulator/health` | GET | Overall health + per-service status |
| `/_emulator/services` | GET | List running services and their ports |
| `/_emulator/reset` | POST | Wipe all state across all services |
| `/_emulator/reset?service=<name>` | POST | Reset state for one service |

No auth on admin API in v1 — the container is meant to be local. Binding to `0.0.0.0` inside the container relies on Docker's network isolation.

**Deferred to v2:** `/_emulator/snapshot` and `/_emulator/restore` for seeded test fixtures.

## 6. Fidelity

### 6.1 Auth / IAM

**None.** Any bearer token accepted (or absent). Project IDs accepted but not validated. No IAM checks. Matches the behavior of Google's own Pub/Sub and Firestore emulators.

v2 candidate: configurable IAM policies for permission-denied testing.

### 6.2 Error-response shape

**Exact match** with GCP's error envelope. Non-negotiable — client libraries parse errors and raise typed exceptions (`google.api_core.exceptions.NotFound`, `AlreadyExists`, `InvalidArgument`, etc.). If our error bodies don't match, user code that catches these exception types breaks, which breaks the plug-and-play promise.

Per service: map each internal error class to the correct HTTP status (REST) or gRPC status code + error-details payload. Canonical error `reason` codes (`"notFound"`, `"alreadyExists"`, `"invalid"`, …) included where GCP uses them.

### 6.3 Behavioral fidelity

**Happy path + obvious errors, synchronous, no simulated cloud semantics.** v1 does not model:

- Eventual consistency windows
- Pub/Sub redelivery randomness or message ordering edge cases
- BigQuery async job state machines (jobs transition `PENDING → DONE` synchronously within the request; the job API exists and returns the right shapes, but no real async work)
- GCS resumable upload edge cases around network interruption

v2 candidate: configurable fault injection (`--simulate-latency`, `--pubsub-redelivery-rate`, `--gcs-consistency-window`) as a marquee differentiating feature.

## 7. Testing strategy

### 7.1 Unit tests

Per-service internals: storage backend correctness, SQL translation (sqlglot BQ→DuckDB), Firestore index matching, Pub/Sub ack/nack, error-envelope construction. Standard `pytest`.

### 7.2 Integration tests

**The primary test suite — and the contract.** Each service has integration tests that import the real official client library (`google-cloud-storage`, `google-cloud-bigquery`, `google-cloud-pubsub`, `google-cloud-firestore`, `google-cloud-secret-manager`), point it at the emulator, and exercise the API surface.

If `google-cloud-storage`'s `Client().create_bucket(...).upload_blob(...)` does not work end-to-end, the emulator is broken — regardless of what unit tests say. These tests double as living documentation of what's supported.

No mocking inside integration tests.

### 7.3 Conformance (v2)

Same integration tests structured to accept a parameterized endpoint (emulator vs. real GCP). In v2, CI runs them against both. This requires real GCP credentials and a metered project. v1 writes the tests in this parameterized form already so turning on real-GCP conformance is a CI-config change, not a test rewrite.

### 7.4 CI

GitHub Actions. On every PR:
1. Lint + type-check (`ruff`, `mypy`).
2. Unit tests.
3. Build Docker image.
4. Boot image; run integration tests against it with real client libraries.
5. On merge to `main`: publish `:nightly` Docker tag.
6. On git tag: publish versioned Docker tag + PyPI release.

## 8. Repo layout and packaging

### 8.1 Layout

```
gcp-local/
├── src/gcp_local/
│   ├── core/
│   │   ├── registry.py        # service registry, entry-point discovery
│   │   ├── lifecycle.py       # start/stop orchestration
│   │   ├── state_hub.py       # in-process event bus
│   │   ├── storage.py         # base Storage protocol + helpers
│   │   ├── admin_api.py       # /_emulator/* REST server
│   │   └── errors.py          # shared error-envelope builders
│   ├── services/
│   │   ├── gcs/
│   │   ├── bigquery/
│   │   ├── pubsub/
│   │   ├── firestore/
│   │   └── secrets/
│   └── cli.py                 # entrypoint
├── tests/
│   ├── unit/
│   └── integration/
├── docker/
│   └── Dockerfile             # multi-arch build
├── docs/
│   ├── README.md
│   ├── services/              # per-service compat notes
│   └── superpowers/specs/     # this spec and follow-ons
├── pyproject.toml
├── LICENSE
└── .github/workflows/
```

### 8.2 Package shape

**One PyPI package**, `gcp-local`. Service selection is runtime (via `SERVICES`), not install-time. The internal plugin interface is clean enough that third parties can publish separate packages (`gcp-local-<service>`) registering via entry points, but we ship v1 as one unit.

### 8.3 Distribution

**Primary:** Docker image `ghcr.io/<user>/gcp-local:<tag>`. Multi-arch (`linux/amd64`, `linux/arm64`). Entry point is `python -m gcp_local.cli`.

**Secondary:** PyPI package for users who want to hack or run outside Docker. Same codebase.

**Not shipping in v1:** Homebrew tap, pyinstaller binaries, system packages.

### 8.4 Dependencies (expected)

- `grpcio`, `grpcio-tools` — gRPC server + code generation from proto files
- `googleapis-common-protos` — canonical GCP proto definitions
- `fastapi` or `starlette` — REST servers (GCS, BigQuery, admin)
- `duckdb` — BigQuery engine
- `sqlglot` — BigQuery → DuckDB SQL translation
- `google-api-core` — error-envelope shapes (imported for types/utilities, not for client behavior)
- `pytest`, `pytest-asyncio` — testing
- The real `google-cloud-*` libraries as **test dependencies** only, not runtime dependencies

### 8.5 License

**Apache 2.0.** Standard for Python infra OSS; permissive; explicit patent grant reassures corporate contributors. MIT is the other viable option but Apache 2.0 is the stronger default for a "serious OSS product" with expected corporate adoption.

## 9. Legal / non-affiliation

README, PyPI description, and any eventual website carry a prominent disclaimer:

> `gcp-local` is an independent open-source project. It is not affiliated with, endorsed by, or sponsored by Google LLC or Google Cloud. "Google Cloud Platform," "GCP," and related product names are trademarks of Google LLC.

No Google logos or GCP product icons are used. No domain name implying affiliation is registered.

## 10. v2 roadmap (non-binding)

In rough priority order:

1. **Cloud Functions** — deployment API, Functions Framework orchestration, event triggers from GCS/Pub/Sub/Firestore.
2. **Fault injection** — configurable latency, error rates, Pub/Sub redelivery, GCS consistency windows.
3. **Conformance tests against real GCP** in CI.
4. **IAM emulation** — configurable policies, permission-denied testing.
5. **Additional services** — Cloud Tasks, Scheduler, Spanner, Bigtable — demand-driven.
6. **Snapshot / restore** — seeded test fixtures.
7. **Firestore real-time listeners.**

## 11. Open questions

- Exact list of BQ function shims (refined during BigQuery service spec).
- Whether to support `SERVICES=all-rest` / `SERVICES=all-grpc` shortcuts (minor UX).
- Docker base image choice: `python:3.13-slim` vs. `distroless` — decided during packaging work.
- Whether Secret Manager's insecure-channel connection helper should be a Python snippet in docs or a tiny shipped utility module.
