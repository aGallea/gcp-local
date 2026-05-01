# Firestore — internals

This document describes how the Firestore emulator is implemented. For the user-facing API surface (what's emulated, how to connect, examples), see [`docs/services/firestore.md`](../services/firestore.md). For the cross-cutting framework this service plugs into, see [`docs/architecture/overview.md`](overview.md).

## At a glance

The Firestore emulator is a pure gRPC service on port **8080** with two servicers:

- **`FirestoreServicer`** — handles the `google.firestore.v1.Firestore` service (document CRUD, queries, aggregations, transactions, batch writes).
- **`FirestoreAdminServicer`** — handles the `google.firestore.admin.v1.FirestoreAdmin` service (index CRUD stubs; all other admin RPCs return `UNIMPLEMENTED`).

Storage is **in-memory by default** (`InMemoryStorage`). Under `PERSIST=1`, `JsonDiskStorage` (a subclass) writes one JSON file per `(project, database)` pair and reloads on startup.

The service reuses the gRPC server framework from Secret Manager and Pub/Sub (vendored proto stubs, a dedicated `grpc.aio.Server`, asyncio-based servicers). What is new is the **query pipeline** in `engine/query.py`, the **aggregation layer** in `engine/aggregations.py`, the **field transforms** in `engine/transforms.py`, and the **OCC transaction state machine** in `engine/transactions.py`.

## Wire & port

gRPC on port **8080** (the canonical Firestore emulator port that `FIRESTORE_EMULATOR_HOST` points to).

The client honors `FIRESTORE_EMULATOR_HOST=localhost:8080` natively — it opens an insecure channel and skips authentication when the env var is set.

The port is overridable via `FIRESTORE_EMULATOR_PORT` through the standard `port_overrides` machinery (`ctx.port_overrides.get("firestore", 8080)` in `service.py`).

The cross-service admin HTTP API (`/_emulator/health`, `/services`, `/reset`) lives on port **4510**, not on 8080. The service registers as `firestore` in `pyproject.toml`'s `[project.entry-points."gcp_local.services"]` block.

## Vendored proto stubs

Pre-generated Python stubs are checked into the repository under:

```
src/gcp_local/generated/google/firestore/
  v1/
    document_pb2.py / document_pb2_grpc.py / document_pb2.pyi
    firestore_pb2.py / firestore_pb2_grpc.py / firestore_pb2.pyi
    query_pb2.py / query_pb2.pyi
    write_pb2.py / write_pb2.pyi
    common_pb2.py / common_pb2.pyi
  admin/v1/
    firestore_admin_pb2.py / firestore_admin_pb2_grpc.py / firestore_admin_pb2.pyi
    index_pb2.py / index_pb2.pyi
    operation_pb2.py / operation_pb2.pyi
```

`google-cloud-firestore` is a **test-only** (dev) dependency, used by integration tests. The runtime image does not install it — only the vendored protos are needed at runtime.

## Storage model

`InMemoryStorage` holds:

| Field | Type | Purpose |
|---|---|---|
| `_documents` | `dict[(project, db), dict[path, DocumentRecord]]` | All documents, keyed by path |
| `_versions` | `dict[(project, db), int]` | Monotonic write counter per database |
| `_locks` | `dict[(project, db), asyncio.Lock]` | Per-database write lock |
| `_txns` | `dict[(project, db, txn_id), TransactionRecord]` | Active transaction records |
| `_indexes` | `dict[(project, db, name), IndexRecord]` | Stored index definitions |

The `DocumentRecord` dataclass (defined in `models.py`):

```python
@dataclass
class DocumentRecord:
    project: str
    database: str
    path: str                     # e.g. "users/alice/posts/p1"
    fields: dict[str, Any]        # Python native values (decoded from proto)
    create_time: datetime
    update_time: datetime
    version: int                  # monotonically increasing per-database
```

The `TransactionRecord` dataclass:

```python
@dataclass
class TransactionRecord:
    txn_id: str
    project: str
    database: str
    snapshot_version: int         # db version at BeginTransaction time
    read_only: bool
    started_at: datetime          # for TTL sweeper
    read_set: set[str]            # doc paths read inside the transaction
    read_time: datetime | None    # for read-only snapshot transactions
```

The `IndexRecord` dataclass:

```python
@dataclass
class IndexRecord:
    name: str                     # resource name
    fields: list[dict]            # field descriptors from the proto
    state: str                    # always "READY" in the emulator
```

### Document path model

Paths are stored as plain `/`-joined strings matching the Firestore document path (e.g. `users/alice`, `users/alice/posts/p1`). Collection paths always have an odd number of segments; document paths always have an even number. The storage layer never interprets path structure — the collection iterator applies the structural rules.

### Concurrency

All writes to a given `(project, database)` are serialized through a per-database `asyncio.Lock`. Reads do not hold the lock — they take a snapshot of the dict at read time. This is safe in a single-process asyncio context because there are no preemptive context switches; a `yield` only happens at `await` points.

### JsonDiskStorage

`JsonDiskStorage` subclasses `InMemoryStorage` and adds:

- Constructor loads all existing `.json` files from `<data_dir>/firestore/` into memory using `_load_all()`.
- `snapshot(project, database)` serializes the current in-memory state for that database to a temporary file and atomically replaces the target (`tmp.replace(target)`).
- `snapshot` is called after every successful `Commit` / `BatchWrite` / `DeleteDocument` / `UpdateDocument` / `CreateDocument`.
- Filename convention: `<project>__<database>.json` (double underscore separates project from database; neither may contain `__`).

The JSON schema includes a `schema_version: 1` guard; loading a file with a different version raises `ValueError` to prevent silent corruption.

## Request lifecycle: Commit happy path

The main write path (`Commit`) illustrates how the storage, servicer, and transforms interact:

```
Client: Commit(project, database, [Write(update=..., update_transforms=[...]), ...], transaction=txn_id)

1. servicer.Commit receives the request.
2. If transaction ID is present: call commit_transaction(storage, project, database, txn_id, has_writes=True).
   - commit_transaction validates the read_set against current doc versions.
   - Returns the TransactionRecord on success; raises TransactionAborted on conflict.
3. Acquire storage.lock(project, database).
4. For each Write in the request:
   a. Resolve the write type (update / delete / verify).
   b. Load or initialize the DocumentRecord.
   c. Check precondition (exists / update_time) via _check_precondition().
   d. Apply field-level update_mask if present (partial update).
   e. Apply update_transforms via engine/transforms.apply_transform().
   f. Bump storage.next_version() — increments the per-database monotonic counter.
   g. Write the new DocumentRecord via storage.put_document() (or delete_document).
5. Release the lock.
6. If PERSIST=1: await storage.snapshot(project, database).
7. Emit StateHub event "firestore.document.written" for each written path.
8. Return CommitResponse with per-write WriteResult (update_time) and commit_time.
```

## Query pipeline

`RunQuery` executes through a linear pipeline of five stages in `engine/query.py`:

```
candidate_docs
  → where (evaluate_filter)
  → orderBy (stable sort by compare())
  → cursors (startAt / startAfter / endAt / endBefore)
  → offset
  → limit
```

**Stage 1 — candidate collection.** `storage.iter_collection()` is called to enumerate the relevant documents. For a regular collection query (`allDescendants=false`), only direct children of the collection path are returned. For a collection-group query (`allDescendants=true`), all documents in the database whose path contains `collection_id` at any collection segment position are returned.

**Stage 2 — filter evaluation.** `evaluate_filter()` in `engine/query.py` handles `field_filter`, `unary_filter` (IS_NULL, IS_NAN), and `composite_filter` (AND, OR). Operators: `==`, `!=`, `<`, `<=`, `>`, `>=`, `array_contains`, `array_contains_any`, `in`, `not_in`. Missing fields fail most comparisons (return `False`).

**Stage 3 — sort.** Documents passing the filter are sorted using Python's `list.sort(key=...)` with a multi-key tuple built from the `order_by` clause. The `compare()` function from `values.py` is used per field, so cross-type comparisons follow Firestore's type-ordering rules. A final implicit sort by document name (full resource path) ensures deterministic ordering.

**Stage 4 — cursors.** After sorting, cursor positions are evaluated by finding the index of the first document that satisfies the cursor bound. `start_at` / `start_after` trim the left; `end_at` / `end_before` trim the right. Partial cursors (fewer values than `order_by` fields) are supported by comparing only the first N sort fields.

**Stage 5 — offset + limit.** Standard Python slice.

### Query pipeline diagram

```
iter_collection()
      │
      ▼
 evaluate_filter()       ← field/unary/composite filters
      │  (keep matching docs)
      ▼
 sort(key=order_by)      ← multi-field sort using compare()
      │
      ▼
 apply_cursors()         ← start_at / start_after / end_at / end_before
      │
      ▼
 offset                  ← skip N docs
      │
      ▼
 limit                   ← take at most M docs
      │
      ▼
 → stream DocumentSnapshot responses to client
```

## Value comparator and type ordering

`engine/values.py` implements the `compare(a, b)` function used by query sort and cursor evaluation. It follows the Firestore value-ordering specification exactly:

| Order | Type |
|---|---|
| 0 | `null` |
| 1 | `boolean` (false < true) |
| 2 | number (int and double, interleaved; NaN sorts smallest) |
| 3 | timestamp |
| 4 | string (lexicographic, byte-wise UTF-8) |
| 5 | bytes (byte-wise) |
| 6 | document reference (by full resource path, byte-wise) |
| 7 | geo point (by latitude, then longitude) |
| 8 | array (lexicographic element-wise) |
| 9 | map (by sorted keys, then value at each key) |

Cross-type comparisons use the rank table above. Within-type ordering follows Firestore semantics for each type.

## Transaction state machine

```
Client: BeginTransaction(options: read_write | read_only)
  → begin_transaction(): snapshot current db version → mint txn_id → store TransactionRecord
  → return txn_id to client

Client: GetDocument / BatchGetDocuments (with transaction=txn_id)
  → record_read(): add doc path to txn.read_set → store updated TransactionRecord

Client: Commit(writes=..., transaction=txn_id)
  → commit_transaction():
      for each path in txn.read_set:
          doc = storage.get_document(path)
          if doc.version > txn.snapshot_version → raise TransactionAborted
      (no conflict) → return txn record
  → apply writes under db lock (same as non-transactional Commit)
  → drop_transaction(txn_id)

Client: Rollback(transaction=txn_id)
  → drop_transaction(txn_id) — no writes applied

TTL sweeper (background asyncio.Task):
  every 30s: drop all TransactionRecords where started_at < now() - 60s
```

Read-only transactions (`options.read_only`) go through the same path but `commit_transaction` raises `InvalidArgument` if the client sends any `Write` records. `read_time` on read-only transactions is stored in the `TransactionRecord` but document reads still return current state (history retention is post-v1).

The TTL sweeper (`TransactionTtlSweeper` in `engine/transactions.py`) runs as an `asyncio.Task` started by `FirestoreService.start()` and canceled by `FirestoreService.stop()`. The default interval is 30 seconds with a 60-second TTL. Both are configurable at construction for test injection.

## Field transforms

`engine/transforms.py::apply_transform(field_path, transform, existing_value, now)` handles the five transform types in `FieldTransform`:

| Transform | Implementation |
|---|---|
| `SERVER_TIMESTAMP` | Returns the current UTC datetime (passed in as `now`) |
| `increment(n)` | Adds n to existing value; promotes int to float when types differ |
| `maximum(n)` | Returns `max(existing, n)` using `compare()`; returns `n` if field absent |
| `minimum(n)` | Returns `min(existing, n)` using `compare()`; returns `n` if field absent |
| `append_missing_elements(vs)` | Extends existing array with elements not already present (compare-based dedup) |
| `remove_all_from_array(vs)` | Removes all elements matching any of `vs` (compare-based) |

Transforms are applied **after** the field update_mask write, so a `Commit` with both an `update` document and `update_transforms` on the same field correctly first sets the document fields and then applies the transform over them.

## Error mapping

Internal exceptions in `errors.py` map to gRPC status codes via `grpc_error_for()`:

| Internal exception | gRPC code | When |
|---|---|---|
| `DocumentNotFound` | `NOT_FOUND` | `GetDocument` / `BatchGetDocuments` on a missing doc |
| `CollectionNotFound` | `NOT_FOUND` | (Reserved; collections are implicit in v1) |
| `DatabaseNotFound` | `NOT_FOUND` | Database resource name not found |
| `DocumentAlreadyExists` | `ALREADY_EXISTS` | `CreateDocument` or `Commit` with `exists=false` precondition when doc exists |
| `InvalidName` | `INVALID_ARGUMENT` | Malformed resource name |
| `InvalidArgument` | `INVALID_ARGUMENT` | Missing required field, bad transaction option, read-only txn with writes |
| `TransactionNotFound` | `INVALID_ARGUMENT` | Using a txn_id that has expired or never existed |
| `FailedPrecondition` | `FAILED_PRECONDITION` | Write precondition violated (doc does not exist when `exists=true`) |
| `TransactionAborted` | `ABORTED` | OCC conflict detected at Commit time |
| `Unimplemented` | `UNIMPLEMENTED` | `Listen`, `PartitionQuery`, admin DB lifecycle, IAM RPCs |
| Uncaught | `INTERNAL` | Fallback — should never happen in normal use |

Status codes are returned via `await context.abort(code, message)` inside the async servicer methods. The servicer wraps every RPC body in a `try / except FirestoreError` block followed by a broad `except Exception` fallback that logs at `ERROR` level and returns `INTERNAL`.

## Cross-service integration

Every successful write (`Commit`, `BatchWrite`, `CreateDocument`, `UpdateDocument`, `DeleteDocument`) emits a `firestore.document.written` event on the StateHub bus:

```python
{
  "project": "my-project",
  "database": "(default)",
  "path": "users/alice",
  "operation": "update",        # "create" | "update" | "delete"
  "update_time": "2026-05-01T...",
}
```

This is the hook the future `Listen` implementation will subscribe to instead of re-running write-side logic.

## Tests

**Unit tests** live under `tests/unit/services/firestore/` — one file per concern:

| File | What it covers |
|---|---|
| `test_names.py` | Resource-name parser and document-path validator |
| `test_models.py` | Record dataclass behavior |
| `test_storage.py` | `InMemoryStorage` CRUD, version counter, `iter_collection` (direct children + all descendants) |
| `test_storage_disk.py` | `JsonDiskStorage`: round-trip save/load, atomic write, schema version guard |
| `test_values.py` | `from_proto` / `to_proto` codec; `compare()` for all type pairs and edge cases (NaN, cross-type) |
| `test_query.py` | Query pipeline: filter operators, orderBy, cursors, offset, limit, collection-group |
| `test_aggregations.py` | count (incl. `up_to`), sum, avg; filter + aggregation combinations |
| `test_transforms.py` | All five field transform types: happy path + edge cases (missing field, int/float promotion) |
| `test_transactions.py` | Begin/record/commit happy path; OCC conflict; rollback; read-only + write raises; TTL sweeper |
| `test_servicer_crud.py` | Servicer-level gRPC: Get/Create/Update/Delete/BatchGet/ListDocuments/ListCollectionIds |
| `test_servicer_query.py` | RunQuery and RunAggregationQuery via gRPC |
| `test_servicer_commit.py` | Commit (single + batch), preconditions, transforms |
| `test_servicer_admin.py` | FirestoreAdmin CRUD stubs; `UNIMPLEMENTED` for database lifecycle RPCs |
| `test_errors.py` | Error-envelope shapes for each (internal exception → gRPC code) row |
| `test_service_scaffold.py` | `FirestoreService` lifecycle (start / stop / health / reset); port resolution; PERSIST flag |

**Integration tests** in `tests/integration/test_firestore_integration.py` start the emulator in-process and drive it with the real `google-cloud-firestore` Python client over a live gRPC channel. The 12 cases cover:

1. Set / get round-trip
2. Subcollection set / get
3. Partial update (field preservation)
4. Delete
5. Where + order_by + limit
6. Composite AND filter
7. Composite OR filter
8. count() aggregation (total + with filter)
9. Collection-group query
10. Transaction happy path
11. Transaction conflict → `ABORTED`
12. Increment field transform, SERVER_TIMESTAMP, multi-database isolation, missing document, duplicate create

## Internals-level limitations

These are gaps a future contributor should know about:

- **Composite indexes not enforced.** `CreateIndex` accepts and stores the definition; queries run regardless of whether a matching index exists. Real Firestore returns `FAILED_PRECONDITION` with an index-creation link. This means tests that pass locally may fail against real Firestore if required indexes are missing.
- **No `Listen` RPC.** `Listen` is the streaming RPC underlying `on_snapshot()`. It is registered in the servicer base class but immediately returns `UNIMPLEMENTED`. Adding it post-v1 only requires subscribing to the `firestore.document.written` StateHub event.
- **No document-history retention.** Documents deleted or overwritten before a `read_time` value are gone. Real Firestore retains a 1-hour window. Read-only transactions with `read_time` in the past always see current document state.
- **Linear query scan.** Every query iterates all documents in the relevant collection(s). No index-backed lookup exists. Adequate for local dev / test data volumes; not suitable for collections with tens of thousands of documents.
- **No security rules / auth.** All requests are accepted regardless of credentials. Any caller can read and write any document.
- **No exports / imports / backups.** `FirestoreAdmin.ExportDocuments`, `ImportDocuments`, and all `*Backup*` RPCs return `UNIMPLEMENTED`.
- **Transaction TTL = 60 s.** Shorter than real Firestore's ~270 s. Intentional — surfaces hung transaction handles quickly in test code.
- **Single-process delivery.** All state lives in one Python process with asyncio-level locking. No distributed consistency, no replication.
- **`PartitionQuery` → `UNIMPLEMENTED`.** Used by Dataflow / parallel export jobs; niche enough to defer post-v1.
- **No IAM enforcement.** `GetIamPolicy`, `SetIamPolicy`, `TestIamPermissions` return `UNIMPLEMENTED`.
