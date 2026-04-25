# BigQuery emulator

gcp-local's BigQuery service emulates the BigQuery REST API backed by DuckDB and sqlglot. The official `google-cloud-bigquery` Python client works against it with no code changes beyond pointing at the emulator host.

Default port: **9050**.

---

## What's emulated

- Dataset lifecycle: `create`, `get`, `list`, `update`, `patch`, `delete`
- Table lifecycle: `create`, `get`, `list`, `update`, `patch`, `delete` — including schemas with `RECORD`/`STRUCT`, `REPEATED`/`ARRAY`, `NULLABLE`, and `REQUIRED` modes
- Query jobs (`jobs.insert` with `QueryJobConfiguration`) and the synchronous `jobs.query` endpoint
- `jobs.get`, `jobs.list`, `jobs.cancel`, `jobs.getQueryResults` with `pageToken` paging
- DML: `INSERT`, `UPDATE`, `DELETE`, `MERGE`
- Streaming inserts: `tabledata.insertAll` — rows immediately visible
- `INFORMATION_SCHEMA` views: `TABLES`, `COLUMNS`, `SCHEMATA`
- Multi-project namespacing: different project IDs share one DuckDB file but are isolated

## What's not emulated (v1)

- Load jobs (`LoadJobConfiguration`), copy jobs, extract jobs
- Table snapshots, clones, time-travel (`FOR SYSTEM_TIME AS OF …`)
- Materialized views, scheduled queries, routines (UDFs, stored procs), models
- `ML.*` functions, `ST_*` geography functions, scripting / procedural SQL
- `INFORMATION_SCHEMA` views beyond `TABLES`, `COLUMNS`, `SCHEMATA` — `JOBS_BY_*`, `PARTITIONS`, `TABLE_OPTIONS`, `STREAMING_TIMELINE`, `OBJECT_PRIVILEGES` return `invalidQuery`
- Storage Read API / Storage Write API (gRPC)
- IAM, row-level access policies, column-level security, dataset access controls
- `GEOGRAPHY` type — rejected at schema creation with `INVALID_ARGUMENT`
- `INTERVAL`, `RANGE` types — rejected
- Partitioning and clustering — DDL accepted and stored in metadata; ignored at query time
- Streaming-buffer simulation (insertions are immediately durable, no eventual-visibility window)
- Legacy SQL (`useLegacySql: true`) — rejected with `invalidQuery`

---

## Connecting

### Environment variable (simplest)

```python
import os
from google.cloud import bigquery
from google.auth import credentials as ga_credentials

os.environ["BIGQUERY_EMULATOR_HOST"] = "localhost:9050"
client = bigquery.Client(
    project="my-project",
    credentials=ga_credentials.AnonymousCredentials(),
)
```

### Explicit `client_options` (more portable across client-library versions)

```python
import os
from google.auth import credentials as ga_credentials
from google.cloud import bigquery

os.environ["BIGQUERY_EMULATOR_HOST"] = "localhost:9050"
client = bigquery.Client(
    project="test-project",
    credentials=ga_credentials.AnonymousCredentials(),
    client_options={"api_endpoint": "http://localhost:9050"},
)
```

**`AnonymousCredentials` is required.** The emulator accepts any project name and performs no authentication. Without `AnonymousCredentials`, the client will attempt ADC and fail unless you have real GCP credentials in your environment — and even then, the real credentials would be sent to the emulator, which ignores them but the client may still balk on TLS mismatch.

---

## Quickstart

```python
import os
from google.auth import credentials as ga_credentials
from google.cloud import bigquery
from google.cloud.bigquery import DatasetReference, SchemaField, TableReference

os.environ["BIGQUERY_EMULATOR_HOST"] = "localhost:9050"
client = bigquery.Client(
    project="my-project",
    credentials=ga_credentials.AnonymousCredentials(),
    client_options={"api_endpoint": "http://localhost:9050"},
)

# 1. Create a dataset
ds_ref = DatasetReference("my-project", "my_dataset")
client.create_dataset(bigquery.Dataset(ds_ref))

# 2. Create a table
schema = [
    SchemaField("id",    "INT64",  mode="REQUIRED"),
    SchemaField("name",  "STRING", mode="NULLABLE"),
    SchemaField("score", "FLOAT64"),
]
table_ref = TableReference(ds_ref, "scores")
client.create_table(bigquery.Table(table_ref, schema=schema))

# 3. Streaming insert
errors = client.insert_rows_json(table_ref, [
    {"id": 1, "name": "alice", "score": 9.5},
    {"id": 2, "name": "bob",   "score": 7.2},
])
assert errors == []

# 4. Query back
rows = list(client.query(
    "SELECT id, name, score FROM `my-project.my_dataset.scores` ORDER BY id"
).result())
for row in rows:
    print(row["id"], row["name"], row["score"])
```

---

## DML example

```python
# INSERT via DML
client.query(
    "INSERT INTO `my-project.my_dataset.scores` VALUES (3, 'carol', 8.1)"
).result()

# UPDATE
client.query(
    "UPDATE `my-project.my_dataset.scores` SET score = 10.0 WHERE name = 'alice'"
).result()

# DELETE
client.query(
    "DELETE FROM `my-project.my_dataset.scores` WHERE id = 2"
).result()

# MERGE
client.query("""
    MERGE `my-project.my_dataset.scores` AS target
    USING (SELECT 3 AS id, 'carol' AS name, 9.9 AS score) AS source
    ON target.id = source.id
    WHEN MATCHED THEN
        UPDATE SET score = source.score
    WHEN NOT MATCHED THEN
        INSERT (id, name, score) VALUES (source.id, source.name, source.score)
""").result()
```

`numDmlAffectedRows` is available on the completed job:

```python
job = client.query("DELETE FROM `my-project.my_dataset.scores` WHERE id = 99")
job.result()
print(job.num_dml_affected_rows)  # 0
```

---

## STRUCT / ARRAY / JSON example

```python
from google.cloud.bigquery import SchemaField, DatasetReference, TableReference
import bigquery

schema = [
    SchemaField("user_id", "INT64", mode="REQUIRED"),
    SchemaField("tags", "STRING", mode="REPEATED"),          # ARRAY<STRING>
    SchemaField("address", "RECORD", mode="NULLABLE", fields=[
        SchemaField("city",  "STRING"),
        SchemaField("zip",   "STRING", mode="REQUIRED"),
    ]),
    SchemaField("meta", "JSON", mode="NULLABLE"),
]

ds_ref = DatasetReference("my-project", "nested")
client.create_dataset(bigquery.Dataset(ds_ref))
table_ref = TableReference(ds_ref, "users")
client.create_table(bigquery.Table(table_ref, schema=schema))

errors = client.insert_rows_json(table_ref, [{
    "user_id": 42,
    "tags":    ["admin", "beta"],
    "address": {"city": "Portland", "zip": "97201"},
    "meta":    '{"plan": "pro"}',
}])
assert errors == []

rows = list(client.query(
    "SELECT user_id, tags, address.city, JSON_EXTRACT_SCALAR(meta, '$.plan') AS plan "
    "FROM `my-project.nested.users`"
).result())
print(rows[0])
# Row((42, ['admin', 'beta'], 'Portland', 'pro'), ...)
```

For `to_dataframe()` and `to_arrow()` you need:

```bash
pip install db-dtypes pyarrow
```

---

## INFORMATION_SCHEMA

Three views are supported: `TABLES`, `COLUMNS`, and `SCHEMATA`.

```python
# List tables in a dataset
rows = list(client.query(
    "SELECT table_name, creation_time "
    "FROM `my-project.my_dataset.INFORMATION_SCHEMA.TABLES`"
).result())

# List columns for a specific table
rows = list(client.query(
    "SELECT column_name, data_type, is_nullable "
    "FROM `my-project.my_dataset.INFORMATION_SCHEMA.COLUMNS` "
    "WHERE table_name = 'scores'"
).result())

# List datasets visible to the project
rows = list(client.query(
    "SELECT schema_name "
    "FROM `my-project.my_dataset.INFORMATION_SCHEMA.SCHEMATA`"
).result())
```

Column shapes match the real BigQuery documentation (e.g. `data_type` is `STRING`, not `VARCHAR`).

**Unsupported views** (`JOBS_BY_USER`, `JOBS_BY_PROJECT`, `PARTITIONS`, `TABLE_OPTIONS`, `STREAMING_TIMELINE`, `OBJECT_PRIVILEGES`) return `invalidQuery` with a message identifying the unsupported view name.

---

## Configuration

| Environment variable        | Default | Description |
|-----------------------------|---------|-------------|
| `BIGQUERY_EMULATOR_HOST`    | —       | Consumed by the `google-cloud-bigquery` client; set to `localhost:9050` (or custom port) |
| `BIGQUERY_EMULATOR_PORT`    | `9050`  | Port the emulator listens on |
| `PERSIST`                   | `0`     | Set to `1` to use a disk-backed DuckDB file instead of in-memory |

When `PERSIST=1`, the DuckDB database is stored at `/data/bigquery.duckdb`. Dataset, table, and row data survive container restarts. Job records do not (see [Reset semantics](#reset-semantics) below).

---

## Reset semantics

`POST /_emulator/reset?service=bigquery`

Drops all datasets, tables, and data; clears all in-memory job records and result temp tables; re-initializes the internal catalog. Disk-backed files are truncated. Useful between test cases.

```bash
curl -X POST http://localhost:9050/_emulator/reset?service=bigquery
```

---

## Known gaps

These are intentional v1 limitations, not bugs.

**Deferred features:**
- Load jobs, copy jobs, extract jobs
- Materialized views, scheduled queries, routines / UDFs / stored procs, BQ ML
- `GEOGRAPHY` type (rejected at schema creation)
- Scripting / procedural SQL (`DECLARE`, `BEGIN…EXCEPTION…END`, `IF…ELSEIF`, `LOOP`)
- Time-travel queries (`FOR SYSTEM_TIME AS OF …`)
- Storage Read API / Storage Write API (gRPC)
- IAM, access controls

**Type fidelity:**
- `TIMESTAMP` and `DATETIME` share DuckDB's `TIMESTAMP` storage type. The emulator preserves the declared BQ type in its own catalog schema and uses that when serializing results, so round-trips are correct. However, operations that rely on DuckDB's own column metadata (e.g. introspecting via DuckDB directly) will see both as `TIMESTAMP`.
- `BIGNUMERIC` is mapped to `DECIMAL(38,18)` — 20 integer digits + 18 fractional. Real BigQuery's `BIGNUMERIC` supports 38 integer digits + 38 fractional. Values within `DECIMAL(38,18)` range round-trip correctly; values exceeding it will error or truncate.

**Job behavior:**
- `totalBytesProcessed` is always `0`. DuckDB does not expose a bytes-scanned metric.
- `etag` is accepted on write requests but not enforced — any `etag` value passes. The emulator returns a computed `etag` on reads for round-trip fidelity.
- Job records are in-memory only, even with `PERSIST=1`. They are lost on container restart. TTL is 1 hour from job completion.

**Streaming inserts:**
- Rows are immediately durable and visible to subsequent queries. There is no streaming-buffer simulation.
- `insertId` is accepted in the request payload but ignored — no deduplication.

---

## Caveats / gotchas

**Async event loop blocking.** The `google-cloud-bigquery` client is synchronous (uses `requests` under the hood). If you run both the emulator and client code in the same async event loop (e.g. in an async pytest test), calling BQ methods directly will block the loop and prevent the in-process uvicorn from serving the request — the call hangs. Dispatch all client calls to a thread:

```python
import asyncio

async def _run(fn):
    return await asyncio.get_running_loop().run_in_executor(None, fn)

# Instead of: client.query("SELECT 1").result()
await _run(lambda: client.query("SELECT 1").result())
```

See `tests/integration/test_bigquery_integration.py` for the full pattern used in this project's integration tests.

**`to_dataframe()` / `to_arrow()`.** These methods require `db-dtypes` and `pyarrow`. Install them separately:

```bash
pip install db-dtypes pyarrow
```

**Project IDs.** The emulator accepts any string that fits the URL path — no allow-list is enforced. Different project IDs are fully isolated (same dataset and table names under different projects are separate resources).

**Wildcard tables.** `` `project.dataset.events_*` `` is resolved by enumerating matching table names in the catalog and emitting a `UNION ALL`. All matched tables must have compatible schemas; DuckDB will error otherwise.
