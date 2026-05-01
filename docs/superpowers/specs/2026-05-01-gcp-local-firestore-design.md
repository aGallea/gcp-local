# gcp-local — Firestore Service Design

**Date:** 2026-05-01
**Status:** Draft for review
**Scope:** Fifth and final v1 service — Cloud Firestore (Native mode). Third gRPC service in the project.
**Core design:** [2026-04-24-gcp-local-core-design.md](./2026-04-24-gcp-local-core-design.md)
**Related:** [2026-04-29-gcp-local-pubsub-design.md](./2026-04-29-gcp-local-pubsub-design.md) — gRPC service template; [2026-04-24-gcp-local-secret-manager-design.md](./2026-04-24-gcp-local-secret-manager-design.md) — JSON-on-disk persistence template.

## 1. Overview

This document specifies the **Firestore emulator** — the fifth and final v1 service in `gcp-local` and the third gRPC service after Secret Manager and Pub/Sub. Success criterion: the official `google-cloud-firestore` Python client library works unchanged against the emulator for the Native-mode `Firestore` API across point reads/writes, batch commits, queries, aggregations, transactions, and field transforms.

Firestore is the last service committed to v1. The bar is "a backend service's `client.collection(...).document(...).set(...)`, `.update(...)`, `.where(...).stream()`, and `client.transaction()` calls round-trip through gcp-local without code changes." Real-time listeners (`Listen` streaming RPC), security rules, exports/imports, and Datastore-mode are explicitly post-v1 (§2.3).

The gRPC framework already exists from Secret Manager and Pub/Sub; this service reuses it directly. The service-level approach is closest to Pub/Sub (vendored protos, two servicers, `engine/` subpackage for the genuinely complex pieces) with the persistence pattern from Secret Manager (`InMemoryStorage` plus optional `JsonDiskStorage` under `PERSIST=1`).

The reference point for "what does an existing Firestore emulator do" is the closed-source Java emulator that ships in two flavors — `gcloud beta emulators firestore start` and the Firebase Local Emulator Suite. Both expose `FIRESTORE_EMULATOR_HOST` to the client libraries. The gap `gcp-local` fills: Python-native install (no JVM, no Node toolchain), faster startup, integration with our admin API and StateHub event bus, and composability with our other services in one container.

## 2. Scope (v1)

### 2.1 In scope

**Firestore (`google.firestore.v1.Firestore`):**

- `GetDocument`, `BatchGetDocuments`, `ListDocuments`, `ListCollectionIds`
- `CreateDocument`, `UpdateDocument`, `DeleteDocument` (legacy single-RPC writes)
- `Commit`, `BatchWrite` — batched writes with `update_mask`, preconditions (`exists`, `update_time`), and `update_transforms`
- `RunQuery`, `RunAggregationQuery` — structured queries with full filter/orderBy/cursor surface
- `BeginTransaction`, `Rollback` — read-write and read-only transactions

**FirestoreAdmin (`google.firestore.admin.v1.FirestoreAdmin`):**

- `CreateIndex` — accepts the index definition, stores it, returns a completed `Operation` immediately
- `ListIndexes`, `GetIndex`, `DeleteIndex` — round-trip the stored definitions
- All other admin RPCs (`*Database`, `*Field`, `Export*`, `Import*`, `*Backup*`) return `UNIMPLEMENTED`

**Field transforms** (applied during `Commit`):

- `set_to_server_value: REQUEST_TIME` (SERVER_TIMESTAMP)
- `increment(value)` with int/double type promotion
- `maximum(value)`, `minimum(value)`
- `append_missing_elements(values)` (arrayUnion)
- `remove_all_from_array(values)` (arrayRemove)

**Transactions:**

- Read-write transactions with optimistic concurrency control: `BeginTransaction` snapshots the per-database version counter; reads inside the transaction record their doc paths into a read-set; `Commit` aborts (`ABORTED`) if any read-set doc has been mutated since the snapshot, otherwise applies all writes atomically.
- Read-only transactions, with optional `read_time` for snapshot reads at a fixed timestamp.
- TTL sweeper drops transactions older than 60 seconds (real Firestore allows ~270s; the emulator runs shorter to surface bugs in tests where a transaction handle is held too long).

**Multi-database support:**

- Each `(project, database)` pair is an independent namespace.
- `(default)` is the default database; non-default databases (e.g. `staging`) come into existence on first write.
- No `FirestoreAdmin.CreateDatabase` RPC — databases are implicit. Documented as a quirk relative to real Firestore.

**Document model:**

- Subcollections (deep paths) up to any depth — paths are stored as `/`-joined strings, no special handling needed.
- Collection-group queries (`allDescendants=true`) find same-named collections anywhere in the tree.
- Document IDs are validated per Firestore rules (1–1500 bytes UTF-8, no `/`, no `..` segments, no reserved `__.*__` prefix on collection IDs).

**Persistence:** in-memory by default; `PERSIST=1` snapshots to JSON files on disk per-database, and reloads on startup.

**gRPC error shapes** matching real Firestore responses (`NOT_FOUND`, `ALREADY_EXISTS`, `INVALID_ARGUMENT`, `FAILED_PRECONDITION`, `ABORTED`, `UNIMPLEMENTED`).

**StateHub events** for cross-service integration: `firestore.document.written` published on every successful write. The Listen service (post-v1) will subscribe to this same event internally.

### 2.2 Accepted-and-ignored

These fields are accepted on the wire (so clients don't crash on validation) and stored on the resource where applicable, but the emulator does not act on them:

- **Composite indexes** — `FirestoreAdmin.CreateIndex` succeeds, the index definition is stored, and `ListIndexes`/`GetIndex` return it. Queries always run regardless of whether a matching index exists. Real Firestore returns `FAILED_PRECONDITION` with an index-creation link when an index is missing; the emulator silently runs the query. Documented limitation.
- **`enableExactlyOnceDelivery` and similar consistency knobs** — N/A for Firestore (no equivalent), called out only to clarify the analogue with Pub/Sub.

**IAM (`GetIamPolicy` / `SetIamPolicy` / `TestIamPermissions`)** — return `UNIMPLEMENTED`, mirroring Secret Manager and Pub/Sub.

### 2.3 Out of v1 (deferred, tracked in `ROADMAP.md`)

- **`Listen`** (streaming bidirectional RPC) — required for real-time `on_snapshot()` callbacks in client SDKs. Returns `UNIMPLEMENTED`. Substantial enough to warrant its own follow-up PR; the StateHub event shape (§7) is designed so Listen can be added without a contract change.
- **`PartitionQuery`** — used by Dataflow and parallel exports. Returns `UNIMPLEMENTED`. Niche.
- **Security rules** — every request is authorized. No rules engine, no `firestore.rules` file processing.
- **TTL field policies** (`FirestoreAdmin.UpdateField` setting TTL) — not implemented.
- **Backups, restores, exports, imports** (`FirestoreAdmin.ExportDocuments`, `ImportDocuments`, `*Backup*`) — return `UNIMPLEMENTED`.
- **Bundles** — not implemented.
- **Datastore-mode API** (`google.datastore.v1`) — separate planned service, not bundled.
- **Document history retention** — read-only transactions with `read_time` only see the current state of documents whose `update_time <= read_time`; deleted documents are gone forever. Real Firestore retains a 1-hour history. Documented limitation.

## 3. Service architecture

### 3.1 Package layout

```
src/gcp_local/services/firestore/
  __init__.py                 # exports FirestoreService
  service.py                  # FirestoreService (Service protocol, lifecycle)
  servicer.py                 # FirestoreServicer + FirestoreAdminServicer (gRPC handlers)
  engine/
    __init__.py
    query.py                  # query evaluator: filters, orderBy, cursors, limit
    transforms.py             # field transforms
    transactions.py           # transaction registry + read-set conflict detection
    aggregations.py           # count / sum / avg
  values.py                   # Firestore Value <-> Python codec; type-aware comparator
  models.py                   # DocumentRecord, TransactionRecord, IndexRecord
  storage.py                  # Storage protocol + InMemoryStorage + JsonDiskStorage
  names.py                    # parse projects/<p>/databases/<db>/documents/<path>
  errors.py                   # exception types + grpc_error mappings
```

Mirrors the Pub/Sub layout. The `engine/` subpackage holds the three things that are genuinely complex (query, transforms, transactions); everything else is plumbing.

### 3.2 Port

Default **8080** (Firebase Local Emulator Suite default for Firestore — most familiar to users coming from Firebase). Override via `FIRESTORE_EMULATOR_PORT` through the existing `port_overrides` machinery.

Existing port map: 4510 admin, 4443 GCS, 8085 Pub/Sub, 8086 Secret Manager, 9050 BigQuery — 8080 doesn't collide.

### 3.3 Connection from client code

The official client reads `FIRESTORE_EMULATOR_HOST` natively — no code changes needed:

```bash
export FIRESTORE_EMULATOR_HOST=localhost:8080
```

```python
from google.cloud import firestore

db = firestore.Client(project="my-project")
db.collection("users").document("alice").set({"name": "Alice", "score": 0})
db.collection("users").document("alice").update({"score": firestore.Increment(1)})
docs = db.collection("users").where(filter=firestore.FieldFilter("score", ">", 0)).stream()
```

### 3.4 gRPC stubs

Same approach as Pub/Sub: vendor `.proto` files under `protos/google/firestore/v1/` (firestore, document, query, write, common, aggregation_result) and `protos/google/firestore/admin/v1/` (firestore_admin, index, field, database, operation), generate `_pb2*.py` once into `src/gcp_local/generated/google/firestore/{v1,admin/v1}/` via `scripts/gen_firestore_protos.sh`, and commit the generated files. This keeps the runtime dep set unchanged (no `google-cloud-firestore` at runtime — it stays test-only).

Servicer subclasses:

```python
from gcp_local.generated.google.firestore.v1 import firestore_pb2_grpc
from gcp_local.generated.google.firestore.admin.v1 import firestore_admin_pb2_grpc

class FirestoreServicer(firestore_pb2_grpc.FirestoreServicer): ...
class FirestoreAdminServicer(firestore_admin_pb2_grpc.FirestoreAdminServicer): ...
```

Both servicers are registered on the same gRPC server bound to port 8080. The split mirrors how the official client is organized (`firestore.Client` for data, `firestore_admin_v1.FirestoreAdminClient` for admin).

`google-cloud-firestore` is a **test-only** (dev) dependency, used by integration tests to drive the emulator.

### 3.5 Concurrency

One `asyncio.Lock` per `(project, database)`. All `Commit` and `RunQuery`-with-transaction calls serialize on it. Read RPCs without a transaction id don't take the lock. This serialization model matches the in-memory storage shape: there is no scenario where two writes need to interleave at the document level, and the lock is cheap.

## 4. Data model

### 4.1 Records

```python
@dataclass
class DocumentRecord:
    project: str
    database: str            # "(default)" or a custom name
    path: str                # full collection-and-doc path: "users/alice/posts/p1"
    fields: dict[str, Value] # Firestore Value structure (see 4.2)
    create_time: datetime
    update_time: datetime
    version: int             # per-database monotonic; bumped on every mutation

@dataclass
class TransactionRecord:
    txn_id: str              # opaque token, e.g. "txn-<uuid>"
    project: str
    database: str
    snapshot_version: int    # database version at BeginTransaction
    read_set: set[str]       # doc paths read inside the txn
    read_only: bool
    read_time: datetime | None  # for read-only txns with explicit read_time
    started_at: datetime     # for TTL eviction (60s)
    writes: list[Write] = field(default_factory=list)  # buffered; applied on Commit if read_set is clean

@dataclass
class IndexRecord:           # accept-and-ignore, never consulted by the query engine
    name: str                # projects/<p>/databases/<db>/collectionGroups/<g>/indexes/<id>
    fields: list[dict]       # fieldPath, order/arrayConfig
    state: str = "READY"
```

`path` is always the full doc path with no leading `/`. Collection paths are derived (`path.rsplit("/", 1)[0]`).

### 4.2 Values

`values.py` is a single module that converts between Firestore `Value` proto and a plain-Python representation, plus implements the type-aware comparator the query engine and cursors need.

| Firestore type | Python form |
|---|---|
| `nullValue` | `None` |
| `booleanValue` | `bool` |
| `integerValue` | `int` (int64 on the wire, str-encoded JSON) |
| `doubleValue` | `float` (NaN / ±Inf preserved) |
| `timestampValue` | `datetime` (UTC, microsecond precision) |
| `stringValue` | `str` |
| `bytesValue` | `bytes` |
| `referenceValue` | `DocumentReference(project, database, path)` |
| `geoPointValue` | `GeoPoint(lat, lng)` |
| `arrayValue` | `list[Value]` |
| `mapValue` | `dict[str, Value]` |

The comparator implements Firestore's documented type ordering (null < bool < number < timestamp < string < bytes < ref < geopoint < array < map) plus the within-type rules (NaN sorts smallest among numbers, byte-wise UTF-8 for strings, lexicographic for arrays, key-ordered then value-compared for maps). Centralized in one `compare(a, b) -> int` function used by both query orderBy and cursors.

### 4.3 Storage shape

`InMemoryStorage` holds:

```python
documents: dict[(project, database), dict[path, DocumentRecord]]
versions: dict[(project, database), int]                       # monotonic per-database counter
transactions: dict[(project, database, txn_id), TransactionRecord]
indexes: dict[(project, database, index_name), IndexRecord]    # accept-and-ignore
```

`JsonDiskStorage` snapshots `documents` and `indexes` to disk on every successful `Commit` when `Context.persist` is true. See §6.

## 5. Query semantics, transforms, transactions

### 5.1 Query evaluator (`engine/query.py`)

Walking the docs once per query is fine for emulator-scale data. The evaluator is a pipeline:

```
candidate_docs(query.from)          # collection or collection-group walk
  → apply where_filter (recursive: composite AND/OR, field, unary)
  → apply orderBy (stable sort using values.compare)
  → apply cursors (startAt/startAfter/endAt/endBefore via comparator on orderBy keys)
  → apply offset
  → apply limit / limit-to-last
  → emit
```

**Candidate set:**
- `from.collection_id` + `allDescendants=False` → docs whose parent collection path matches `<parent>/<collection_id>`.
- `from.collection_id` + `allDescendants=True` → docs where any segment of `path` equals `<collection_id>` (collection-group query).

**Filters:**
- `EQUAL`, `LESS_THAN`, `LESS_THAN_OR_EQUAL`, `GREATER_THAN`, `GREATER_THAN_OR_EQUAL`, `NOT_EQUAL` → `values.compare`.
- `ARRAY_CONTAINS` → membership test on array fields.
- `ARRAY_CONTAINS_ANY`, `IN`, `NOT_IN` → set-style membership.
- Unary: `IS_NAN`, `IS_NOT_NAN`, `IS_NULL`, `IS_NOT_NULL`.
- Composite `AND` / `OR` → recursive eval, short-circuiting.

**Implicit orderBy:** Firestore appends `__name__` (document path) ASC as a final orderBy if it's not already present, and adds an orderBy on every inequality field. The evaluator applies these implicit additions before sorting, matching the official client's expectations.

**Aggregations** (`RunAggregationQuery`): apply the same pipeline minus limit/orderBy/cursors, then fold the result set: `count`, `sum` (numeric coercion: int+int→int, double anywhere→double, ignore non-numeric fields per Firestore semantics), `avg` (sum/count, returns null for empty set).

### 5.2 Field transforms (`engine/transforms.py`)

Applied during `Commit` after merging the `update_mask` writes but before persisting:

| Transform | Behavior |
|---|---|
| `set_to_server_value: REQUEST_TIME` | Set field to `now()` (UTC). |
| `increment(value)` | `current + value`; type promotion (int+int→int, double anywhere→double). Missing field treated as 0. |
| `maximum(value)` | `max(current, value)` per the type comparator; missing field → use `value`. |
| `minimum(value)` | `min(current, value)`; symmetric. |
| `append_missing_elements(values)` (arrayUnion) | Append each value not already in array, preserving order. Missing field → new array. Non-array existing field → replaced with new array. |
| `remove_all_from_array(values)` (arrayRemove) | Drop all matching elements. Missing/non-array → no-op. |

`WriteResult.transform_results` is populated with the post-transform value, matching the wire contract — clients use this for `Increment` round-trips.

### 5.3 Transactions (`engine/transactions.py`)

**`BeginTransaction`** → mint `txn_id`, snapshot current `versions[(project, database)]`, store `TransactionRecord`. Read-write by default; read-only if `TransactionOptions.read_only` is set (with optional `read_time` for snapshot reads at a specific timestamp).

**Reads inside a transaction** (`Get`, `BatchGetDocuments`, `RunQuery`, `RunAggregationQuery` with `transaction=<id>`): the evaluator records every doc path it touches (whether returned or filtered out) into `read_set`. For `read_time`, return docs as of that timestamp by filtering on `update_time <= read_time` and rejecting docs whose `create_time > read_time`.

**`Commit` with `transaction=<id>`**: under the database lock —
1. Look up the `TransactionRecord`. If missing/stale → `INVALID_ARGUMENT` ("transaction not found").
2. If read-only → reject any writes → `INVALID_ARGUMENT`.
3. Re-check every doc path in `read_set`: if any doc's `version > snapshot_version` → return `ABORTED`. Drop the txn.
4. Otherwise apply all writes (with transforms), bump `versions`, drop the txn.

**`Rollback`**: drop the `TransactionRecord`. Idempotent.

**TTL sweeper:** an `asyncio.Task` runs every 30 seconds and drops transactions older than 60 seconds. Real Firestore allows up to ~270s but auto-aborts at ~5min — 60s is fine for tests and prevents leaks.

### 5.4 Document and collection name validation

Document IDs: 1–1500 bytes UTF-8, no `/`, no `.`/`..` segments. Collection IDs: same plus no `__.*__` reserved prefix (the implicit `__name__` field is the only allowed exception, and it never appears as a collection ID). Validation lives in `names.py` and is called on every write and query.

## 6. Storage

In-memory by default. `JsonDiskStorage` activates when `Context.persist` is true.

### 6.1 Layout

```
state/firestore/
  <project>__<database>.json    # one file per (project, database)
  myproj__staging.json
```

Filename uses `__` as separator because both project IDs and database names allow hyphens (real Firestore database names match `[a-z][a-z0-9-]{3,62}`); `__` cannot appear in either, so it's an unambiguous split. `(default)` is stored as the literal string `(default)` in the filename — JSON-safe and round-trips on macOS/Linux/Windows-via-Docker.

Each file holds:

```json
{
  "schema_version": 1,
  "documents": {
    "<path>": {"fields": {...}, "create_time": "...", "update_time": "...", "version": 42}
  },
  "indexes": [{"name": "...", "fields": [...]}]
}
```

Snapshots happen at the end of every mutating RPC (`Commit`, `BatchWrite`, `CreateDocument`, `UpdateDocument`, `DeleteDocument`) — one fsync per RPC, not per individual write. On startup, all matching files load; rebuild `versions[(project, database)] = max(record.version) + 1`. Transactions are not persisted (by definition in-flight). The `schema_version` marker is forward-compat — if a future change breaks the layout, we bump it and refuse-to-load with a clear error.

### 6.2 PERSIST behavior

When `PERSIST=0` (default), the service uses `InMemoryStorage` and writes nothing. When `PERSIST=1`, `JsonDiskStorage` is wired through. Same opt-in shape as Secret Manager.

## 7. Cross-service integration

### 7.1 StateHub events

Every successful write emits a `firestore.document.written` event on the StateHub bus:

```python
{
    "project": "my-project",
    "database": "(default)",
    "path": "users/alice",
    "operation": "create" | "update" | "delete",
    "update_time": "2026-05-01T...",
}
```

This is the local hook for tests that want to assert "the writer actually wrote" without polling Firestore. The post-v1 `Listen` implementation will subscribe to this same event internally — designing the event shape now means Listen can be added without a contract change.

### 7.2 No GCS/BigQuery integration in v1

Firestore export-to-GCS and Firestore-to-BigQuery dataflows are separate `FirestoreAdmin` RPCs we explicitly don't implement (§2.3).

## 8. Error mapping

Internal exceptions → `grpc_error` codes:

| Internal | gRPC code | Reason |
|---|---|---|
| `DocumentNotFound`, `CollectionNotFound`, `DatabaseNotFound` | `NOT_FOUND` | resource missing |
| `DocumentAlreadyExists` (on `current_document.exists=false` precondition where doc exists; or `CreateDocument` collision) | `ALREADY_EXISTS` | duplicate create |
| `InvalidName` (path validation) | `INVALID_ARGUMENT` | naming violation |
| `InvalidArgument` (bad filter, malformed Value, missing required field, non-numeric increment) | `INVALID_ARGUMENT` | field validation |
| `FailedPrecondition` (write with `current_document.exists=true` on missing doc, or `update_time` mismatch) | `FAILED_PRECONDITION` | precondition failed |
| `TransactionAborted` (read-set conflict) | `ABORTED` | optimistic-concurrency conflict |
| `TransactionNotFound` (commit/rollback with stale or unknown txn id) | `INVALID_ARGUMENT` | unknown transaction |
| `Unimplemented` (Listen, PartitionQuery, FirestoreAdmin export/import/backup, security rules) | `UNIMPLEMENTED` | not yet supported |
| Uncaught | `INTERNAL` | fallback |

The official client lib raises typed exceptions (`google.api_core.exceptions.Aborted`, `FailedPrecondition`, `NotFound`, etc.) on these codes; tests assert on those.

## 9. Tests

### 9.1 Unit

Under `tests/unit/services/firestore/`. One file per concern:

- `test_names.py` — path/ID validators round-trip; reject reserved prefixes, traversal segments, oversize IDs.
- `test_values.py` — every Value kind round-trips proto↔Python; comparator obeys type ordering; NaN sorts smallest; nested arrays/maps compare lexicographically.
- `test_storage.py` — InMemoryStorage CRUD; JsonDiskStorage snapshot+reload round-trips; multi-database isolation.
- `test_models.py` — record dataclasses + serializers.
- `test_transforms.py` — every transform: SERVER_TIMESTAMP, increment with type promotion, maximum/minimum, arrayUnion uniqueness, arrayRemove no-op on missing, missing-field semantics.
- `test_query_filters.py` — every operator across every type; composite AND/OR; unary; NOT_IN excludes nulls per Firestore rule.
- `test_query_orderby.py` — single + multi-field; implicit `__name__` tiebreak; implicit orderBy on inequality field; type-aware ordering.
- `test_query_cursors.py` — startAt/startAfter/endAt/endBefore including partial cursors.
- `test_query_collection_group.py` — `allDescendants=true` finds same-named collections at any depth.
- `test_aggregations.py` — count/sum/avg with numeric coercion + empty-set semantics.
- `test_transactions.py` — happy path, conflict → `ABORTED`, read-only rejects writes, TTL sweeper drops stale txns, read_time filtering.
- `test_servicer_documents.py` — Get / Create / Update / Delete / BatchGet through an in-process gRPC channel; preconditions (exists/update_time).
- `test_servicer_commit.py` — multi-write Commit with mixed transforms and updates; BatchWrite per-write atomicity.
- `test_servicer_run_query.py` — RunQuery + RunAggregationQuery wire contract; pagination via cursor.
- `test_servicer_admin.py` — FirestoreAdmin: CreateIndex returns a fake completed Operation; ListIndexes / GetIndex round-trip; ExportDocuments / ImportDocuments / `*Backup*` → `UNIMPLEMENTED`.
- `test_errors.py` — every (internal exception → grpc code) row.

### 9.2 Integration

`tests/integration/test_firestore_integration.py` drives the real `google-cloud-firestore` Python client against the in-process emulator. Coverage:

- Set/Get/Update/Delete on a document with subcollections.
- `where`/`order_by`/`limit` queries returning ordered results.
- Composite filter (`firestore.And`, `firestore.Or`) and aggregation (`.count()`).
- Collection-group query.
- `db.transaction()` happy path; deliberate conflict (two transactions on the same doc) asserts one gets `Aborted`.
- `firestore.Increment(1)` and `firestore.SERVER_TIMESTAMP` round-trip via `WriteResult.transform_results`.
- Multi-database client (`Client(database="staging")`) is isolated from `(default)`.
- `client.collection("...").stream()` returns documents matching real client expectations.
- Resource-not-found and duplicate-create error mapping.

The existing `emulator` fixture in `tests/integration/conftest.py` is extended to include `firestore` in the default service list. The cross-service health assertion (analogous to the one Pub/Sub added) covers Firestore too.

## 10. PR phasing

Per user direction: **single PR**. Justified despite the project's <500-LOC ceiling because Firestore's components (CRUD, query evaluator, transforms, transactions, admin stub) are tightly interdependent — the official Python client uses field transforms on common idiomatic writes (`Increment`, `SERVER_TIMESTAMP`), so a CRUD-only first PR would not pass the "client works unchanged" success criterion. Estimated **~3000 LOC production + ~2000 LOC tests + ~600 LOC docs**, larger than Pub/Sub.

Branch: `feat/firestore-service`. PR description will explicitly call out the size override and link this spec.

If during implementation a clean seam emerges (e.g. core CRUD + queries can ship before transactions + transforms), we'll split. We don't expect to.

## 11. Documentation deliverables

Per `docs/development/adding-a-service.md` §6:

- `docs/services/firestore.md` — user-facing usage doc with elevator pitch, what's emulated, what's not (Listen, security rules, exports, partition query, composite-index enforcement), connection recipe, examples (CRUD, queries, transactions, transforms, multi-database), limits & quirks.
- `docs/architecture/firestore.md` — internals deep-dive: at-a-glance, wire & port, storage model, request lifecycle, query pipeline (the §5.1 diagram), transaction state machine, value comparator rules, error mapping, internals-level limitations.
- `README.md` — flip Firestore row Planned → Alpha; add port 8080 to default-ports list; update "five services implemented" copy.
- `ROADMAP.md` — delete Firestore from "Planned (v1)"; add deferred items (Listen, security rules, exports/imports, partition query, composite-index enforcement, document history retention) under "Per-service follow-ups → Firestore".
- `docs/deployment.md` — add 8080 to the default-ports table.
- `CHANGELOG.md` — `[Unreleased] Added` entry.
- `pyproject.toml` — add `google-cloud-firestore` to dev/test deps; no runtime dependencies added (vendored protos use only `grpcio` + `protobuf` already in the runtime set).

## 12. Internals-level limitations (carried forward to architecture doc)

- **Composite indexes are not enforced.** Every query runs regardless of whether a matching index exists. Real Firestore returns `FAILED_PRECONDITION` with an index-creation link.
- **No `Listen`.** `on_snapshot()` callbacks raise `UNIMPLEMENTED`. Deferred to a follow-up PR.
- **No document-history retention.** Read-only transactions with `read_time` only see the current state of documents whose `update_time <= read_time`; deleted documents are gone.
- **Linear query scan.** Every query walks the full collection (or descendants for collection-group). Fine up to ~10k docs per collection in tests; not designed for production-scale data.
- **No security rules / auth.** Every request is authorized.
- **No exports / imports / backups** via FirestoreAdmin — `UNIMPLEMENTED`.
- **No field admin** (`UpdateField` for TTL etc.) — `UNIMPLEMENTED`.
- **Transaction TTL is 60s**, shorter than real Firestore's ~270s, to surface bugs in tests where a transaction handle is held too long.
- **Single-process delivery.** Emulator runs in one Python process; no horizontal scale-out.
- **No `PartitionQuery`** — returns `UNIMPLEMENTED`. Niche; used by Dataflow.
