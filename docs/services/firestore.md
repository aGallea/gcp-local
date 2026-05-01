# Firestore emulator

Firestore (Native mode) emulator on port **8080**. Drop-in replacement for the official Java emulator for backend / server-side Firestore use cases — no JVM, no Node toolchain, integrates with the rest of gcp-local's services.

The official `google-cloud-firestore` Python client works against it with no code changes — set `FIRESTORE_EMULATOR_HOST` and construct the client normally.

Default port: **8080**. Wire protocol: **gRPC**.

---

## What's emulated

**Document operations**

- `GetDocument`, `BatchGetDocuments`
- `CreateDocument`, `UpdateDocument`, `DeleteDocument`
- `ListDocuments`, `ListCollectionIds`
- `Commit` (batched writes with `update_mask`, preconditions, and transforms)
- `BatchWrite` (per-write result status)

**Documents, collections, subcollections, multi-database namespacing.**  Each `(project, database)` pair is an independent namespace. `(default)` is the default database; additional databases (e.g. `staging`) come into existence on first write — no explicit creation needed.

**Structured queries (`RunQuery`)**

- `where` — all field filter operators: `==`, `!=`, `<`, `<=`, `>`, `>=`, `array_contains`, `array_contains_any`, `in`, `not_in`
- Composite filters: `AND` and `OR` (and nested combinations)
- `order_by` — multi-field, ASCENDING / DESCENDING, with stable secondary sort by document name
- Cursors — `start_at`, `start_after`, `end_at`, `end_before`, including partial-field cursors
- `limit` and `offset`
- Collection-group queries (`allDescendants=true`) — queries across same-named collections anywhere in the document tree

**Aggregations (`RunAggregationQuery`)**

- `count()` — with optional `up_to` clamp
- `sum(field)` — numeric field sum
- `avg(field)` — numeric field average; `null` when the collection is empty

**Atomic writes**

- `Commit` — applies a list of writes atomically under the database lock
- `BatchWrite` — applies writes individually; returns a per-write `WriteResult` / status

**Field transforms** (applied during `Commit` / `UpdateDocument` with `update_transforms`)

- `SERVER_TIMESTAMP` (`set_to_server_value: REQUEST_TIME`)
- `Increment(n)` — integer or double; promotes int → double when mixed
- `arrayUnion(values)` — `append_missing_elements`
- `arrayRemove(values)` — `remove_all_from_array`
- `maximum(value)`, `minimum(value)` — keep the greater/lesser of the existing and incoming values

**Transactions**

- `BeginTransaction`, `Rollback`
- Read-write transactions — optimistic concurrency control (OCC): reads are tracked in a read-set; `Commit` aborts with `ABORTED` if any read document was mutated since the transaction began
- Read-only transactions — with optional `read_time` for snapshot semantics
- TTL: transactions are dropped after **60 seconds** by a background sweeper (shorter than real Firestore's ~270s — intentional, to surface bugs quickly)

**FirestoreAdmin (accept-and-ignore stubs)**

- `CreateIndex` / `GetIndex` / `ListIndexes` / `DeleteIndex` — stored and returned, but index definitions are never enforced at query time. Queries always run regardless of whether a matching index exists.

**Persistence**

- Default: in-memory (state is lost on process exit).
- `PERSIST=1`: one JSON file per `(project, database)` under the data directory; loaded on startup.

---

## What's not emulated

These RPCs return gRPC `UNIMPLEMENTED`:

- **`Listen`** — real-time `on_snapshot()` / `watch()` callbacks. The streaming RPC is registered but returns `UNIMPLEMENTED`. See ROADMAP.
- **Security rules** — every request is authorized; no `firestore.rules` processing.
- **Exports / imports / backups** — `ExportDocuments`, `ImportDocuments`, `*Backup*` admin RPCs.
- **`PartitionQuery`** — used by Dataflow and parallel exports; niche use case.
- **Composite-index enforcement** — queries always run, regardless of stored indexes.
- **FirestoreAdmin database lifecycle** — `CreateDatabase`, `UpdateDatabase`, `DeleteDatabase` etc. return `UNIMPLEMENTED`; databases are implicit.
- **IAM** — `GetIamPolicy`, `SetIamPolicy`, `TestIamPermissions` return `UNIMPLEMENTED`.

---

## Connecting

The official Python client reads `FIRESTORE_EMULATOR_HOST` natively. Setting that environment variable before constructing the client is all that is needed — no `AnonymousCredentials` boilerplate required when the env var is set:

```bash
export FIRESTORE_EMULATOR_HOST=localhost:8080
```

```python
from google.cloud import firestore

db = firestore.Client(project="my-project")
```

### Port override

Override the default port with `FIRESTORE_EMULATOR_PORT` before starting the emulator:

```bash
FIRESTORE_EMULATOR_PORT=18080 python -m gcp_local
```

Then point the client at the new port:

```bash
export FIRESTORE_EMULATOR_HOST=localhost:18080
```

---

## Quickstart

```python
import os
os.environ["FIRESTORE_EMULATOR_HOST"] = "localhost:8080"

from google.cloud import firestore

db = firestore.Client(project="my-project")

# Create a document
db.collection("users").document("alice").set({"name": "Alice", "score": 0})

# Read it back
snap = db.collection("users").document("alice").get()
print(snap.to_dict())  # {'name': 'Alice', 'score': 0}

# Update a single field (others are preserved)
db.collection("users").document("alice").update({"score": 10})

# Delete
db.collection("users").document("alice").delete()
```

---

## Examples

The examples below assume `FIRESTORE_EMULATOR_HOST` is exported and `PROJECT = "my-project"`.

### CRUD

```python
from google.cloud import firestore

db = firestore.Client(project="my-project")

# Set (full overwrite)
db.collection("users").document("bob").set({"name": "Bob", "score": 5, "active": True})

# Partial update — only listed fields are changed; others are preserved
db.collection("users").document("bob").update({"score": 20})

# Read
snap = db.collection("users").document("bob").get()
if snap.exists:
    print(snap.to_dict())

# Delete
db.collection("users").document("bob").delete()

# create() fails if the document already exists (AlreadyExists error)
db.collection("unique").document("one").set({"x": 1})
try:
    db.collection("unique").document("one").create({"x": 2})
except Exception as e:
    print("already exists:", e)
```

### Subcollections

```python
db = firestore.Client(project="my-project")

user_ref = db.collection("users").document("alice")
user_ref.set({"name": "Alice"})

post_ref = user_ref.collection("posts").document("p1")
post_ref.set({"title": "Hello World", "views": 0})

snap = post_ref.get()
print(snap.to_dict())  # {'title': 'Hello World', 'views': 0}
```

### Queries

```python
from google.cloud import firestore

db = firestore.Client(project="my-project")
coll = db.collection("scores")

for i in range(10):
    coll.add({"user": f"user{i}", "score": i * 10})

# where + order_by + limit
results = (
    coll.where(filter=firestore.FieldFilter("score", ">", 40))
    .order_by("score", direction=firestore.Query.DESCENDING)
    .limit(3)
    .get()
)
for snap in results:
    print(snap.to_dict())  # scores 90, 80, 70

# Composite AND filter
fruits = db.collection("items")
fruits.document("a").set({"type": "fruit", "price": 1})
fruits.document("b").set({"type": "fruit", "price": 5})
fruits.document("c").set({"type": "veggie", "price": 2})

expensive_fruits = fruits.where(
    filter=firestore.And(
        filters=[
            firestore.FieldFilter("type", "==", "fruit"),
            firestore.FieldFilter("price", ">", 2),
        ]
    )
).get()
# Returns only document "b" (fruit, price 5)

# OR filter
mixed = db.collection("mixed")
mixed.document("x").set({"cat": "A"})
mixed.document("y").set({"cat": "B"})
mixed.document("z").set({"cat": "C"})

a_or_c = mixed.where(
    filter=firestore.Or(
        filters=[
            firestore.FieldFilter("cat", "==", "A"),
            firestore.FieldFilter("cat", "==", "C"),
        ]
    )
).get()
# Returns documents "x" and "z"
```

### Aggregations

```python
from google.cloud import firestore

db = firestore.Client(project="my-project")
coll = db.collection("events")
for i in range(7):
    coll.document(f"e{i}").set({"value": i * 10})

# count()
count_result = coll.count().get()
print(count_result[0][0].value)  # 7

# count() with up_to clamp
clamped = coll.count(count_up_to=5).get()
print(clamped[0][0].value)  # 5 (clamped)

# sum() and avg()
sum_result = coll.sum("value").get()
print(sum_result[0][0].value)  # 210

avg_result = coll.avg("value").get()
print(avg_result[0][0].value)  # 30.0
```

### Collection-group query

```python
from google.cloud import firestore

db = firestore.Client(project="my-project")

# Two different users, each with an "items" subcollection
db.collection("users").document("a").collection("items").document("i1").set({"label": "item-a"})
db.collection("users").document("b").collection("items").document("i2").set({"label": "item-b"})

# Query all "items" collections anywhere in the tree
results = db.collection_group("items").get()
labels = sorted(r.to_dict()["label"] for r in results)
print(labels)  # ['item-a', 'item-b']
```

### Transactions

```python
from google.cloud import firestore

db = firestore.Client(project="my-project")
ref = db.collection("accounts").document("account-1")
ref.set({"balance": 100})

@firestore.transactional
def transfer(txn: firestore.Transaction, doc_ref) -> None:
    snap = doc_ref.get(transaction=txn)
    new_balance = snap.get("balance") + 50
    txn.update(doc_ref, {"balance": new_balance})

txn = db.transaction()
transfer(txn, ref)

snap = ref.get()
print(snap.to_dict()["balance"])  # 150
```

Transactions support optimistic concurrency: if a document read inside the transaction is modified by another writer before `Commit`, the transaction is aborted with an `ABORTED` error and the client retries. The default `db.transaction()` retries up to 4 times automatically.

### Field transforms

```python
from google.cloud import firestore

db = firestore.Client(project="my-project")
ref = db.collection("counters").document("hits")
ref.set({"count": 0, "tags": [], "max_seen": 0})

# Increment
ref.update({"count": firestore.Increment(1)})

# SERVER_TIMESTAMP — the server fills in the current time
ref.update({"last_seen": firestore.SERVER_TIMESTAMP})

# arrayUnion — adds elements not already present
ref.update({"tags": firestore.ArrayUnion(["python", "gcp"])})
ref.update({"tags": firestore.ArrayUnion(["python"])})  # no duplicate added

# arrayRemove — removes matching elements
ref.update({"tags": firestore.ArrayRemove(["gcp"])})

# max / min — keep the larger / smaller of the existing and new value
ref.update({"max_seen": firestore.Increment(100)})   # now 100
ref.update({"max_seen": firestore.MAX_VALUE(50)})    # stays 100 (50 < 100)
```

### Multi-database

```python
from google.cloud import firestore

# Each database is a fully independent namespace
db_default = firestore.Client(project="my-project", database="(default)")
db_staging = firestore.Client(project="my-project", database="staging")

db_default.collection("settings").document("cfg").set({"env": "production"})
db_staging.collection("settings").document("cfg").set({"env": "staging"})

# Reads are fully isolated
snap_default = db_default.collection("settings").document("cfg").get()
snap_staging = db_staging.collection("settings").document("cfg").get()

print(snap_default.to_dict()["env"])  # production
print(snap_staging.to_dict()["env"])  # staging
```

---

## Configuration

| Environment variable | Default | Description |
|---|---|---|
| `FIRESTORE_EMULATOR_HOST` | — | Consumed by `google-cloud-firestore`; set to `localhost:8080` (or custom port) |
| `FIRESTORE_EMULATOR_PORT` | `8080` | Port the Firestore gRPC server listens on |
| `PERSIST` | `0` | `1` = write one JSON file per `(project, database)` under the data directory; reload on startup |

---

## Reset semantics

`POST /_emulator/reset?service=firestore`

Drops all documents, transactions, and index records for every database. Useful between test cases.

```bash
curl -X POST http://localhost:4510/_emulator/reset?service=firestore
```

Note: the reset endpoint is served by the admin API on port **4510**, not on the Firestore gRPC port (8080).

---

## Limits & quirks

**Linear query scan.** Every query performs a full scan of the relevant collection (or all collections for collection-group queries). No indexes are consulted at query time. Performance is fine for typical local-dev or test workloads but will degrade on very large in-memory datasets.

**Composite-index enforcement is a no-op.** `CreateIndex` succeeds and stores the index definition, and `ListIndexes` / `GetIndex` reflect it. But the emulator never enforces index presence — it will happily run a query that real Firestore would reject with a "requires an index" error. This means tests may pass locally and fail against real Firestore if the required index is missing from `firestore.indexes.json`.

**1500-byte document ID limit.** Document ID validation matches the real Firestore rules: IDs may not contain `/`, may not be `..` or `.`, and the path segment must be ≤1500 UTF-8 bytes.

**Transaction TTL is 60 seconds.** Real Firestore allows up to ~270 seconds. The emulator's background sweeper drops transactions older than 60 seconds to surface hung transaction handles quickly in test code. Long-running `with db.transaction():` blocks that pause for more than a minute will see `ABORTED`.

**Databases are created implicitly.** There is no `FirestoreAdmin.CreateDatabase` RPC. A `(project, database)` pair comes into existence on the first write. This differs from real Firestore, which requires explicit database creation.

**`read_time` in read-only transactions.** The emulator honors `read_time` on `BeginTransaction` only to the extent of accepting it on the wire; it always reads current document state. Documents deleted before `read_time` are gone. Real Firestore retains a 1-hour history.

**No real-time listeners.** `Listen` (the streaming RPC underlying `on_snapshot()` and `watch()`) returns `UNIMPLEMENTED`. Polling via repeated `get()` calls is the workaround for local testing.

**No security rules.** Every caller can read and write every document in every project/database. Do not use this emulator for testing security-rules code paths.

**Single-process.** All state lives in one Python process; `asyncio.Lock`s protect concurrent access. Horizontal scale-out is not supported.
